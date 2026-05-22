import { useState, type FormEvent } from 'react';
import { motion } from 'framer-motion';
import { useAuthStore } from '@/state/auth';
import { Button, Card, Input, useToast } from '@/design/components';

export function LoginPage() {
  const login = useAuthStore((s) => s.loginWithCredentials);
  const error = useAuthStore((s) => s.error);
  const toast = useToast();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await login(email.trim(), password);
      toast.push({ tone: 'mint', title: 'Bentornato', body: 'Eccoti dentro casa.' });
    } catch (err) {
      toast.push({ tone: 'coral', title: 'Accesso fallito', body: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="min-h-[100dvh] grid place-items-center p-6">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0.2, 0, 0, 1] }}
        className="w-full max-w-sm"
      >
        <div className="text-center mb-8">
          <h1 className="font-display text-4xl tracking-tight text-text-primary">CARA</h1>
          <p className="mt-2 text-text-secondary">La casa che ti riconosce.</p>
        </div>

        <Card elevation={2} padding="lg" surface="elevated">
          <form onSubmit={onSubmit} className="space-y-4">
            <Input
              type="email"
              label="Email"
              autoComplete="email"
              inputMode="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="tu@casa.it"
            />
            <Input
              type="password"
              label="Password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error && <p className="text-sm text-accent-coral">{error}</p>}
            <Button type="submit" loading={busy} fullWidth>
              Entra
            </Button>
          </form>
        </Card>

        <p className="mt-6 text-xs text-center text-text-muted">
          Se sei sulla rete di casa, l'accesso è automatico.
        </p>
      </motion.div>
    </main>
  );
}
