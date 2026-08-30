"""
READ-ONLY safety report for the canonical Aalto University institution,
requested before any key migration or regeneration decision is made.
Performs SELECT statements only — never INSERT, UPDATE, or DELETE.

Reports exactly what was asked: institution id, whether public_key exists,
whether encrypted_private_key exists, credential counts (total/active/
revoked), and which existing credentials currently depend on the
institution's on-record public_key for signature verification. Never
prints the public_key or any key material — only presence/absence.

Deliberately uses raw, explicit-column SQL (not the ORM model) so this
report stays safe to run both BEFORE and AFTER the encrypted-key migration
is applied — an ORM SELECT * against Institution would otherwise fail with
"column does not exist" on a database that hasn't been migrated yet.

Usage:
    cd backend
    venv\\Scripts\\python.exe -m scripts.aalto_signing_key_safety_report
"""

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402

# The canonical Aalto University directory row, confirmed by direct inspection earlier in this
# project's history — hardcoded on purpose, never guessed or pattern-matched.
AALTO_INSTITUTION_ID = "a45421f4-714b-4004-9964-a753f382fb82"


def main() -> None:
    db = SessionLocal()
    try:
        print("READ-ONLY Aalto signing-key safety report — no data will be modified.\n")

        has_encrypted_column = "encrypted_private_key" in {c["name"] for c in inspect(engine).get_columns("institutions")}

        select_cols = "id, name, public_key IS NOT NULL AS has_public_key"
        if has_encrypted_column:
            select_cols += ", encrypted_private_key IS NOT NULL AS has_encrypted_private_key"

        row = db.execute(
            text(f"SELECT {select_cols} FROM institutions WHERE id = :id"), {"id": AALTO_INSTITUTION_ID}
        ).mappings().first()
        if row is None:
            print(f"Institution {AALTO_INSTITUTION_ID} NOT FOUND.")
            return

        print(f"institution_id: {row['id']}")
        print(f"name: {row['name']!r}")
        print(f"public_key present: {row['has_public_key']}")
        if has_encrypted_column:
            print(f"encrypted_private_key present: {row['has_encrypted_private_key']}")
        else:
            print("encrypted_private_key present: N/A — this database has not had the encrypted-key migration applied yet")

        status_counts = db.execute(
            text("SELECT status, COUNT(*) AS n FROM credentials WHERE institution_id = :id GROUP BY status"),
            {"id": AALTO_INSTITUTION_ID},
        ).mappings().all()
        total = sum(r["n"] for r in status_counts)
        print(f"\ntotal credentials issued by this institution: {total}")
        for r in status_counts:
            print(f"  {r['status']}: {r['n']}")

        signed_rows = db.execute(
            text(
                "SELECT id, status, credential_type, issued_at FROM credentials "
                "WHERE institution_id = :id AND signature IS NOT NULL ORDER BY issued_at DESC"
            ),
            {"id": AALTO_INSTITUTION_ID},
        ).mappings().all()
        print(
            f"\ncredentials whose stored signature depends on the CURRENT institutions.public_key value: "
            f"{len(signed_rows)} (any of these would fail signature verification if public_key were ever replaced)"
        )
        for r in signed_rows:
            print(f"    id={r['id']} status={r['status']} type={r['credential_type']} issued_at={r['issued_at']}")

        print("\nThis was a read-only scan. Nothing was modified. No key regeneration or migration was performed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
