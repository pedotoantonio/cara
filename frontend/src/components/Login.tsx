import { useState } from 'react';

import { login } from '../api/auth';

export function Login({ onSuccess }: { onSuccess: () => void }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      onSuccess();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-dvh flex items-center justify-center p-6 bg-slate-900 text-slate-100">
      <form
        onSubmit={submit}
        className="w-full max-w-sm space-y-4 rounded-2xl bg-slate-800/60 border border-slate-700 p-6"
      >
        <div className="text-center space-y-1">
          <h1 className="text-4xl font-light tracking-tight">cara</h1>
          <p className="text-xs text-slate-400">Casa AI for Routines &amp; Activities</p>
        </div>
        <div className="space-y-2">
          <label className="block text-xs text-slate-400">Email</label>
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
          />
        </div>
        <div className="space-y-2">
          <label className="block text-xs text-slate-400">Password</label>
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
          />
        </div>
        {error && <p className="text-xs text-rose-400">{error}</p>}
        <button
          type="submit"
          disabled={submitting || !email || !password}
          className="w-full rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 px-3 py-2 text-sm font-medium"
        >
          {submitting ? 'Accesso…' : 'Accedi'}
        </button>
      </form>
    </main>
  );
}
