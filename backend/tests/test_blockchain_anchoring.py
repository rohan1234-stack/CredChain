# ---------------------------------------------------------------------------
# Phase 9A/9B tests: credential hash anchoring.
#
# No test in this file makes a real network call — BLOCKCHAIN_ENABLED is
# forced false in conftest.py, and tests that need a successful/failed
# anchor inject a FakeBlockchainClient directly into anchoring_service
# (which is exactly what the `client` parameter of anchor_credential exists
# for). Tests that only exercise authorization/eligibility rejections
# (student/company/wrong-institution/revoked) go through the real HTTP
# route, since those checks happen before any blockchain call is attempted.
# ---------------------------------------------------------------------------

import hashlib
import uuid

from app.models.activity_log import ActivityLog
from app.models.credential import Credential
from app.models.enums import BlockchainAnchorStatus
from app.models.institution import Institution
from app.services import verification_service
from app.services.blockchain import anchoring_service
from app.services.blockchain.client import (
    BlockchainSubmissionError,
    CredentialAlreadyAnchoredOnChainError,
)
from app.services.credential_payload import canonicalize_credential_payload

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n%credchain-test-fixture\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF"
)


class FakeBlockchainClient:
    """Simulates the on-chain contract without any network access."""

    def __init__(self, *, fail: bool = False, already_anchored: bool = False):
        self.fail = fail
        self.already_anchored = already_anchored
        self.calls = 0
        self.anchored_hashes: dict[str, dict] = {}

    def anchor_hash(self, credential_hash_hex: str) -> dict:
        self.calls += 1
        if self.already_anchored:
            raise CredentialAlreadyAnchoredOnChainError(credential_hash_hex)
        if self.fail:
            raise BlockchainSubmissionError("simulated RPC failure")
        result = {"tx_hash": "0x" + hashlib.sha256(credential_hash_hex.encode()).hexdigest(), "block_timestamp": 1_800_000_000}
        self.anchored_hashes[credential_hash_hex] = result
        return result

    def get_anchor(self, credential_hash_hex: str) -> dict:
        return {"issuer": "0x0000000000000000000000000000000000dEaD", "timestamp": 1_800_000_000, "exists": True}


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, *, role, email, **extra):
    payload = {"email": email, "password": "Password123", "full_name": f"Test {role.title()}", "role": role, **extra}
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_institution(client, db_session, email="anchor-inst@test.credchain.dev", name="Anchor University"):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    body = _register(client, role="institution", email=email, institution_id=str(institution.id))
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, db_session, institution_id, email="anchor-student@test.credchain.dev", identifier="STU-ANCH-001"):
    from app.models.student import Student

    body = _register(client, role="student", email=email, student_identifier=identifier)
    student_id = body["user"]["student_id"]
    student = db_session.query(Student).filter(Student.id == uuid.UUID(student_id)).first()
    student.institution_id = uuid.UUID(institution_id)
    db_session.commit()
    return {"token": body["access_token"], "student_id": student_id}


def _register_verifier(client, db_session, email="anchor-verifier@test.credchain.dev", name="Anchor Company"):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    body = _register(client, role="verifier", email=email, company_id=str(company.id))
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _issue(client, institution_token, student_id, **overrides) -> dict:
    data = {
        "student_id": student_id,
        "credential_type": "transcript",
        "title": "Final Transcript",
        "degree": "B.Tech Computer Science",
        "graduation_year": "2026",
        "cgpa": "8.7",
    }
    data.update(overrides)
    files = {"document": ("transcript.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials", data=data, files=files, headers=_auth_header(institution_token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _setup(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    credential = _issue(client, inst["token"], student["student_id"])
    return {"inst": inst, "student": student, "credential": credential}


def _anchor_via_service(db_session, ctx, fake_client):
    institution = db_session.query(Institution).filter(Institution.id == uuid.UUID(ctx["inst"]["institution_id"])).first()
    return anchoring_service.anchor_credential(
        db_session, institution, uuid.UUID(ctx["credential"]["id"]), client=fake_client
    )


# --- 1/2: hash reproducibility + existing canonical payload is the source --------------------


def test_hash_is_reproducible_and_uses_existing_canonical_payload(client, db_session):
    ctx = _setup(client, db_session)
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()

    hash_a = anchoring_service.compute_blockchain_credential_hash(credential)
    hash_b = anchoring_service.compute_blockchain_credential_hash(credential)
    assert hash_a == hash_b
    assert hash_a.startswith("0x")
    assert len(hash_a) == 66  # 0x + 64 hex chars

    # Prove it's derived from the SAME function verification_service already
    # trusts, not a second, competing serialization.
    canonical_bytes = verification_service.reconstruct_canonical_payload(credential)
    expected = "0x" + hashlib.sha256(canonical_bytes).hexdigest()
    assert hash_a == expected

    # And that canonical_bytes is exactly canonicalize_credential_payload's
    # output — the one true serialization function, used nowhere else.
    assert canonical_bytes == canonicalize_credential_payload(
        __import__("json").loads(canonical_bytes.decode())
    )


# --- 3: student cannot anchor -----------------------------------------------------------------


def test_student_cannot_anchor(client, db_session):
    ctx = _setup(client, db_session)
    resp = client.post(f"/api/credentials/{ctx['credential']['id']}/anchor", headers=_auth_header(ctx["student"]["token"]))
    assert resp.status_code == 403


# --- 4: company cannot anchor -----------------------------------------------------------------


def test_company_cannot_anchor(client, db_session):
    ctx = _setup(client, db_session)
    verifier = _register_verifier(client, db_session)
    resp = client.post(f"/api/credentials/{ctx['credential']['id']}/anchor", headers=_auth_header(verifier["token"]))
    assert resp.status_code == 403


# --- unauthenticated cannot anchor ------------------------------------------------------------


def test_unauthenticated_cannot_anchor(client, db_session):
    ctx = _setup(client, db_session)
    resp = client.post(f"/api/credentials/{ctx['credential']['id']}/anchor")
    assert resp.status_code == 401


# --- 5: institution cannot anchor another institution's credential --------------------------


def test_institution_cannot_anchor_another_institutions_credential(client, db_session):
    ctx = _setup(client, db_session)
    other_inst = _register_institution(client, db_session, email="other-anchor-inst@test.credchain.dev", name="Other University")

    resp = client.post(f"/api/credentials/{ctx['credential']['id']}/anchor", headers=_auth_header(other_inst["token"]))
    assert resp.status_code == 403


# --- 6: revoked credential cannot be newly anchored -------------------------------------------


def test_revoked_credential_cannot_be_anchored(client, db_session):
    ctx = _setup(client, db_session)
    revoke_resp = client.post(
        f"/api/credentials/{ctx['credential']['id']}/revoke", headers=_auth_header(ctx["inst"]["token"])
    )
    assert revoke_resp.status_code == 200

    resp = client.post(f"/api/credentials/{ctx['credential']['id']}/anchor", headers=_auth_header(ctx["inst"]["token"]))
    assert resp.status_code == 409


# --- not-configured blockchain fails cleanly via the real route (BLOCKCHAIN_ENABLED=false) ----


def test_anchor_endpoint_fails_cleanly_when_blockchain_not_configured(client, db_session):
    ctx = _setup(client, db_session)
    resp = client.post(f"/api/credentials/{ctx['credential']['id']}/anchor", headers=_auth_header(ctx["inst"]["token"]))
    assert resp.status_code == 503

    db_session.expire_all()
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    assert credential.blockchain_status == BlockchainAnchorStatus.FAILED
    # The credential itself is untouched by the blockchain failure.
    assert credential.signature is not None
    assert credential.status.value == "active"


# --- 7: duplicate anchor is idempotent (service-level, fake client) --------------------------


def test_duplicate_anchor_is_idempotent(client, db_session):
    ctx = _setup(client, db_session)
    fake_client = FakeBlockchainClient()

    first = _anchor_via_service(db_session, ctx, fake_client)
    assert first.blockchain_status == BlockchainAnchorStatus.ANCHORED
    first_tx_hash = first.blockchain_tx_hash
    assert fake_client.calls == 1

    second = _anchor_via_service(db_session, ctx, fake_client)
    assert second.blockchain_status == BlockchainAnchorStatus.ANCHORED
    assert second.blockchain_tx_hash == first_tx_hash
    # No new transaction was submitted for the second call.
    assert fake_client.calls == 1


# --- 8: blockchain failure does not corrupt the credential ------------------------------------


def test_blockchain_failure_does_not_corrupt_credential(client, db_session):
    ctx = _setup(client, db_session)
    original_signature = ctx["credential"]["signature"]
    original_document_hash = ctx["credential"]["document_hash"]

    fake_client = FakeBlockchainClient(fail=True)
    try:
        _anchor_via_service(db_session, ctx, fake_client)
        assert False, "expected BlockchainAnchoringFailedError"
    except anchoring_service.BlockchainAnchoringFailedError:
        pass

    db_session.expire_all()
    result = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    assert result.blockchain_status == BlockchainAnchorStatus.FAILED
    assert result.blockchain_tx_hash is None
    assert result.signature == original_signature
    assert result.document_hash == original_document_hash
    assert result.status.value == "active"


def test_already_anchored_on_chain_is_recovered_not_treated_as_failure(client, db_session):
    """A retry after a lost receipt (tx actually succeeded) must land on ANCHORED, not FAILED."""
    ctx = _setup(client, db_session)
    fake_client = FakeBlockchainClient(already_anchored=True)

    result = _anchor_via_service(db_session, ctx, fake_client)
    assert result.blockchain_status == BlockchainAnchorStatus.ANCHORED


# --- 9: private key / RPC credentials never exposed in the response ---------------------------


def test_anchor_response_never_exposes_secrets(client, db_session):
    ctx = _setup(client, db_session)
    fake_client = FakeBlockchainClient()
    _anchor_via_service(db_session, ctx, fake_client)

    resp = client.get(f"/api/credentials/{ctx['credential']['id']}", headers=_auth_header(ctx["inst"]["token"]))
    body_text = resp.text.lower()
    assert "private_key" not in body_text
    assert "blockchain_private_key" not in body_text
    assert "rpc_url" not in body_text


# --- 10/11/12: metadata persisted, ActivityLog created, signature unchanged -------------------


def test_successful_anchor_persists_metadata_and_activity_log(client, db_session):
    ctx = _setup(client, db_session)
    original_signature = ctx["credential"]["signature"]
    fake_client = FakeBlockchainClient()

    result = _anchor_via_service(db_session, ctx, fake_client)

    assert result.blockchain_status == BlockchainAnchorStatus.ANCHORED
    assert result.blockchain_tx_hash is not None
    assert result.blockchain_network == "polygon-amoy"
    assert result.blockchain_credential_hash is not None
    assert result.blockchain_anchored_at is not None
    # Signature is completely untouched by anchoring.
    assert result.signature == original_signature

    log = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.action == "CREDENTIAL_ANCHORED", ActivityLog.entity_id == result.id)
        .first()
    )
    assert log is not None
    assert log.metadata_["tx_hash"] == result.blockchain_tx_hash


# --- 13: existing verification still works before and after anchoring -------------------------


def test_verification_unaffected_by_anchoring(client, db_session):
    from datetime import datetime, timedelta, timezone

    from app.models.share_grant import ShareGrant, ShareGrantCredential

    ctx = _setup(client, db_session)
    verifier = _register_verifier(client, db_session, email="anchor-verify-check@test.credchain.dev")

    grant = ShareGrant(
        student_id=uuid.UUID(ctx["student"]["student_id"]),
        company_id=uuid.UUID(verifier["company_id"]),
        share_token_hash="test-token-hash-" + uuid.uuid4().hex,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db_session.add(grant)
    db_session.flush()
    db_session.add(ShareGrantCredential(share_grant_id=grant.id, credential_id=uuid.UUID(ctx["credential"]["id"])))
    db_session.commit()

    pre = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["credential"]["id"]},
        headers=_auth_header(verifier["token"]),
    )
    assert pre.json()["result"] == "VERIFIED"

    fake_client = FakeBlockchainClient()
    _anchor_via_service(db_session, ctx, fake_client)

    post = client.post(
        "/api/verification/verify",
        json={"credential_id": ctx["credential"]["id"]},
        headers=_auth_header(verifier["token"]),
    )
    assert post.json()["result"] == "VERIFIED"
    assert post.json()["checks"]["signature"] is True
