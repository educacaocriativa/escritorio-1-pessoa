import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import AgendaPage from "../features/agenda/AgendaPage";
import LoginPage from "../features/auth/LoginPage";
import CockpitPage from "../features/cockpit/CockpitPage";
import CrmPage from "../features/crm/CrmPage";
import { AuthProvider, useAuth } from "../store/auth";
import { PageActionsProvider } from "../store/pageActions";
import AppShell from "./AppShell";

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginRoute />} />
        <Route element={<ProtectedLayout />}>
          <Route path="/" element={<CockpitPage />} />
          <Route path="/agenda" element={<AgendaPage />} />
          <Route path="/crm" element={<CrmPage />} />
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

function ComingSoon() {
  return (
    <div className="flex h-full items-center justify-center text-neutral-400">
      Módulo em construção — ver <code className="mx-1">docs/MODULES.md</code> para a ordem de entrega.
    </div>
  );
}
