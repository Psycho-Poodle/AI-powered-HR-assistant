"""Real DB checks for the additional model-history transmission boundary."""

from uuid import uuid4

import pytest
from sqlalchemy import insert, select, update

from app.agent.state import ExecutionState, SubtaskResult
from app.db.models import Policy, Task
from app.security.authorization import ActorContext
from app.seed.load_seed import seed_id
from app.services.ingestion import index_seed_policies
from app.services.task_context import load_context
from app.tools.policy import search_hr_policy

pytestmark = pytest.mark.integration


def test_history_excludes_other_owner_and_withholds_revoked_answer(
    booking_engine, real_embeddings
):
    engine = booking_engine
    actor = ActorContext(
        seed_id("user", "summit", "maya"), seed_id("company", "summit"), "employee"
    )
    prior_id = seed_id("proposal-test-task", "maya")
    current_id = uuid4()
    with engine.begin() as c:
        index_seed_policies(c, real_embeddings)
        evidence = search_hr_policy(c, actor, "late attendance policy", real_embeddings)
        assert evidence.sources
        prior = c.execute(select(Task).where(Task.id == prior_id)).mappings().one()
        state = ExecutionState(
            task_id=prior_id,
            original_request="Late policy",
            status="completed",
            answer="REVOKED_ANSWER_CANARY",
            subtasks=(
                SubtaskResult(
                    id="policy",
                    tool="search_hr_policy",
                    status="completed",
                    data=evidence,
                ),
            ),
        )
        c.execute(
            update(Task)
            .where(Task.id == prior_id)
            .values(plan={"execution": state.model_dump(mode="json")})
        )
        other_id = uuid4()
        other = ExecutionState(
            task_id=other_id,
            original_request="OTHER_OWNER_REQUEST_CANARY",
            status="completed",
            answer="OTHER_OWNER_ANSWER_CANARY",
        )
        c.execute(
            insert(Task).values(
                id=other_id,
                company_id=actor.company_id,
                owner_user_id=seed_id("user", "summit", "leila"),
                conversation_id=prior["conversation_id"],
                created_at=prior["created_at"],
                original_request=other.original_request,
                status="completed",
                plan={"execution": other.model_dump(mode="json")},
            )
        )
        c.execute(
            update(Policy)
            .where(Policy.company_id == actor.company_id)
            .values(status="retired")
        )
        c.execute(
            insert(Task).values(
                id=current_id,
                company_id=actor.company_id,
                owner_user_id=actor.user_id,
                conversation_id=prior["conversation_id"],
                original_request="Explain that",
                status="queued",
            )
        )
        current = c.execute(select(Task).where(Task.id == current_id)).mappings().one()
    context = load_context(engine, current, actor, ())
    encoded = context.model_dump_json()
    assert len(context.history) == 1
    assert "Prior sources no longer available" in encoded
    assert "REVOKED_ANSWER_CANARY" not in encoded
    assert "OTHER_OWNER" not in encoded
