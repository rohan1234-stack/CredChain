# ---------------------------------------------------------------------------
# Job marketplace Phase F/G/H/I/J/K: applications, document sharing (via the
# EXISTING credential-request/share pipeline), company dashboard privacy,
# real verification, requested-vs-received mismatch, and the decision
# workflow. This is the core "does the whole job-application trust chain
# actually work" test file.
# ---------------------------------------------------------------------------

import os
import threading
import uuid as uuid_module

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as RawSession

from app.models.activity_log import ActivityLog
from app.models.company import Company
from app.models.enums import JobEmploymentType, JobStatus
from app.models.job import Job
from app.models.job_application import JobApplication
from app.models.notification import Notification
from app.models.student import Student
from app.services import job_application_service

# Same URL conftest.py's own `engine` uses (see TEST_DATABASE_URL there) — a
# second Engine instance pointed at the identical database, needed here only
# so the two background threads below can each hold a genuinely independent
# connection for a real concurrent-write test.
_TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://credchain:credchain@localhost:5432/credchain_test",
)
_race_test_engine = create_engine(_TEST_DATABASE_URL)

SAMPLE_PDF_BYTES = b"%PDF-1.4\n%app\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF"


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _register_verifier(client, db_session, email, name):
    from app.models.company import Company

    company = Company(name=name)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "App Verifier", "role": "verifier", "company_id": str(company.id)},
    )
    body = resp.json()
    return {"token": body["access_token"], "company_id": body["user"]["company_id"]}


def _register_institution(client, db_session, email, name):
    from app.models.institution import Institution

    institution = Institution(name=name)
    db_session.add(institution)
    db_session.commit()
    db_session.refresh(institution)
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123", "full_name": "App Inst", "role": "institution", "institution_id": str(institution.id)},
    )
    body = resp.json()
    return {"token": body["access_token"], "institution_id": body["user"]["institution_id"]}


def _register_student(client, institution_id, email, identifier):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "Password123",
            "full_name": "App Student",
            "role": "student",
            "student_identifier": identifier,
            "institution_id": institution_id,
        },
    )
    body = resp.json()
    return {"token": body["access_token"], "student_id": body["user"]["student_id"]}


def _issue_credential(client, inst_token, student_id, credential_type, title):
    files = {"document": ("x.pdf", SAMPLE_PDF_BYTES, "application/pdf")}
    resp = client.post(
        "/api/institutions/me/credentials",
        data={"student_id": student_id, "credential_type": credential_type, "title": title},
        files=files,
        headers=_auth_header(inst_token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_open_job(client, verifier_token, **overrides):
    payload = {
        "title": "Software Engineer",
        "description": "Real job.",
        "employment_type": "full_time",
        "required_documents": ["Migration Certificate"],
    }
    payload.update(overrides)
    job = client.post("/api/companies/me/jobs", json=payload, headers=_auth_header(verifier_token)).json()
    client.post(f"/api/companies/me/jobs/{job['id']}/publish", headers=_auth_header(verifier_token))
    return job


def test_student_can_apply_with_owned_credential_and_see_it_in_my_applications(client, db_session):
    verifier = _register_verifier(client, db_session, "app-co-1@test.credchain.dev", "App Co 1")
    inst = _register_institution(client, db_session, "app-inst-1@test.credchain.dev", "App University 1")
    student = _register_student(client, inst["institution_id"], "app-stu-1@test.credchain.dev", "APP-STU-1")
    job = _create_open_job(client, verifier["token"])
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    resp = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "applied"
    assert resp.json()["company_name"] == "App Co 1"

    list_resp = client.get("/api/students/me/applications", headers=_auth_header(student["token"]))
    assert len(list_resp.json()) == 1


def test_cannot_apply_twice_or_to_closed_or_nonexistent_job(client, db_session):
    import uuid

    verifier = _register_verifier(client, db_session, "app-co-2@test.credchain.dev", "App Co 2")
    inst = _register_institution(client, db_session, "app-inst-2@test.credchain.dev", "App University 2")
    student = _register_student(client, inst["institution_id"], "app-stu-2@test.credchain.dev", "APP-STU-2")
    job = _create_open_job(client, verifier["token"])
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    first = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    assert first.status_code == 201

    second = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    assert second.status_code == 409

    closed_job = _create_open_job(client, verifier["token"], title="Closing Job")
    client.post(f"/api/companies/me/jobs/{closed_job['id']}/close", headers=_auth_header(verifier["token"]))
    closed_resp = client.post(
        "/api/students/me/applications", json={"job_id": closed_job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    assert closed_resp.status_code == 409

    missing_resp = client.post(
        "/api/students/me/applications", json={"job_id": str(uuid.uuid4()), "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    assert missing_resp.status_code == 404


def test_company_sees_only_its_own_applicants_never_other_companies_or_all_students(client, db_session):
    verifier_a = _register_verifier(client, db_session, "app-co-a@test.credchain.dev", "App Co A")
    verifier_b = _register_verifier(client, db_session, "app-co-b@test.credchain.dev", "App Co B")
    inst = _register_institution(client, db_session, "app-inst-3@test.credchain.dev", "App University 3")
    student = _register_student(client, inst["institution_id"], "app-stu-3@test.credchain.dev", "APP-STU-3")
    job_a = _create_open_job(client, verifier_a["token"])
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    client.post("/api/students/me/applications", json={"job_id": job_a["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"]))

    a_apps = client.get("/api/companies/me/applications", headers=_auth_header(verifier_a["token"])).json()
    b_apps = client.get("/api/companies/me/applications", headers=_auth_header(verifier_b["token"])).json()
    assert len(a_apps) == 1
    assert len(b_apps) == 0


def test_company_sees_shared_credential_verify_flow_matching_case(client, db_session):
    verifier = _register_verifier(client, db_session, "app-co-4@test.credchain.dev", "App Co 4")
    inst = _register_institution(client, db_session, "app-inst-4@test.credchain.dev", "App University 4")
    student = _register_student(client, inst["institution_id"], "app-stu-4@test.credchain.dev", "APP-STU-4")
    job = _create_open_job(client, verifier["token"], required_documents=["Migration Certificate"])
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    client.post("/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"]))

    apps = client.get("/api/companies/me/applications", headers=_auth_header(verifier["token"])).json()
    app = apps[0]
    assert app["credential_request"]["requested_credentials"] == ["Migration Certificate"]
    assert app["credential_request"]["shared_credentials"][0]["credential_type"] == "migration"

    verify_resp = client.post("/api/verification/verify", json={"credential_id": cred_id}, headers=_auth_header(verifier["token"]))
    assert verify_resp.status_code == 200
    assert verify_resp.json()["result"] == "VERIFIED"


def test_wrong_credential_shared_produces_type_mismatch_not_verified(client, db_session):
    verifier = _register_verifier(client, db_session, "app-co-5@test.credchain.dev", "App Co 5")
    inst = _register_institution(client, db_session, "app-inst-5@test.credchain.dev", "App University 5")
    student = _register_student(client, inst["institution_id"], "app-stu-5@test.credchain.dev", "APP-STU-5")
    # Job requires Migration Certificate, but the student only shares a Degree.
    job = _create_open_job(client, verifier["token"], required_documents=["Migration Certificate"])
    degree_cred_id = _issue_credential(client, inst["token"], student["student_id"], "degree", "B.Tech Degree")

    apply_resp = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [degree_cred_id]}, headers=_auth_header(student["token"])
    )
    assert apply_resp.status_code == 201

    apps = client.get("/api/companies/me/applications", headers=_auth_header(verifier["token"])).json()
    app = apps[0]
    assert app["credential_request"]["requested_credentials"] == ["Migration Certificate"]
    assert app["credential_request"]["shared_credentials"][0]["credential_type"] == "degree"

    verify_resp = client.post("/api/verification/verify", json={"credential_id": degree_cred_id}, headers=_auth_header(verifier["token"]))
    assert verify_resp.status_code == 200
    assert verify_resp.json()["result"] == "TYPE_MISMATCH"
    assert verify_resp.json()["result"] != "VERIFIED"


def test_company_decision_workflow_whitelisted_transitions(client, db_session):
    verifier = _register_verifier(client, db_session, "app-co-6@test.credchain.dev", "App Co 6")
    inst = _register_institution(client, db_session, "app-inst-6@test.credchain.dev", "App University 6")
    student = _register_student(client, inst["institution_id"], "app-stu-6@test.credchain.dev", "APP-STU-6")
    job = _create_open_job(client, verifier["token"])
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")
    application = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    ).json()
    app_id = client.get("/api/companies/me/applications", headers=_auth_header(verifier["token"])).json()[0]["id"]

    step1 = client.post(f"/api/companies/me/applications/{app_id}/status", json={"status": "under_review"}, headers=_auth_header(verifier["token"]))
    assert step1.status_code == 200
    assert step1.json()["status"] == "under_review"

    # Cannot skip straight to accepted from under_review.
    invalid = client.post(f"/api/companies/me/applications/{app_id}/status", json={"status": "accepted"}, headers=_auth_header(verifier["token"]))
    assert invalid.status_code == 409

    step2 = client.post(f"/api/companies/me/applications/{app_id}/status", json={"status": "shortlisted"}, headers=_auth_header(verifier["token"]))
    assert step2.status_code == 200
    step3 = client.post(f"/api/companies/me/applications/{app_id}/status", json={"status": "accepted"}, headers=_auth_header(verifier["token"]))
    assert step3.status_code == 200
    assert step3.json()["status"] == "accepted"


def test_student_cannot_set_application_status_and_company_cannot_touch_others_application(client, db_session):
    verifier_a = _register_verifier(client, db_session, "app-co-x@test.credchain.dev", "App Co X")
    verifier_b = _register_verifier(client, db_session, "app-co-y@test.credchain.dev", "App Co Y")
    inst = _register_institution(client, db_session, "app-inst-7@test.credchain.dev", "App University 7")
    student = _register_student(client, inst["institution_id"], "app-stu-7@test.credchain.dev", "APP-STU-7")
    job = _create_open_job(client, verifier_a["token"])
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")
    client.post("/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"]))
    app_id = client.get("/api/companies/me/applications", headers=_auth_header(verifier_a["token"])).json()[0]["id"]

    # No student-facing route exists for this at all.
    student_attempt = client.post(f"/api/companies/me/applications/{app_id}/status", json={"status": "accepted"}, headers=_auth_header(student["token"]))
    assert student_attempt.status_code == 403

    other_company_attempt = client.post(
        f"/api/companies/me/applications/{app_id}/status", json={"status": "under_review"}, headers=_auth_header(verifier_b["token"])
    )
    assert other_company_attempt.status_code == 403


# ---------------------------------------------------------------------------
# Prompt 3: database-level uniqueness on (job_id, student_id) — the final
# concurrency safety boundary behind the existing application-level check
# above (test_cannot_apply_twice_or_to_closed_or_nonexistent_job).
# ---------------------------------------------------------------------------


def test_unique_constraint_exists_on_job_id_and_student_id(client, db_session):
    """
    Deterministic, no service layer, no threads: proves the DB itself
    rejects a second (job_id, student_id) row under the exact constraint
    name the migration/model declare, independent of any application code.
    """
    verifier = _register_verifier(client, db_session, "app-uq-co@test.credchain.dev", "App UQ Co")
    inst = _register_institution(client, db_session, "app-uq-inst@test.credchain.dev", "App UQ University")
    student = _register_student(client, inst["institution_id"], "app-uq-stu@test.credchain.dev", "APP-UQ-STU")
    job = _create_open_job(client, verifier["token"])

    common = dict(
        student_id=uuid_module.UUID(student["student_id"]),
        job_id=uuid_module.UUID(job["id"]),
        company_id=uuid_module.UUID(verifier["company_id"]),
    )
    db_session.add(JobApplication(**common))
    db_session.flush()

    db_session.add(JobApplication(**common))
    with pytest.raises(IntegrityError) as excinfo:
        db_session.flush()
    constraint = getattr(getattr(excinfo.value.orig, "diag", None), "constraint_name", None)
    assert constraint == "uq_job_applications_job_id_student_id"
    db_session.rollback()


def test_different_students_can_apply_to_same_job(client, db_session):
    verifier = _register_verifier(client, db_session, "app-multi-co@test.credchain.dev", "App Multi Co")
    inst = _register_institution(client, db_session, "app-multi-inst@test.credchain.dev", "App Multi University")
    student_a = _register_student(client, inst["institution_id"], "app-multi-stu-a@test.credchain.dev", "APP-MULTI-A")
    student_b = _register_student(client, inst["institution_id"], "app-multi-stu-b@test.credchain.dev", "APP-MULTI-B")
    job = _create_open_job(client, verifier["token"])
    cred_a = _issue_credential(client, inst["token"], student_a["student_id"], "migration", "Migration Certificate")
    cred_b = _issue_credential(client, inst["token"], student_b["student_id"], "migration", "Migration Certificate")

    resp_a = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_a]}, headers=_auth_header(student_a["token"])
    )
    resp_b = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_b]}, headers=_auth_header(student_b["token"])
    )
    assert resp_a.status_code == 201
    assert resp_b.status_code == 201


def test_same_student_can_apply_to_different_jobs(client, db_session):
    verifier = _register_verifier(client, db_session, "app-two-jobs-co@test.credchain.dev", "App Two Jobs Co")
    inst = _register_institution(client, db_session, "app-two-jobs-inst@test.credchain.dev", "App Two Jobs University")
    student = _register_student(client, inst["institution_id"], "app-two-jobs-stu@test.credchain.dev", "APP-TWO-JOBS")
    job_1 = _create_open_job(client, verifier["token"], title="Job One")
    job_2 = _create_open_job(client, verifier["token"], title="Job Two")
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    resp_1 = client.post(
        "/api/students/me/applications", json={"job_id": job_1["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    resp_2 = client.post(
        "/api/students/me/applications", json={"job_id": job_2["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    assert resp_1.status_code == 201
    assert resp_2.status_code == 201


def test_sequential_duplicate_creates_no_extra_activity_log_or_notification(client, db_session):
    verifier = _register_verifier(client, db_session, "app-dup-side-co@test.credchain.dev", "App Dup Side Co")
    inst = _register_institution(client, db_session, "app-dup-side-inst@test.credchain.dev", "App Dup Side University")
    student = _register_student(client, inst["institution_id"], "app-dup-side-stu@test.credchain.dev", "APP-DUP-SIDE")
    job = _create_open_job(client, verifier["token"])
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    first = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    assert first.status_code == 201
    application_id = uuid_module.UUID(first.json()["id"])

    second = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    assert second.status_code == 409

    logs = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.entity_type == "job_application", ActivityLog.entity_id == application_id)
        .all()
    )
    assert len(logs) == 1

    notifications = db_session.query(Notification).filter(Notification.activity_log_id == logs[0].id).all()
    assert len(notifications) == 1


def test_database_level_duplicate_becomes_already_applied_not_500(client, db_session, monkeypatch):
    """
    Exercises the NEW IntegrityError -> AlreadyAppliedError conversion in
    apply_to_job deterministically, without relying on real thread timing.

    A genuine concurrent race is timing-dependent by nature (see
    test_concurrent_duplicate_applications_only_one_succeeds below for a
    best-effort real-thread version): here, the application-level duplicate
    check is monkeypatched to report "no existing row" for exactly one call
    -- precisely what it could legitimately observe a fraction of a second
    before a concurrent request's INSERT lands -- while a real duplicate row
    already exists. This isolates and proves the database-level fallback
    handles that scenario cleanly (409, not 500) independent of scheduling.
    """
    verifier = _register_verifier(client, db_session, "app-race-mock-co@test.credchain.dev", "App Race Mock Co")
    inst = _register_institution(client, db_session, "app-race-mock-inst@test.credchain.dev", "App Race Mock University")
    student = _register_student(client, inst["institution_id"], "app-race-mock-stu@test.credchain.dev", "APP-RACE-MOCK")
    job = _create_open_job(client, verifier["token"])
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    first = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    assert first.status_code == 201

    real_query = db_session.query

    def _query_missing_the_row_already_created_above(model, *args, **kwargs):
        query = real_query(model, *args, **kwargs)
        if model is JobApplication:

            class _AlwaysEmpty:
                def filter(self, *a, **kw):
                    return self

                def first(self):
                    return None

            return _AlwaysEmpty()
        return query

    monkeypatch.setattr(db_session, "query", _query_missing_the_row_already_created_above)

    second = client.post(
        "/api/students/me/applications", json={"job_id": job["id"], "credential_ids": [cred_id]}, headers=_auth_header(student["token"])
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "You have already applied to this job"


def test_concurrent_duplicate_applications_only_one_succeeds(client, db_session):
    """
    Best-effort real-concurrency test: two threads, each on its own DB
    connection/session, both call apply_to_job for the same (job, student)
    synchronized by a barrier so both are as likely as practically possible
    to pass the application-level duplicate check before either commits.

    True kernel-level simultaneity can never be guaranteed from a test, so
    this cannot force the race every run -- but the assertions below hold
    regardless of how the two threads actually interleave: exactly one
    application is ever created, the other request is always rejected with
    the same friendly error, and neither ever surfaces a raw 500.
    """
    verifier = _register_verifier(client, db_session, "app-race-co@test.credchain.dev", "App Race Co")
    inst = _register_institution(client, db_session, "app-race-inst@test.credchain.dev", "App Race University")
    student = _register_student(client, inst["institution_id"], "app-race-stu@test.credchain.dev", "APP-RACE-STU")
    job = _create_open_job(client, verifier["token"])
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    job_id = uuid_module.UUID(job["id"])
    cred_uuid = uuid_module.UUID(cred_id)

    results: list[str] = []
    barrier = threading.Barrier(2)

    def attempt() -> None:
        session = RawSession(bind=_race_test_engine)
        try:
            student_obj = session.query(Student).filter(Student.student_identifier == "APP-RACE-STU").one()
            barrier.wait(timeout=5)
            try:
                job_application_service.apply_to_job(session, student_obj, job_id=job_id, credential_ids=[cred_uuid])
                results.append("success")
            except job_application_service.AlreadyAppliedError:
                results.append("already_applied")
            except Exception as exc:  # pragma: no cover - would fail the assertion below
                results.append(f"unexpected:{exc!r}")
        finally:
            session.close()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sorted(results) == ["already_applied", "success"]

    apps = db_session.query(JobApplication).filter(JobApplication.job_id == job_id).all()
    assert len(apps) == 1


# ---------------------------------------------------------------------------
# Directory-only company jobs (mirrors scripts/seed_directory.py's own
# shape: a Company row with user_id=None, and an OPEN Job created directly
# against it, bypassing create_job/publish_job entirely) must never crash
# apply_to_job with a NOT NULL violation on notifications.user_id.
# ---------------------------------------------------------------------------


def _create_directory_only_job(db_session, *, title: str) -> Job:
    """Same shape seed_directory.py produces: a directory-only Company (user_id=None)
    with an OPEN Job created directly, never through create_job/publish_job."""
    company = Company(name="Directory Only Co", user_id=None)
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)

    job = Job(
        company_id=company.id,
        title=title,
        description="A real job, seeded directly like scripts/seed_directory.py does.",
        employment_type=JobEmploymentType.FULL_TIME,
        required_documents=["Migration Certificate"],
        status=JobStatus.OPEN,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_directory_only_company_job_application_succeeds_without_notification(client, db_session):
    inst = _register_institution(client, db_session, "app-dirjob-inst@test.credchain.dev", "App DirJob University")
    student = _register_student(client, inst["institution_id"], "app-dirjob-stu@test.credchain.dev", "APP-DIRJOB")
    job = _create_directory_only_job(db_session, title="Systems Engineer Trainee")
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    resp = client.post(
        "/api/students/me/applications",
        json={"job_id": str(job.id), "credential_ids": [cred_id]},
        headers=_auth_header(student["token"]),
    )
    assert resp.status_code == 201, resp.text
    application_id = uuid_module.UUID(resp.json()["id"])

    application = db_session.get(JobApplication, application_id)
    assert application is not None
    assert application.job_id == job.id

    notifications = db_session.query(Notification).filter(Notification.link_entity_id == application_id).all()
    assert notifications == []


def test_registered_company_job_application_still_notifies_exactly_once(client, db_session):
    verifier = _register_verifier(client, db_session, "app-notify-co@test.credchain.dev", "App Notify Co")
    inst = _register_institution(client, db_session, "app-notify-inst@test.credchain.dev", "App Notify University")
    student = _register_student(client, inst["institution_id"], "app-notify-stu@test.credchain.dev", "APP-NOTIFY")
    job = _create_open_job(client, verifier["token"])
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    resp = client.post(
        "/api/students/me/applications",
        json={"job_id": job["id"], "credential_ids": [cred_id]},
        headers=_auth_header(student["token"]),
    )
    assert resp.status_code == 201, resp.text
    application_id = uuid_module.UUID(resp.json()["id"])

    notifications = db_session.query(Notification).filter(Notification.link_entity_id == application_id).all()
    assert len(notifications) == 1
    assert notifications[0].title == "New job application"
    company = db_session.get(Company, uuid_module.UUID(verifier["company_id"]))
    assert notifications[0].user_id == company.user_id


def test_duplicate_application_to_directory_only_company_job_still_returns_409(client, db_session):
    inst = _register_institution(client, db_session, "app-dirdup-inst@test.credchain.dev", "App DirDup University")
    student = _register_student(client, inst["institution_id"], "app-dirdup-stu@test.credchain.dev", "APP-DIRDUP")
    job = _create_directory_only_job(db_session, title="Duplicate-Prone Trainee Role")
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    first = client.post(
        "/api/students/me/applications",
        json={"job_id": str(job.id), "credential_ids": [cred_id]},
        headers=_auth_header(student["token"]),
    )
    assert first.status_code == 201, first.text

    second = client.post(
        "/api/students/me/applications",
        json={"job_id": str(job.id), "credential_ids": [cred_id]},
        headers=_auth_header(student["token"]),
    )
    assert second.status_code == 409
    assert second.json()["detail"] == "You have already applied to this job"


def test_directory_only_company_job_application_still_creates_activity_log(client, db_session):
    inst = _register_institution(client, db_session, "app-dirlog-inst@test.credchain.dev", "App DirLog University")
    student = _register_student(client, inst["institution_id"], "app-dirlog-stu@test.credchain.dev", "APP-DIRLOG")
    job = _create_directory_only_job(db_session, title="Logged Trainee Role")
    cred_id = _issue_credential(client, inst["token"], student["student_id"], "migration", "Migration Certificate")

    resp = client.post(
        "/api/students/me/applications",
        json={"job_id": str(job.id), "credential_ids": [cred_id]},
        headers=_auth_header(student["token"]),
    )
    assert resp.status_code == 201, resp.text
    application_id = uuid_module.UUID(resp.json()["id"])

    logs = (
        db_session.query(ActivityLog)
        .filter(ActivityLog.entity_type == "job_application", ActivityLog.entity_id == application_id)
        .all()
    )
    assert len(logs) == 1
    assert logs[0].action == "APPLICATION_SUBMITTED"
