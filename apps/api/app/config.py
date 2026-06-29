from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-secret-change-in-production"  # noqa: S105 (sentinela do default de dev)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"

    # Banco
    database_url: str = "postgresql+psycopg://e1puser:e1ppass@localhost:5432/e1pdb"

    # IA
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-4-8"

    # Auth
    jwt_secret: str = _DEV_SECRET
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

    @model_validator(mode="after")
    def _guard_production_secrets(self) -> "Settings":
        """Fail-fast: em produção, segredos fracos não podem subir (isolamento de tenant
        depende inteiramente da integridade do JWT)."""
        if self.is_production:
            if self.jwt_secret == _DEV_SECRET or len(self.jwt_secret) < 32:
                raise ValueError(
                    "JWT_SECRET inseguro em produção: defina uma string aleatória de >=32 chars"
                )
            if not self.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY ausente em produção")
        return self


settings = Settings()
