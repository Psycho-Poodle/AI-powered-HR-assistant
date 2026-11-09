"""Authenticated self reads and advisory validation, with no mutation endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Engine

from app.auth.dependencies import CurrentActor, Db, get_engine, reject_query_parameters
from app.schemas.hr import (
    BalanceResponse,
    HistoryPage,
    HistoryQuery,
    LeaveValidationInput,
    LeaveValidationResult,
    ProfileResponse,
)
from app.schemas.proposals import (
    BookingResult,
    ProposalCreate,
    ProposalVersion,
    ProposalView,
)
from app.services import proposals
from app.services.leave import HRToolError
from app.tools.leave import (
    get_employee_profile,
    get_leave_balance,
    get_leave_history,
    validate_leave_request,
)

router = APIRouter(prefix="/api/v1", tags=["hr"])


def tool_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except HRToolError as error:
        status = {"not_found": 404, "forbidden": 403}.get(error.code, 422)
        raise HTTPException(status, error.code) from error


@router.get(
    "/leave/balance",
    response_model=BalanceResponse,
    dependencies=[Depends(reject_query_parameters)],
)
def balance(actor: CurrentActor, connection: Db):
    return tool_call(get_leave_balance, connection, actor)


@router.get(
    "/employee/profile",
    response_model=ProfileResponse,
    dependencies=[Depends(reject_query_parameters)],
)
def profile(actor: CurrentActor, connection: Db):
    return tool_call(get_employee_profile, connection, actor)


@router.get("/leave/history", response_model=HistoryPage)
def history(
    actor: CurrentActor, connection: Db, query: Annotated[HistoryQuery, Query()]
):
    return tool_call(
        get_leave_history, connection, actor, limit=query.limit, cursor=query.cursor
    )


@router.post(
    "/leave/validate",
    response_model=LeaveValidationResult,
    dependencies=[Depends(reject_query_parameters)],
)
def validate(body: LeaveValidationInput, actor: CurrentActor, connection: Db):
    # CurrentActor enforces Origin and CSRF for this POST despite its read-only work.
    return tool_call(validate_leave_request, connection, actor, body)


def get_mutation_engine() -> Engine:
    return get_engine()


MutationEngine = Annotated[Engine, Depends(get_mutation_engine)]


def proposal_transaction(engine, function, actor, *args):
    with engine.begin() as connection:
        result = function(connection, actor, *args)
    # Expiry is a committed state transition even though the action returns 409.
    # Unexpected database errors escape the context and roll back completely.
    if isinstance(result, proposals.ProposalFailure):
        raise HTTPException(result.status, result.code)
    return result


@router.post(
    "/leave/proposals",
    response_model=ProposalView,
    status_code=201,
    dependencies=[Depends(reject_query_parameters)],
)
def propose(body: ProposalCreate, actor: CurrentActor, engine: MutationEngine):
    return proposal_transaction(engine, proposals.create_proposal, actor, body)


@router.get(
    "/leave/proposals/{proposal_id}",
    response_model=ProposalView,
    dependencies=[Depends(reject_query_parameters)],
)
def get_proposal(proposal_id: UUID, actor: CurrentActor, connection: Db):
    row = proposals.owned_proposal(connection, actor, proposal_id)
    if row is None:
        raise HTTPException(404, "not_found")
    return proposals.view(row)


@router.post(
    "/leave/proposals/{proposal_id}/confirm",
    response_model=BookingResult,
    dependencies=[Depends(reject_query_parameters)],
)
def confirm(
    proposal_id: UUID,
    body: ProposalVersion,
    actor: CurrentActor,
    engine: MutationEngine,
):
    return proposal_transaction(
        engine, proposals.confirm_proposal, actor, proposal_id, body.expected_version
    )


@router.post(
    "/leave/proposals/{proposal_id}/cancel",
    response_model=ProposalView,
    dependencies=[Depends(reject_query_parameters)],
)
def cancel(
    proposal_id: UUID,
    body: ProposalVersion,
    actor: CurrentActor,
    engine: MutationEngine,
):
    return proposal_transaction(
        engine, proposals.cancel_proposal, actor, proposal_id, body.expected_version
    )
