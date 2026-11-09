"""Authenticated search and HR-only Markdown ingestion."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import CurrentActor, Db, reject_query_parameters, require_hr
from app.rag.embeddings import EmbeddingUnavailable, get_embeddings
from app.security.authorization import ActorContext
from app.services.ingestion import IngestConflict, IngestRequest, ingest_markdown
from app.tools.policy import PolicyToolResult, search_hr_policy

router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    q: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)


@router.get("/search", response_model=PolicyToolResult)
def search(actor: CurrentActor, connection: Db, query: Annotated[SearchQuery, Query()]):
    try:
        return search_hr_policy(
            connection, actor, query.q, get_embeddings(), query.limit
        )
    except EmbeddingUnavailable as error:
        raise HTTPException(503, "Local embedding model unavailable") from error
    except ValueError as error:
        raise HTTPException(422, "Invalid search input") from error


@router.post("/ingest", dependencies=[Depends(reject_query_parameters)])
def ingest(
    body: IngestRequest,
    connection: Db,
    actor: Annotated[ActorContext, Depends(require_hr)],
):
    try:
        return ingest_markdown(connection, actor, body, get_embeddings())
    except IngestConflict as error:
        raise HTTPException(409, "Policy version conflict") from error
    except PermissionError as error:
        raise HTTPException(403, "Access denied") from error
    except EmbeddingUnavailable as error:
        raise HTTPException(503, "Local embedding model unavailable") from error
    except ValueError as error:
        raise HTTPException(422, "Invalid Markdown input") from error
