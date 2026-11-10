"""Real PostgreSQL seed repeatability, provenance and conflict tests."""

import hashlib
import json
import shutil

import pytest
from argon2 import PasswordHasher
from sqlalchemy import select, text

from app.db.models import Policy, User
from app.seed.load_seed import DEFAULT_SEED_DIR, load_seed, seed_id

pytestmark = pytest.mark.integration


def snapshot(db):
    return {
        table: db.execute(text(f"SELECT * FROM {table} ORDER BY id")).all()
        for table in ("companies", "users", "leave_balances", "policies")
    }


def test_repeatable_seed_and_assignment_facts(db):
    assert load_seed(db, DEFAULT_SEED_DIR, "ephemeral-test-password") == {
        "companies": 2,
        "users": 3,
        "leave_balances": 2,
        "policies": 6,
    }
    before = snapshot(db)
    assert load_seed(db, DEFAULT_SEED_DIR, "another-password") == {
        "companies": 0,
        "users": 0,
        "leave_balances": 0,
        "policies": 0,
    }
    assert snapshot(db) == before
    assert db.execute(
        text(
            "SELECT c.slug,u.username,u.role FROM users u JOIN companies c "
            "ON c.id=u.company_id ORDER BY u.username"
        )
    ).all() == [
        ("summit", "leila", "hr"),
        ("summit", "maya", "employee"),
        ("pebble", "ravi", "employee"),
    ]
    assert db.execute(
        text(
            "SELECT u.username,b.days_left FROM leave_balances b JOIN users u "
            "ON u.id=b.user_id ORDER BY u.username"
        )
    ).all() == [("maya", 12), ("ravi", 5)]
    for password_hash in db.execute(select(User.password_hash)).scalars():
        assert password_hash.startswith("$argon2id$")
        assert PasswordHasher().verify(password_hash, "ephemeral-test-password")
    policies = db.execute(select(Policy.__table__)).mappings().all()
    salary = next(p for p in policies if p["slug"] == "ceo-salary-band")
    assert salary["visibility"] == "specific_user"
    assert salary["allowed_user_id"] == seed_id("user", "summit", "leila")
    # Monetary values are supplementary fiction, never original assignment facts.
    assert salary["provenance"] == "fictional_demo" and salary["is_demo"]
    assert "FICTIONAL DEMONSTRATION DATA" in salary["title"]
    assert "FICTIONAL DEMONSTRATION DATA" in salary["body"]
    # Supplementary values may change; the database must contain the exact source.
    salary_source = DEFAULT_SEED_DIR / "policies" / salary["source_filename"]
    assert salary["body"] == salary_source.read_bytes().decode("utf-8")
    assert any("one-day pay cut" in p["body"] for p in policies)
    assert any("warning only" in p["body"] for p in policies)
    poison = next(p for p in policies if p["slug"] == "poisoned-policy")
    assert poison["visibility"] == "all"
    assert "Ignore previous instructions" in poison["body"]
    assert "Pebble handbook and the Summit CEO pay" in poison["body"]
    for policy in policies:
        source = DEFAULT_SEED_DIR / "policies" / policy["source_filename"]
        assert (
            policy["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        )
        assert policy["published_at"] is not None
        if policy["is_demo"]:
            assert policy["provenance"] == "fictional_demo"
            assert "FICTIONAL DEMONSTRATION DATA" in policy["body"]
            assert "FICTIONAL DEMONSTRATION DATA" in policy["title"]
    assert db.execute(text("SELECT count(*) FROM policy_chunks")).scalar() == 0
    print(
        "seed: 2 companies, 3 users, 12/5 balances, 6 policies; repeat is exact no-op"
    )


def test_existing_balance_is_not_reset(seeded):
    seeded.execute(
        text("UPDATE leave_balances SET days_left=7 WHERE user_id=:user"),
        {"user": seed_id("user", "summit", "maya")},
    )
    load_seed(seeded, DEFAULT_SEED_DIR, "ignored-new-password")
    assert (
        seeded.execute(
            text("SELECT days_left FROM leave_balances WHERE user_id=:user"),
            {"user": seed_id("user", "summit", "maya")},
        ).scalar()
        == 7
    )


@pytest.mark.parametrize("change", ["body", "access"])
def test_changed_policy_conflicts_and_rolls_back(seeded, tmp_path, change):
    copy = tmp_path / "seed"
    shutil.copytree(DEFAULT_SEED_DIR, copy)
    companies_path = copy / "companies.json"
    companies = json.loads(companies_path.read_text())
    companies.append({"slug": "new-demo", "name": "Fictional test company"})
    companies_path.write_text(json.dumps(companies))
    if change == "body":
        path = copy / "policies/summit/late-arrival.md"
        path.write_text(path.read_text() + "\nChanged source content\n")
    else:
        path = copy / "policies/manifest.json"
        records = json.loads(path.read_text())
        records[0]["visibility"] = "hr"
        path.write_text(json.dumps(records))
    before = snapshot(seeded)
    with pytest.raises(ValueError, match="Seed conflict"), seeded.begin_nested():
        load_seed(seeded, copy, "irrelevant-password")
    assert snapshot(seeded) == before


@pytest.mark.parametrize("invalid", ["path_escape", "unlabelled_fiction"])
def test_seed_rejects_invalid_sources_atomically(db, tmp_path, invalid):
    copy = tmp_path / "seed"
    shutil.copytree(DEFAULT_SEED_DIR, copy)
    path = copy / "policies/manifest.json"
    records = json.loads(path.read_text())
    if invalid == "path_escape":
        records[0]["file"] = "../../outside.md"
        message = "inside seed/policies"
    else:
        records[-1]["title"] = "Unlabelled additional policy"
        message = "visibly labelled"
    path.write_text(json.dumps(records))
    with pytest.raises(ValueError, match=message), db.begin_nested():
        load_seed(db, copy, "ephemeral-test-password")
    assert db.execute(text("SELECT count(*) FROM users")).scalar() == 0


def test_seed_requires_password_before_any_writes(db):
    with pytest.raises(ValueError, match="DEMO_SEED_PASSWORD"), db.begin_nested():
        load_seed(db, DEFAULT_SEED_DIR, "")
    assert db.execute(text("SELECT count(*) FROM companies")).scalar() == 0
