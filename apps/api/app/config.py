from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    # Banco
    database_url: str = "postgresql+psycopg://e1puser:e1ppass@localhost:5432/e1pdb"

    # IA
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"

    # Auth
    jwt_secret: str = "dev-secret-change-in-production"  # noqa: S105 (default só de dev; prod via env)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080  # 7 dias
    session_idle_timeout_minutes: int = 30  # LGPD

    # App
    root_domain: str = "e1p.com"
    frontend_url: str = "http://localhost:5173"
    upload_dir: str = "./uploads"
    generated_dir: str = "./generated"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


settings = Settings()
