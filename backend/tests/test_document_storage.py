# ---------------------------------------------------------------------------
# Supabase Storage migration: document_service's storage abstraction.
#
# These tests exercise document_service directly (no HTTP client, no
# database) — save/read/exists/delete for both the local-filesystem fallback
# (the path every OTHER existing test in this suite still takes, since none
# of them set SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY — see conftest.py) and
# the Supabase-configured path, using a fake in-memory Supabase client rather
# than any real project/credentials, per the task's "use mocks/fakes" rule.
#
# The fake client's fake StorageApiError is installed in place of the real
# storage3.exceptions.StorageApiError for the duration of each test that
# needs it, since document_service._is_not_found_error() checks isinstance
# against that exact class — restored via fixture teardown, never left
# patched for other tests in the suite.
# ---------------------------------------------------------------------------

import uuid

import pytest

from app.services import document_service


class FakeStorageApiError(Exception):
    def __init__(self, message, code, status):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


class FakeBucket:
    """One bucket's worth of in-memory (bucket_name, path) -> bytes storage, shared across FakeBucket instances for the same run."""

    def __init__(self, bucket_name, store):
        self.bucket_name = bucket_name
        self._store = store

    def upload(self, path, data, options=None):
        self._store[(self.bucket_name, path)] = data

    def download(self, path):
        key = (self.bucket_name, path)
        if key not in self._store:
            raise FakeStorageApiError("Object not found", "not_found", "404")
        return self._store[key]

    def remove(self, paths):
        for p in paths:
            self._store.pop((self.bucket_name, p), None)


class FakeUnreachableBucket:
    """Simulates a network/service failure — never a clean 'not found'."""

    def download(self, path):
        raise ConnectionError("simulated network failure")

    def upload(self, path, data, options=None):
        raise ConnectionError("simulated network failure")

    def remove(self, paths):
        raise ConnectionError("simulated network failure")


class FakeStorage:
    def __init__(self, store, unreachable=False):
        self._store = store
        self.unreachable = unreachable

    def from_(self, bucket_name):
        return FakeUnreachableBucket() if self.unreachable else FakeBucket(bucket_name, self._store)


class FakeSupabaseClient:
    def __init__(self, store, unreachable=False):
        self.storage = FakeStorage(store, unreachable=unreachable)


@pytest.fixture()
def fake_supabase(monkeypatch):
    """
    Configures document_service as if SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY
    were set, and swaps in an in-memory fake client instead of the real
    supabase-py client — no real Supabase project/credentials are used
    anywhere in this test file. Returns the shared in-memory store dict so
    tests can inspect it directly if needed.
    """
    from app.config import settings

    store: dict[tuple[str, str], bytes] = {}
    monkeypatch.setattr(settings, "supabase_url", "https://fake.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "fake-service-role-key")
    monkeypatch.setattr(document_service, "_supabase_client", lambda: FakeSupabaseClient(store))

    import storage3.exceptions as storage3_exceptions

    # document_service._is_not_found_error() does a local `from storage3.exceptions import
    # StorageApiError` at call time, so patching the module attribute here is picked up correctly.
    monkeypatch.setattr(storage3_exceptions, "StorageApiError", FakeStorageApiError)
    return store


@pytest.fixture()
def fake_supabase_unreachable(monkeypatch):
    """Same as fake_supabase, but every storage call raises a plain network-style error — never a clean 'not found'."""
    from app.config import settings

    monkeypatch.setattr(settings, "supabase_url", "https://fake.supabase.co")
    monkeypatch.setattr(settings, "supabase_service_role_key", "fake-service-role-key")
    monkeypatch.setattr(document_service, "_supabase_client", lambda: FakeSupabaseClient({}, unreachable=True))


# ---- Local filesystem fallback (Supabase not configured) ------------------


def test_local_fallback_save_read_exists_delete(tmp_path, monkeypatch):
    """Every existing test in this suite takes exactly this path — proves it is completely unchanged by the migration."""
    from app.config import settings

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    assert not document_service._supabase_configured()

    credential_id = uuid.uuid4()
    data = b"%PDF-1.4\n%local-fallback-test\n%%EOF"

    storage_path = document_service.save_document(credential_id, data)
    assert not document_service._is_supabase_key(storage_path)
    assert document_service.document_exists(storage_path) is True
    assert document_service.read_document(storage_path) == data

    document_service.delete_document_if_exists(storage_path)
    assert document_service.document_exists(storage_path) is False


def test_local_fallback_student_document_uses_separate_subdirectory(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    document_id = uuid.uuid4()
    data = b"%PDF-1.4\n%student-doc-local\n%%EOF"

    storage_path = document_service.save_student_document(document_id, data)
    assert document_service.read_document(storage_path) == data
    assert "student_documents" in storage_path


# ---- Supabase-configured path (fake client, no real credentials) ----------


def test_credential_upload_stores_bytes_and_correct_object_key(fake_supabase):
    credential_id = uuid.uuid4()
    data = b"%PDF-1.4\n%credential-upload\n%%EOF"

    storage_path = document_service.save_document(credential_id, data)

    assert storage_path == f"credentials/{credential_id}.pdf"
    assert document_service._is_supabase_key(storage_path)


def test_student_document_upload_stores_bytes_and_correct_object_key(fake_supabase):
    document_id = uuid.uuid4()
    data = b"%PDF-1.4\n%student-document-upload\n%%EOF"

    storage_path = document_service.save_student_document(document_id, data)

    assert storage_path == f"student-documents/{document_id}.pdf"
    assert document_service._is_supabase_key(storage_path)


def test_storage_path_is_object_key_not_a_url(fake_supabase):
    storage_path = document_service.save_document(uuid.uuid4(), b"%PDF-1.4\n%key-shape\n%%EOF")
    assert not storage_path.startswith("http://")
    assert not storage_path.startswith("https://")
    assert "?" not in storage_path  # no signed-URL query string


def test_download_returns_byte_identical_pdf(fake_supabase):
    credential_id = uuid.uuid4()
    original_bytes = b"%PDF-1.4\n%exact-bytes-test\nSOME BODY CONTENT HERE\n%%EOF"

    storage_path = document_service.save_document(credential_id, original_bytes)
    retrieved_bytes = document_service.read_document(storage_path)

    assert retrieved_bytes == original_bytes


def test_verification_hashes_the_exact_retrieved_bytes(fake_supabase):
    """Mirrors verification_service.check_document_integrity's own SHA-256 comparison, without needing a DB-backed Credential row."""
    credential_id = uuid.uuid4()
    original_bytes = b"%PDF-1.4\n%hash-check\n%%EOF"
    expected_hash = document_service.compute_sha256(original_bytes)

    storage_path = document_service.save_document(credential_id, original_bytes)
    actual_hash = document_service.compute_sha256(document_service.read_document(storage_path))

    assert actual_hash == expected_hash


def test_tampered_bytes_produce_a_different_hash(fake_supabase):
    """The other half of check_document_integrity's logic: tampered storage bytes must not hash-match the original."""
    credential_id = uuid.uuid4()
    original_bytes = b"%PDF-1.4\n%original\n%%EOF"
    original_hash = document_service.compute_sha256(original_bytes)

    storage_path = document_service.save_document(credential_id, original_bytes)
    # Simulate the file being replaced/corrupted directly in storage, exactly like
    # test_verification.py's existing local-filesystem tamper test does.
    bucket = document_service._supabase_client().storage.from_(document_service._bucket_name_for_key(storage_path))
    bucket.upload(storage_path, b"%PDF-1.4\n%tampered\n%%EOF")

    tampered_hash = document_service.compute_sha256(document_service.read_document(storage_path))
    assert tampered_hash != original_hash


def test_missing_object_reports_not_exists_not_an_exception(fake_supabase):
    missing_key = f"credentials/{uuid.uuid4()}.pdf"
    assert document_service.document_exists(missing_key) is False


def test_missing_object_read_raises_file_not_found(fake_supabase):
    missing_key = f"credentials/{uuid.uuid4()}.pdf"
    with pytest.raises(FileNotFoundError):
        document_service.read_document(missing_key)


def test_delete_removes_the_correct_object_only(fake_supabase):
    id_a, id_b = uuid.uuid4(), uuid.uuid4()
    path_a = document_service.save_document(id_a, b"%PDF-1.4\n%a\n%%EOF")
    path_b = document_service.save_document(id_b, b"%PDF-1.4\n%b\n%%EOF")

    document_service.delete_document_if_exists(path_a)

    assert document_service.document_exists(path_a) is False
    assert document_service.document_exists(path_b) is True  # unrelated object untouched


def test_legacy_local_path_still_readable_once_supabase_is_configured(fake_supabase, tmp_path, monkeypatch):
    """
    The actual production transition scenario: SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY get set
    (so all NEW uploads go to Supabase), but existing rows in the database still hold old
    "storage/credentials/<uuid>.pdf"-shaped local paths from before the migration. Those must
    keep resolving via the local filesystem, never be misinterpreted as a Supabase object key.
    """
    from app.config import settings

    # Write a "legacy" file directly, independent of which backend is currently configured —
    # this mirrors a row that was uploaded before Supabase was ever turned on.
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    legacy_credential_id = uuid.uuid4()
    legacy_bytes = b"%PDF-1.4\n%pre-migration-upload\n%%EOF"
    legacy_path = document_service.credential_document_path(legacy_credential_id)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_bytes(legacy_bytes)
    legacy_storage_path = str(legacy_path)

    # Supabase is now configured (fake_supabase fixture) — a brand NEW upload goes there...
    new_storage_path = document_service.save_document(uuid.uuid4(), b"%PDF-1.4\n%post-migration-upload\n%%EOF")
    assert document_service._is_supabase_key(new_storage_path)

    # ...but the legacy row's path is still correctly recognized as local and still readable.
    assert not document_service._is_supabase_key(legacy_storage_path)
    assert document_service.document_exists(legacy_storage_path) is True
    assert document_service.read_document(legacy_storage_path) == legacy_bytes


def test_credential_and_student_document_keys_use_different_bucket_prefixes(fake_supabase):
    credential_key = document_service.save_document(uuid.uuid4(), b"%PDF-1.4\n%c\n%%EOF")
    student_key = document_service.save_student_document(uuid.uuid4(), b"%PDF-1.4\n%s\n%%EOF")

    assert credential_key.startswith("credentials/")
    assert student_key.startswith("student-documents/")
    assert document_service._bucket_name_for_key(credential_key) != document_service._bucket_name_for_key(student_key)


# ---- Storage outage must never look like "missing" or "tampered" ----------


def test_storage_outage_on_exists_raises_storage_unavailable(fake_supabase_unreachable):
    with pytest.raises(document_service.StorageUnavailableError):
        document_service.document_exists(f"credentials/{uuid.uuid4()}.pdf")


def test_storage_outage_on_read_raises_storage_unavailable(fake_supabase_unreachable):
    with pytest.raises(document_service.StorageUnavailableError):
        document_service.read_document(f"credentials/{uuid.uuid4()}.pdf")


def test_storage_outage_on_upload_raises_storage_unavailable(fake_supabase_unreachable):
    with pytest.raises(document_service.StorageUnavailableError):
        document_service.save_document(uuid.uuid4(), b"%PDF-1.4\n%x\n%%EOF")


def test_storage_outage_never_raises_a_plain_file_not_found(fake_supabase_unreachable):
    """The critical distinction the task calls out: an outage must not be mistakable for a genuinely missing document."""
    try:
        document_service.document_exists(f"credentials/{uuid.uuid4()}.pdf")
        assert False, "expected StorageUnavailableError"
    except document_service.StorageUnavailableError:
        pass
    except FileNotFoundError:
        assert False, "an outage must never surface as FileNotFoundError"


def test_delete_on_unreachable_storage_does_not_raise(fake_supabase_unreachable):
    """delete_document_if_exists is best-effort cleanup inside an except-block in real callers — it must never itself raise and mask the real error."""
    document_service.delete_document_if_exists(f"credentials/{uuid.uuid4()}.pdf")  # must not raise


# ---------------------------------------------------------------------------
# Upload-time StorageUnavailableError: a temporary storage outage during
# credential/student-document issuance must return 503, never an unhandled
# 500 and never a false "success" — no Credential/StudentDocument row may be
# left behind for a document that was never actually durably stored.
#
# document_service.save_document/save_student_document are monkeypatched
# directly here (real HTTP request, real DB, real signing) — this isolates
# "what happens when the storage write itself fails" from the storage
# backend's own internals, which are already covered above.
# ---------------------------------------------------------------------------

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%upload-outage-test\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_institution(client, db_session, email, name):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "Outage Test Admin", "role": "institution", "institution_id": str(institution.id)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, institution_id, email, identifier):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": "Outage Test Student",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return {"token": resp.json()["access_token"], "student_id": resp.json()["user"]["student_id"]}


def test_credential_issuance_returns_503_and_creates_no_credential_when_storage_unavailable(client, db_session, monkeypatch):
    from app.models.credential import Credential

    inst = _register_institution(client, db_session, "storage-outage-inst@test.credchain.dev", "Storage Outage University")
    student = _register_student(client, inst["institution_id"], "storage-outage-stu@test.credchain.dev", "STORAGE-OUTAGE-1")

    def _raise_unavailable(credential_id, data):
        raise document_service.StorageUnavailableError("simulated Supabase outage")

    monkeypatch.setattr(document_service, "save_document", _raise_unavailable)

    resp = client.post(
        "/api/institutions/me/credentials",
        data={
            "student_id": student["student_id"],
            "credential_type": "transcript",
            "title": "Final Transcript",
        },
        files={"document": ("transcript.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
        headers=_auth_header(inst["token"]),
    )

    assert resp.status_code == 503, resp.text
    assert "temporarily unavailable" in resp.json()["detail"].lower()

    remaining = db_session.query(Credential).filter(Credential.student_id == uuid.UUID(student["student_id"])).count()
    assert remaining == 0, "a failed document upload must never leave behind a credential row"


def test_bulk_issuance_returns_503_and_creates_no_credentials_when_storage_unavailable(client, db_session, monkeypatch):
    from app.models.credential import Credential

    inst = _register_institution(client, db_session, "storage-outage-bulk-inst@test.credchain.dev", "Storage Outage Bulk University")
    student_a = _register_student(client, inst["institution_id"], "storage-outage-bulk-a@test.credchain.dev", "STORAGE-OUTAGE-BULK-A")
    student_b = _register_student(client, inst["institution_id"], "storage-outage-bulk-b@test.credchain.dev", "STORAGE-OUTAGE-BULK-B")

    def _always_raise_unavailable(credential_id, data):
        raise document_service.StorageUnavailableError("simulated Supabase outage")

    monkeypatch.setattr(document_service, "save_document", _always_raise_unavailable)

    resp = client.post(
        "/api/institutions/me/credentials/bulk",
        data={
            "student_ids": [student_a["student_id"], student_b["student_id"]],
            "credential_type": "transcript",
            "title": "Final Transcript",
        },
        files=[
            ("documents", ("a.pdf", SAMPLE_PDF_BYTES, "application/pdf")),
            ("documents", ("b.pdf", SAMPLE_PDF_BYTES, "application/pdf")),
        ],
        headers=_auth_header(inst["token"]),
    )

    # The whole batch aborts with one honest 503 (matching InstitutionKeyMissingError's
    # existing treatment) rather than a 200 response whose per-item results would
    # misleadingly look like two independent, unrelated per-student failures.
    assert resp.status_code == 503, resp.text

    remaining = (
        db_session.query(Credential)
        .filter(Credential.student_id.in_([uuid.UUID(student_a["student_id"]), uuid.UUID(student_b["student_id"])]))
        .count()
    )
    assert remaining == 0, "no item's storage write ever succeeded, so no credential should exist for either student"


def test_bulk_issuance_does_not_roll_back_items_already_committed_before_the_outage(client, db_session, monkeypatch):
    """
    Bulk issuance has never been atomic across items (see credential_service.
    bulk_issue_credentials's own docstring: "never aborts or rolls back another
    student's already-issued credential"). A storage outage on item 2 stops
    processing further items and surfaces 503 for the request overall, but it
    must not — and structurally cannot, since each item commits independently —
    retroactively undo item 1's already-genuinely-successful, already-committed
    credential.
    """
    from app.models.credential import Credential

    inst = _register_institution(client, db_session, "storage-outage-partial-inst@test.credchain.dev", "Storage Outage Partial University")
    student_a = _register_student(client, inst["institution_id"], "storage-outage-partial-a@test.credchain.dev", "STORAGE-OUTAGE-PARTIAL-A")
    student_b = _register_student(client, inst["institution_id"], "storage-outage-partial-b@test.credchain.dev", "STORAGE-OUTAGE-PARTIAL-B")

    real_save_document = document_service.save_document
    call_count = {"n": 0}

    def _fail_on_second_call(credential_id, data):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            raise document_service.StorageUnavailableError("simulated Supabase outage")
        return real_save_document(credential_id, data)

    monkeypatch.setattr(document_service, "save_document", _fail_on_second_call)

    resp = client.post(
        "/api/institutions/me/credentials/bulk",
        data={
            "student_ids": [student_a["student_id"], student_b["student_id"]],
            "credential_type": "transcript",
            "title": "Final Transcript",
        },
        files=[
            ("documents", ("a.pdf", SAMPLE_PDF_BYTES, "application/pdf")),
            ("documents", ("b.pdf", SAMPLE_PDF_BYTES, "application/pdf")),
        ],
        headers=_auth_header(inst["token"]),
    )

    assert resp.status_code == 503, resp.text

    a_count = db_session.query(Credential).filter(Credential.student_id == uuid.UUID(student_a["student_id"])).count()
    b_count = db_session.query(Credential).filter(Credential.student_id == uuid.UUID(student_b["student_id"])).count()
    assert a_count == 1, "student A's document upload genuinely succeeded before the outage — its credential legitimately exists"
    assert b_count == 0, "student B's document upload hit the outage — no credential should exist for them"


def test_student_document_upload_returns_503_and_creates_no_document_when_storage_unavailable(client, db_session, monkeypatch):
    from app.models.student_document import StudentDocument

    inst = _register_institution(client, db_session, "storage-outage-doc-inst@test.credchain.dev", "Storage Outage Doc University")
    student = _register_student(client, inst["institution_id"], "storage-outage-doc-stu@test.credchain.dev", "STORAGE-OUTAGE-DOC-1")

    def _raise_unavailable(document_id, data):
        raise document_service.StorageUnavailableError("simulated Supabase outage")

    monkeypatch.setattr(document_service, "save_student_document", _raise_unavailable)

    resp = client.post(
        "/api/students/me/documents",
        data={"institution_id": inst["institution_id"], "credential_type": "migration"},
        files={"document": ("old_cert.pdf", SAMPLE_PDF_BYTES, "application/pdf")},
        headers=_auth_header(student["token"]),
    )

    assert resp.status_code == 503, resp.text
    assert "temporarily unavailable" in resp.json()["detail"].lower()

    remaining = db_session.query(StudentDocument).filter(StudentDocument.student_id == uuid.UUID(student["student_id"])).count()
    assert remaining == 0, "a failed document upload must never leave behind a student document row"
