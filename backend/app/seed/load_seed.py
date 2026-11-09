"""Transactional, conflict-detecting bootstrap. Never resets live balances."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

from argon2 import PasswordHasher
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from sqlalchemy import Connection, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.models import Company, LeaveBalance, Policy, User

DEFAULT_SEED_DIR = Path(__file__).resolve().parents[3] / "seed"


class ManifestRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyRecord(ManifestRecord):
    slug: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1)


class UserRecord(ManifestRecord):
    company: str
    username: str
    role: Literal["employee", "hr"]


class BalanceRecord(ManifestRecord):
    company: str
    username: str
    days_left: int = Field(ge=0)


class PolicyRecord(ManifestRecord):
    company: str
    slug: str
    title: str
    version: int = Field(gt=0)
    visibility: Literal["all", "hr", "specific_user"]
    allowed_user: str | None = None
    status: Literal["draft", "published", "retired"]
    provenance: Literal["assignment", "fictional_demo"]
    file: str

    @model_validator(mode="after")
    def check_acl(self):
        if (self.visibility == "specific_user") != (self.allowed_user is not None):
            raise ValueError(
                "specific_user visibility requires exactly one allowed user"
            )
        return self


def read_records(path: Path, record_type: type[BaseModel]):
    return TypeAdapter(list[record_type]).validate_python(
        json.loads(path.read_text(encoding="utf-8"))
    )


def seed_id(kind: str, *parts: str):
    return uuid5(NAMESPACE_URL, "/".join(("hr-chat-assistant", kind, *parts)))


def insert_immutable(connection: Connection, model, values: dict) -> bool:
    table = model.__table__
    inserted = connection.execute(
        insert(table).values(**values).on_conflict_do_nothing().returning(table.c.id)
    ).scalar_one_or_none()
    if inserted is not None:
        return True
    existing = (
        connection.execute(select(table).where(table.c.id == values["id"]))
        .mappings()
        .one_or_none()
    )
    if existing is None or any(existing[key] != value for key, value in values.items()):
        raise ValueError(f"Seed conflict in {table.name}: {values['id']}")
    return False


def load_seed(connection: Connection, seed_dir: Path, password: str) -> dict[str, int]:
    """Caller owns transaction; all changes roll back on any manifest conflict."""
    if not password:
        raise ValueError("DEMO_SEED_PASSWORD must be nonempty")
    companies = read_records(seed_dir / "companies.json", CompanyRecord)
    users = read_records(seed_dir / "users.json", UserRecord)
    balances = read_records(seed_dir / "leave_balances.json", BalanceRecord)
    policies = read_records(seed_dir / "policies/manifest.json", PolicyRecord)
    company_slugs = {c.slug for c in companies}
    user_keys = {(u.company, u.username) for u in users}
    if len(company_slugs) != len(companies) or len(user_keys) != len(users):
        raise ValueError("Duplicate company or user in seed manifest")
    if any(u.company not in company_slugs for u in users):
        raise ValueError("Unknown user company")
    if len({(p.company, p.slug, p.version) for p in policies}) != len(policies):
        raise ValueError("Duplicate policy version in seed manifest")
    if len({(b.company, b.username) for b in balances}) != len(balances):
        raise ValueError("Duplicate balance in seed manifest")

    # Serialize cooperating seed processes; uniqueness still guards other writers.
    connection.execute(text("SELECT pg_advisory_xact_lock(7352042)"))
    added = {"companies": 0, "users": 0, "leave_balances": 0, "policies": 0}
    for company in companies:
        added["companies"] += insert_immutable(
            connection,
            Company,
            {
                "id": seed_id("company", company.slug),
                **company.model_dump(),
            },
        )
    for user in users:
        uid = seed_id("user", user.company, user.username)
        values = {
            "id": uid,
            "company_id": seed_id("company", user.company),
            "username": user.username,
            "role": user.role,
        }
        existing = (
            connection.execute(select(User.__table__).where(User.id == uid))
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if any(existing[k] != v for k, v in values.items()):
                raise ValueError("Seed user identity conflict")
            continue  # Do not rotate credentials on a repeat run.
        values["password_hash"] = PasswordHasher().hash(password)
        added["users"] += insert_immutable(connection, User, values)
    for balance in balances:
        if (balance.company, balance.username) not in user_keys:
            raise ValueError("Unknown balance user")
        bid = seed_id("balance", balance.company, balance.username)
        values = {
            "id": bid,
            "company_id": seed_id("company", balance.company),
            "user_id": seed_id("user", balance.company, balance.username),
        }
        existing = (
            connection.execute(
                select(LeaveBalance.__table__).where(LeaveBalance.id == bid)
            )
            .mappings()
            .one_or_none()
        )
        if existing is not None:
            if any(existing[k] != v for k, v in values.items()):
                raise ValueError("Seed balance identity conflict")
            continue  # Current balance is mutable truth, not reset by seed.
        added["leave_balances"] += insert_immutable(
            connection,
            LeaveBalance,
            {
                **values,
                "days_left": balance.days_left,
            },
        )
    policy_root = (seed_dir / "policies").resolve()
    for policy in policies:
        if policy.company not in company_slugs:
            raise ValueError("Unknown policy company")
        if (
            policy.allowed_user
            and (policy.company, policy.allowed_user) not in user_keys
        ):
            raise ValueError("Policy recipient must belong to the same company")
        source = (policy_root / policy.file).resolve()
        if not source.is_relative_to(policy_root):
            raise ValueError("Policy source must stay inside seed/policies")
        raw = source.read_bytes()
        body = raw.decode("utf-8")
        if not body.strip():
            raise ValueError("Empty policy source")
        if policy.provenance == "fictional_demo" and (
            "FICTIONAL DEMONSTRATION DATA" not in body
            or "FICTIONAL DEMONSTRATION DATA" not in policy.title
        ):
            raise ValueError("Fictional policy must be visibly labelled")
        values = {
            "id": seed_id("policy", policy.company, policy.slug, str(policy.version)),
            "company_id": seed_id("company", policy.company),
            "slug": policy.slug,
            "title": policy.title,
            "body": body,
            "version": policy.version,
            "status": policy.status,
            "visibility": policy.visibility,
            "allowed_user_id": (
                seed_id("user", policy.company, policy.allowed_user)
                if policy.allowed_user
                else None
            ),
            "source_filename": policy.file,
            "source_sha256": hashlib.sha256(raw).hexdigest(),
            "provenance": policy.provenance,
            "is_demo": policy.provenance == "fictional_demo",
        }
        # published_at is a first-insert timestamp, excluded from immutable comparison.
        inserted = insert_immutable(connection, Policy, values)
        if inserted and policy.status == "published":
            connection.execute(
                Policy.__table__.update()
                .where(Policy.id == values["id"])
                .values(published_at=text("now()"))
            )
        added["policies"] += inserted
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-dir", type=Path, default=DEFAULT_SEED_DIR)
    args = parser.parse_args()
    password = os.environ.get("DEMO_SEED_PASSWORD", "")
    if not password:
        parser.error("Set DEMO_SEED_PASSWORD in the environment")
    url = make_url(str(get_settings().database_url)).set(
        drivername="postgresql+psycopg"
    )
    engine = create_engine(url)
    with engine.begin() as connection:
        result = load_seed(connection, args.seed_dir, password)
    engine.dispose()
    print(json.dumps({"inserted": result}))


if __name__ == "__main__":
    main()
