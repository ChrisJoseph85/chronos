"""Single OpenAI-compatible adapter for text, speech and embeddings.

Only base URL + model differ between groups; the wire shape is identical.
No network here: HTTP goes through the injected ``transport`` callable.
"""

DEFAULT_TEXT_MODEL = "openai/gpt-oss-120b"
DEFAULT_TEXT_PROVIDER = "groq"
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NIM_MODEL = "nvidia/nemotron-3-super-120b-a12b"
DEFAULT_STT_MODEL = "whisper-large-v3-turbo"
DEFAULT_EMBEDDING_MODEL = "llama-embedding"
DEFAULT_EMBEDDING_ENDPOINT = "llama-embedding"


class OpenAICompatibleAdapter:
    """One adapter class for all three provider groups."""

    def __init__(self, *, base_url, model, api_keys, name=None, transport=None):
        self.base_url = base_url
        self.model = model
        self.api_keys = list(api_keys) if api_keys else []
        self.name = name
        self.transport = transport
        self._key_index = 0

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_keys:
            key = self.api_keys[self._key_index % len(self.api_keys)]
            headers["Authorization"] = "Bearer %s" % key
        return headers

    def complete(self, messages):
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {"model": self.model, "messages": list(messages)}
        headers = self._headers()
        if self.api_keys:
            self._key_index = (self._key_index + 1) % len(self.api_keys)
        if self.transport is None:
            raise RuntimeError("no transport injected for adapter %r" % (self.name,))
        response = self.transport(url, headers, payload)
        return response["choices"][0]["message"]["content"]
