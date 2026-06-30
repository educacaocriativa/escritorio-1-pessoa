import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import AdminDashboard from "../features/admin/AdminDashboard";
import AgendaPage from "../features/agenda/AgendaPage";
import LoginPage from "../features/auth/LoginPage";
import CockpitPage from "../features/cockpit/CockpitPage";
import ConfiguracoesPage from "../features/config/ConfiguracoesPage";
import CobrancasPage from "../features/cobrancas/CobrancasPage";
import ContractBuilderPage from "../features/contratos/ContractBuilderPage";
import ContratosPage from "../features/contratos/ContratosPage";
import PublicContractPage from "../features/contratos/PublicContractPage";
import ClientDetailPage from "../features/crm/ClientDetailPage";
import CrmPage from "../features/crm/CrmPage";
import EstoquePage from "../features/estoque/EstoquePage";
import FinanceiroPage from "../features/financeiro/FinanceiroPage";
import FunisPage from "../features/funis/FunisPage";
import FunnelBuilderPage from "../features/funis/FunnelBuilderPage";
import CarrosselBuilderPage from "../features/marketing/CarrosselBuilderPage";
import MarketingPage from "../features/marketing/MarketingPage";
import PagarPage from "../features/pagar/PagarPage";
import OrcamentosPage from "../features/orcamentos/OrcamentosPage";
import PublicProposalPage from "../features/orcamentos/PublicProposalPage";
import QuoteBuilderPage from "../features/orcamentos/QuoteBuilderPage";
import ProdutosPage from "../features/produtos/ProdutosPage";
import { AuthProvider, useAuth } from "../store/auth";
import { PageActionsProvider } from "../store/pageActions";
import AppShell from "./AppShell";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginRoute />} />
        <Route path="/orcamento/:slug" element={<PublicProposalPage />} />
        <Route path="/contrato/:slug" element={<PublicContractPage />} />
        <Route element={<ProtectedLayout />}>
          <Route path="/" element={<CockpitPage />} />
          <Route path="/agenda" element={<AgendaPage />} />
          <Route path="/crm" element={<CrmPage />} />
          <Route path="/crm/clients/:id" element={<ClientDetailPage />} />
          <Route path="/financeiro" element={<FinanceiroPage />} />
          <Route path="/cobrancas" element={<CobrancasPage />} />
          <Route path="/pagar" element={<PagarPage />} />
          <Route path="/produtos" element={<ProdutosPage />} />
          <Route path="/estoque" element={<EstoquePage />} />
          <Route path="/config" element={<ConfiguracoesPage />} />
          <Route path="/orcamentos" element={<OrcamentosPage />} />
          <Route path="/orcamentos/novo" element={<QuoteBuilderPage />} />
          <Route path="/orcamentos/:id" element={<QuoteBuilderPage />} />
          <Route path="/contratos" element={<ContratosPage />} />
          <Route path="/contratos/novo" element={<ContractBuilderPage />} />
          <Route path="/contratos/:id" element={<ContractBuilderPage />} />
          <Route path="/marketing" element={<MarketingPage />} />
          <Route path="/marketing/novo" element={<CarrosselBuilderPage />} />
          <Route path="/marketing/:id" element={<CarrosselBuilderPage />} />
          <Route path="/funis" element={<FunisPage />} />
          <Route path="/funis/novo" element={<FunnelBuilderPage />} />
          <Route path="/funis/:id" element={<FunnelBuilderPage />} />
          <Route path="/admin" element={<AdminOnly />} />
          <Route path="*" element={<ComingSoon />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}

function LoginRoute() {
  const { isAuthenticated } = useAuth();
  return isAuthenticated ? <Navigate to="/" replace /> : <LoginPage />;
}

function ProtectedLayout() {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  return (
    <PageActionsProvider>
      <AppShell>
        <Outlet />
      </AppShell>
    </PageActionsProvider>
  );
}

function AdminOnly() {
  const { user } = useAuth();
  if (!user?.is_platform_admin) return <Navigate to="/" replace />;
  return <AdminDashboard />;
}

function ComingSoon() {
  return (
    <div className="flex h-full items-center justify-center text-neutral-400">
      Módulo em construção — ver <code className="mx-1">docs/MODULES.md</code> para a ordem de entrega.
    </div>
  );
}
