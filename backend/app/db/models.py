"""Phase 2 schema only; no authorization, retrieval or booking services."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Created, Identity


def tenant_constraints(*extra):
    return (UniqueConstraint("company_id", "id"), *extra)


def tenant_fk(column: str, parent: str):
    return ForeignKeyConstraint(
        ["company_id", column],
        [f"{parent}.company_id", f"{parent}.id"],
        name=f"fk_{column}_{parent}_tenant",
    )


class Tenant:
    company_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("companies.id"),
        nullable=False,
    )


class Company(Identity, Created, Base):
    __tablename__ = "companies"
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class User(Tenant, Identity, Created, Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    __table_args__ = tenant_constraints(
        UniqueConstraint("company_id", "username"),
        CheckConstraint("role IN ('employee','hr')", name="role"),
        Index("ix_users_company_role", "company_id", "role"),
    )


class EmployeeProfile(Tenant, Identity, Base):
    __tablename__ = "employee_profiles"
    user_id: Mapped[UUID] = mapped_column(Uuid)
    display_name: Mapped[str] = mapped_column(Text)
    department: Mapped[str] = mapped_column(Text)
    employment_start: Mapped[date]
    __table_args__ = tenant_constraints(
        UniqueConstraint("company_id", "user_id"),
        tenant_fk("user_id", "users"),
    )


class Policy(Tenant, Identity, Base):
    __tablename__ = "policies"
    slug: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text)
    allowed_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    source_filename: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[str] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    indexed_model: Mapped[str | None] = mapped_column(Text)
    indexed_revision: Mapped[str | None] = mapped_column(Text)
    indexed_chunker: Mapped[str | None] = mapped_column(Text)
    indexed_source_sha256: Mapped[str | None] = mapped_column(String(64))
    index_fingerprint: Mapped[str | None] = mapped_column(String(64))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_constraints(
        UniqueConstraint("company_id", "slug", "version"),
        tenant_fk("allowed_user_id", "users"),
        CheckConstraint("version > 0", name="version"),
        CheckConstraint(
            "visibility IN ('all','hr','specific_user')", name="visibility"
        ),
        CheckConstraint("status IN ('draft','published','retired')", name="status"),
        CheckConstraint(
            "(visibility='specific_user') = (allowed_user_id IS NOT NULL)",
            name="allowed_user_visibility",
        ),
        CheckConstraint("source_sha256 ~ '^[0-9a-f]{64}$'", name="source_hash"),
        CheckConstraint(
            "provenance IN ('assignment','fictional_demo')", name="provenance"
        ),
        CheckConstraint(
            "is_demo = (provenance='fictional_demo')", name="demo_provenance"
        ),
        Index("ix_policies_access", "company_id", "status", "visibility"),
    )


class PolicyChunk(Tenant, Identity, Created, Base):
    __tablename__ = "policy_chunks"
    policy_id: Mapped[UUID] = mapped_column(Uuid)
    chunk_no: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
    __table_args__ = tenant_constraints(
        tenant_fk("policy_id", "policies"),
        UniqueConstraint("policy_id", "chunk_no"),
        CheckConstraint("chunk_no >= 0", name="chunk_no"),
        Index("ix_policy_chunks_company_policy", "company_id", "policy_id"),
    )


class LeaveBalance(Tenant, Identity, Base):
    __tablename__ = "leave_balances"
    user_id: Mapped[UUID] = mapped_column(Uuid)
    days_left: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = tenant_constraints(
        tenant_fk("user_id", "users"),
        UniqueConstraint("company_id", "user_id"),
        CheckConstraint("days_left >= 0", name="balance"),
        CheckConstraint("version > 0", name="version"),
    )


class Conversation(Tenant, Identity, Created, Base):
    __tablename__ = "conversations"
    owner_user_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = tenant_constraints(
        tenant_fk("owner_user_id", "users"),
        Index("ix_conversations_owner", "company_id", "owner_user_id"),
    )


class Message(Tenant, Identity, Created, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[UUID] = mapped_column(Uuid)
    sender: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    __table_args__ = tenant_constraints(
        tenant_fk("conversation_id", "conversations"),
        CheckConstraint("sender IN ('user','assistant','system')", name="sender"),
        Index("ix_messages_conversation_time", "conversation_id", "created_at"),
    )


class Task(Tenant, Identity, Created, Base):
    __tablename__ = "tasks"
    conversation_id: Mapped[UUID] = mapped_column(Uuid)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid)
    original_request: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"))
    instruction_revision: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    plan: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = tenant_constraints(
        tenant_fk("conversation_id", "conversations"),
        tenant_fk("owner_user_id", "users"),
        CheckConstraint(
            "status IN ('queued','running','awaiting_confirmation',"
            "'completed','failed','cancelling','cancelled')",
            name="status",
        ),
        CheckConstraint("instruction_revision >= 0", name="revision"),
        Index("ix_tasks_claim", "status", "lease_until"),
    )


class TaskMessage(Tenant, Identity, Created, Base):
    __tablename__ = "task_messages"
    task_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    instruction: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    client_note_id: Mapped[UUID | None] = mapped_column(Uuid)
    __table_args__ = tenant_constraints(
        tenant_fk("task_id", "tasks"),
        tenant_fk("user_id", "users"),
        UniqueConstraint("task_id", "revision"),
        UniqueConstraint("task_id", "client_note_id"),
        CheckConstraint("revision > 0", name="revision"),
    )


class TaskEvent(Tenant, Identity, Created, Base):
    __tablename__ = "task_events"
    task_id: Mapped[UUID] = mapped_column(Uuid)
    seq: Mapped[int] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = tenant_constraints(
        tenant_fk("task_id", "tasks"),
        UniqueConstraint("task_id", "seq"),
        CheckConstraint("seq > 0", name="seq"),
    )


class ActionProposal(Tenant, Identity, Created, Base):
    __tablename__ = "action_proposals"
    task_id: Mapped[UUID] = mapped_column(Uuid)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid)
    action_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = tenant_constraints(
        tenant_fk("task_id", "tasks"),
        tenant_fk("owner_user_id", "users"),
        CheckConstraint(
            "status IN ('pending','confirmed','cancelled','expired')", name="status"
        ),
        CheckConstraint("version > 0", name="version"),
        Index("ix_action_proposals_owner", "company_id", "owner_user_id", "status"),
    )


class LeaveRequest(Tenant, Identity, Created, Base):
    __tablename__ = "leave_requests"
    user_id: Mapped[UUID] = mapped_column(Uuid)
    start_date: Mapped[date]
    end_date: Mapped[date]
    days: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    status: Mapped[str] = mapped_column(Text)
    confirmed_proposal_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    __table_args__ = tenant_constraints(
        tenant_fk("user_id", "users"),
        tenant_fk("confirmed_proposal_id", "action_proposals"),
        CheckConstraint("end_date >= start_date", name="dates"),
        CheckConstraint("days > 0", name="days"),
        CheckConstraint("status IN ('booked','cancelled','pending')", name="status"),
        Index("ix_leave_requests_owner_dates", "company_id", "user_id", "start_date"),
    )


class LeaveHistory(Tenant, Identity, Base):
    __tablename__ = "leave_history"
    user_id: Mapped[UUID] = mapped_column(Uuid)
    request_id: Mapped[UUID] = mapped_column(Uuid)
    actor_id: Mapped[UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(Text)
    days_delta: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    __table_args__ = tenant_constraints(
        tenant_fk("user_id", "users"),
        tenant_fk("actor_id", "users"),
        tenant_fk("request_id", "leave_requests"),
        Index("ix_leave_history_owner_time", "company_id", "user_id", "occurred_at"),
    )


class AuditLog(Tenant, Identity, Created, Base):
    __tablename__ = "audit_logs"
    actor_user_id: Mapped[UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(Text)
    object_type: Mapped[str] = mapped_column(Text)
    object_id: Mapped[UUID] = mapped_column(Uuid)
    outcome: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column("metadata", JSONB)
    __table_args__ = tenant_constraints(tenant_fk("actor_user_id", "users"))
