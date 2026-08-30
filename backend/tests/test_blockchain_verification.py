# ---------------------------------------------------------------------------
# Phase 9C tests: blockchain verification as an additional, read-only check
# in the existing verification flow.
#
# No test here makes a real network call. Scenarios that need a specific
# on-chain outcome (ANCHORED / UNAVAILABLE) call verification_service.
# verify_credential directly with a FakeBlockchainClient injected via its
# `blockchain_client` parameter — this is NOT a real testnet check, and is
# labeled as such throughout. Scenarios that don't depend on a successful
# anchor (revoked/unauthorized/tampered/etc.) go through the real HTTP
# route, exactly like the existing Phase 5 tests in test_verification.py.
#
# NOTE on "expired share": the phase spec assumes an expired ShareGrant
# produces an "EXPIRED" overall result. The EXISTING (pre-Phase-9)
# architecture does not work that way — authorization_service.
# is_verifier_authorized already filters out expired grants, so an expired
# share is indistinguishable from "no share at all" and correctly produces
# UNAUTHORIZED (see test_verification.py's EXPIRED test, which reaches
# EXPIRED only by setting credential.status directly, a separate lifecycle
# field). This file preserves that existing, tested behavior rather than
# changing the authorization boundary to match the spec's assumption.
# ---------------------------------------------------------------------------

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from app.models.credential import Credential
from app.models.enums import BlockchainAnchorStatus
from app.models.institution import Institution
from app.models.share_grant import ShareGrant, ShareGrantCredential
from app.models.student import Student
from app.services import verification_service
from app.services.blockchain.anchoring_service import compute_blockchain_credential_hash

SAMPLE_PDF_BYTES = (
    b"%PDF-1.4\n%credchain-test-fixture\n"
    b"1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF"
)


class FakeBlockchainClient:
    """
    Simulates the deployed contract's READ-ONLY function only. Deliberately
    has no working anchor_hash() — any test that accidentally tried to
    submit a transaction through this fake would get an AttributeError/
    AssertionError, not a silent success, which is how test 12 proves
    verification never submits one.
    """

    def __init__(self, *, exists: bool = True, fail: bool = False):
        self.exists = exists
        self.fail = fail
        self.get_anchor_calls = 0

    def get_anchor(self, credential_hash_hex: str) -> dict:
        self.get_anchor_calls += 1
        if self.fail:
            raise ConnectionError("simulated RPC failure")
        return {"issuer": "0x0000000000000000000000000000000000dEaD", "timestamp": 1_800_000_000, "exists": self.exists}


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register(client, *, role, email, **extra):
    payload = {"email": email, "password": "Password123", "full_name": f"Test {role.title()}", "role": role, **extra}
    resp = client.post("/api/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _register_institution(client, db_session, email="bcv-inst@test.credchain.dev", name="Blockchain Verify University"):
    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    body = _register(client, role="institution", email=email, institution_id=str(institution.id))
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, db_session, institution_id, email="bcv-student@test.credchain.dev", identifier="STU-BCV-001"):
    body = _register(client, role="student", email=email, student_identifier=identifier)
    student_id = body["user"]["student_id"]
    student = db_session.query(Student).filter(Student.id == uuid.UUID(student_id)).first()
    student.institution_id = uuid.UUID(institution_id)
    db_session.commit()
    return {"token": body["access_token"], "student_id": student_id}


def _register_verifier(client, db_session, email="bcv-verifier@test.credchain.dev", name="Blockchain Verify Company"):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    body = _register(client, role="verifier", email=email, company_id=str(company.id))
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _issue_credential(client, institution_token, student_id, **overrides) -> dict:
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


def _grant_access(db_session, *, student_id, company_id, credential_id, expires_in_days=7, revoked=False):
    grant = ShareGrant(
        student_id=uuid.UUID(student_id),
        company_id=uuid.UUID(company_id),
        share_token_hash="test-token-hash-" + uuid.uuid4().hex,
        expires_at=datetime.now(timezone.utc) + timedelta(days=expires_in_days),
        revoked_at=datetime.now(timezone.utc) if revoked else None,
    )
    db_session.add(grant)
    db_session.flush()
    db_session.add(ShareGrantCredential(share_grant_id=grant.id, credential_id=uuid.UUID(credential_id)))
    db_session.commit()
    return grant


def _verify(client, verifier_token, credential_id):
    return client.post(
        "/api/verification/verify", json={"credential_id": credential_id}, headers=_auth_header(verifier_token)
    )


def _setup(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    credential = _issue_credential(client, inst["token"], student["student_id"])
    verifier = _register_verifier(client, db_session)
    _grant_access(
        db_session, student_id=student["student_id"], company_id=verifier["company_id"], credential_id=credential["id"]
    )
    return {"inst": inst, "student": student, "credential": credential, "verifier": verifier}


def _mark_anchored(db_session, credential_id: str, *, hash_override: str | None = None) -> Credential:
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(credential_id)).first()
    real_hash = compute_blockchain_credential_hash(credential)
    credential.blockchain_status = BlockchainAnchorStatus.ANCHORED
    credential.blockchain_credential_hash = hash_override if hash_override is not None else real_hash
    credential.blockchain_network = "polygon-amoy"
    credential.blockchain_contract_address = "0x1111111111111111111111111111111111111a"
    credential.blockchain_tx_hash = "0x" + hashlib.sha256(credential_id.encode()).hexdigest()
    credential.blockchain_anchored_at = datetime.now(timezone.utc)
    db_session.add(credential)
    db_session.commit()
    db_session.refresh(credential)
    return credential


def _company_of(db_session, company_id: str):
    from app.models.company import Company

    return db_session.query(Company).filter(Company.id == uuid.UUID(company_id)).first()


# --- 1: anchored credential + matching hash -> blockchain ANCHORED ----------------------------


def test_anchored_matching_hash_gives_blockchain_anchored(client, db_session):
    ctx = _setup(client, db_session)
    _mark_anchored(db_session, ctx["credential"]["id"])
    company = _company_of(db_session, ctx["verifier"]["company_id"])

    fake_client = FakeBlockchainClient(exists=True)
    result = verification_service.verify_credential(
        db_session, company, uuid.UUID(ctx["credential"]["id"]), blockchain_client=fake_client
    )

    assert result["blockchain"]["status"] == "ANCHORED"
    assert result["blockchain"]["anchored"] is True
    assert result["blockchain"]["hash_matches"] is True
    assert result["blockchain"]["network"] == "polygon-amoy"
    assert result["blockchain"]["transaction_hash"] is not None
    assert result["result"] == "VERIFIED"
    assert fake_client.get_anchor_calls == 1


# --- 2/4: recorded anchor hash != current hash -> MISMATCH -> overall INVALID -----------------


def test_hash_changed_since_anchoring_gives_mismatch_and_invalid(client, db_session):
    ctx = _setup(client, db_session)
    # Anchor recorded against a hash that does NOT match this credential's
    # real current data — signature/document are both still genuinely
    # valid, isolating the MISMATCH check as the sole cause of INVALID.
    bogus_hash = "0x" + hashlib.sha256(b"not-the-real-payload").hexdigest()
    _mark_anchored(db_session, ctx["credential"]["id"], hash_override=bogus_hash)
    company = _company_of(db_session, ctx["verifier"]["company_id"])

    result = verification_service.verify_credential(
        db_session, company, uuid.UUID(ctx["credential"]["id"]), blockchain_client=FakeBlockchainClient()
    )

    assert result["blockchain"]["status"] == "MISMATCH"
    assert result["blockchain"]["hash_matches"] is False
    assert result["checks"]["signature"] is True  # proves this isn't a signature failure in disguise
    assert result["checks"]["integrity"] is True
    assert result["result"] == "INVALID"


# --- 3: no anchor -> NOT_ANCHORED, credential still VERIFIED ----------------------------------


def test_no_anchor_gives_not_anchored_but_still_verified(client, db_session):
    ctx = _setup(client, db_session)
    resp = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["blockchain"]["status"] == "NOT_ANCHORED"
    assert body["blockchain"]["anchored"] is False
    assert body["result"] == "VERIFIED"


# --- 5: revoked credential -> REVOKED, unaffected by (absent) blockchain anchor ---------------


def test_revoked_credential_still_revoked_with_blockchain_not_anchored(client, db_session):
    ctx = _setup(client, db_session)
    revoke_resp = client.post(
        f"/api/credentials/{ctx['credential']['id']}/revoke", headers=_auth_header(ctx["inst"]["token"])
    )
    assert revoke_resp.status_code == 200

    resp = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    body = resp.json()
    assert body["result"] == "REVOKED"
    assert body["blockchain"]["status"] == "NOT_ANCHORED"


# --- 6: expired share -> UNAUTHORIZED (existing architecture; see module docstring) -----------


def test_expired_share_is_unauthorized(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    credential = _issue_credential(client, inst["token"], student["student_id"])
    verifier = _register_verifier(client, db_session)
    _grant_access(
        db_session,
        student_id=student["student_id"],
        company_id=verifier["company_id"],
        credential_id=credential["id"],
        expires_in_days=-1,  # already expired
    )

    resp = _verify(client, verifier["token"], credential["id"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "UNAUTHORIZED"
    assert body["blockchain"] is None


# --- 7: unauthorized verifier (no share at all) -----------------------------------------------


def test_no_share_grant_is_unauthorized(client, db_session):
    inst = _register_institution(client, db_session)
    student = _register_student(client, db_session, inst["institution_id"])
    credential = _issue_credential(client, inst["token"], student["student_id"])
    verifier = _register_verifier(client, db_session, email="bcv-no-access@test.credchain.dev")

    resp = _verify(client, verifier["token"], credential["id"])
    assert resp.json()["result"] == "UNAUTHORIZED"


# --- 8: invalid Ed25519 signature -> INVALID ----------------------------------------------------


def test_tampered_signature_is_invalid(client, db_session):
    ctx = _setup(client, db_session)
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    credential.signature = "dGFtcGVyZWQtc2lnbmF0dXJl"  # base64 garbage, not a real signature
    db_session.add(credential)
    db_session.commit()

    resp = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    body = resp.json()
    assert body["result"] == "INVALID"
    assert body["checks"]["signature"] is False


# --- 9: invalid document integrity -> INVALID ----------------------------------------------------


def test_corrupted_document_is_invalid(client, db_session):
    from pathlib import Path

    ctx = _setup(client, db_session)
    credential = db_session.query(Credential).filter(Credential.id == uuid.UUID(ctx["credential"]["id"])).first()
    Path(credential.document.storage_path).write_bytes(b"%PDF-1.4\ncorrupted-after-issuance")

    resp = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    body = resp.json()
    assert body["result"] == "INVALID"
    assert body["checks"]["integrity"] is False


# --- 10: blockchain unavailable -> safe UNAVAILABLE result, never silently "verified" ----------


def test_blockchain_read_failure_gives_unavailable(client, db_session):
    ctx = _setup(client, db_session)
    _mark_anchored(db_session, ctx["credential"]["id"])
    company = _company_of(db_session, ctx["verifier"]["company_id"])

    fake_client = FakeBlockchainClient(fail=True)
    result = verification_service.verify_credential(
        db_session, company, uuid.UUID(ctx["credential"]["id"]), blockchain_client=fake_client
    )

    assert result["blockchain"]["status"] == "UNAVAILABLE"
    assert result["blockchain"]["hash_matches"] is None
    # UNAVAILABLE never downgrades an otherwise-valid credential, and never
    # claims blockchain verification succeeded (status is explicitly
    # UNAVAILABLE, not ANCHORED).
    assert result["result"] == "VERIFIED"
    assert result["blockchain"]["status"] != "ANCHORED"


# --- 11/12: no verifier wallet required; no transaction ever submitted ------------------------


def test_verification_requires_no_wallet_and_submits_no_transaction(client, db_session):
    ctx = _setup(client, db_session)
    _mark_anchored(db_session, ctx["credential"]["id"])
    company = _company_of(db_session, ctx["verifier"]["company_id"])

    fake_client = FakeBlockchainClient(exists=True)
    assert not hasattr(fake_client, "anchor_hash")  # the fake has no write path at all

    resp = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    body = resp.json()
    body_text = str(body).lower()
    assert "wallet" not in body_text
    assert "private_key" not in body_text

    # Direct service call with the fake proves only the read-only method is
    # ever invoked for a verify — no attribute/call resembling a write path.
    result = verification_service.verify_credential(
        db_session, company, uuid.UUID(ctx["credential"]["id"]), blockchain_client=fake_client
    )
    assert fake_client.get_anchor_calls == 1
    assert result["result"] == "VERIFIED"


# --- 13: existing verification behavior unchanged for unanchored credentials ------------------


def test_existing_checks_dict_shape_unchanged(client, db_session):
    ctx = _setup(client, db_session)
    resp = _verify(client, ctx["verifier"]["token"], ctx["credential"]["id"])
    body = resp.json()
    assert set(body["checks"].keys()) == {"issuer", "signature", "integrity", "status", "access"}
    assert body["checks"] == {"issuer": True, "signature": True, "integrity": True, "status": True, "access": True}
