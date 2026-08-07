"""Embedding generation service."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("app")
settings = get_settings()


class Embedder:
    """Generates embeddings for documents and queries.

    Uses the configured embedding model. Falls back to a local
    sentence-transformers model when no API key is configured, or when the
    configured key fails at call time (quota, billing, revocation).
    """

    def __init__(self) -> None:
        self._client = None
        self._local_model = None
        self._backend = None
        self._init_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Lazily initialize the embedding backend."""
        if self._backend is not None:
            return
        async with self._init_lock:
            if self._backend is not None:  # re-check: lost the race to init
                return
            if settings.openai_api_key:
                try:
                    from openai import OpenAI

                    # The local-model fallback covers retrying elsewhere -
                    # the SDK's own internal retries (default 2, with
                    # backoff) just add seconds of dead time to every single
                    # embed() call before that fallback ever gets a chance.
                    self._client = OpenAI(api_key=settings.openai_api_key, max_retries=0)
                    self._backend = "openai"
                    return
                except Exception as exc:  # noqa: BLE001
                    logger.warning("OpenAI embedding init failed: %s", exc)
            await self._load_local_model()

    async def _load_local_model(self) -> None:
        """Load the local sentence-transformers model off the event loop.

        Model construction is a synchronous, CPU/IO-bound call that can take
        real seconds on first load - running it inline here would stall
        every other request this server is handling for that entire time.
        """
        if self._local_model is not None:
            self._backend = "local"
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._local_model = await asyncio.to_thread(SentenceTransformer, "all-MiniLM-L6-v2")
            self._backend = "local"
            logger.info("Using local embedding model")
        except Exception as exc:  # noqa: BLE001
            logger.error("No embedding backend available: %s", exc)
            self._backend = "hash"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts."""
        await self.initialize()
        if not texts:
            return []
        if self._backend == "openai" and self._client:
            try:
                response = await asyncio.to_thread(
                    self._client.embeddings.create, model=settings.embedding_model, input=texts
                )
                return [item.embedding for item in response.data]
            except Exception as exc:  # noqa: BLE001
                # A configured key can still fail at call time (quota,
                # billing, revocation) even though it passed init - degrade
                # to the local model rather than breaking every search, and
                # switch `_backend` so later calls skip straight past the
                # now-known-broken key instead of re-failing on it every time.
                logger.warning("OpenAI embedding call failed, falling back to local model: %s", exc)
                await self._load_local_model()
        if self._local_model:
            encoded = await asyncio.to_thread(self._local_model.encode, texts)
            return encoded.tolist()
        # Last-resort fallback: deterministic hash-based embedding
        return [self._hash_embedding(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        embeddings = await self.embed([text])
        return embeddings[0] if embeddings else []

    def _hash_embedding(self, text: str, dim: int = 768) -> list[float]:
        """Deterministic fallback embedding (hash-based)."""
        import hashlib

        vector = []
        for i in range(dim):
            digest = hashlib.sha256(f"{text}:{i}".encode()).digest()
            vector.append(int.from_bytes(digest[:4], "big") / 2**32 - 0.5)
        return vector
