# ---------------------------------------------------------------------------
# Centralized app configuration, loaded from environment variables (.env).
# Nothing sensitive here has a real default — .env.example documents the
# shape, actual values live only in a git-ignored .env file.
# ---------------------------------------------------------------------------

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Database ---
    database_url: str = "postgresql+psycopg2://credchain:credchain@localhost:5432/credchain"

    # --- Auth / JWT (wired in Phase 3) ---
    jwt_secret_key: str = "changeme-dev-only-do-not-use-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # --- CORS ---
    # Comma-separated. Render's CORS_ORIGINS env var (if set) overrides this default entirely —
    # this fallback exists so the deployed API still allows the known production frontend even
    # if that env var is unset or stale.
    cors_origins: str = "http://localhost:5173,https://cred-chain-five.vercel.app"

    # --- Sharing (Phase 6) ---
    # Base URL used to build share links (e.g. http://localhost:5173/share/verify/<token>).
    frontend_base_url: str = "https://cred-chain-five.vercel.app"

    # --- Institution signing-key encryption ---
    # Master secret for encrypting institution private keys before they're stored in
    # institutions.encrypted_private_key (see app/security/key_encryption.py). Kept ONLY as an
    # env var — never in the database, never in source control — so that DB access alone can
    # never decrypt a private key. No real default; empty means encryption is unavailable and
    # key_encryption.py raises rather than silently operating with a weak/predictable key.
    key_encryption_secret: str = ""

    # --- AI (Phase 7) ---
    # Disabled by default so the project runs with no key configured — see
    # app/services/ai/ai_service.py for the fallback behavior this enables.
    ai_enabled: bool = False
    ai_provider: str = "anthropic"
    ai_api_key: str = ""
    ai_model: str = "claude-opus-5"
    # Groq uses an OpenAI-compatible endpoint (https://api.groq.com/openai/v1) with
    # its own key, kept separate from ai_api_key (Anthropic) so both providers can
    # stay configured side by side without one overwriting the other.
    groq_api_key: str = ""

    # --- Document storage ---
    storage_path: str = "./storage"
    max_document_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    # Supabase Storage (durable — fixes credential/student-document PDFs being lost on every
    # Render redeploy, since local disk there is ephemeral while Postgres is not). Same
    # "disabled until configured" pattern as ai_enabled/blockchain_enabled: empty by default, so
    # every existing test/dev environment that hasn't set these keeps using local filesystem
    # storage completely unchanged (see document_service.py). SUPABASE_SERVICE_ROLE_KEY must
    # never be sent to the frontend, logged, or committed — same handling as
    # key_encryption_secret/blockchain_private_key above.
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_credential_bucket: str = "credential-documents"
    supabase_student_document_bucket: str = "student-documents"

    # --- Institution signing keys (dev key management — see
    # app/services/signing_service.py for the documented tradeoff) ---
    keys_path: str = "./keys"

    # --- Blockchain credential-hash anchoring (Phase 9A/9B) ---
    # Disabled by default, same pattern as AI_ENABLED: with no RPC/key/
    # contract configured, the anchoring endpoint fails cleanly with
    # blockchain_status=FAILED instead of attempting a network call. This is
    # a BACKEND service identity's key, completely separate from the
    # institution's Ed25519 signing key (see signing_service.py) and from
    # any user's credentials — see blockchain/README.md.
    blockchain_enabled: bool = False
    blockchain_rpc_url: str = ""
    blockchain_chain_id: int = 80002  # Polygon Amoy testnet
    blockchain_network_name: str = "polygon-amoy"
    blockchain_private_key: str = ""
    blockchain_contract_address: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
