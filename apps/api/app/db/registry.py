"""Importa TODOS os modelos para que Base.metadata os conheça.

Usado pelo Alembic (autogenerate) e pelos testes (create_all). Sempre que criar um modelo novo,
garanta que ele seja importado aqui (direta ou indiretamente).
"""
# noqa: F401 — imports existem só para registrar as tabelas no metadata.
from app.core.audit import AuditEntry  # noqa: F401
from app.db.base import Base
from app.modules.agenda.models import AgendaEvent  # noqa: F401
from app.modules.attachments.models import Attachment  # noqa: F401
from app.modules.auth.models import Tenant, User  # noqa: F401
from app.modules.contracts.models import (  # noqa: F401
    Contract,
    ContractTemplate,
    PublishedContract,
)
from app.modules.crm.models import Client, PipelineStage  # noqa: F401
from app.modules.funnels.models import Funnel, FunnelRun  # noqa: F401
from app.modules.juridico.models import LegalDocument  # noqa: F401
from app.modules.marketing.models import Carousel  # noqa: F401
from app.modules.notifications.models import Notification  # noqa: F401
from app.modules.pages.models import Page, PublishedPage  # noqa: F401
from app.modules.payables.models import Payable  # noqa: F401
from app.modules.products.models import Coupon, Enrollment, Product  # noqa: F401
from app.modules.quotes.models import PublishedProposal, Quote  # noqa: F401
from app.modules.receivables.models import Charge  # noqa: F401
from app.modules.settings.models import TenantProfile  # noqa: F401
from app.modules.stock.models import StockItem, StockMovement  # noqa: F401
from app.modules.wallet.models import (  # noqa: F401
    PlatformEarning,
    PlatformSetting,
    Transaction,
)

__all__ = ["Base"]
