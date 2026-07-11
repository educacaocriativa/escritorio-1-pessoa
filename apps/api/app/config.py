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
    # E-mail transacional (SMTP genérico; cobre também o endpoint SMTP do Amazon SES).
    # SMTP_HOST vazio = e-mail vira log (dev/graceful degradation); preencher p/ entrega real.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # remetente; vazio = usa smtp_user
    smtp_use_tls: bool = True
    # Segredo do webhook do gateway de pagamento. Vazio (dev) = webhook aberto p/ testes;
    # em produção, defina para que SÓ o gateway confirme pagamentos (o dono nunca marca à mão).
    gateway_webhook_secret: str = ""
    # Gateway de pagamento REAL (Asaas) — gera boleto/Pix registrado + envia o webhook de verdade.
    # Vazio = mantém o stub atual (core/boleto + código stub): graceful degradation INCLUSIVE em
    # produção (diferente de JWT_SECRET/ANTHROPIC_API_KEY, que são bloqueantes). Preencher a chave
    # para ativar. base_url vazio = usa o default do provedor (aponte p/ o sandbox ao testar).
    payment_gateway_provider: str = ""  # "asaas" | "" (vazio = mantém o stub)
    payment_gateway_api_key: str = ""
    payment_gateway_base_url: str = ""  # ex.: https://api-sandbox.asaas.com/v3

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

    # OAuth Google (Meet/Calendar) — app OAuth GLOBAL da plataforma (um Google Cloud project
    # para todos os tenants). Vazio = integração indisponível (fail-safe: o sistema segue
    # funcionando com o campo manual de reunião, só não oferece "Conectar Google"). O token de
    # acesso à agenda é POR TENANT (ver modules/google_calendar), não confundir com estes.
    google_client_id: str = ""
    google_client_secret: str = ""
    google_oauth_redirect_uri: str = ""

    # App
    root_domain: str = "e1p.com"
    frontend_url: str = "http://localhost:5173"
    upload_dir: str = "./uploads"
    generated_dir: str = "./generated"
    # Worker durável (app.worker): intervalo entre sweeps (tick do funil + fila de notificações).
    # Operacional, não é segredo — sem guard de produção (mesmo espírito de session_idle_timeout).
    worker_tick_interval_seconds: int = 60

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def google_oauth_configured(self) -> bool:
        """True quando o app OAuth do Google está configurado (client id/secret + redirect).

        Usado pelo backend (para permitir/negar o fluxo de conexão) E exposto num endpoint de
        status para o frontend decidir se mostra o botão "Conectar Google". Integração OPCIONAL
        por design (AC3): vazio não quebra nada, apenas desabilita a geração automática de Meet."""
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.google_oauth_redirect_uri
        )

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
