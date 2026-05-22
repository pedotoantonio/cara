import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { useAuthStore } from '@/state/auth';
import { ToastProvider } from '@/design/components';
import { AppShell } from '@/components/common/AppShell';

import { LoginPage } from '@/routes/auth/LoginPage';
import { HubHome } from '@/routes/home/HubHome';
import { ChatPage } from '@/routes/chat/ChatPage';
import { ListHub } from '@/routes/list/ListHub';
import { LifeHub } from '@/routes/life/LifeHub';
import { MePage } from '@/routes/me/MePage';

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
  return <Outlet />;
}

function Bootstrap() {
  const bootstrap = useAuthStore((s) => s.bootstrap);
  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);
  return null;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Bootstrap />
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<Protected />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<HubHome />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/list" element={<ListHub />} />
                <Route path="/list/:tab" element={<ListHub />} />
                <Route path="/life" element={<LifeHub />} />
                <Route path="/life/:tab" element={<LifeHub />} />
                <Route path="/me" element={<MePage />} />
                <Route path="/me/:section" element={<MePage />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
