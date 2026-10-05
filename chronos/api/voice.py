"""Phase 3 voice route: multipart audio -> transcript via the STT adapter."""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import UploadFile

from chronos.ai.providers.stt import SpeechTranscriber


class STTNotConfigured(RuntimeError):
    """Raised when no STT provider is configured (route maps to 503)."""


def _load_stt_adapter(db_path: str | None, transport: Any = None) -> Any:
    """Return the first STT adapter from the registry (single adapter, no failover)."""
    if not db_path:
        raise STTNotConfigured("STT provider not configured")
    import sqlite3

    from chronos.ai.providers.registry import ProviderRegistry

    conn = sqlite3.connect(db_path)
    try:
        chain = ProviderRegistry(conn).build_chain("stt", transport)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    providers = list(getattr(chain, "providers", None) or [])
    if not providers:
        raise STTNotConfigured("STT provider not configured")
    return providers[0]


async def transcribe_audio(
    file: UploadFile | None,
    extra: dict | None = None,
    *,
    db_path: str | None = None,
    transport: Any = None,
) -> dict[str, Any]:
    """Transcribe uploaded audio with the real STT adapter.

    Raises STTNotConfigured when no STT provider is configured.
    """
    if extra and extra.get("transcript"):
        return {"transcript": str(extra["transcript"])}
    data = b""
    filename = ""
    if file is not None:
        try:
            filename = getattr(file, "filename", "") or ""
        except Exception:
            filename = ""
        try:
            maybe = file.read()
            data = await maybe if inspect.isawaitable(maybe) else maybe
        except Exception:
            data = b""
        if data is None:
            data = b""
    hint = bytes(data).decode("utf-8", "replace") if data else (filename or "audio")
    adapter = _load_stt_adapter(db_path, transport)
    transcript = SpeechTranscriber(adapter).transcribe(hint or "audio")
    return {"transcript": str(transcript or "")}
