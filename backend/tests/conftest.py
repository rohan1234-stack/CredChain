# ---------------------------------------------------------------------------
# Test fixtures: a dedicated `credchain_test` Postgres database (never the
# dev `credchain` database), created fresh from the current models at the
# start of the test session and dropped at the end. Each test runs inside
# its own transaction that's rolled back afterward, so tests can't leak
# state into each other regardless of order.
# ---------------------------------------------------------------------------

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Must happen BEFORE any `from app...` import: app.config.settings is a
# module-level singleton built from the environment at import time, so
# these have to land before app.config (or anything importing it) is first
# imported — otherwise Phase 4 tests would write real key/document files
# into the dev backend/keys and backend/storage directories.
_TEST_KEYS_DIR = tempfile.mkdtemp(prefix="credchain_test_keys_")
_TEST_STORAGE_DIR = tempfile.mkdtemp(prefix="credchain_test_storage_")
os.environ["KEYS_PATH"] = _TEST_KEYS_DIR
os.environ["STORAGE_PATH"] = _TEST_STORAGE_DIR
# ensure_institution_keypair() now encrypts every new institution's private key for storage in
# Postgres (see app/security/key_encryption.py) — every test that registers an institution needs
# a working secret for that, not just the tests that specifically exercise key encryption.
os.environ["KEY_ENCRYPTION_SECRET"] = "test-only-encryption-secret-never-used-in-production"
# The test suite must be deterministic regardless of whatever a developer
# currently has in their local .env (e.g. AI_ENABLED=true with a real key
# for manual smoke testing) — tests that exercise the fallback path assume
# AI is off, and no test in this suite needs a real AI call.
os.environ["AI_ENABLED"] = "false"
# Same rationale as AI_ENABLED above — tests that exercise blockchain
# behavior construct a fake BlockchainClient explicitly (see
# test_blockchain_anchoring.py); no test should accidentally attempt a real
# network call because a developer's local .env has real testnet creds set.
os.environ["BLOCKCHAIN_ENABLED"] = "false"

from app import models  # noqa: E402,F401  (populates Base.metadata)
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.institution import Institution  # noqa: E402

# Phase A added a verification_status gate (PENDING by default) on newly registered
# institutions/companies — production correctly requires an admin to approve a real account
# before it can issue credentials / publish jobs (see services/admin_service.py). The other 300+
# tests in this suite predate that gate and register an institution/company purely as a
# precondition for testing something else entirely (credential issuance, sharing, job postings,
# etc.) — they were never meant to exercise the verification gate itself, and forcing every one
# of them to also call the admin approval endpoint would be pure churn unrelated to what each
# test actually checks. So: every institution/company created anywhere in this test suite is
# auto-verified immediately at insert time. The verification-gate behavior itself (PENDING/
# REJECTED correctly blocking issuance/publishing) is tested directly and explicitly in
# test_admin_verification.py, which deliberately resets verification_status back to PENDING (or
# REJECTED) before asserting the gate holds — this hook never masks that.
@event.listens_for(Institution, "after_insert")
def _auto_verify_institution(mapper, connection, target) -> None:
    connection.execute(Institution.__table__.update().where(Institution.__table__.c.id == target.id).values(verification_status="verified"))


@event.listens_for(Company, "after_insert")
def _auto_verify_company(mapper, connection, target) -> None:
    connection.execute(Company.__table__.update().where(Company.__table__.c.id == target.id).values(verification_status="verified"))


TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://credchain:credchain@localhost:5432/credchain_test",
)

engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="session", autouse=True)
def _test_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        # A test that hits an unhandled exception mid-request (e.g. testing
        # that a failure rolls back cleanly) may have already caused this
        # transaction to end itself — only roll back if it's still ours to roll back.
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture()
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
