"""REST (stdlib urllib) + WS (`websockets`) transport for the Chronos API.

Auth: `X-Chronos-Key` header on every non-open route. `GET /api/health` is
the only open route and gates all writes: while unhealthy, mutating calls
raise :class:`ServerDown` without touching the network.

The instance key (and provider key values) NEVER appear in logs: only the
method, path, status and redacted headers are logged; bodies are never logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

API_KEY_HEADER = "X-Chronos-Key"
WS_PATH = "/ws"
DEVICE_ID = "desktop"


class ChronosError(Exception):
    """Base for all transport errors."""


class ServerDown(ChronosError):
    """Server unreachable or health gate failed; writes are blocked."""


class AuthError(ChronosError):
    """Missing/invalid key (HTTP 401)."""


class ApiError(ChronosError):
    def __init__(self, status, message="request failed", payload=None):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.payload = payload


class TimerConflict(ChronosError):
    """HTTP 409: a session is already running (start) or none is (stop)."""

    def __init__(self, message="timer conflict", payload=None):
        super().__init__(message)
        self.payload = payload


def safe_headers(headers):
    """Return headers with anything key-like redacted (for logging)."""
    return {k: ("***" if "key" in k.lower() else v) for k, v in dict(headers).items()}


def _frame_kind(frame):
    """Best-effort one-word kind of a WS frame, for redacted logging."""
    if isinstance(frame, dict) and frame:
        return next(iter(frame))
    return type(frame).__name__


class ChronosClient:
    """Thin REST client. `opener` is injectable for tests (fn(req) -> resp)."""

    def __init__(self, base_url, key=None, timeout=10, opener=None):
        self.base_url = base_url.rstrip("/")
        self._key = key
        self.timeout = timeout
        self._opener = opener
        self.healthy = True
        self.version = None

    def set_key(self, key):
        self._key = key

    # -- health gate -----------------------------------------------------
    def check_health(self):
        """GET /api/health (open route). Sets .healthy; raises ServerDown."""
        try:
            data = self._request("GET", "/api/health", gate=False, needs_key=False)
        except ChronosError:
            self.healthy = False
            raise
        self.healthy = True
        self.version = (data or {}).get("version")
        return data

    # -- core ------------------------------------------------------------
    def _request(self, method, path, body=None, *, gate=True, needs_key=True):
        if gate and method in ("POST", "PUT", "DELETE") and not self.healthy:
            raise ServerDown(f"server unhealthy: {method} {path} blocked")
        url = self.base_url + path
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(
            url, data=payload, method=method,
            headers={"Content-Type": "application/json"},
        )
        if needs_key and self._key:
            req.add_header(API_KEY_HEADER, self._key)
        log.debug("%s %s headers=%s", method, path, safe_headers(dict(req.header_items())))
        try:
            resp = self._opener(req) if self._opener else urllib.request.urlopen(req, timeout=self.timeout)
            raw = resp.read() or b""
            status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as e:
            try:
                err_body = json.loads((e.read() or b"").decode("utf-8") or "null")
            except ValueError:
                err_body = None
            log.debug("%s %s -> HTTP %s", method, path, e.code)
            if e.code == 401:
                raise AuthError("missing/invalid key") from e
            if e.code == 409:
                raise TimerConflict("timer conflict", payload=err_body) from e
            raise ApiError(e.code, getattr(err_body, "get", lambda *a: None)("error", "request failed")
                           if isinstance(err_body, dict) else "request failed", payload=err_body) from e
        except OSError as e:  # URLError is an OSError: server unreachable
            self.healthy = False
            raise ServerDown(f"unreachable: {e}") from e
        log.debug("%s %s -> HTTP %s", method, path, status)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as e:
            raise ApiError(status, "non-JSON response") from e

    # -- say / commands --------------------------------------------------
    def say(self, text, device_id=None):
        return self._request("POST", "/api/say",
                             {"text": text, "device_id": device_id or DEVICE_ID})

    def commands(self, tool, arguments, device_id=None):
        return self._request("POST", "/api/commands",
                             {"tool": tool, "arguments": arguments,
                              "device_id": device_id or DEVICE_ID})

    # -- reads -----------------------------------------------------------
    def events(self, from_iso, to_iso):
        return self._request("GET", f"/api/events?from={from_iso}&to={to_iso}", gate=False)

    def nodes(self, parent=None, tag=None):
        q = f"?parent={parent or ''}" + (f"&tag={tag}" if tag else "")
        return self._request("GET", f"/api/nodes{q}", gate=False)

    def reminders(self):
        return self._request("GET", "/api/reminders", gate=False)

    def briefing(self, date):
        return self._request("GET", f"/api/briefing?date={date}", gate=False)

    def search(self, q, limit=20):
        return self._request("GET", f"/api/search?q={q}&limit={limit}", gate=False)

    # -- timer -----------------------------------------------------------
    def timer_start(self, label, node_id=None, mode="stopwatch", target_ms=None, source=None):
        body = {"label": label, "mode": mode, "source": source or DEVICE_ID}
        if node_id:
            body["node_id"] = node_id
        if target_ms and mode != "stopwatch":
            body["target_ms"] = target_ms
        return self._request("POST", "/api/timer/start", body)

    def timer_stop(self, source=None, void=False):
        from .state import build_stop_body  # local import: no cycle at module load
        return self._request("POST", "/api/timer/stop",
                             build_stop_body(source or DEVICE_ID, distracted=void))

    def timer_get(self, node_id=None):
        return self._request("GET", "/api/timer" + (f"?node_id={node_id}" if node_id else ""),
                             gate=False)

    def timer_summary(self, node_id=None):
        return self._request("GET", "/api/timer/summary" + (f"?node_id={node_id}" if node_id else ""),
                             gate=False)

    def timer_breakdown(self, node_id, from_iso, to_iso):
        return self._request(
            "GET", f"/api/stats/breakdown?node_id={node_id}&from={from_iso}&to={to_iso}", gate=False)

    def timer_presets(self):
        return self._request("GET", "/api/timer/presets", gate=False)

    def timer_presets_add(self, name, focus_minutes, break_minutes, cycles=1):
        return self._request("POST", "/api/timer/presets",
                             {"name": name, "focus_minutes": focus_minutes,
                              "break_minutes": break_minutes, "cycles": cycles})

    # -- providers / settings --------------------------------------------
    def providers(self):
        return self._request("GET", "/api/providers", gate=False)

    def providers_add(self, group, name, base_url, model=None, position=None):
        body = {"group": group, "name": name, "base_url": base_url}
        if model is not None:
            body["model"] = model
        if position is not None:
            body["position"] = position
        return self._request("POST", "/api/providers", body)

    def providers_update(self, pid, **fields):
        return self._request("PUT", f"/api/providers/{pid}", dict(fields))

    def providers_delete(self, pid):
        return self._request("DELETE", f"/api/providers/{pid}")

    def providers_add_key(self, pid, key_value):
        # key VALUE goes out in the body; bodies are never logged.
        return self._request("POST", f"/api/providers/{pid}/keys", {"key": key_value})

    def providers_delete_key(self, pid, key_id):
        return self._request("DELETE", f"/api/providers/{pid}/keys/{key_id}")

    def providers_activate(self, group, pid):
        return self._request("POST", "/api/providers/active", {"group": group, "id": pid})

    def settings_get(self):
        return self._request("GET", "/api/settings", gate=False)

    def settings_update(self, values):
        return self._request("PUT", "/api/settings", dict(values))


def _ws_uri(base_url):
    base = base_url.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://"):]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://"):]
    return base + WS_PATH


def _default_connect(uri, headers):
    from websockets.asyncio.client import connect
    return connect(uri, additional_headers=headers)


class WsClient:
    """WS client. Frames in: state/patch/proposal/question/timer/queued/retrying.
    Proposal accept/reject/skip out. `connect_fn(uri, headers)` injectable."""

    def __init__(self, base_url, key, device_id=DEVICE_ID, on_frame=None, connect_fn=None):
        self._uri = _ws_uri(base_url)
        self._key = key
        self._device_id = device_id
        self._on_frame = on_frame or (lambda frame: None)
        self._connect_fn = connect_fn or _default_connect
        self._sock = None
        self._outbox = []
        self._stop = threading.Event()

    @property
    def connected(self):
        return self._sock is not None

    def set_key(self, key):
        self._key = key

    def queue(self, obj):
        """Queue an outgoing frame (e.g. {"accept": pid}); flush on connect."""
        self._outbox.append(obj)
        if self._sock is not None:
            asyncio.get_event_loop().call_soon_threadsafe(lambda: None)  # wake not needed; flush in send loop
        return obj

    async def connect_and_hello(self):
        """Connect, send {hello key device}, flush outbox. Returns socket."""
        sock = await self._connect_fn(self._uri, {API_KEY_HEADER: self._key or ""})
        hello = {"hello": {"key": self._key, "device": self._device_id}}
        await sock.send(json.dumps(hello))
        log.debug("ws hello sent (credentials redacted)")
        self._sock = sock
        await self._flush()
        return sock

    async def _flush(self):
        while self._outbox:
            obj = self._outbox.pop(0)
            await self._sock.send(json.dumps(obj))
            log.debug("ws -> %s", _frame_kind(obj))

    async def send(self, obj):
        if self._sock is None:
            return self.queue(obj)
        await self._sock.send(json.dumps(obj))
        log.debug("ws -> %s", _frame_kind(obj))

    async def listen_forever(self):
        backoff = 1
        while not self._stop.is_set():
            try:
                await self.connect_and_hello()
                backoff = 1
                async for raw in self._sock:
                    try:
                        frame = json.loads(raw)
                    except ValueError:
                        continue
                    log.debug("ws <- %s", _frame_kind(frame))
                    try:
                        self._on_frame(frame)
                    except Exception:  # never let UI callbacks kill the loop
                        log.exception("ws on_frame failed")
            except Exception as e:
                log.debug("ws down (%s); retry in %ss", e, backoff)
                self._sock = None
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def run_in_thread(self):
        t = threading.Thread(target=lambda: asyncio.run(self.listen_forever()),
                             name="chronos-ws", daemon=True)
        t.start()
        return t

    def stop(self):
        self._stop.set()
