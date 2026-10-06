"""App state, key storage, and pure timer/breakdown helpers.

Key storage: libsecret preferred, 0600-file fallback
(`~/.config/chronos-desktop/key`). The key is never logged anywhere.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

KEY_PATH = os.path.expanduser("~/.config/chronos-desktop/key")
SECRET_SERVICE = "chronos-desktop"
SECRET_ACCOUNT = "instance-key"


# -- key storage ----------------------------------------------------------
def _secret():
    try:
        import gi
        gi.require_version("Secret", "1")
        from gi.repository import Secret
        return Secret
    except Exception:
        return None


def save_key(key, path=KEY_PATH, use_secret=True):
    """Store the instance key (libsecret, else 0600 file)."""
    if use_secret:
        Secret = _secret()
        if Secret is not None:
            try:
                schema = Secret.Schema.new(
                    SECRET_SERVICE, Secret.SchemaFlags.NONE,
                    {"account": Secret.SchemaAttributeType.STRING})
                Secret.password_store_sync(
                    schema, {"account": SECRET_ACCOUNT},
                    Secret.COLLECTION_DEFAULT, "Chronos instance key",
                    key, None)
                return "secret"
            except Exception as e:
                log.debug("libsecret store failed, file fallback: %s", e)
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(key)
    except BaseException:
        os.close(fd)
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return "file"


def load_key(path=KEY_PATH, use_secret=True):
    """Load the instance key, or None."""
    if use_secret:
        Secret = _secret()
        if Secret is not None:
            try:
                schema = Secret.Schema.new(
                    SECRET_SERVICE, Secret.SchemaFlags.NONE,
                    {"account": Secret.SchemaAttributeType.STRING})
                found = Secret.password_lookup_sync(
                    schema, {"account": SECRET_ACCOUNT}, None)
                if found:
                    return found
            except Exception as e:
                log.debug("libsecret lookup failed, file fallback: %s", e)
    try:
        with open(os.path.expanduser(path)) as f:
            return f.read().strip() or None
    except OSError:
        return None


def clear_key(path=KEY_PATH, use_secret=True):
    if use_secret:
        Secret = _secret()
        if Secret is not None:
            try:
                schema = Secret.Schema.new(
                    SECRET_SERVICE, Secret.SchemaFlags.NONE,
                    {"account": Secret.SchemaAttributeType.STRING})
                Secret.password_clear_sync(schema, {"account": SECRET_ACCOUNT}, None)
            except Exception:
                pass
    try:
        os.unlink(os.path.expanduser(path))
    except OSError:
        pass


# -- pure timer helpers ----------------------------------------------------
def session_elapsed_ms(sess, now_ms):
    """Elapsed ms for a session {start_ms, end_ms|None, base_ms?} at now_ms."""
    start = sess.get("start_ms") or 0
    base = sess.get("base_ms") or 0
    end = sess.get("end_ms")
    if end is None:
        end = now_ms
    return max(0, base + (end - start))


def build_stop_body(source, distracted=False):
    """Stop clean -> keeps (void:false); user-marked distracted -> void:true."""
    return {"source": source, "void": bool(distracted)}


def summarize_breakdown(rows):
    """Aggregate GET /api/stats/breakdown rows (server already excludes
    voided + pomodoro breaks): total + per-kind totals, sorted desc."""
    rows = list(rows or [])
    total = sum(int(r.get("total_ms") or 0) for r in rows)
    by_kind = {}
    for r in rows:
        by_kind[r.get("kind", "?")] = by_kind.get(r.get("kind", "?"), 0) + int(r.get("total_ms") or 0)
    ordered = sorted(rows, key=lambda r: int(r.get("total_ms") or 0), reverse=True)
    return {"total_ms": total, "by_kind": by_kind, "rows": ordered}


def format_ms(ms):
    ms = max(0, int(ms))
    s = ms // 1000
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# -- in-memory app state ----------------------------------------------------
class AppState:
    """Shared UI state, updated by REST results and WS frames."""

    def __init__(self, base_url="http://127.0.0.1:8080"):
        self.base_url = base_url
        self.healthy = True
        self.server_version = None
        self.timer_session = None       # latest timer frame / GET /api/timer
        self.proposals = {}             # proposal_id -> proposal frame
        self.questions = []             # briefing-question pings
        self.events = []
        self.nodes = []
        self.strict_default = False

    def update_from_frame(self, frame):
        """Handle WS server frames: state/patch/proposal/question/timer."""
        if not isinstance(frame, dict):
            return None
        if "timer" in frame:
            self.timer_session = frame["timer"]
            return "timer"
        if "proposal" in frame:
            p = frame["proposal"] or {}
            if p.get("proposal_id"):
                self.proposals[p["proposal_id"]] = p
            return "proposal"
        if "question" in frame:
            self.questions.append(frame["question"])
            return "question"
        if "state" in frame:
            st = frame["state"] or {}
            if "timer" in st:
                self.timer_session = st["timer"]
            return "state"
        if "patch" in frame:
            return "patch"  # views re-fetch on patch
        if frame.get("queued") or frame.get("retrying"):
            return "queued"
        return None

    def take_proposal(self, proposal_id):
        return self.proposals.pop(proposal_id, None)
