import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app, list_tools, call_tool
from app.database import Incident, Target
from mcp.types import TextContent

@pytest.fixture
def client():
    return TestClient(app)

def test_api_search_incidents(client, db_session):
    # Setup test incidents
    target = Target(id="test-search-target", type="docker")
    db_session.add(target)
    db_session.commit()

    incident = Incident(
        id="incident-uuid-1",
        target_id="test-search-target",
        status="RESOLVED",
        category="network",
        root_cause="Network timeout to gateway.",
        proposed_fix="ping 1.1.1.1"
    )
    db_session.add(incident)
    db_session.commit()

    # Mock qdrant_mem.semantic_search
    mock_match = MagicMock()
    mock_match.id = "incident-uuid-1"
    mock_match.score = 0.95

    with patch("app.qdrant_mem.qdrant_mem.semantic_search", return_value=[mock_match]):
        resp = client.get("/api/incidents/search?q=timeout")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "incident-uuid-1"
        assert data[0]["category"] == "network"
        assert data[0]["score"] == 0.95

@pytest.mark.asyncio
async def test_mcp_list_tools():
    tools = await list_tools()
    tool_names = [t.name for t in tools]
    assert "search_incidents" in tool_names
    assert "get_incident_history" in tool_names
    assert "trigger_remediation" in tool_names

@pytest.mark.asyncio
async def test_mcp_call_tool_search(db_session):
    target = Target(id="test-mcp-target", type="docker")
    db_session.add(target)
    db_session.commit()

    incident = Incident(
        id="incident-uuid-mcp",
        target_id="test-mcp-target",
        status="RESOLVED",
        category="permissions",
        root_cause="File permission mismatch.",
        proposed_fix="chmod +x app.sh"
    )
    db_session.add(incident)
    db_session.commit()

    mock_match = MagicMock()
    mock_match.id = "incident-uuid-mcp"
    mock_match.score = 0.88

    with patch("app.qdrant_mem.qdrant_mem.semantic_search", return_value=[mock_match]):
        result = await call_tool("search_incidents", {"query": "file permissions", "limit": 2})
        assert len(result) == 1
        assert isinstance(result[0], TextContent)
        assert "incident-uuid-mcp" in result[0].text
        assert "permissions" in result[0].text

@pytest.mark.asyncio
async def test_mcp_call_tool_history(db_session):
    target = Target(id="test-mcp-hist", type="docker")
    db_session.add(target)
    db_session.commit()

    incident = Incident(
        id="incident-uuid-mcp-hist",
        target_id="test-mcp-hist",
        status="RESOLVED",
        category="settings",
        root_cause="Config parameter mismatch.",
        proposed_fix="restart app"
    )
    db_session.add(incident)
    db_session.commit()

    result = await call_tool("get_incident_history", {"target_id": "test-mcp-hist", "limit": 5})
    assert len(result) == 1
    assert "settings" in result[0].text
    assert "Config parameter mismatch." in result[0].text
