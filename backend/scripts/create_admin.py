"""
Provisions a single ADMIN user. This is the ONLY supported way to create an
admin account — there is no public "register as admin" path anywhere in the
API (auth_service.register_user explicitly refuses role=admin), and this
script is never imported by, or reachable from, the running app.

Reads the new admin's identity from environment variables — never a
command-line argument (would land in shell history) and never a hardcoded
value in this file:

    ADMIN_EMAIL       (required)
    ADMIN_PASSWORD    (required, same minimum strength as any other account:
                       at least 8 characters, containing a letter and a digit)
    ADMIN_FULL_NAME   (required)

This script NEVER prints the password (or any other secret) — only a
confirmation of the email that was created. Run it once, against the same
database the backend itself is configured for (via backend/.env's
DATABASE_URL, exactly like the directory import scripts) — never against a
database you haven't already confirmed with `SELECT 1`.

Usage (PowerShell):
    cd backend
    $env:ADMIN_EMAIL = "admin@example.com"
    $env:ADMIN_PASSWORD = "<a real strong password>"
    $env:ADMIN_FULL_NAME = "Platform Admin"
    venv\\Scripts\\python.exe -m scripts.create_admin
    Remove-Item Env:\\ADMIN_EMAIL, Env:\\ADMIN_PASSWORD, Env:\\ADMIN_FULL_NAME
"""

import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal  # noqa: E402
from app.models.enums import UserRole  # noqa: E402
from app.models.user import User  # noqa: E402
from app.security.password import hash_password  # noqa: E402
from app.services.auth_service import get_user_by_email  # noqa: E402


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"Missing required environment variable: {name}")
        sys.exit(1)
    return value


def _validate_password(password: str) -> None:
    if len(password) < 8:
        raise ValueError("ADMIN_PASSWORD must be at least 8 characters")
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        raise ValueError("ADMIN_PASSWORD must contain at least one letter and one number")


def main() -> None:
    email = _require_env("ADMIN_EMAIL").strip().lower()
    password = _require_env("ADMIN_PASSWORD")
    full_name = _require_env("ADMIN_FULL_NAME").strip()

    try:
        _validate_password(password)
    except ValueError as exc:
        print(f"Invalid ADMIN_PASSWORD: {exc}")
        sys.exit(1)

    db = SessionLocal()
    try:
        if get_user_by_email(db, email) is not None:
            print(f"A user with email {email} already exists — no account was created.")
            sys.exit(1)

        admin = User(email=email, password_hash=hash_password(password), full_name=full_name, role=UserRole.ADMIN, is_active=True)
        db.add(admin)
        db.commit()
        print(f"Admin account created: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
