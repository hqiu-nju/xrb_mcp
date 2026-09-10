from functools import lru_cache
from typing import Protocol

import numpy as np

from xrb_mcp.server.config import get_settings


class EmbeddingBackend(Protocol):
    model: str
    version: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def checked_embeddings(backend: EmbeddingBackend, texts: list[str]) -> list[list[float]]:
    vectors = backend.embed(texts)
    array = np.asarray(vectors, dtype=float)
    if array.shape != (len(texts), backend.dimension):
        raise ValueError("Embedding backend returned an incorrect batch shape")
    if not np.isfinite(array).all() or (np.linalg.norm(array, axis=1) == 0).any():
        raise ValueError("Embeddings must be finite, nonzero vectors")
    return array.tolist()


class SentenceTransformerBackend:
    def __init__(self, model: str, revision: str):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Install xrb-mcp[embeddings] to enable semantic retrieval") from exc
        self.encoder = SentenceTransformer(model, revision=revision, trust_remote_code=False)
        self.model = model
        # Record resolved weights when the underlying transformer exposes a commit hash.
        config = self.encoder[0].auto_model.config
        self.version = getattr(config, "_commit_hash", None) or revision
        self.dimension = self.encoder.get_sentence_embedding_dimension()

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Avoid silent truncation: average normalized embeddings of tokenizer-sized windows.
        tokenizer = self.encoder.tokenizer
        limit = self.encoder.max_seq_length - tokenizer.num_special_tokens_to_add(pair=False)
        windows: list[str] = []
        spans: list[tuple[int, int]] = []
        for text in texts:
            tokens = tokenizer.encode(text, add_special_tokens=False)
            start = len(windows)
            windows.extend(
                tokenizer.decode(tokens[i : i + limit]) for i in range(0, len(tokens), limit)
            )
            spans.append((start, len(windows)))
        encoded = self.encoder.encode(windows, normalize_embeddings=True, show_progress_bar=False)
        result = []
        for start, end in spans:
            vector = np.mean(encoded[start:end], axis=0)
            result.append((vector / np.linalg.norm(vector)).tolist())
        return result


@lru_cache
def get_embedding_backend() -> EmbeddingBackend | None:
    settings = get_settings()
    if settings.embedding_backend == "none":
        return None
    return SentenceTransformerBackend(settings.embedding_model, settings.embedding_revision)
