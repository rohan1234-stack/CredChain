"""
ONE-TIME, idempotent backfill: migrates an institution's private signing key
from the legacy on-disk PEM file (KEYS_PATH/<institution_id>.pem) into
encrypted database storage (institutions.encrypted_private_key), for
institutions where:
  - public_key IS set (this institution has a real signing identity), AND
  - encrypted_private_key IS NULL (not yet migrated), AND
  - the exact expected PEM file is actually present on THIS machine's disk

Never overwrites an existing encrypted_private_key (the query itself only
ever selects rows where it's still NULL). Never generates a new keypair.
Never touches an institution whose PEM file is missing on this machine —
that institution is reported SKIPPED and left completely untouched;
recovering it requires a separate, explicit key-regeneration decision that
this script deliberately does not make.

Safety check before writing anything: the candidate PEM file's own public
key is derived (signatures.derive_public_pem) and compared byte-for-byte
against institutions.public_key already on record. A mismatch means this
file does NOT actually belong to this institution — reported MISMATCH, and
nothing is written for that row. This guards against ever persisting the
wrong private key under someone else's institution.

Never prints key material (public or private) — only ids, names, and
outcome labels.

Run this FROM the same machine/filesystem that actually holds the .pem
files you intend to migrate. Running it anywhere else (e.g. a fresh local
checkout that never had those files) will honestly report every candidate
as SKIPPED — that is the correct, safe behavior, not a bug.

Usage:
    cd backend
    venv\\Scripts\\python.exe -m scripts.backfill_encrypted_signing_keys            # dry run (default, writes nothing)
    venv\\Scripts\\python.exe -m scripts.backfill_encrypted_signing_keys --apply    # actually writes encrypted_private_key
"""

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models.institution import Institution  # noqa: E402
from app.security import key_encryption, signatures  # noqa: E402
from app.services.signing_service import legacy_private_key_path  # noqa: E402


def _candidates(db):
    """Institutions with a signing identity that hasn't been migrated to encrypted DB storage yet — never a row that already has encrypted_private_key set."""
    return (
        db.query(Institution)
        .filter(Institution.public_key.isnot(None))
        .filter(Institution.encrypted_private_key.is_(None))
        .order_by(Institution.name)
        .all()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write encrypted_private_key for verified matches. Without this flag, only reports what WOULD happen — nothing is written.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        institutions = _candidates(db)
        print(f"{'APPLY' if args.apply else 'DRY RUN'} — {len(institutions)} institution(s) have a public_key but no encrypted_private_key yet.\n")

        counts = {"migrated": 0, "skipped_missing_file": 0, "mismatch": 0, "error": 0}

        for inst in institutions:
            legacy_path = legacy_private_key_path(inst.id)
            label = f"institution id={inst.id} name={inst.name!r}"

            if not legacy_path.exists():
                print(f"SKIPPED (no legacy PEM file found on this machine) — {label}")
                counts["skipped_missing_file"] += 1
                continue

            try:
                private_pem = legacy_path.read_bytes()
                derived_public_pem = signatures.derive_public_pem(private_pem)
            except Exception as exc:  # noqa: BLE001 — any parse failure means this file is unusable; report and move on, never crash the whole run
                print(f"ERROR (could not read/parse this PEM file: {type(exc).__name__} — not migrated) — {label}")
                counts["error"] += 1
                continue

            on_record_public_pem = inst.public_key.encode("utf-8")
            if derived_public_pem.strip() != on_record_public_pem.strip():
                print(f"MISMATCH (this file's derived public key does NOT match institutions.public_key on record — NOT migrated) — {label}")
                counts["mismatch"] += 1
                continue

            if not args.apply:
                print(f"WOULD MIGRATE (public key verified to match) — {label}")
                counts["migrated"] += 1
                continue

            inst.encrypted_private_key = key_encryption.encrypt_private_key(private_pem)
            db.add(inst)
            db.commit()
            print(f"MIGRATED (public key verified to match; now encrypted in the database) — {label}")
            counts["migrated"] += 1

        print("\n--- summary ---")
        for label, n in counts.items():
            print(f"{label}: {n}")
        if not args.apply:
            print("\nThis was a DRY RUN — nothing was written. Re-run with --apply once you've reviewed this output.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
