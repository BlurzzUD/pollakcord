from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_KRETA_SCRIPT = BASE_DIR / "app" / "integrations" / "kreta" / "script" / "kreta_login_from_dumps.py"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POLLAKCORD_", env_file=".env", extra="ignore")

    app_name: str = "PollákCord"
    environment: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    log_client_ip: bool = False

    database_url: str = "sqlite+aiosqlite:///./data/pollakcord.db"
    database_pool_size: int = 10

    public_origin: str = "http://localhost:5173"
    extra_origins: str = ""
    cookie_secure: bool = True
    trusted_proxy_hops: int = 0
    serve_frontend: bool = True
    frontend_dist: Path = BASE_DIR.parent / "frontend" / "dist"

    master_key: SecretStr | None = None
    master_key_file: Path | None = None
    master_key_id: str = "k1"
    previous_master_keys: SecretStr | None = None
    pepper: SecretStr | None = None
    pepper_file: Path | None = None
    dev_secrets_file: Path = BASE_DIR / "data" / "dev-secrets.json"

    session_ttl_hours: int = 24 * 14
    session_idle_hours: int = 24 * 5
    setup_session_ttl_minutes: int = 30
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536
    argon2_parallelism: int = 2
    lockout_threshold: int = 5
    lockout_base_seconds: int = 30
    lockout_max_seconds: int = 900

    kreta_script_path: Path = DEFAULT_KRETA_SCRIPT
    kreta_script_sha256: str | None = None
    kreta_python: str | None = None
    kreta_flow_ttl_seconds: int = 180
    kreta_process_timeout_seconds: int = 75
    kreta_max_concurrent: int = 6
    kreta_identity_namespace: str = "kreta"

    upload_dir: Path = BASE_DIR / "data" / "uploads"
    avatar_max_bytes: int = 2 * 1024 * 1024
    banner_max_bytes: int = 6 * 1024 * 1024
    icon_max_bytes: int = 2 * 1024 * 1024
    max_image_pixels: int = 25_000_000

    message_max_length: int = 4000
    data_key_rotation_messages: int = 500_000
    ws_max_connections_per_user: int = 6
    voice_max_participants: int = 8
    call_ring_seconds: int = 45

    stun_urls: str = "stun:stun.l.google.com:19302"
    turn_urls: str = ""
    turn_secret: SecretStr | None = None
    turn_ttl_seconds: int = 3600

    rate_limit_enabled: bool = True
    auto_create_schema: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def allowed_origins(self) -> set[str]:
        origins = {self.public_origin.rstrip("/")}
        origins.update(o.strip().rstrip("/") for o in self.extra_origins.split(",") if o.strip())
        return origins

    @property
    def stun_list(self) -> list[str]:
        return [u.strip() for u in self.stun_urls.split(",") if u.strip()]

    @property
    def turn_list(self) -> list[str]:
        return [u.strip() for u in self.turn_urls.split(",") if u.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
