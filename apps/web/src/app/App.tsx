import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import AdminDashboard from "../features/admin/AdminDashboard";
import AgendaPage from "../features/agenda/AgendaPage";
import LoginPage from "../features/auth/LoginPage";
import CockpitPage from "../features/cockpit/CockpitPage";
import CobrancasPage from "../features/cobrancas/CobrancasPage";
import CrmPage from "../features/crm/CrmPage";
import FinanceiroPage from "../features/financeiro/FinanceiroPage";
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
        <Route element={<ProtectedLayout />}>
          <Route path="/" element={<CockpitPage />} />
          <Route path="/agenda" element={<AgendaPage />} />
          <Route path="/crm" element={<CrmPage />} />
          <Route path="/financeiro" element={<FinanceiroPage />} />
          <Route path="/cobrancas" element={<CobrancasPage />} />
          <Route path="/pagar" element={<PagarPage />} />
          <Route path="/produtos" element={<ProdutosPage />} />
          <Route path="/orcamentos" element={<OrcamentosPage />} />
          <Route path="/orcamentos/novo" element={<QuoteBuilderPage />} />
          <Route path="/orcamentos/:id" element={<QuoteBuilderPage />} />
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
