import pytest


@pytest.fixture(autouse=True)
def bridge_auth_env(monkeypatch, tmp_path):
    """Keep tests from reading or creating the real ~/.blender-mcp/token."""
    monkeypatch.setenv("BLENDER_MCP_TOKEN", "test-token")
    monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(tmp_path / "token"))


@pytest.fixture
def headless_policy():
    from blender_mcp_server.shared import policy

    return policy.Policy(transports=("headless",))
