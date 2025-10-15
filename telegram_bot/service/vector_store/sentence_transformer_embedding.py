from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from chromadb.api.types import EmbeddingFunction, Embeddings
from sentence_transformers import SentenceTransformer


class SentenceTransformerEmbeddingFunction(EmbeddingFunction[Sequence[str]]):
    """ChromaDB-compatible embedding function using SentenceTransformers."""

    def __init__(self, model_name: str) -> None:
        """Initialize the embedding function with a SentenceTransformer model.

        Args:
            model_name: Name of the SentenceTransformer model to use
        """
        self._model_name = model_name
        self._model = SentenceTransformer(model_name)

    def __call__(self, input: Sequence[str]) -> Embeddings:
        """Generate embeddings for the input texts.

        Args:
            input: Sequence of texts to embed

        Returns:
            List of embeddings as lists of floats
        """
        embeddings = self._model.encode(
            list(input),
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embeddings.tolist() if hasattr(embeddings, "tolist") else embeddings

    def name(self) -> str:
        """Return the name of the embedding function.

        Returns:
            A descriptive name for this embedding function
        """
        return f"SentenceTransformer({self._model_name})"

    def get_config(self) -> dict[str, Any]:
        """Return the config for the embedding function.

        Returns:
            Configuration dictionary for serialization
        """
        return {"model_name": self._model_name}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> SentenceTransformerEmbeddingFunction:
        """Build the embedding function from a config.

        Args:
            config: Configuration dictionary

        Returns:
            New instance of SentenceTransformerEmbeddingFunction
        """
        return SentenceTransformerEmbeddingFunction(model_name=config["model_name"])
