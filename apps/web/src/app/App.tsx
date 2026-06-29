import { Route, Routes } from "react-router-dom";
import AgendaPage from "../features/agenda/AgendaPage";
import CockpitPage from "../features/cockpit/CockpitPage";
import CrmPage from "../features/crm/CrmPage";
import AppShell from "./AppShell";

/**
 * Roteamento raiz. Por ora só o Cockpit existe; cada módulo construído registra sua rota aqui.
 * (Auth/login será adicionado quando o módulo de autenticação entrar — Fase 1.)
 */
export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<CockpitPage />} />
        <Route path="/agenda" element={<AgendaPage />} />
        <Route path="/crm" element={<CrmPage />} />
        <Route path="*" element={<ComingSoon />} />
      </Routes>
    </AppShell>
  );
}

function ComingSoon() {
  return (
    <div className="flex h-full items-center justify-center text-neutral-400">
      Módulo em construção — ver <code className="mx-1">docs/MODULES.md</code> para a ordem de entrega.
    </div>
  );
}
