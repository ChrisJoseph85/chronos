"""Realtime hub: one hub, many clients; every mutation broadcasts to all."""

from __future__ import annotations

import asyncio
from typing import Any


class Hub:
    def __init__(self) -> None:
        self._clients: set[Any] = set()
        self._lock = asyncio.Lock()

    async def register(self, ws: Any) -> None:
        async with self._lock:
            self._clients.add(ws)

    async def unregister(self, ws: Any) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            clients = list(self._clients)
        dead = []
        for ws in clients:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    async def disconnect_all(self, code: int = 4001) -> None:
        async with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for ws in clients:
            try:
                await ws.close(code=code)
            except Exception:
                pass

    def client_count(self) -> int:
        return len(self._clients)
