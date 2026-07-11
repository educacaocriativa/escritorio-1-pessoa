"""Schemas do Super Admin (Master). Gerencia as contas (tenant + owner) e os usuários."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.validators import validate_document
from app.modules.auth.schemas import RegisterRequest, TenantOut, UserOut


class CreateAccountRequest(RegisterRequest):
    """Cadastro completo do escritório + dono. A senha NÃO vem do formulário: a plataforma gera
    uma temporária e envia por e-mail/WhatsApp; o dono a troca no 1º acesso (mesma regra dos
    funcionários — qualquer novo usuário segue esse fluxo)."""
    password: str = Field(default="", max_length=128)  # ignorado (senha é gerada)
    address: str = Field(min_length=1, max_length=500)
    phone: str = Field(min_length=8, max_length=32)  # WhatsApp do dono
    delivery: Literal["email", "whatsapp"] = "email"


class UpdateAccountRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None


class AccountOut(BaseModel):
    tenant: TenantOut
    owner: UserOut


class AccountInviteOut(BaseModel):
    """Conta criada via convite: tenant + dono + senha temporária e como foi entregue."""
    tenant: TenantOut
    owner: UserOut
    # None em produção (não vaza no corpo — a senha vai por e-mail/WhatsApp; Story 2.1 AC3).
    temp_password: str | None = None
    delivery: str
    delivery_status: str


# ── Hierarquia de usuários (Super Admin vê tudo) ────────────────────────────
class CustomerOut(BaseModel):
    """Cliente comprador (aluno/matrícula) — ainda não é um User de login, vive em Enrollment."""
    name: str
    email: str | None = None
    purchases: int = 1


class PlatformCustomerOut(CustomerOut):
    """Cliente na visão do Master: inclui de qual escritório ele comprou."""
    tenant_id: str
    tenant_name: str


class TenantUsersOut(BaseModel):
    """Um escritório (Admin) com sua equipe e seus clientes — o nó da hierarquia."""
    tenant: TenantOut
    admin: UserOut | None  # o dono (role=owner)
    staff: list[UserOut]  # funcionários (role=sub_user)
    customers: list[CustomerOut]  # compradores de cursos/produtos
    staff_count: int
    customer_count: int


class CreateStaffRequest(BaseModel):
    """Cadastro completo de um novo usuário. A senha NÃO vem aqui: a plataforma gera uma
    temporária e envia por e-mail/WhatsApp; o usuário a troca no 1º acesso."""
    name: str = Field(min_length=1, max_length=255)  # nome completo
    email: EmailStr
    document: str = Field(min_length=11, max_length=18)  # CPF
    address: str = Field(min_length=1, max_length=500)
    phone: str = Field(min_length=8, max_length=32)  # WhatsApp
    allowed_modules: list[str] = Field(default_factory=list)
    delivery: Literal["email", "whatsapp"] = "email"  # canal de envio da senha

    @field_validator("document")
    @classmethod
    def valid_document(cls, v: str) -> str:
        # Valida CPF/CNPJ (dígito verificador) e normaliza para só-dígitos antes de persistir.
        return validate_document(v)


class StaffInviteOut(BaseModel):
    """Resultado do convite: o usuário criado + a senha temporária e como foi entregue."""
    user: UserOut
    # None em produção (não vaza no corpo — a senha vai por e-mail/WhatsApp; Story 2.1 AC3).
    temp_password: str | None = None
    delivery: str
    delivery_status: str  # sent | logged | failed


class UpdateUserRequest(BaseModel):
    name: str | None = None
    is_active: bool | None = None
    allowed_modules: list[str] | None = None
