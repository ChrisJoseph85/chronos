"""Phase 3 voice route: multipart audio -> transcript."""

from __future__ import annotations

from typing import Any

from fastapi import UploadFile


async def transcribe_audio(file: UploadFile | None, extra: dict | None = None) -> dict[str, Any]:
    """Return a transcript shape; offline fallback is an empty transcript."""
    name = ""
    try:
        name = getattr(file, "filename", "") or ""
    except Exception:
        name = ""
    if extra and extra.get("transcript"):
        return {"transcript": str(extra["transcript"])}
    if name:
        return {"transcript": ""}
    return {"transcript": ""}
