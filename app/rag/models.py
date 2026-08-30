"""Shared data structures for IntelliDocs.

Plain dataclasses preserve a stable shape when swapping the retrieval backend
from the in-memory fake to a real OpenSearch client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UserContext:
    """Authorization context propagated through pipeline state (simplified)."""
    user_id: str
    role: str


@dataclass
class Chunk:
    """A single document chunk.

    The field set mirrors the expected OpenSearch mapping.
    """

    chunk_id: str
    document_id: str
    document_name: str
    text: str
    page_number: int
    embedding: list[float] = field(default_factory=list)

    def to_index_doc(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "document_name": self.document_name,
            "text": self.text,
            "page_number": self.page_number,
            "embedding": list(self.embedding),
        }


@dataclass
class Citation:
    """One citation for one atomic claim in the answer."""

    chunk_id: str
    document_id: str
    document_name: str
    page_number: int

    def is_complete(self) -> bool:
        return bool(
            self.chunk_id
            and self.document_id
            and self.document_name
            and self.page_number is not None
        )

    def format(self) -> str:
        return f"({self.document_name}, Page {self.page_number})"


@dataclass
class GraderResult:
    label: str  # Relevant | Ambiguous | Irrelevant
    confidence: float
    reasons: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    required_action: str = ""
