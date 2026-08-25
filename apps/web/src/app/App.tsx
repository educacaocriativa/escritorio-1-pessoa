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
import { hasModule } from "../lib/access";
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
          <Route path="/agenda" element={<Modulo m="agenda"><AgendaPage /></Modulo>} />
          <Route path="/busca" element={<BuscaPage />} />
          <Route path="/crm" element={<Modulo m="crm"><CrmPage /></Modulo>} />
          <Route path="/crm/clients/:id" element={<Modulo m="crm"><ClientDetailPage /></Modulo>} />
          <Route path="/conversas" element={<Modulo m="crm"><ConversasPage /></Modulo>} />
          {/* A conversa tem URL própria desde a Onda 1: é assim que a ficha 360° aponta para ela, e
              de quebra o botão voltar do navegador passa a funcionar nesta tela. */}
          <Route path="/conversas/:chatId" element={<Modulo m="crm"><ConversasPage /></Modulo>} />
          <Route path="/financeiro" element={<Modulo m="wallet"><FinanceiroPage /></Modulo>} />
          <Route path="/financeiro/contas" element={<Modulo m="bank"><ContasSaldosPage /></Modulo>} />
          {/* Story 8.7 — rota DELIBERADAMENTE fora da sidebar: a conferência é resposta a um
              sinal (o cartão de completude do diagnóstico / o "Conferir" de uma conta), não uma
              tarefa de rotina. Ver a docstring de ConferenciaPage.tsx antes de "consertar" isto. */}
          <Route path="/financeiro/conferencia" element={<Modulo m="bank"><ConferenciaPage /></Modulo>} />
          <Route path="/financeiro/plano-contas" element={<Modulo m="chart_of_accounts"><PlanoContasPage /></Modulo>} />
          <Route path="/financeiro/centros-custo" element={<Modulo m="cost_centers"><CentrosCustoPage /></Modulo>} />
          <Route path="/financeiro/investimentos" element={<Modulo m="investments"><InvestimentosPage /></Modulo>} />
          <Route path="/financeiro/dre" element={<Modulo m="financial_intelligence"><DrePage /></Modulo>} />
          <Route path="/financeiro/lucratividade" element={<Modulo m="financial_intelligence"><LucratividadePage /></Modulo>} />
          <Route path="/financeiro/projecao-caixa" element={<Modulo m="financial_intelligence"><ProjecaoCaixaPage /></Modulo>} />
          <Route path="/financeiro/fila-pagamentos" element={<Modulo m="payables"><FilaPagamentosPage /></Modulo>} />
          <Route path="/financeiro/diagnostico" element={<Modulo m="financial_intelligence"><DiagnosticoPage /></Modulo>} />
          <Route path="/financeiro/contratos/:id/dre" element={<Modulo m="financial_intelligence"><ContratoDrePage /></Modulo>} />
          <Route path="/cobrancas" element={<Modulo m="receivables"><CobrancasPage /></Modulo>} />
          <Route path="/pagar" element={<Modulo m="payables"><PagarPage /></Modulo>} />
          <Route path="/produtos" element={<Modulo m="products"><ProdutosPage /></Modulo>} />
          <Route path="/estoque" element={<Modulo m="stock"><EstoquePage /></Modulo>} />
          <Route path="/config" element={<Modulo m="settings"><ConfiguracoesPage /></Modulo>} />
          <Route path="/sites" element={<Modulo m="pages"><SitesPage /></Modulo>} />
          <Route path="/sites/:id" element={<Modulo m="pages"><PageBuilderPage /></Modulo>} />
          <Route path="/orcamentos" element={<Modulo m="quotes"><OrcamentosPage /></Modulo>} />
          <Route path="/orcamentos/novo" element={<Modulo m="quotes"><QuoteBuilderPage /></Modulo>} />
          <Route path="/orcamentos/:id" element={<Modulo m="quotes"><QuoteBuilderPage /></Modulo>} />
          <Route path="/contratos" element={<Modulo m="contracts"><ContratosPage /></Modulo>} />
          <Route path="/contratos/novo" element={<Modulo m="contracts"><ContractBuilderPage /></Modulo>} />
          <Route path="/contratos/:id" element={<Modulo m="contracts"><ContractBuilderPage /></Modulo>} />
          <Route path="/marketing" element={<Modulo m="marketing"><MarketingPage /></Modulo>} />
          <Route path="/marketing/novo" element={<Modulo m="marketing"><CarrosselBuilderPage /></Modulo>} />
          <Route path="/marketing/:id" element={<Modulo m="marketing"><CarrosselBuilderPage /></Modulo>} />
          <Route path="/juridico" element={<Modulo m="juridico"><JuridicoPage /></Modulo>} />
          <Route path="/juridico/novo" element={<Modulo m="juridico"><JuridicoWizardPage /></Modulo>} />
          <Route path="/juridico/:id" element={<Modulo m="juridico"><JuridicoDocumentPage /></Modulo>} />
          <Route path="/funis" element={<Modulo m="funnels"><FunisPage /></Modulo>} />
          <Route path="/funis/novo" element={<Modulo m="funnels"><FunnelBuilderPage /></Modulo>} />
          <Route path="/funis/:id" element={<Modulo m="funnels"><FunnelBuilderPage /></Modulo>} />
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

/**
 * Guarda de módulo por ROTA: espelha `require_module` do backend (mesmo nome de módulo) e
 * impede a página de sequer MONTAR — logo de nunca disparar a requisição que voltaria 403.
 *
 * Antes disto a sidebar mostrava todo item a todo usuário (ver `navigation.ts`) e cada página
 * tentava buscar seus dados de qualquer forma; um sub-usuário sem o módulo via a tela travar em
 * "Carregando..." para sempre (o 403 vira promise rejeitada sem `.catch`, em vez de erro
 * tratado). Complementa `visibleNavSections` — aquele esconde o item do menu, este protege
 * contra link direto, favorito ou digitação da URL.
 */
export function Modulo({ m, children }: { m: string; children: ReactElement }) {
  const { user } = useAuth();
  if (!hasModule(user, m)) {
    return (
      <div className="flex h-full items-center justify-center text-center text-neutral-400">
        Você não tem acesso a este módulo. Fale com o administrador da sua conta se precisar dele.
      </div>
    );
  }
  return children;
}

function ComingSoon() {
  return (
    <div className="flex h-full items-center justify-center text-neutral-400">
      Módulo em construção — ver <code className="mx-1">docs/MODULES.md</code> para a ordem de entrega.
    </div>
  );
}
