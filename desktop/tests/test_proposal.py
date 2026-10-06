"""Proposal flow tests: say -> proposal_id -> WS accept/reject. Fakes only."""
import asyncio
import json

from desktop.app.state import AppState
from desktop.app.transport import ChronosClient, WsClient


class FakeResp:
    status = 200

    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode()


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        raise StopAsyncIteration


def test_say_proposal_then_ws_accept():
    def opener(req):
        return FakeResp({"intent": "schedule", "proposal_id": "p-1",
                         "committed": False, "message": "book it?"})

    c = ChronosClient("http://127.0.0.1:8080", key="K", opener=opener)
    res = c.say("schedule dentist tuesday")
    assert res["proposal_id"] == "p-1"

    sock = FakeSocket()

    async def connect(uri, headers):
        assert headers["X-Chronos-Key"] == "K"
        return sock

    frames = []
    ws = WsClient("http://127.0.0.1:8080", "K", on_frame=frames.append, connect_fn=connect)
    asyncio.run(ws.connect_and_hello())
    assert sock.sent[0] == {"hello": {"key": "K", "device": "desktop"}}
    asyncio.run(ws.send({"accept": "p-1"}))
    assert {"accept": "p-1"} in sock.sent


def test_ws_reject_and_queue_before_connect():
    sock = FakeSocket()

    async def connect(uri, headers):
        return sock

    ws = WsClient("http://127.0.0.1:8080", "K", connect_fn=connect)
    ws.queue({"reject": "p-9"})  # queued while disconnected
    asyncio.run(ws.connect_and_hello())
    assert {"reject": "p-9"} in sock.sent


def test_state_stores_proposal_and_question_frames():
    st = AppState()
    assert st.update_from_frame({"proposal": {"proposal_id": "p-1", "message": "m"}}) == "proposal"
    assert "p-1" in st.proposals
    assert st.update_from_frame({"question": {"text": "q?"}}) == "question"
    assert st.questions == [{"text": "q?"}]
    assert st.update_from_frame({"timer": {"label": "x"}}) == "timer"
    assert st.timer_session == {"label": "x"}
    assert st.take_proposal("p-1") == {"proposal_id": "p-1", "message": "m"}
    assert st.take_proposal("p-1") is None
