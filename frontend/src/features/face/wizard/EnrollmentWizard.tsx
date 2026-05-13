/**
 * Face enrollment wizard — 6 step flow.
 *
 *   consent → details → capture_front → capture_left → capture_right
 *           → capture_expression_smile → capture_expression_neutral → review
 *
 * Each capture step asks the user to pose differently, watches the live
 * detection quality, and auto-snaps after 3 consecutive frames at
 * quality ≥ 0.8. On review the wizard creates the profile + uploads all
 * 5 descriptors in a single bulk POST.
 *
 * Mounts its own FaceProvider so the rest of the app doesn't have to.
 * The provider stops the worker on unmount → webcam light goes off.
 */

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { addDescriptors, createFaceProfile } from '../../../api/face';
import { FaceProvider, useFaceContext } from '../FaceContext';

import { CaptureStep, type CapturePrompt } from './CaptureStep';
import { ConsentStep } from './ConsentStep';
import { DetailsStep } from './DetailsStep';
import { ReviewStep } from './ReviewStep';
import {
  CONSENT_TEXT_VERSION,
  type WizardCapture,
  type WizardDetails,
  type WizardStep,
} from './types';


const CAPTURE_PROMPTS: Record<
  Exclude<WizardStep, 'consent' | 'details' | 'review'>,
  CapturePrompt
> = {
  capture_front: {
    angle: 'front',
    title: 'Guarda dritto verso la camera',
    instruction: 'Stai fermo, sguardo dritto, faccia centrata.',
  },
  capture_left: {
    angle: 'left',
    title: 'Gira leggermente la testa a sinistra',
    instruction: 'Solo un piccolo angolo — non più di 30°.',
  },
  capture_right: {
    angle: 'right',
    title: 'Adesso a destra',
    instruction: 'Stessa cosa, ruota leggermente verso destra.',
  },
  capture_expression_smile: {
    angle: 'smile',
    title: 'Adesso sorridi',
    instruction: 'Un sorriso naturale, occhi sulla camera.',
  },
  capture_expression_neutral: {
    angle: 'neutral',
    title: 'Espressione neutra',
    instruction: 'Rilassa il viso, espressione neutra.',
  },
};


function WizardInner() {
  const face = useFaceContext();
  const navigate = useNavigate();

  const [step, setStep] = useState<WizardStep>('consent');
  const [details, setDetails] = useState<WizardDetails>({
    displayName: '',
    isChild: false,
  });
  const [captures, setCaptures] = useState<WizardCapture[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Trigger recognition net load as soon as the user accepts consent —
  // by the time they reach the first capture step the weights are warm.
  const advanceFromConsent = useCallback(() => {
    face.enableRecognition();
    setStep('details');
  }, [face]);

  const advanceFromDetails = useCallback((d: WizardDetails) => {
    setDetails(d);
    setStep('capture_front');
  }, []);

  const onCaptured = useCallback(
    (capture: WizardCapture) => {
      const next: WizardStep | null = (() => {
        switch (step) {
          case 'capture_front':
            return 'capture_left';
          case 'capture_left':
            return 'capture_right';
          case 'capture_right':
            return 'capture_expression_smile';
          case 'capture_expression_smile':
            return 'capture_expression_neutral';
          case 'capture_expression_neutral':
            return 'review';
          default:
            return null;
        }
      })();
      setCaptures((prev) => [...prev, capture]);
      if (next) setStep(next);
    },
    [step],
  );

  const retryCaptures = useCallback(() => {
    setCaptures([]);
    setStep('capture_front');
  }, []);

  const saveProfile = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const profile = await createFaceProfile({
        display_name: details.displayName,
        is_child: details.isChild,
        consent_text_version: CONSENT_TEXT_VERSION,
      });
      await addDescriptors(
        profile.id,
        captures.map((c) => ({
          descriptor: c.descriptor,
          source: 'enrollment',
          quality: c.quality,
        })),
      );
      // Refresh worker cache so the new profile is immediately
      // recognisable from any open surface.
      await face.refreshProfiles();
      navigate('/face/enroll/done', {
        replace: true,
        state: { displayName: profile.displayName, captureCount: captures.length },
      });
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  }, [captures, details, face, navigate]);

  const cancel = useCallback(() => {
    face.stop();
    navigate('/', { replace: true });
  }, [face, navigate]);

  // Total wizard progress (1..6 visible steps, capture-expression collapsed
  // to a single visible step for the progress dot count, but the inner
  // smile + neutral count separately for the captures array).
  const visibleStepIndex = stepToVisibleIndex(step);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 flex flex-col">
      <header className="border-b bg-white">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between gap-4">
          <h1 className="text-lg font-semibold">Registra un nuovo volto</h1>
          <button
            type="button"
            onClick={cancel}
            className="text-sm text-slate-600 hover:text-slate-900"
          >
            Annulla
          </button>
        </div>
        <ProgressBar current={visibleStepIndex} total={6} />
      </header>

      <main className="flex-1">
        <div className="max-w-3xl mx-auto px-6 py-8">
          {step === 'consent' && <ConsentStep onAccept={advanceFromConsent} />}

          {step === 'details' && (
            <DetailsStep initial={details} onSubmit={advanceFromDetails} />
          )}

          {(step === 'capture_front' ||
            step === 'capture_left' ||
            step === 'capture_right' ||
            step === 'capture_expression_smile' ||
            step === 'capture_expression_neutral') && (
            <CaptureStep
              prompt={CAPTURE_PROMPTS[step]}
              completed={captures.length}
              total={5}
              onCaptured={onCaptured}
            />
          )}

          {step === 'review' && (
            <ReviewStep
              details={details}
              captures={captures}
              saving={saving}
              error={saveError}
              onSave={saveProfile}
              onRetry={retryCaptures}
            />
          )}
        </div>
      </main>
    </div>
  );
}


function stepToVisibleIndex(step: WizardStep): number {
  switch (step) {
    case 'consent':
      return 1;
    case 'details':
      return 2;
    case 'capture_front':
      return 3;
    case 'capture_left':
      return 4;
    case 'capture_right':
      return 5;
    case 'capture_expression_smile':
    case 'capture_expression_neutral':
      return 6;
    case 'review':
      return 6;
  }
}


function ProgressBar({ current, total }: { current: number; total: number }) {
  return (
    <div className="max-w-3xl mx-auto px-6 pb-3 flex gap-1.5">
      {Array.from({ length: total }, (_, i) => (
        <div
          key={i}
          className={`h-1 flex-1 rounded-full transition-colors ${
            i < current ? 'bg-emerald-500' : 'bg-slate-200'
          }`}
        />
      ))}
    </div>
  );
}


/**
 * The exported wizard mounts its own FaceProvider so it can be dropped
 * on any route without the rest of the app having to think about it.
 */
export function EnrollmentWizard() {
  // The provider doesn't actually start the worker until WizardInner
  // calls `start(video)` from inside a capture step, so cold-route
  // navigation here doesn't yet open the webcam.
  return (
    <FaceProvider>
      <BootstrapAndRun />
    </FaceProvider>
  );
}


function BootstrapAndRun() {
  const face = useFaceContext();
  // Make sure profile cache is populated before any matching happens.
  useEffect(() => {
    void face.refreshProfiles();
    return () => face.stop();
  }, [face]);
  return <WizardInner />;
}
