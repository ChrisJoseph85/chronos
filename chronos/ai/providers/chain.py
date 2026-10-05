"""Failover chain: entry order IS the failover order."""

import urllib.error


def _retryable(exc):
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or 500 <= exc.code < 600
    if isinstance(exc, urllib.error.URLError):
        return True
    return False


class ProviderChain:
    def __init__(self, providers):
        self.providers = list(providers)

    def names(self):
        return [p.name for p in self.providers]

    def complete(self, messages):
        last = None
        for provider in self.providers:
            try:
                return provider.complete(messages)
            except Exception as exc:  # noqa: BLE001 -- failover, never raise mid-chain
                if not _retryable(exc):
                    raise
                last = exc
        if last is not None:
            raise last
        raise RuntimeError("empty provider chain")
