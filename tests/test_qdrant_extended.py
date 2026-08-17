import pytest
from unittest.mock import MagicMock
from app.qdrant_mem import QdrantMemory

def test_qdrant_memory_query_and_learn():
    mem = QdrantMemory()
    mock_client = MagicMock()
    mem.client = mock_client
    
    # Test learn_incident
    res = mem.learn_incident("test-id", "test-container", "permission denied", "chmod +x file")
    assert res is True
    mock_client.add.assert_called_once()
    
    # Test query_similar_fix
    mock_hit = MagicMock()
    mock_hit.score = 0.85
    mock_hit.metadata = {"successful_command": "chmod +x file"}
    mock_client.query.return_value = [mock_hit]
    
    hit = mem.query_similar_fix("test-container", "permission denied")
    assert hit is not None
    assert hit.metadata["successful_command"] == "chmod +x file"

def test_qdrant_semantic_search():
    mem = QdrantMemory()
    mock_client = MagicMock()
    mem.client = mock_client
    
    mock_hit = MagicMock()
    mock_hit.id = "hit-1"
    mock_hit.score = 0.92
    mock_client.query.return_value = [mock_hit]
    
    results = mem.semantic_search("search query", limit=5)
    assert len(results) == 1
    assert results[0].id == "hit-1"

def test_qdrant_list_memories():
    mem = QdrantMemory()
    mock_client = MagicMock()
    mem.client = mock_client
    
    # Non existent collection
    mock_client.collection_exists.return_value = False
    assert mem.list_memories() == []
    
    # Existing collection scroll
    mock_client.collection_exists.return_value = True
    mock_client.scroll.return_value = (["record1", "record2"], None)
    res = mem.list_memories(limit=10)
    assert len(res) == 2
    
    # Client is None
    mem.client = None
    assert mem.list_memories() == []
    
    # Exception branch
    mem.client = mock_client
    mock_client.scroll.side_effect = Exception("Qdrant scroll error")
    assert mem.list_memories() == []
