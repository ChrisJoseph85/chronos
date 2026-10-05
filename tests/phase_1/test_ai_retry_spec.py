"""Phase 2 retry/failover spec tests — Chronos.md §5.2 + decisions (Phase 2: 1, 4).

Spec-only contract. Implementation surface pinned here:

  chronos.ai.providers.worker.RetryWorker
      __init__(providers, *, max_inflight=RETRY_MAX_INFLIGHT,
               skip_after_seconds=RETRY_SKIP_AFTER_SECONDS,
               sleep=None, clock=None)
          providers: objects with .name + .complete(payload);
                     failure = raise TimeoutError/ConnectionError/HTTPError.
          sleep(seconds): injectable, records instead of waiting.
          clock(): injectable, returns seconds (float).
      .submit(payload) -> job (.id, .status == "queued" immediately)
      .drain(max_steps=...)      # synchronous test pump, no threads needed
      .status_of(job_id) -> job (.status in queued/retrying/skipped/done)
      .attempt_log               # list of provider names tried, in order
      .can_skip(job_id) -> bool
      .skip(job_id)              # terminal state "skipped"
      .inflight_count() -> int
      .queued_count() -> int
  chronos.ai.providers.worker.compute_backoff(attempt) -> float seconds
  chronos.ai.providers.worker.RETRY_SKIP_AFTER_SECONDS == 120
  chronos.ai.providers.worker.RETRY_MAX_INFLIGHT (int)

Decisions applied: chain cycles in configured order (ruling 1);
first attempt is immediate, later retries are background (ruling 4).
Backend-only freeze (2026-10-05): NO token-cost table assertions anywhere.
No network: providers are fakes raising stdlib errors.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import socket
import time
import urllib.error
import urllib.request

import pytest

SPEC = "docs/server/Chronos.md §5.2"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network blocked in phase-2 tests: inject fakes (%s)" % SPEC)

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)


# ---------------------------------------------------------------- helpers

def _load_worker():
    try:
        from chronos.ai.providers import worker as w
        return w
    except Exception as exc:
        pytest.fail("%s: missing chronos.ai.providers.worker (%s)" % (SPEC, exc))


def _http_error(code):
    return urllib.error.HTTPError("http://fake/v1", code, "fake-%d" % code, {}, None)


class FakeProvider:
    def __init__(self, name, failures_before_success, error=None):
        self.name = name
        self.failures_before_success = failures_before_success
        self.error = error if error is not None else _http_error(429)
        self.calls = 0

    def complete(self, payload):
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise self.error
        return "ok-from-%s" % self.name


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeSleep:
    def __init__(self, clock):
        self.clock = clock
        self.durations = []

    def __call__(self, seconds):
        self.durations.append(seconds)
        self.clock.advance(seconds)


def _make_worker(w, providers, **overrides):
    kwargs = {
        "max_inflight": overrides.get("max_inflight", w.RETRY_MAX_INFLIGHT),
        "skip_after_seconds": overrides.get("skip_after_seconds", w.RETRY_SKIP_AFTER_SECONDS),
    }
    clock = overrides.get("clock", FakeClock())
    sleep = FakeSleep(clock)
    kwargs["clock"] = clock
    kwargs["sleep"] = sleep
    try:
        worker = w.RetryWorker(list(providers), **kwargs)
    except TypeError as exc:
        pytest.fail(
            "%s: RetryWorker must accept (providers, *, max_inflight=, skip_after_seconds=, "
            "sleep=, clock=) (%s)" % (SPEC, exc)
        )
    worker._test_clock = clock
    worker._test_sleep = sleep
    return worker


# ---------------------------------------------------------------- tests

def test_failover_never_raises_to_caller_absolute():
    """§5.2: failover never raises to the caller. Absolute — all providers dead."""
    w = _load_worker()
    providers = [
        FakeProvider("cloudflare", 10 ** 9, _http_error(500)),
        FakeProvider("groq", 10 ** 9, TimeoutError("t")),
        FakeProvider("nim", 10 ** 9, _http_error(429)),
    ]
    worker = _make_worker(w, providers)
    try:
        job = worker.submit({"messages": [{"role": "user", "content": "hi"}]})
        worker.drain(max_steps=12)
        final = worker.status_of(job.id)
    except Exception as exc:
        pytest.fail("%s: worker raised to caller with all providers failing: %r" % (SPEC, exc))
    assert final.status in ("queued", "retrying", "skipped"), \
        "%s: dead providers must leave job queued/retrying/skipped, got %r" % (SPEC, final.status)


def test_request_path_returns_immediately_with_queued_result():
    """§5.2: never on the request path — say/tool returns at once with queued result."""
    w = _load_worker()
    providers = [FakeProvider("cloudflare", 10 ** 9), FakeProvider("groq", 10 ** 9)]
    worker = _make_worker(w, providers)
    started = time.monotonic()
    job = worker.submit({"messages": [{"role": "user", "content": "hi"}]})
    elapsed = time.monotonic() - started
    assert job.status == "queued", "%s: submit must return status 'queued', got %r" % (SPEC, job.status)
    assert job.id is not None, "%s: queued job must carry an id" % SPEC
    assert elapsed < 1.0, "%s: submit blocked %.3fs on the request path" % (SPEC, elapsed)


def test_backoff_grows_exponentially_with_jitter_no_tight_loop():
    """§5.2: background worker uses exponential backoff plus jitter, never a tight loop."""
    w = _load_worker()
    assert w.compute_backoff(0) > 0, "%s: backoff(0) must be positive (no tight loop)" % SPEC
    samples_1 = [w.compute_backoff(1) for _ in range(25)]
    samples_5 = [w.compute_backoff(5) for _ in range(25)]
    mean_1 = sum(samples_1) / len(samples_1)
    mean_5 = sum(samples_5) / len(samples_5)
    assert mean_5 > mean_1, \
        "%s: backoff must grow exponentially (mean(5)=%.3f not > mean(1)=%.3f)" % (SPEC, mean_5, mean_1)
    assert len(set(samples_5)) > 1, "%s: backoff must include jitter (all 25 samples identical)" % SPEC
    assert min(samples_1) >= 0, "%s: backoff must never be negative" % SPEC


def test_worker_cycles_cloudflare_groq_nim_on_429_5xx_timeout():
    """§5.2: worker cycles Cloudflare → Groq → NIM on 429, 5xx and timeout."""
    w = _load_worker()
    providers = [
        FakeProvider("cloudflare", 10 ** 9, _http_error(429)),
        FakeProvider("groq", 10 ** 9, _http_error(503)),
        FakeProvider("nim", 10 ** 9, TimeoutError("t")),
    ]
    worker = _make_worker(w, providers)
    job = worker.submit({"messages": [{"role": "user", "content": "hi"}]})
    worker.drain(max_steps=6)
    log = list(worker.attempt_log)
    assert log[0:3] == ["cloudflare", "groq", "nim"], \
        "%s: attempts must cycle in configured order, got %r" % (SPEC, log[0:3])
    assert log[3:6] == ["cloudflare", "groq", "nim"], \
        "%s: cycle must repeat in order, got %r" % (SPEC, log[3:6])
    assert worker.status_of(job.id).status in ("queued", "retrying", "skipped"), \
        "%s: job must still be pending after 6 failed attempts" % SPEC


def test_retry_skip_after_seconds_defaults_to_120():
    """§5.2: RETRY_SKIP_AFTER_SECONDS defaults to 120."""
    w = _load_worker()
    assert w.RETRY_SKIP_AFTER_SECONDS == 120, \
        "%s: RETRY_SKIP_AFTER_SECONDS must default to 120, got %r" % (SPEC, w.RETRY_SKIP_AFTER_SECONDS)


def test_manual_skip_offered_after_skip_timeout_and_honored():
    """§5.2: after RETRY_SKIP_AFTER_SECONDS the client is offered a manual skip."""
    w = _load_worker()
    providers = [FakeProvider("groq", 10 ** 9, _http_error(500))]
    worker = _make_worker(w, providers, skip_after_seconds=120)
    job = worker.submit({"messages": [{"role": "user", "content": "hi"}]})
    worker.drain(max_steps=3)
    assert worker.can_skip(job.id) is False, \
        "%s: skip must not be offered before the timeout" % SPEC
    worker._test_clock.advance(121)
    worker.drain(max_steps=1)
    assert worker.can_skip(job.id) is True, \
        "%s: skip must be offered after RETRY_SKIP_AFTER_SECONDS" % SPEC
    worker.skip(job.id)
    assert worker.status_of(job.id).status == "skipped", \
        "%s: skipped job must reach terminal state 'skipped'" % SPEC


def test_max_inflight_caps_excess_queues():
    """§5.2: RETRY_MAX_INFLIGHT caps concurrent retry jobs; excess queue."""
    w = _load_worker()
    assert isinstance(w.RETRY_MAX_INFLIGHT, int), \
        "%s: RETRY_MAX_INFLIGHT must be an int" % SPEC
    providers = [FakeProvider("groq", 10 ** 9, _http_error(500))]
    worker = _make_worker(w, providers, max_inflight=2)
    jobs = [worker.submit({"n": i}) for i in range(5)]
    assert len(jobs) == 5, "%s: all 5 submits must be accepted" % SPEC
    assert worker.inflight_count() == 2, \
        "%s: inflight must be capped at 2, got %r" % (SPEC, worker.inflight_count())
    assert worker.queued_count() == 3, \
        "%s: excess must queue (expected 3, got %r)" % (SPEC, worker.queued_count())
