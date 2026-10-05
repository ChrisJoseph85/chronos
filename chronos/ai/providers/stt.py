"""Single STT adapter: no failover, one speech endpoint + one model.

Uses OpenAICompatibleAdapter under the hood; only the base URL and the
whisper model differ from the text group.
"""

from chronos.ai.providers.adapter import DEFAULT_STT_MODEL


class SpeechTranscriber:
    """Thin wrapper over a speech-group adapter (single adapter, no failover)."""

    def __init__(self, adapter):
        self.adapter = adapter

    @property
    def model(self):
        return getattr(self.adapter, "model", DEFAULT_STT_MODEL)

    def transcribe(self, audio_text):
        messages = [{"role": "user", "content": audio_text}]
        return self.adapter.complete(messages)
