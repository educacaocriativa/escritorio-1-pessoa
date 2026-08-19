import type { ReactElement } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import AdminDashboard from "../features/admin/AdminDashboard";
import AgendaPage from "../features/agenda/AgendaPage";
import FirstAccessPage from "../features/auth/FirstAccessPage";
import BuscaPage from "../features/busca/BuscaPage";
import LoginPage from "../features/auth/LoginPage";
import CockpitPage from "../features/cockpit/CockpitPage";
import ConfiguracoesPage from "../features/config/ConfiguracoesPage";
import CobrancasPage from "../features/cobrancas/CobrancasPage";
import ContractBuilderPage from "../features/contratos/ContractBuilderPage";
import ContratosPage from "../features/contratos/ContratosPage";
import PublicContractPage from "../features/contratos/PublicContractPage";
import ClientDetailPage from "../features/crm/ClientDetailPage";
import CrmPage from "../features/crm/CrmPage";
import ConversasPage from "../features/conversas/ConversasPage";
import EstoquePage from "../features/estoque/EstoquePage";
import CentrosCustoPage from "../features/financeiro/CentrosCustoPage";
import ConferenciaPage from "../features/financeiro/ConferenciaPage";
import ContasSaldosPage from "../features/financeiro/ContasSaldosPage";
import ContratoDrePage from "../features/financeiro/ContratoDrePage";
import DiagnosticoPage from "../features/financeiro/DiagnosticoPage";
import DrePage from "../features/financeiro/DrePage";
import FilaPagamentosPage from "../features/financeiro/FilaPagamentosPage";
import FinanceiroPage from "../features/financeiro/FinanceiroPage";
import InvestimentosPage from "../features/financeiro/InvestimentosPage";
import LucratividadePage from "../features/financeiro/LucratividadePage";
import PlanoContasPage from "../features/financeiro/PlanoContasPage";
import ProjecaoCaixaPage from "../features/financeiro/ProjecaoCaixaPage";
import FunisPage from "../features/funis/FunisPage";
import FunnelBuilderPage from "../features/funis/FunnelBuilderPage";
import JuridicoDocumentPage from "../features/juridico/JuridicoDocumentPage";
import JuridicoPage from "../features/juridico/JuridicoPage";
import JuridicoWizardPage from "../features/juridico/JuridicoWizardPage";
import CarrosselBuilderPage from "../features/marketing/CarrosselBuilderPage";
import MarketingPage from "../features/marketing/MarketingPage";
import CompartilharPage from "../features/pagar/CompartilharPage";
import ComprovantePage from "../features/pagar/ComprovantePage";
import PagarPage from "../features/pagar/PagarPage";
import OrcamentosPage from "../features/orcamentos/OrcamentosPage";
import PublicProposalPage from "../features/orcamentos/PublicProposalPage";
import QuoteBuilderPage from "../features/orcamentos/QuoteBuilderPage";
import ProdutosPage from "../features/produtos/ProdutosPage";
import PageBuilderPage from "../features/sites/PageBuilderPage";
import PublicPage from "../features/sites/PublicPage";
import SitesPage from "../features/sites/SitesPage";
import NucleoPage from "../features/dna/NucleoPage";
import BriefingPage from "../features/vima/BriefingPage";
import EntradaDoDia from "../features/vima/EntradaDoDia";
import IdleWarningModal from "../components/IdleWarningModal";
import { AuthProvider, useAuth } from "../store/auth";
import { useIdleTimeout } from "../store/useIdleTimeout";
import { PageActionsProvider } from "../store/pageActions";
import AppShell from "./AppShell";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginRoute />} />
        <Route path="/orcamento/:slug" element={<PublicProposalPage />} />
        <Route path="/contrato/:slug" element={<PublicContractPage />} />
        <Route path="/p/:slug" element={<PublicPage />} />
        <Route element={<ProtectedLayout />}>
          {/*
            A raiz autenticada não é mais o Cockpit direto: `EntradaDoDia` decide a porta do dia
            (briefing de hoje ainda não lido → `/vima`; já lido → o Cockpit). Ver a decisão em
            `features/vima/EntradaDoDia.tsx` — uma vez por dia, não a cada login.
          */}
          <Route
            path="/"
            element={
              <EntradaDoDia>
                <CockpitPage />
              </EntradaDoDia>
            }
          />
          <Route path="/agenda" element={<AgendaPage />} />
          <Route path="/busca" element={<BuscaPage />} />
          <Route path="/crm" element={<CrmPage />} />
          <Route path="/crm/clients/:id" element={<ClientDetailPage />} />
          <Route path="/conversas" element={<ConversasPage />} />
          {/* A conversa tem URL própria desde a Onda 1: é assim que a ficha 360° aponta para ela, e
              de quebra o botão voltar do navegador passa a funcionar nesta tela. */}
          <Route path="/conversas/:chatId" element={<ConversasPage />} />
          <Route path="/financeiro" element={<FinanceiroPage />} />
          <Route path="/financeiro/contas" element={<ContasSaldosPage />} />
          {/* Story 8.7 — rota DELIBERADAMENTE fora da sidebar: a conferência é resposta a um
              sinal (o cartão de completude do diagnóstico / o "Conferir" de uma conta), não uma
              tarefa de rotina. Ver a docstring de ConferenciaPage.tsx antes de "consertar" isto. */}
          <Route path="/financeiro/conferencia" element={<ConferenciaPage />} />
          <Route path="/financeiro/plano-contas" element={<PlanoContasPage />} />
          <Route path="/financeiro/centros-custo" element={<CentrosCustoPage />} />
          <Route path="/financeiro/investimentos" element={<InvestimentosPage />} />
          <Route path="/financeiro/dre" element={<DrePage />} />
          <Route path="/financeiro/lucratividade" element={<LucratividadePage />} />
          <Route path="/financeiro/projecao-caixa" element={<ProjecaoCaixaPage />} />
          <Route path="/financeiro/fila-pagamentos" element={<FilaPagamentosPage />} />
          <Route path="/financeiro/diagnostico" element={<DiagnosticoPage />} />
          <Route path="/financeiro/contratos/:id/dre" element={<ContratoDrePage />} />
          <Route path="/cobrancas" element={<CobrancasPage />} />
          <Route path="/pagar" element={<PagarPage />} />
          <Route path="/produtos" element={<ProdutosPage />} />
          <Route path="/estoque" element={<EstoquePage />} />
          <Route path="/config" element={<ConfiguracoesPage />} />
          <Route path="/sites" element={<SitesPage />} />
          <Route path="/sites/:id" element={<PageBuilderPage />} />
          <Route path="/orcamentos" element={<OrcamentosPage />} />
          <Route path="/orcamentos/novo" element={<QuoteBuilderPage />} />
          <Route path="/orcamentos/:id" element={<QuoteBuilderPage />} />
          <Route path="/contratos" element={<ContratosPage />} />
          <Route path="/contratos/novo" element={<ContractBuilderPage />} />
          <Route path="/contratos/:id" element={<ContractBuilderPage />} />
          <Route path="/marketing" element={<MarketingPage />} />
          <Route path="/marketing/novo" element={<CarrosselBuilderPage />} />
          <Route path="/marketing/:id" element={<CarrosselBuilderPage />} />
          <Route path="/juridico" element={<JuridicoPage />} />
          <Route path="/juridico/novo" element={<JuridicoWizardPage />} />
          <Route path="/juridico/:id" element={<JuridicoDocumentPage />} />
          <Route path="/funis" element={<FunisPage />} />
          <Route path="/funis/novo" element={<FunnelBuilderPage />} />
          <Route path="/funis/:id" element={<FunnelBuilderPage />} />
          <Route path="/admin" element={<AdminOnly />} />
          <Route path="*" element={<ComingSoon />} />
        </Route>
        {/* Telas de tarefa única vindas do share sheet do celular: mesma proteção, sem shell. */}
        <Route element={<ProtectedBareLayout />}>
          {/*
            Sem sidebar e sem topbar, pelo mesmo motivo de `/comprovante/:id`: o briefing é uma
            tela de leitura única, lida no celular de manhã, e o menu ali é ruído disputando uma
            largura que o polegar já disputa. A saída fica na própria tela.
          */}
          <Route path="/vima" element={<BriefingPage />} />
          {/* O núcleo do DNA mora aqui pelo mesmo motivo do briefing: é porta de entrada, não
              uma página do produto — sem shell, sem menu, desenhado para 360px. */}
          <Route path="/dna/nucleo" element={<NucleoPage />} />
          <Route path="/compartilhar" element={<CompartilharPage />} />
          <Route path="/comprovante/:id" element={<ComprovantePage />} />
        </Route>
      </Routes>
    </AuthProvider>
  );
}

/** Origem guardada pelo `ProtectedLayout` ao redirecionar para `/login` (ver abaixo). */
interface LoginLocationState {
  from?: { pathname: string; search: string; hash: string };
}

/** Rota que originou o redirecionamento para `/login`, formatada de volta como caminho. Sem
 * origem guardada (visita direta a `/login`, não um redirecionamento), cai em `/`. */
function loginReturnTo(state: unknown): string {
  const from = (state as LoginLocationState | null)?.from;
  return from ? `${from.pathname}${from.search}${from.hash}` : "/";
}

export function LoginRoute() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  // Compartilhar comprovante (Android/iOS) e qualquer outra rota protegida podem ser acessados
  // deslogado — sem retomar a origem depois do login, a chave do comprovante (só na URL) seria
  // destruída pelo `replace` e o arquivo ficaria perdido no IndexedDB sem explicação nenhuma.
  return isAuthenticated ? <Navigate to={loginReturnTo(location.state)} replace /> : <LoginPage />;
}

/**
 * Portão de autenticação, sem nenhuma decisão visual: devolve `null` quando pode seguir, ou o
 * elemento que deve ser renderizado no lugar do conteúdo (redirect para login / troca de senha).
 *
 * Extraído para que `ProtectedLayout` (com shell) e `ProtectedBareLayout` (tela cheia) apliquem
 * exatamente a MESMA regra de acesso — duplicar isso seria criar duas portas para o mesmo prédio.
 */
function useAuthGate(): ReactElement | null {
  const { isAuthenticated, user } = useAuth();
  const location = useLocation();
  if (!isAuthenticated) {
    // Guarda a rota de origem para o LoginRoute retomar após autenticar — genérico para
    // qualquer rota protegida, não só `/compartilhar`/`/comprovante/:id`.
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  // 1º acesso: bloqueia o app até o usuário trocar a senha temporária.
  if (user?.must_reset_password) return <FirstAccessPage />;
  return null;
}

export function ProtectedLayout() {
  // Idle timeout LGPD (Story 1.3): hook sempre chamado (regra dos hooks); no-op quando deslogado.
  const { showWarning, stayConnected } = useIdleTimeout();
  const blocked = useAuthGate();
  if (blocked) return blocked;
  return (
    <PageActionsProvider>
      <AppShell>
        <Outlet />
      </AppShell>
      <IdleWarningModal open={showWarning} onStay={stayConnected} />
    </PageActionsProvider>
  );
}

/**
 * Mesma proteção do `ProtectedLayout`, SEM sidebar e SEM topbar.
 *
 * Para telas de tarefa única que chegam pelo compartilhamento do celular: ali o menu não é
 * navegação, é ruído competindo por uma largura que o polegar já disputa. A saída fica na
 * própria tela (o "Cancelar" do cabeçalho), não no shell.
 */
export function ProtectedBareLayout() {
  const { showWarning, stayConnected } = useIdleTimeout();
  const blocked = useAuthGate();
  if (blocked) return blocked;
  return (
    <>
      <div className="min-h-screen bg-neutral-50 p-4">
        <Outlet />
      </div>
      <IdleWarningModal open={showWarning} onStay={stayConnected} />
    </>
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
