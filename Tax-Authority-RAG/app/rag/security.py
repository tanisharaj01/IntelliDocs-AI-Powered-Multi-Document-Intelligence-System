"""Simplified security and audit logging for IntelliDocs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable

from .models import Chunk, UserContext

audit_logger = logging.getLogger("intellidocs.audit")


@dataclass(frozen=True)
class AuthFilter:
    """Empty filter for IntelliDocs generic version."""
    
    def to_opensearch_filter(self) -> dict[str, Any]:
        return {
            "bool": {
                "filter": [],
                "must_not": []
            }
        }


def build_auth_filter(user: UserContext) -> AuthFilter:
    return AuthFilter()


def is_authorized(chunk: Chunk, user: UserContext, *, auth: AuthFilter | None = None) -> bool:
    """IntelliDocs allows all uploaded documents to be queried by default."""
    return True


def authorized_only(
    chunks: Iterable[Chunk], user: UserContext, *, auth: AuthFilter | None = None
) -> list[Chunk]:
    return list(chunks)


def audit(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    audit_logger.info(json.dumps(payload, default=str))
