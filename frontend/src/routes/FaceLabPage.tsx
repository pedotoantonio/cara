/**
 * FaceLab — admin-only sandbox to inspect every (energy × emotion) of CARA's
 * avatar. Useful for visual QA, content review, and showcase.
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';

import type { User } from '../api/auth';
import {
  type Emotion,
  type EnergyState,
} from '../components/CaraFace';
import { CaraFaceFX } from '../components/CaraFaceFX';

const ENERGIES: EnergyState[] = [
  'idle',
  'listening',
  'sensing',
  'thinking',
  'speaking',
  'sleeping',
  'deep_sleep',
  'waking_up',
  'focused',
];

const EMOTIONS: Emotion[] = [
  'neutral',
  'happy',
  'joyful',
  'love',
  'surprised',
  'thoughtful',
  'confused',
  'sad',
  'embarrassed',
  'ironic',
  'sleepy',
  'error',
];

export function FaceLabPage() {
  const { user } = useOutletContext<{ user: User }>();
  const navigate = useNavigate();

  // Gated to admin. Use a tiny effect rather than a ProtectedRoute wrapper
  // because this is the only admin-only route we have today.
  useEffect(() => {
    if (!user.is_admin) navigate('/chat', { replace: true });
  }, [user, navigate]);

  const [energy, setEnergy] = useState<EnergyState>('idle');
  const [emotion, setEmotion] = useState<Emotion>('neutral');
  const [size, setSize] = useState(180);
  const [particles, setParticles] = useState(true);
  const [glow, setGlow] = useState(true);

  // Auto-cycle preview
  const [auto, setAuto] = useState(false);
  useEffect(() => {
    if (!auto) return;
    let i = 0;
    const id = setInterval(() => {
      i = (i + 1) % EMOTIONS.length;
      setEmotion(EMOTIONS[i]);
    }, 1500);
    return () => clearInterval(id);
  }, [auto]);

  const matrixCells = useMemo(() => {
    const out: Array<{ e: EnergyState; emo: Emotion }> = [];
    for (const e of ENERGIES) for (const emo of EMOTIONS) out.push({ e, emo });
    return out;
  }, []);

  return (
    <main className="flex-1 overflow-y-auto bg-slate-900 text-slate-100">
      <div className="max-w-5xl mx-auto p-4 md:p-6 space-y-6">
        <header>
          <h1 className="text-xl font-medium">Face Lab</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Sandbox per esaminare tutte le combinazioni di stato × emozione.
          </p>
        </header>

        {/* Live preview + controls */}
        <section className="rounded-2xl bg-slate-800/60 border border-slate-700 p-5 grid md:grid-cols-2 gap-6">
          <div className="flex items-center justify-center">
            <CaraFaceFX
              energy={energy}
              emotion={emotion}
              size={size}
              particles={particles}
              glow={glow}
            />
          </div>
          <div className="space-y-4">
            <div>
              <label className="text-xs text-slate-400 block mb-1">Stato energia</label>
              <select
                value={energy}
                onChange={(e) => setEnergy(e.target.value as EnergyState)}
                className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
              >
                {ENERGIES.map((e) => (
                  <option key={e} value={e}>{e}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">Emozione</label>
              <select
                value={emotion}
                onChange={(e) => setEmotion(e.target.value as Emotion)}
                className="w-full rounded-xl bg-slate-900 border border-slate-700 px-3 py-2 text-sm"
              >
                {EMOTIONS.map((e) => (
                  <option key={e} value={e}>{e}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs text-slate-400 block mb-1">
                Dimensione: {size}px
              </label>
              <input
                type="range"
                min={60}
                max={320}
                step={20}
                value={size}
                onChange={(e) => setSize(Number(e.target.value))}
                className="w-full accent-emerald-500"
              />
            </div>
            <div className="flex items-center gap-4 text-xs">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={particles}
                  onChange={(e) => setParticles(e.target.checked)}
                  className="accent-emerald-500"
                />
                Particelle
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={glow}
                  onChange={(e) => setGlow(e.target.checked)}
                  className="accent-emerald-500"
                />
                Glow bordo
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={auto}
                  onChange={(e) => setAuto(e.target.checked)}
                  className="accent-emerald-500"
                />
                Auto-cicla emozioni
              </label>
            </div>
          </div>
        </section>

        {/* Matrix overview: every (energy × emotion) at glance */}
        <section>
          <h2 className="text-sm font-medium mb-3">
            Matrice {ENERGIES.length} × {EMOTIONS.length} ({matrixCells.length} celle)
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            {matrixCells.map(({ e, emo }) => (
              <button
                key={`${e}.${emo}`}
                type="button"
                onClick={() => {
                  setEnergy(e);
                  setEmotion(emo);
                }}
                className="rounded-xl bg-slate-800/40 border border-slate-700/50 p-2 flex flex-col items-center gap-1 hover:bg-slate-800/80 transition"
                title={`${e} × ${emo}`}
              >
                <CaraFaceFX
                  energy={e}
                  emotion={emo}
                  size={60}
                  particles={false}
                  glow={false}
                />
                <span className="text-[10px] text-slate-500 truncate w-full text-center">
                  {emo}
                </span>
                <span className="text-[10px] text-slate-600 truncate w-full text-center">
                  {e}
                </span>
              </button>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
