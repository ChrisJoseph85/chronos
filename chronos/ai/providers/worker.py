"""Background retry worker: first attempt sync, retries in background.

Failover never raises to the caller; jobs stay queued/retrying until they
succeed or are skipped. Pure stdlib; no threads needed in tests (drain pump).
"""

import itertools
import random

RETRY_SKIP_AFTER_SECONDS = 120
RETRY_MAX_INFLIGHT = 4


def compute_backoff(attempt):
    base = 1.0 * (2.0 ** max(0, int(attempt)))
    capped = min(base, 60.0)
    return capped + random.uniform(0, 1.0)


class Job:
    def __init__(self, job_id, payload, created_at):
        self.id = job_id
        self.payload = payload
        self.status = "queued"
        self.created_at = created_at
        self.attempts = 0
        self.result = None


class RetryWorker:
    def __init__(self, providers, *, max_inflight=RETRY_MAX_INFLIGHT,
                 skip_after_seconds=RETRY_SKIP_AFTER_SECONDS,
                 sleep=None, clock=None):
        import time
        self.providers = list(providers)
        self.max_inflight = max_inflight
        self.skip_after_seconds = skip_after_seconds
        self.sleep = sleep if sleep is not None else time.sleep
        self.clock = clock if clock is not None else time.time
        self.attempt_log = []
        self._jobs = {}
        self._order = []
        self._ids = itertools.count(1)

    # -- submission (request path: returns immediately) -------------------
    def submit(self, payload):
        job = Job("job-%d" % next(self._ids), payload, self.clock())
        self._jobs[job.id] = job
        self._order.append(job.id)
        return job

    # -- inspection --------------------------------------------------------
    def status_of(self, job_id):
        return self._jobs[job_id]

    def _pending_ids(self):
        return [jid for jid in self._order
                if self._jobs[jid].status in ("queued", "retrying")]

    def inflight_count(self):
        return min(len(self._pending_ids()), self.max_inflight)

    def queued_count(self):
        return max(0, len(self._pending_ids()) - self.max_inflight)

    def _active_ids(self):
        return self._pending_ids()[:self.max_inflight]

    # -- background pump ---------------------------------------------------
    def drain(self, max_steps=100):
        for _ in range(max_steps):
            active = self._active_ids()
            if not active:
                return
            progressed = False
            for jid in active:
                job = self._jobs[jid]
                if job.status not in ("queued", "retrying"):
                    continue
                self._attempt(job)
                progressed = True
            if not progressed:
                return

    def _attempt(self, job):
        if not self.providers:
            return
        provider = self.providers[job.attempts % len(self.providers)]
        self.attempt_log.append(provider.name)
        try:
            job.result = provider.complete(job.payload)
        except Exception:  # noqa: BLE001 -- failover never raises
            job.attempts += 1
            job.status = "retrying"
            try:
                self.sleep(compute_backoff(job.attempts))
            except Exception:  # noqa: BLE001
                pass
            return
        job.attempts += 1
        job.status = "done"

    # -- manual skip -------------------------------------------------------
    def can_skip(self, job_id):
        job = self._jobs[job_id]
        if job.status in ("done", "skipped"):
            return False
        return (self.clock() - job.created_at) >= self.skip_after_seconds

    def skip(self, job_id):
        self._jobs[job_id].status = "skipped"
