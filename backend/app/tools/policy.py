"""Return authorized reference data, never instructions or executable tool calls."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection

from app.rag.embeddings import LocalEmbeddings
from app.rag.search import Evidence, retrieve
from app.security.authorization import ActorContext


class PolicyToolResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: Literal["sources_found", "insufficient_sources"]
    sources: tuple[Evidence, ...]

    def llm_context(self) -> str:
        """Explicit data boundary for a future LLM adapter, not a system prompt."""
        return json.dumps(
            {
                "type": "untrusted_policy_references",
                "status": self.status,
                "documents": [
                    source.model_dump(mode="json") for source in self.sources
                ],
            },
            ensure_ascii=True,
        )


def search_hr_policy(
    connection: Connection,
    actor: ActorContext,
    query: str,
    embedder: LocalEmbeddings,
    top_k: int = 5,
) -> PolicyToolResult:
    sources = retrieve(connection, actor, query, embedder, top_k)
    return PolicyToolResult(
        status="sources_found" if sources else "insufficient_sources", sources=sources
    )
