"""Provider defaults (single adapter + configs, no provider-specific paths)."""

from chronos.ai.providers.adapter import (
    DEFAULT_TEXT_MODEL,
    DEFAULT_TEXT_PROVIDER,
    NIM_BASE_URL,
    NIM_MODEL,
    DEFAULT_STT_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_ENDPOINT,
)

__all__ = [
    "DEFAULT_TEXT_MODEL",
    "DEFAULT_TEXT_PROVIDER",
    "NIM_BASE_URL",
    "NIM_MODEL",
    "DEFAULT_STT_MODEL",
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_EMBEDDING_ENDPOINT",
]
