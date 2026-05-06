/**
 * HomePage — voice-first.
 *
 * Layout:
 *   - hero zone: CaraFace al centro, respira come una pianta
 *   - banner errore (se STT fallisce)
 *   - caption live + mic button in basso
 *
 * La greeting principale è ora nel TopBar dello shell, qui ci concentriamo
 * sulla "presenza" di CARA. La pagina chat tradizionale è in /chat.
 */

import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';

import type { User } from '../api/auth';
import { CaraFaceFX } from '../components/CaraFaceFX';
import { LiveCaption } from '../components/LiveCaption';
import { MicButton, type MicState } from '../components/MicButton';
import { type Emotion, type EnergyState } from '../components/CaraFace';
import { Badge, Card, Icon, IconButton } from '../design';
import { useVoiceConversation } from '../lib/voiceConversation';
import { loadPrefs } from '../lib/userPrefs';
import { inferEmotion } from '../lib/expressionFromText';

export function HomePage() {
  useOutletContext<{ user: User }>(); // ensures we're inside the shell
  const navigate = useNavigate();
  const wakeWordPref = useMemo(() => loadPrefs().wakeWordEnabled, []);
  const conv = useVoiceConversation({ autoSpeak: true, wakeWord: wakeWordPref });

  const [faceSize, setFaceSize] = useState(() =>
    typeof window === 'undefined'
      ? 280
      : Math.min(360, Math.min(window.innerWidth * 0.7, window.innerHeight * 0.5)),
  );
  useEffect(() => {
    const onResize = () =>
      setFaceSize(
        Math.min(360, Math.min(window.innerWidth * 0.7, window.innerHeight * 0.5)),
      );
    window.addEventListener('resize', onResize);
    window.addEventListener('orientationchange', onResize);
    return () => {
      window.removeEventListener('resize', onResize);
      window.removeEventListener('orientationchange', onResize);
    };
  }, []);

  // No voice at all? Push the user to /chat.
  useEffect(() => {
    if (!conv.sttOk && !conv.ttsOk) {
      navigate('/chat', { replace: true });
    }
  }, [conv.sttOk, conv.ttsOk, navigate]);

  const { energy, emotion } = useMemo<{ energy: EnergyState; emotion: Emotion }>(() => {
    switch (conv.phase) {
      case 'listening':
        return { energy: 'listening', emotion: 'neutral' };
      case 'thinking':
        return { energy: 'thinking', emotion: 'thoughtful' };
      case 'speaking':
        // Drive the face from what CARA is actually saying.
        return { energy: 'speaking', emotion: inferEmotion(conv.assistantText) };
      default:
        // After a turn ends, hold the closing mood briefly so the face
        // doesn't snap to neutral the instant audio stops.
        return {
          energy: 'idle',
          emotion: conv.assistantText ? inferEmotion(conv.assistantText) : 'happy',
        };
    }
  }, [conv.phase, conv.assistantText]);

  const micState: MicState = !conv.sttOk
    ? 'disabled'
    : conv.phase === 'idle'
      ? 'idle'
      : conv.phase;

  return (
    <div className="flex flex-col h-full select-none">
      {/* Wake-word indicator */}
      {conv.wakeWordActive && (
        <div className="px-5 -mt-1 mb-2">
          <Badge tone="ok" dot size="sm">
            in ascolto di "CARA"
          </Badge>
        </div>
      )}

      {/* Error banner */}
      {conv.errorMessage && (
        <div className="mx-5 md:mx-8 mb-2">
          <Card variant="outline" tint="alert" padded={false}>
            <div className="flex items-start gap-3 px-4 py-3">
              <Icon name="bell" size={18} className="text-alert mt-0.5 shrink-0" />
              <div className="flex-1 text-sm text-fg">{conv.errorMessage}</div>
              <IconButton
                name="close"
                label="Chiudi avviso"
                size="sm"
                variant="plain"
                onClick={conv.dismissError}
              />
            </div>
          </Card>
        </div>
      )}

      {/* Hero — CaraFace */}
      <div className="flex-1 flex items-center justify-center px-4 min-h-0">
        <CaraFaceFX
          energy={energy}
          emotion={emotion}
          size={faceSize}
          gestures
          onTap={() => conv.start()}
        />
      </div>

      {/* Caption + Mic */}
      <div className="pb-[max(env(safe-area-inset-bottom),1.25rem)]">
        <div className="min-h-20 px-4 mb-3">
          {conv.phase === 'listening' ? (
            // While listening, show what the STT is hearing.
            <LiveCaption text={conv.userText} role="user" collapseEmpty />
          ) : conv.phase === 'thinking' ? (
            // During thinking, neither stream the LLM tokens (they'd
            // race ahead of the audio that hasn't started yet) nor
            // hide everything — show the user's last utterance frozen.
            <LiveCaption text={conv.userText} role="user" collapseEmpty />
          ) : (
            // speaking / idle → assistant caption with karaoke sync to audio.
            <LiveCaption text={conv.assistantText} role="assistant" collapseEmpty />
          )}
        </div>

        <div className="flex justify-center">
          <MicButton
            state={micState}
            onClick={conv.start}
            size={96}
            label={
              conv.phase === 'listening' && conv.userText.trim()
                ? 'Tocca per inviare'
                : undefined
            }
          />
        </div>

        <p className="text-center text-2xs text-fg-muted mt-3 px-4">
          {conv.sttOk
            ? 'Tocca Cara o il microfono per parlare.'
            : 'Microfono non supportato — usa la chat scritta.'}
        </p>
      </div>
    </div>
  );
}
