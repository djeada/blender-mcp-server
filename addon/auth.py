"""Shared-secret token file used by the bridge."""

import contextlib
import os
import secrets
import stat
import tempfile

TOKEN_ENV_VAR = "BLENDER_MCP_TOKEN"
TOKEN_FILE_ENV_VAR = "BLENDER_MCP_TOKEN_FILE"


def token_file_path() -> str:
    return os.path.abspath(
        os.path.expanduser(os.environ.get(TOKEN_FILE_ENV_VAR) or os.path.join("~", ".blender-mcp", "token"))
    )


def _read_token(path: str) -> str:
    mode = os.lstat(path).st_mode
    if not stat.S_ISREG(mode) or (os.name == "posix" and mode & 0o077):
        raise PermissionError("Token file must be private. Set mode 0600 or use the Windows setup script")
    with open(path, encoding="utf-8-sig") as handle:
        token = handle.read(1025).strip()
    if not token or len(token) > 1024:
        raise ValueError("Token file is empty or invalid. Remove it and restart Blender to regenerate it")
    return token


def load_or_create_token() -> str:
    env_token = os.environ.get(TOKEN_ENV_VAR)
    if env_token:
        return env_token
    path = token_file_path()
    with contextlib.suppress(FileNotFoundError):
        return _read_token(path)

    directory = os.path.dirname(path)
    os.makedirs(directory, mode=0o700, exist_ok=True)
    token = secrets.token_urlsafe(32)
    fd, temporary = tempfile.mkstemp(prefix=".token-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
        try:
            # Publish atomically, and let a concurrent Blender instance keep the first token.
            if os.name == "nt":
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
        except FileExistsError:
            return _read_token(path)
        return token
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
