"""Phase 2 providers spec tests — Chronos.md §5.1.

Spec-only contract. The code agent owns `chronos/ai/` (unreadable here);
these tests pin the public surface the implementation must provide:

  adapter: chronos.ai.providers.adapter.OpenAICompatibleAdapter
      __init__(*, base_url, model, api_keys, name=None, transport=None)
      .complete(messages) -> str   (uses transport, never the network)
      transport(url, headers, payload) -> {"choices": [{"message": {"content": ...}}]}
  chain:   chronos.ai.providers.chain.ProviderChain
      __init__(providers)  # objects with .name + .complete(messages)
      .names() -> [str]    # entry order preserved
      .complete(messages)  # failover in order on 429/5xx/timeout
  setup:   chronos.ai.setup (fallback: chronos.ai.providers.setup)
      .SETUP_GROUPS == ["stt", "text", "embeddings"]
  defaults: chronos.ai.providers.defaults (fallback: adapter module attrs)
      DEFAULT_TEXT_MODEL, DEFAULT_TEXT_PROVIDER, NIM_BASE_URL, NIM_MODEL,
      DEFAULT_STT_MODEL, DEFAULT_EMBEDDING_MODEL, DEFAULT_EMBEDDING_ENDPOINT

Backend-only freeze (2026-10-05): no token-cost anywhere in these tests.
No network: all HTTP goes through injected FakeTransport.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import socket
import urllib.error
import urllib.request

import pytest

SPEC = "docs/server/Chronos.md §5.1"

NIM_URL = "https://integrate.api.nvidia.com/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
NIM_MODEL = "nvidia/nemotron-3-super-120b-a12b"
STT_MODEL = "whisper-large-v3-turbo"
EMB_MODEL = "llama-embedding"
EMB_ENDPOINT = "llama-embedding"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network blocked in phase-2 tests: inject fakes (%s)" % SPEC)

    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)


# ---------------------------------------------------------------- helpers

class FakeTransport:
    """Injectable OpenAI-compatible HTTP stand-in. No network."""

    def __init__(self, content="ok", status=200):
        self.content = content
        self.status = status
        self.calls = []

    def __call__(self, url, headers, payload):
        self.calls.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        if self.status >= 400:
            raise urllib.error.HTTPError(url, self.status, "fake", {}, None)
        return {"choices": [{"message": {"content": self.content}}]}


def _load_adapter():
    try:
        from chronos.ai.providers.adapter import OpenAICompatibleAdapter
        return OpenAICompatibleAdapter
    except Exception as exc:
        pytest.fail("%s: missing chronos.ai.providers.adapter.OpenAICompatibleAdapter (%s)" % (SPEC, exc))


def _load_chain():
    try:
        from chronos.ai.providers.chain import ProviderChain
        return ProviderChain
    except Exception as exc:
        pytest.fail("%s: missing chronos.ai.providers.chain.ProviderChain (%s)" % (SPEC, exc))


def _load_setup_module():
    for path in ("chronos.ai.setup", "chronos.ai.providers.setup"):
        try:
            __import__(path)
            return sys.modules[path]
        except Exception:
            continue
    pytest.fail(
        "%s: missing setup module (tried chronos.ai.setup, chronos.ai.providers.setup); "
        "it must expose SETUP_GROUPS == ['stt', 'text', 'embeddings']" % SPEC
    )


def _load_defaults():
    try:
        from chronos.ai.providers import defaults as d
        return d
    except Exception:
        try:
            from chronos.ai.providers import adapter as a
            return a
        except Exception as exc:
            pytest.fail(
                "%s: missing provider defaults (tried chronos.ai.providers.defaults, "
                "chronos.ai.providers.adapter attrs) (%s)" % (SPEC, exc)
            )


def _make_adapter(cls, base_url, model, keys, name, transport):
    try:
        return cls(base_url=base_url, model=model, api_keys=list(keys), name=name, transport=transport)
    except TypeError as exc:
        pytest.fail(
            "%s: OpenAICompatibleAdapter must accept "
            "(base_url=, model=, api_keys=, name=, transport=) (%s)" % (SPEC, exc)
        )


class FakeProvider:
    def __init__(self, name, behaviour):
        self.name = name
        self.behaviour = behaviour
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        outcome = self.behaviour(self.calls)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _http_error(code):
    return urllib.error.HTTPError("http://fake/v1", code, "fake-%d" % code, {}, None)


# ---------------------------------------------------------------- tests

def test_single_openai_compatible_adapter_class():
    """§5.1: one adapter serves text, speech and embeddings (URL+model differ)."""
    cls = _load_adapter()
    t = FakeTransport()
    a = _make_adapter(cls, "https://api.groq.com/openai/v1", GROQ_DEFAULT_MODEL, ["k1"], "groq", t)
    b = _make_adapter(cls, "https://stt.local/v1", STT_MODEL, ["k2"], "stt", t)
    c = _make_adapter(cls, "http://127.0.0.1:11434/v1", EMB_MODEL, [], "embeddings", t)
    assert type(a) is type(b) is type(c), "%s: text/speech/embeddings must share one adapter class" % SPEC


def test_three_groups_configurable_independently():
    """§5.1: three independent provider groups, only base URL and model differ."""
    cls = _load_adapter()
    groups = [
        ("groq", "https://api.groq.com/openai/v1", GROQ_DEFAULT_MODEL),
        ("stt", "https://stt.local/v1", STT_MODEL),
        ("embeddings", "http://127.0.0.1:11434/v1", EMB_MODEL),
    ]
    adapters = [_make_adapter(cls, url, model, ["k"], name, FakeTransport()) for name, url, model in groups]
    models = [a.model for a in adapters]
    assert models == [GROQ_DEFAULT_MODEL, STT_MODEL, EMB_MODEL], "%s: groups differ by model" % SPEC
    urls = [a.base_url for a in adapters]
    assert urls[0] != urls[1], "%s: text and speech endpoints must differ" % SPEC


def test_adapter_sends_openai_compatible_shape():
    """§5.1: all groups speak OpenAI-compatible shapes (model + messages)."""
    cls = _load_adapter()
    t = FakeTransport(content="hello")
    a = _make_adapter(cls, "https://api.groq.com/openai/v1", GROQ_DEFAULT_MODEL, ["k1"], "groq", t)
    messages = [{"role": "user", "content": "hi"}]
    out = a.complete(messages)
    assert out == "hello", "%s: adapter must return the choice content" % SPEC
    assert len(t.calls) == 1, "%s: exactly one HTTP call expected" % SPEC
    assert t.calls[0]["payload"]["model"] == GROQ_DEFAULT_MODEL, "%s: payload model mismatch" % SPEC
    assert t.calls[0]["payload"]["messages"] == messages, "%s: payload messages mismatch" % SPEC


def test_nim_uses_cloud_url_not_self_hosted():
    """§5.1: NIM appears solely as the free cloud endpoint, never self-hosted."""
    d = _load_defaults()
    url = getattr(d, "NIM_BASE_URL", None)
    assert url == NIM_URL, "%s: NIM base URL must be exactly %s, got %r" % (SPEC, NIM_URL, url)
    assert url != "http://127.0.0.1:11434/v1", "%s: NIM must not point at localhost" % SPEC


def test_default_text_model_is_gpt_oss_on_groq():
    """§5.1: default text model is openai/gpt-oss-120b on Groq."""
    d = _load_defaults()
    assert getattr(d, "DEFAULT_TEXT_MODEL", None) == GROQ_DEFAULT_MODEL, \
        "%s: DEFAULT_TEXT_MODEL must be %s" % (SPEC, GROQ_DEFAULT_MODEL)
    assert getattr(d, "DEFAULT_TEXT_PROVIDER", None) == "groq", \
        "%s: DEFAULT_TEXT_PROVIDER must be 'groq'" % SPEC


def test_nim_leg_uses_nemotron_never_gpt_oss():
    """§5.1: NIM returns 410 for gpt-oss, so the NIM leg stays on Nemotron."""
    d = _load_defaults()
    assert getattr(d, "NIM_MODEL", None) == NIM_MODEL, \
        "%s: NIM leg model must be %s" % (SPEC, NIM_MODEL)
    assert getattr(d, "NIM_MODEL", None) != GROQ_DEFAULT_MODEL, \
        "%s: NIM leg must never name the model the provider rejects (410)" % SPEC


def test_speech_model_whisper_not_text_model():
    """§5.1: speech is whisper-large-v3-turbo; speech cannot use the text model."""
    d = _load_defaults()
    assert getattr(d, "DEFAULT_STT_MODEL", None) == STT_MODEL, \
        "%s: DEFAULT_STT_MODEL must be %s" % (SPEC, STT_MODEL)
    assert getattr(d, "DEFAULT_STT_MODEL", None) != getattr(d, "DEFAULT_TEXT_MODEL", None), \
        "%s: speech must not reuse the text model" % SPEC


def test_embeddings_default_local_not_text_model():
    """§5.1: embeddings default to local llama-embedding, not the text model."""
    d = _load_defaults()
    assert getattr(d, "DEFAULT_EMBEDDING_MODEL", None) == EMB_MODEL, \
        "%s: DEFAULT_EMBEDDING_MODEL must be %s" % (SPEC, EMB_MODEL)
    assert getattr(d, "DEFAULT_EMBEDDING_ENDPOINT", None) == EMB_ENDPOINT, \
        "%s: DEFAULT_EMBEDDING_ENDPOINT must be %s" % (SPEC, EMB_ENDPOINT)
    assert getattr(d, "DEFAULT_EMBEDDING_MODEL", None) != getattr(d, "DEFAULT_TEXT_MODEL", None), \
        "%s: embeddings must not reuse the text model" % SPEC


def test_setup_group_order_stt_then_text_then_embeddings():
    """§5.1: interactive setup order is STT → text → embeddings."""
    mod = _load_setup_module()
    groups = getattr(mod, "SETUP_GROUPS", None)
    assert list(groups) == ["stt", "text", "embeddings"], \
        "%s: SETUP_GROUPS must be ['stt', 'text', 'embeddings'], got %r" % (SPEC, groups)


def test_failover_order_is_entry_order():
    """§5.1: the order text providers are entered IS the failover order."""
    Chain = _load_chain()
    first = FakeProvider("groq", lambda n: _http_error(429))
    second = FakeProvider("nim", lambda n: "second-wins")
    chain = Chain([first, second])
    assert chain.names() == ["groq", "nim"], "%s: chain must preserve entry order" % SPEC
    out = chain.complete([{"role": "user", "content": "hi"}])
    assert out == "second-wins", "%s: chain must fall through to the next provider on 429" % SPEC
    assert first.calls == 1, "%s: first provider must be tried first" % SPEC
    assert second.calls == 1, "%s: second provider must be tried after first fails" % SPEC


def test_multi_key_round_robin_before_fallthrough():
    """§5.1: multiple keys per endpoint tried round-robin before falling through."""
    cls = _load_adapter()
    t = FakeTransport(content="x")
    a = _make_adapter(cls, "https://api.groq.com/openai/v1", GROQ_DEFAULT_MODEL, ["k1", "k2"], "groq", t)
    messages = [{"role": "user", "content": "hi"}]
    for _ in range(4):
        a.complete(messages)
    bearers = [c["headers"].get("Authorization") for c in t.calls]
    assert bearers == ["Bearer k1", "Bearer k2", "Bearer k1", "Bearer k2"], \
        "%s: keys must cycle round-robin, got %r" % (SPEC, bearers)
