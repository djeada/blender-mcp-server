"""Shared-secret token file used by the bridge."""

import os
import secrets

TOKEN_ENV_VAR = "BLENDER_MCP_TOKEN"
TOKEN_FILE_ENV_VAR = "BLENDER_MCP_TOKEN_FILE"


def token_file_path() -> str:
    """Location of the shared auth token, overridable via BLENDER_MCP_TOKEN_FILE."""
    return os.environ.get(TOKEN_FILE_ENV_VAR) or os.path.join(os.path.expanduser("~"), ".blender-mcp", "token")


def load_or_create_token() -> str:
    """Return the bridge auth token, creating a private token file on first use.

    The MCP server reads the same file (or the BLENDER_MCP_TOKEN environment
    variable), so only processes that can read the user's files can talk to
    the bridge. This keeps web pages and other users from driving Blender.
    """
    env_token = os.environ.get(TOKEN_ENV_VAR)
    if env_token:
        return env_token
    path = token_file_path()
    try:
        with open(path, encoding="utf-8") as f:
            existing = f.read().strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    token = secrets.token_urlsafe(32)
    tmp_path = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    os.replace(tmp_path, path)
    return token
