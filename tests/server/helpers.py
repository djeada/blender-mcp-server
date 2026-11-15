"""Stream and render stand-ins shared by server tests."""

import json
from unittest.mock import AsyncMock, MagicMock


def _echo_stream(response_fields: dict, stale_first: dict | None = None):
    """Mock reader/writer pair that answers each written request with a matching id."""
    sent: list[dict] = []
    mock_writer = AsyncMock()
    mock_writer.write = MagicMock(side_effect=lambda data: sent.append(json.loads(data)))
    mock_writer.drain = AsyncMock()
    mock_writer.close = MagicMock()
    mock_writer.sent = sent
    lines: list[bytes] = []

    async def readline():
        if not lines:
            if stale_first is not None:
                lines.append(json.dumps(stale_first).encode() + b"\n")
            lines.append(json.dumps({"id": sent[-1]["id"], **response_fields}).encode() + b"\n")
        return lines.pop(0)

    mock_reader = AsyncMock()
    mock_reader.readline = readline
    return mock_reader, mock_writer


class _FakeRender:
    resolution_x = 1920
    resolution_y = 1080
    filepath = ""

    def __init__(self, engines):
        self._engines = engines
        self._engine = engines[0]

    @property
    def engine(self):
        return self._engine

    @engine.setter
    def engine(self, value):
        if value not in self._engines:
            raise TypeError(f'enum "{value}" not found in {self._engines}')
        self._engine = value
