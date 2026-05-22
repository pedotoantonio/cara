import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useAuthStore } from '@/state/auth';
import { ToastProvider } from '@/design/components';
import { AppShell } from '@/components/common/AppShell';
import { ErrorBoundary } from '@/components/common/ErrorBoundary';

import { LoginPage } from '@/routes/auth/LoginPage';
import { PermissionsPage } from '@/routes/onboarding/PermissionsPage';
import { HubHome } from '@/routes/home/HubHome';
import { ChatPage } from '@/routes/chat/ChatPage';
import { ListLayout } from '@/routes/list/ListLayout';
import { TasksPage } from '@/routes/list/TasksPage';
import { ShoppingPage } from '@/routes/list/ShoppingPage';
import { NotesPage } from '@/routes/list/NotesPage';
import { RemindersPage } from '@/routes/list/RemindersPage';
import { LifeLayout } from '@/routes/life/LifeLayout';
import { CalendarPage } from '@/routes/life/CalendarPage';
import { MeteoPage } from '@/routes/life/MeteoPage';
import { NewsPage } from '@/routes/life/NewsPage';
import { RadioPage } from '@/routes/life/RadioPage';
import { MePage } from '@/routes/me/MePage';
import { SettingsPage } from '@/routes/me/SettingsPage';
import { PersonaPage } from '@/routes/me/PersonaPage';
import { MemoryPage } from '@/routes/me/MemoryPage';
import { WalletPage } from '@/routes/me/WalletPage';
import { IntegrationsPage } from '@/routes/me/IntegrationsPage';
import { ProposalsPage } from '@/routes/me/ProposalsPage';
import { DevicesPage } from '@/routes/me/DevicesPage';
import { AdminHub } from '@/routes/admin/AdminHub';
import { DiscoveriesPage } from '@/routes/DiscoveriesPage';
import { DiagnosticsPage } from '@/routes/DiagnosticsPage';
import { LifeopsListsPage } from '@/routes/lifeops/LifeopsListsPage';
import { LifeopsListDetailPage } from '@/routes/lifeops/LifeopsListDetailPage';
import { LifeopsPendingPage } from '@/routes/lifeops/LifeopsPendingPage';
import { LifeopsFinancePage } from '@/routes/lifeops/LifeopsFinancePage';
import { hasCompletedOnboarding } from '@/hooks/usePermissions';
import { reaffirmSubscriptionSilently } from '@/api/push';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function Protected() {
  const status = useAuthStore((s) => s.status);
  if (status === 'loading' || status === 'idle') {
    return (
      <main className="min-h-[100dvh] grid place-items-center">
        <div className="text-text-muted">Caricamento…</div>
      </main>
    );
  }
  if (status !== 'authenticated') {
    return <Navigate to="/login" replace />;
  }
  // First-run: redirect a /permissions se onboarding non completato
  if (!hasCompletedOnboarding()) {
    return <Navigate to="/permissions" replace />;
  }
  return <Outlet />;
}

function Bootstrap() {
  const bootstrap = useAuthStore((s) => s.bootstrap);
  useEffect(() => {
    void bootstrap();
    // Tenta di re-affermare la subscription push se permission granted.
    // Silenzioso: se non c'è niente, non fa nulla.
    void reaffirmSubscriptionSilently();
  }, [bootstrap]);
  return null;
}

function AuthedPermissionsRoute() {
  const status = useAuthStore((s) => s.status);
  if (status !== 'authenticated') return <Navigate to="/login" replace />;
  return <PermissionsPage />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <BrowserRouter>
            <Bootstrap />
            <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/permissions" element={<AuthedPermissionsRoute />} />
            <Route element={<Protected />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<HubHome />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/chat/:conversationId" element={<ChatPage />} />
                <Route path="/list" element={<ListLayout />}>
                  <Route index element={<Navigate to="/list/tasks" replace />} />
                  <Route path="tasks" element={<TasksPage />} />
                  <Route path="shopping" element={<ShoppingPage />} />
                  <Route path="notes" element={<NotesPage />} />
                  <Route path="reminders" element={<RemindersPage />} />
                </Route>
                <Route path="/life" element={<LifeLayout />}>
                  <Route index element={<Navigate to="/life/calendar" replace />} />
                  <Route path="calendar" element={<CalendarPage />} />
                  <Route path="meteo" element={<MeteoPage />} />
                  <Route path="news" element={<NewsPage />} />
                  <Route path="radio" element={<RadioPage />} />
                </Route>
                <Route path="/me" element={<MePage />} />
                <Route path="/me/settings" element={<SettingsPage />} />
                <Route path="/me/persona" element={<PersonaPage />} />
                <Route path="/me/memory" element={<MemoryPage />} />
                <Route path="/me/wallet" element={<WalletPage />} />
                <Route path="/me/integrations" element={<IntegrationsPage />} />
                <Route path="/me/proposals" element={<ProposalsPage />} />
                <Route path="/me/devices" element={<DevicesPage />} />
                <Route path="/lifeops/lists" element={<LifeopsListsPage />} />
                <Route path="/lifeops/lists/:slug" element={<LifeopsListDetailPage />} />
                <Route path="/lifeops/pending" element={<LifeopsPendingPage />} />
                <Route path="/lifeops/finance" element={<LifeopsFinancePage />} />
                <Route path="/discoveries" element={<DiscoveriesPage />} />
                <Route path="/diagnostics" element={<DiagnosticsPage />} />
                <Route path="/admin" element={<AdminHub />} />
              </Route>
            </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </ToastProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
