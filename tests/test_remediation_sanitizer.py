import pytest
from unittest.mock import patch, MagicMock
from app.remediator import sanitize_remediation_command, run_remediation
from app.database import Incident, Target

def test_sanitize_markdown_fences():
    raw = "```bash\ncd /containers/media_content && docker compose restart radarr4k\n```"
    clean = sanitize_remediation_command(raw)
    assert clean == "cd /containers/media_content && docker compose restart radarr4k"

def test_sanitize_numbered_bullets():
    raw = "1. Restart Radarr4K to clear error: cd /containers/media_content && docker compose restart radarr4k\n2. Verify health: ping 10.0.0.10"
    clean = sanitize_remediation_command(raw)
    assert "1. Restart" not in clean
    assert "cd /containers/media_content && docker compose restart radarr4k" in clean

def test_sanitize_trailing_commentary():
    raw = "cd /containers/cameras && docker compose up -d --force-recreate frigate\nIf this fails, check logs."
    clean = sanitize_remediation_command(raw)
    assert clean.startswith("cd /containers/cameras && docker compose up -d --force-recreate frigate")
    assert "If this fails" not in clean

def test_sanitize_sh_fences_and_inline_backticks():
    raw = "```sh\n`docker compose restart prowlarr`\n```"
    clean = sanitize_remediation_command(raw)
    assert clean == "docker compose restart prowlarr"

def test_sanitize_leading_bullets_and_numbers():
    raw = (
        "- cd /containers/media_downloads && docker compose restart qbittorrent\n"
        "* docker compose ps\n"
        "1) systemctl restart monitorbot\n"
        "2. curl -fsSL http://localhost:9013/api/health"
    )
    clean = sanitize_remediation_command(raw)
    lines = clean.splitlines()
    assert lines[0] == "cd /containers/media_downloads && docker compose restart qbittorrent"
    assert lines[1] == "docker compose ps"
    assert lines[2] == "systemctl restart monitorbot"
    assert lines[3] == "curl -fsSL http://localhost:9013/api/health"

def test_sanitize_empty_and_none():
    assert sanitize_remediation_command("") == ""
    assert sanitize_remediation_command("   \n  ") == ""
    assert sanitize_remediation_command(None) == ""

def test_sanitize_ignores_pure_commentary():
    raw = (
        "The container seems to have run out of memory.\n"
        "Please check the system logs with journalctl.\n"
        "docker restart my_container\n"
        "Let me know if this helps!"
    )
    clean = sanitize_remediation_command(raw)
    assert clean == "docker restart my_container"

@patch("app.remediator.subprocess.run")
@patch("app.remediator.time.sleep", return_value=None)
@patch("docker.from_env")
def test_run_remediation_uses_sanitized_command(mock_docker, mock_sleep, mock_run, db_session):
    target = Target(id="app_with_fence", type="docker")
    db_session.add(target)

    raw_fix = "```bash\n1. Restart service: docker restart app_with_fence\n```"
    inc = Incident(id="inc-fence-test", target_id="app_with_fence", status="PENDING_USER", proposed_fix=raw_fix)
    db_session.add(inc)
    db_session.commit()

    mock_run.return_value = MagicMock(returncode=0, stdout="Restarted", stderr="")
    mock_container = MagicMock()
    mock_container.labels = {}
    mock_container.attrs = {"State": {"Running": True, "Health": {"Status": "healthy"}}}
    mock_docker_client = MagicMock()
    mock_docker_client.containers.get.return_value = mock_container
    mock_docker.return_value = mock_docker_client

    with patch("app.remediator.send_followup_notification"), \
         patch("app.qdrant_mem.qdrant_mem.learn_incident"):
        run_remediation("inc-fence-test")
        db_session.refresh(inc)
        assert inc.status == "RESOLVED"
        # Verify subprocess.run was called with sanitized command, not markdown fence
        mock_run.assert_called_once()
        executed_cmd = mock_run.call_args[0][0]
        assert "```" not in executed_cmd
        assert "1. Restart" not in executed_cmd
        assert executed_cmd == "docker restart app_with_fence"
