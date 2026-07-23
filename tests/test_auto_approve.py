import os
import pytest
from unittest.mock import patch, MagicMock
from app.database import Incident, Target
from app.investigator import trigger_investigation

def test_auto_approve_caddy_when_external_domain_down(db_session):
    incident = Incident(
        id="test_auto_approve_inc",
        target_id="caddy",
        status="DETECTED",
        error_logs="Caddyfile parse error at line 14: unknown directive foo"
    )
    db_session.add(incident)
    db_session.commit()

    # Mock subprocess run for agy
    mock_agy_output = (
        '{\n'
        '  "root_cause": "Syntax error in Caddyfile",\n'
        '  "proposed_fix": "docker compose restart caddy",\n'
        '  "category": "reverse_proxy"\n'
        '}'
    )
    mock_sub_res = MagicMock()
    mock_sub_res.returncode = 0
    mock_sub_res.stdout = mock_agy_output

    with patch("subprocess.run", return_value=mock_sub_res), \
         patch("requests.get", side_effect=Exception("Connection refused")), \
         patch("app.notifier.send_incident_notification") as mock_notify, \
         patch("app.remediator.run_remediation") as mock_remediate:

        trigger_investigation("test_auto_approve_inc")

        # Verify incident status was changed directly to FIXING (auto-approved)
        inc = db_session.query(Incident).filter(Incident.id == "test_auto_approve_inc").first()
        assert inc.status == "FIXING"
        assert inc.category == "reverse_proxy"
        assert "Syntax error in Caddyfile" in inc.root_cause

        # Verify notification and remediation background worker were spawned
        mock_notify.assert_called_once_with("test_auto_approve_inc")
