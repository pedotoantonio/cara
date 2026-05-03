/**
 * Voice-first home page.
 *
 * Layout (per the brief):
 *   - top 10%:    discreet quick-access strip (chat link, settings)
 *   - middle 70%: CARA's animated face, large
 *   - bottom 20%: live caption + big mic button
 *
 * The classical text chat lives at /chat (still navigable).
 */

import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useOutletContext } from 'react-router-dom';

import type { User } from '../api/auth';
import { CaraFaceFX } from '../components/CaraFaceFX';
import { LiveCaption } from '../components/LiveCaption';
import { MicButton, type MicState } from '../components/MicButton';
import { type Emotion, type EnergyState } from '../components/CaraFace';
import { useVoiceConversation } from '../lib/voiceConversation';
import { loadPrefs } from '../lib/userPrefs';

export function HomePage() {
  const { user } = useOutletContext<{ user: User }>();
  const navigate = useNavigate();
  // Read the wake-word preference once on mount; toggling it requires a
  // /settings round-trip, so we don't need to subscribe to changes.
  const wakeWordPref = useMemo(() => loadPrefs().wakeWordEnabled, []);
  const conv = useVoiceConversation({ autoSpeak: true, wakeWord: wakeWordPref });

  // Face size needs to react to viewport changes (orientation flip,
  // window resize on desktop) — a static read of window.innerWidth at first
  // render leaves the face the wrong size after rotation.
  const [faceSize, setFaceSize] = useState(() =>
    typeof window === 'undefined' ? 280 : Math.min(360, Math.min(window.innerWidth * 0.7, window.innerHeight * 0.55)),
  );
  useEffect(() => {
    const onResize = () =>
      setFaceSize(Math.min(360, Math.min(window.innerWidth * 0.7, window.innerHeight * 0.55)));
    window.addEventListener('resize', onResize);
    window.addEventListener('orientationchange', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('orientationchange', onResize);
    };
  }, []);

  // If voice isn't available at all, push the user to /chat.
  useEffect(() => {
    if (!conv.sttOk && !conv.ttsOk) {
      navigate('/chat', { replace: true });
    }
  }, [conv.sttOk, conv.ttsOk, navigate]);

  // Map the voice state machine to the face state machine.
  const { energy, emotion } = useMemo<{ energy: EnergyState; emotion: Emotion }>(() => {
    switch (conv.phase) {
      case 'listening':
        return { energy: 'listening', emotion: 'neutral' };
      case 'thinking':
        return { energy: 'thinking', emotion: 'thoughtful' };
      case 'speaking':
        return { energy: 'speaking', emotion: 'happy' };
      default:
        return { energy: 'idle', emotion: 'happy' };
    }
  }, [conv.phase]);

  const micState: MicState = !conv.sttOk
    ? 'disabled'
    : conv.phase === 'idle'
      ? 'idle'
      : conv.phase;

  // Face size scales with viewport; clamp so it never overflows or shrinks.
  // We pick min(viewport-width, viewport-height * 0.55) at runtime via CSS.
  return (
    <main
      className="flex-1 flex flex-col bg-gradient-to-b from-slate-900 via-slate-900 to-slate-950
                 text-slate-100 select-none"
    >
      {/* Top strip — 10% */}
      <div className="h-[10vh] flex items-center justify-between px-4 md:px-6">
        <div className="text-xs text-slate-500 truncate">
          Ciao {user.full_name?.split(' ')[0] ?? user.email}
        </div>
        <div className="flex items-center gap-3 text-slate-400">
          {conv.wakeWordActive && (
            <span
              className="flex items-center gap-1 text-[11px] text-emerald-400/80"
              title='In ascolto della parola "CARA"'
            >
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              CARA
            </span>
          )}
          <Link to="/chat" title="Modalità chat scritta" className="text-lg hover:text-slate-100">
            💬
          </Link>
          <Link to="/settings" title="Impostazioni" className="text-lg hover:text-slate-100">
            ⚙️
          </Link>
        </div>
      </div>

      {/* Error banner — visible when STT fails (permission denied, no recognizer, …) */}
      {conv.errorMessage && (
        <div
          role="alert"
          className="mx-4 md:mx-6 -mt-2 mb-2 rounded-xl bg-rose-500/15 border border-rose-500/40
                     text-rose-200 text-xs px-3 py-2 flex items-start gap-2"
        >
          <span className="flex-1">{conv.errorMessage}</span>
          <button
            type="button"
            onClick={conv.dismissError}
            className="text-rose-200 hover:text-white text-base leading-none"
            aria-label="Chiudi avviso"
          >
            ✕
          </button>
        </div>
      )}

      {/* Face — 70% */}
      <div className="flex-1 flex items-center justify-center px-4">
        <CaraFaceFX
          energy={energy}
          emotion={emotion}
          size={faceSize}
          gestures
          onTap={() => conv.start()}
        />
      </div>

      {/* Bottom — 20%: caption + mic */}
      <div className="min-h-[20vh] flex flex-col justify-end pb-[max(env(safe-area-inset-bottom),1.25rem)] gap-4">
        <div className="min-h-20 px-4">
          {conv.phase === 'listening' || (conv.userText && !conv.assistantText) ? (
            <LiveCaption text={conv.userText} role="user" collapseEmpty />
          ) : (
            <LiveCaption text={conv.assistantText} role="assistant" collapseEmpty />
          )}
        </div>

        <div className="flex justify-center">
          <MicButton state={micState} onClick={conv.start} size={104} />
        </div>

        <p className="text-center text-[11px] text-slate-600">
          {conv.sttOk
            ? 'Tocca CARA o il microfono per parlare. Tocca di nuovo per fermare.'
            : 'Microfono non supportato in questo browser — usa la modalità chat 💬'}
        </p>
      </div>
    </main>
  );
}
