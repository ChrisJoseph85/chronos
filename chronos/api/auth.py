"""Phase 3 auth: Argon2 instance key, header + ?key= fallback, log redaction."""

from __future__ import annotations

import logging
import re

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError

    _PH = PasswordHasher()
except ImportError:  # pragma: no cover
    _PH = None
    VerifyMismatchError = Exception  # type: ignore

_KEY_PARAM_RE = re.compile(r"([?&]key=)[^&\s\"']+")
_BEARER_RE = re.compile(r"(X-Chronos-Key\s*[:=]\s*)([A-Za-z0-9_\-]{8,})", re.IGNORECASE)


def redact_text(text: str) -> str:
    text = _KEY_PARAM_RE.sub(r"\1[REDACTED]", text)
    text = _BEARER_RE.sub(r"\1[REDACTED]", text)
    return text


# Redact at record-creation time (LogRecord factory), not with a
# logger-attached filter — filters do not run for descendant loggers.
_orig_get_message = logging.LogRecord.getMessage


def _redact_arg(value: Any) -> Any:
    try:
        text = value if isinstance(value, str) else str(value)
    except Exception:
        return value
    if "key=" in text or "X-Chronos-Key" in text or "x-chronos-key" in text.lower():
        return redact_text(text)
    return value


def _redact_args(args: Any) -> Any:
    try:
        if isinstance(args, dict):
            return {key: _redact_arg(val) for key, val in args.items()}
        if isinstance(args, (tuple, list)):
            redacted = [_redact_arg(val) for val in args]
            return tuple(redacted) if isinstance(args, tuple) else redacted
    except Exception:
        pass
    return args


_orig_factory = logging.getLogRecordFactory()


def _redacting_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _orig_factory(*args, **kwargs)
    try:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if record.args:
            record.args = _redact_args(record.args)
    except Exception:
        pass
    return record


try:
    logging.setLogRecordFactory(_redacting_factory)
except Exception:
    pass


def _redacted_get_message(self) -> str:  # type: ignore[no-untyped-def]
    try:
        msg = _orig_get_message(self)
    except Exception:
        return ""
    try:
        return redact_text(str(msg))
    except Exception:
        return ""


if getattr(logging.LogRecord.getMessage, "__name__", "") != "_redacted_get_message":
    logging.LogRecord.getMessage = _redacted_get_message  # type: ignore[method-assign]


def hash_key(raw: str) -> str:
    if _PH is not None:
        return _PH.hash(raw)
    import hashlib

    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_key(candidate: str | None, key_hash: str | None) -> bool:
    if not candidate or not key_hash:
        return False
    if _PH is not None:
        try:
            return bool(_PH.verify(key_hash, candidate))
        except VerifyMismatchError:
            return False
        except Exception:
            pass
    import hashlib
    import hmac

    if key_hash.startswith("sha256:"):
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        return hmac.compare_digest(digest, key_hash[len("sha256:"):])
    return hmac.compare_digest(str(candidate), str(key_hash))


def extract_key(headers, query_params) -> str | None:
    try:
        candidate = headers.get("X-Chronos-Key") or headers.get("x-chronos-key")
    except Exception:
        candidate = None
    if candidate:
        return str(candidate)
    try:
        get = getattr(query_params, "get", None)
        if callable(get):
            value = get("key")
            if value:
                return str(value)
    except Exception:
        pass
    return None
