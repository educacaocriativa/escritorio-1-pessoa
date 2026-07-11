from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-secret-change-in-production"  # noqa: S105 (sentinela do default de dev)
_DEFAULT_ADMIN_PASSWORD = "trocar-no-primeiro-acesso"  # noqa: S105 (sentinela do default de dev)


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

    # Super Admin (Master) — semeado no start. Em produção, defina por env.
    super_admin_email: str = "admin@e1p.com"
    super_admin_password: str = _DEFAULT_ADMIN_PASSWORD
    super_admin_name: str = "Administrador e1p"

    # Integrações (vazio = stub/log; preencher quando conectar)
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    smtp_host: str = ""  # vazio = e-mail vira log (dev); preencher p/ entrega real
    # Segredo do webhook do gateway de pagamento. Vazio (dev) = webhook aberto p/ testes;
    # em produção, defina para que SÓ o gateway confirme pagamentos (o dono nunca marca à mão).
    gateway_webhook_secret: str = ""

    # Staging: quando True, o boot semeia dados sintéticos (tenant/usuário/registros de demo)
    # para o smoke test antes de promover à produção. Default False = produção NUNCA semeia
    # (é o ÚNICO gate — ver app/seed_staging.py e docs/HOSTINGER-DEPLOY.md §8). Só o
    # .env de staging define SEED_SYNTHETIC_DATA=true (Story 3.1).
    seed_synthetic_data: bool = False

    # Object storage S3-compatível para os Anexos (Story 3.5). Vazio (default) = anexos
    # continuam no Postgres (comportamento legado preservado). Preencher `s3_bucket` + credenciais
    # para ativar (AWS S3 real ou provedor S3-compatível barato via `s3_endpoint_url`).
    s3_endpoint_url: str = ""  # vazio = endpoint padrão da AWS; defina p/ MinIO/B2/Wasabi
    s3_bucket: str = ""  # vazio = storage S3 desligado (fallback Postgres)
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_region: str = "auto"

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
            if self.super_admin_password == _DEFAULT_ADMIN_PASSWORD:
                raise ValueError(
                    "SUPER_ADMIN_PASSWORD default em produção: defina uma senha forte"
                )
        return self


settings = Settings()
