"""Notify tests: poll floor >=30s, dedupe, milestone texts. Fakes only."""
from desktop.app.notify import (MIN_POLL_S, briefing_question_text, clamp_interval,
                                milestone_text, poll_once, reminder_text)


class FakeClient:
    def __init__(self, reminders):
        self._reminders = reminders

    def reminders(self):
        return self._reminders


class FakeNotifier:
    def __init__(self):
        self.sent = []

    def send(self, title, body=""):
        self.sent.append((title, body))
        return "fake"


def test_poll_floor_never_below_30():
    assert MIN_POLL_S == 30
    assert clamp_interval(1) == 30
    assert clamp_interval(29.9) == 30
    assert clamp_interval(30) == 30
    assert clamp_interval(120) == 120


def test_poll_once_notifies_unseen_only():
    n = FakeNotifier()
    seen = poll_once(FakeClient([{"id": "r1", "text": "standup"}]), n, set())
    assert seen == {"r1"} and len(n.sent) == 1
    seen = poll_once(FakeClient([{"id": "r1", "text": "standup"}]), n, seen)
    assert len(n.sent) == 1  # no dupe
    seen = poll_once(FakeClient([{"id": "r1", "text": "x"}, {"id": "r2", "text": "y"}]),
                     n, seen)
    assert len(n.sent) == 2


def test_poll_failure_is_silent():
    class Boom:
        def reminders(self):
            raise ConnectionError("down")

    n = FakeNotifier()
    assert poll_once(Boom(), n, set()) == set()
    assert n.sent == []


def test_milestone_and_briefing_texts():
    assert milestone_text("start", {"label": "deep work"})[0] == "Timer started"
    t, b = milestone_text("void", {"label": "email"})
    assert t == "Session voided" and "email" in b
    assert milestone_text("stop", {"label": "x"})[0] == "Timer stopped"
    assert briefing_question_text({"question": {"text": "carry over?"}})[1] == "carry over?"
    assert briefing_question_text({}) is None
    assert reminder_text({"text": "dentist"}) == ("Chronos reminder", "dentist")
