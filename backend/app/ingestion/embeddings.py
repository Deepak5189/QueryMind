"""
Pluggable embedding provider for schema/glossary RAG.

EMBEDDING_PROVIDER=local  (default)
    Stateless scikit-learn HashingVectorizer -> dense projection, L2
    normalized. No API key, no model download (unlike sentence-transformers,
    which pulls a ~90MB+ torch-based model). Semantic quality is weaker than
    a real embedding model (it's bag-of-words hashing, not learned
    semantics) but it's deterministic, fast, and free — good enough to
    prove the ingest -> pgvector -> cosine-similarity pipeline end to end
    in Phase 1. Swap to a real model/API in Phase 2 by setting
    EMBEDDING_PROVIDER=openai (or extend this module with an Anthropic/
    local sentence-transformers backend) without touching any caller code.

EMBEDDING_PROVIDER=openai
    Calls OpenAI's embeddings endpoint (text-embedding-3-small by default).
    Requires OPENAI_API_KEY.

Both providers implement the same interface:
    embed(texts: list[str]) -> list[list[float]]
    dim: int
"""

import hashlib
import os
import struct

import numpy as np
from dotenv import load_dotenv

load_dotenv()

LOCAL_EMBEDDING_DIM = 384


class LocalHashingEmbedder:
    """
    Deterministic, dependency-light "embedding" for local dev/demo use.

    Approach: hash each token into one of `dim` buckets (signed, so
    collisions partially cancel instead of only adding), scale by a
    simple log-count term-frequency weighting, then L2-normalize. This is
    intentionally simple — it's a stand-in for a real embedding model, not
    a replacement for one. It captures shared-vocabulary similarity (e.g.
    a query containing "transaction" and "state" will score docs that also
    mention "transaction" and "state" highly) which is enough to sanity
    check the retrieval pipeline, but it does not capture synonyms or
    deeper semantics the way a trained model would.
    """

    def __init__(self, dim: int = LOCAL_EMBEDDING_DIM):
        self.dim = dim

    def _hash_token(self, token: str) -> tuple[int, int]:
        digest = hashlib.md5(token.encode("utf-8")).digest()
        bucket = struct.unpack("I", digest[:4])[0] % self.dim
        sign = 1 if digest[4] % 2 == 0 else -1
        return bucket, sign

    def _embed_one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float64)
        tokens = [t for t in "".join(c.lower() if c.isalnum() else " " for c in text).split() if t]
        for token in tokens:
            bucket, sign = self._hash_token(token)
            vec[bucket] += sign * (1.0 + np.log(1.0))  # simple presence weight
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t).tolist() for t in texts]


class OpenAIEmbedder:
    def __init__(self, model: str | None = None):
        from openai import OpenAI  # imported lazily so it's an optional dep

        self.client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        self.model = model or os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.dim = 1536 if "3-small" in self.model else 3072

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]


def get_embedder():
    provider = os.environ.get("EMBEDDING_PROVIDER", "local").lower()
    if provider == "local":
        return LocalHashingEmbedder()
    if provider == "openai":
        return OpenAIEmbedder()
    raise ValueError(f"Unknown EMBEDDING_PROVIDER: {provider!r} (expected 'local' or 'openai')")
