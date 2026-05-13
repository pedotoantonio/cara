/**
 * /admin/face/debug — live diagnostics for the face recognition stack.
 *
 * Surface intended for the household admin (and the person who wrote
 * the feature) while tuning thresholds or chasing a regression.
 * Shows, in real time:
 *
 *   - effective FPS (derived from currentIntervalMs)
 *   - last + rolling-average worker latency
 *   - idle + spoofing flags
 *   - the last 20 lifecycle events with timestamps
 *   - the distance distribution of the most recent matches
 *
 * Mounts its own FaceProvider + ActiveProfileProvider so it works
 * standalone. The webcam only opens after the user clicks "Avvia":
 * a passive load of the debug page leaves the camera off.
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { Badge, Button, Card, CardSubtitle, CardTitle, cn, useToast } from '../design';
import {
  ActiveProfileBadge,
  ActiveProfileProvider,
  FaceOverlay,
  FaceProvider,
  useFaceContext,
} from '../features/face';
import type { FaceEvent } from '../features/face/types';


const RENDER_W = 480;
const RENDER_H = 360;


export default function AdminFaceDebugPage() {
  return (
    <FaceProvider>
      <ActiveProfileProvider>
        <Inner />
      </ActiveProfileProvider>
    </FaceProvider>
  );
}


function Inner() {
  const face = useFaceContext();
  const toast = useToast();
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [running, setRunning] = useState(false);

  // Rolling buffers for the diagnostics view.
  const [recentDurations, setRecentDurations] = useState<number[]>([]);
  const [events, setEvents] = useState<{ at: number; event: FaceEvent }[]>([]);
  const [distances, setDistances] = useState<number[]>([]);

  // Subscribe to events once.
  useEffect(() => {
    const off = face.onEvent((event) => {
      setEvents((prev) => [{ at: Date.now(), event }, ...prev].slice(0, 20));
      if (event.kind === 'face.identified') {
        setDistances((prev) => [event.distance, ...prev].slice(0, 50));
      }
    });
    return off;
  }, [face]);

  // Track recent worker latencies via the public lastDurationMs field.
  useEffect(() => {
    if (face.lastDurationMs === 0) return;
    setRecentDurations((prev) => [face.lastDurationMs, ...prev].slice(0, 20));
  }, [face.lastDurationMs]);

  // Try to keep the profile cache warm so identified events fire.
  useEffect(() => {
    void face.refreshProfiles();
  }, [face]);

  const start = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
        audio: false,
      });
      streamRef.current = stream;
      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        await video.play().catch(() => undefined);
        face.enableRecognition();
        face.start(video);
        setRunning(true);
      }
    } catch (err) {
      toast.push({
        kind: 'alert',
        title: 'Camera non disponibile',
        body: err instanceof Error ? err.message : String(err),
      });
    }
  }, [face, toast]);

  const stop = useCallback(() => {
    face.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setRunning(false);
  }, [face]);

  useEffect(() => () => stop(), [stop]);

  const effectiveFps = face.currentIntervalMs > 0
    ? 1000 / face.currentIntervalMs
    : 0;
  const avgLatency = recentDurations.length > 0
    ? recentDurations.reduce((a, b) => a + b, 0) / recentDurations.length
    : 0;

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 py-6 space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-start gap-3">
          <div>
            <h1 className="text-2xl font-semibold">Face debug</h1>
            <p className="text-sm text-slate-500">
              Latenza, FPS, eventi, distribuzione distanze. Solo admin.
            </p>
          </div>
          <ActiveProfileBadge />
        </div>
        {running ? (
          <Button onClick={stop} variant="alert">
            Ferma
          </Button>
        ) : (
          <Button onClick={start} variant="primary" iconLeft="mic">
            Avvia camera
          </Button>
        )}
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardTitle>Stream</CardTitle>
          <CardSubtitle>
            Anteprima locale; nessun byte di immagine lascia il browser.
          </CardSubtitle>
          <div
            className="relative mt-3 rounded-xl overflow-hidden bg-slate-900"
            style={{ width: RENDER_W, height: RENDER_H, maxWidth: '100%' }}
          >
            <video
              ref={videoRef}
              width={RENDER_W}
              height={RENDER_H}
              autoPlay
              muted
              playsInline
              className="w-full h-full object-cover"
            />
            <FaceOverlay
              sourceWidth={RENDER_W}
              sourceHeight={RENDER_H}
              width={RENDER_W}
              height={RENDER_H}
              hideWhenEmpty={false}
            />
          </div>
        </Card>

        <Card>
          <CardTitle>Pipeline</CardTitle>
          <CardSubtitle>Lo stato del worker e del frame loop.</CardSubtitle>
          <dl className="mt-3 grid grid-cols-2 gap-y-2 gap-x-4 text-sm">
            <DtDd label="FPS effettivi" value={effectiveFps.toFixed(1)} />
            <DtDd label="Interval" value={`${face.currentIntervalMs} ms`} />
            <DtDd label="Latenza ultima" value={`${face.lastDurationMs.toFixed(0)} ms`} />
            <DtDd label="Latenza media" value={`${avgLatency.toFixed(0)} ms`} />
            <DtDd label="Worker pronto" value={face.modelsReady ? 'sì' : 'no'} />
            <DtDd
              label="Recognition net"
              value={face.recognitionReady ? 'caricato' : '—'}
            />
            <DtDd label="Profili in cache" value={String(face.profilesCount)} />
            <DtDd label="Volti visti" value={String(face.detections.length)} />
          </dl>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            {face.idle && <Badge tone="muted">idle 1 FPS</Badge>}
            {face.spoofingSuspected && (
              <Badge tone="alert">possibile foto (statica)</Badge>
            )}
            {!face.modelsReady && <Badge tone="neutral">in caricamento</Badge>}
            {face.lastError && (
              <Badge tone="alert">errore: {face.lastError}</Badge>
            )}
          </div>
        </Card>
      </div>

      <Card>
        <CardTitle>Distribuzione distanze (ultimi {distances.length} match)</CardTitle>
        <CardSubtitle>
          Una distanza vicino a 0 = match netto. Vicino alla soglia = match
          dubbio. Sopra la soglia = no match.
        </CardSubtitle>
        {distances.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">
            Nessun match registrato in questa sessione.
          </p>
        ) : (
          <Histogram values={distances} />
        )}
      </Card>

      <Card>
        <CardTitle>Ultimi 20 eventi</CardTitle>
        <CardSubtitle>
          Detection, conferme identità, scomparse, sconosciuti.
        </CardSubtitle>
        {events.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">Nessun evento ancora.</p>
        ) : (
          <ul className="mt-3 divide-y divide-slate-100 text-sm">
            {events.map(({ at, event }, idx) => (
              <li key={idx} className="py-1.5 flex items-baseline gap-3">
                <span className="text-xs text-slate-400 tabular-nums">
                  {new Date(at).toLocaleTimeString('it-IT')}
                </span>
                <EventLine event={event} />
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}


function DtDd({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt className="text-slate-500">{label}</dt>
      <dd className="font-medium tabular-nums">{value}</dd>
    </>
  );
}


function EventLine({ event }: { event: FaceEvent }) {
  switch (event.kind) {
    case 'face.detected':
      return (
        <span>
          <code className="text-slate-400">face.detected</code>{' '}
          score {event.score.toFixed(2)}
        </span>
      );
    case 'face.identified':
      return (
        <span>
          <code className="text-emerald-600">face.identified</code>{' '}
          <strong>{event.displayName}</strong> · d={event.distance.toFixed(3)}
          {event.companions.length > 0 && (
            <span className="text-slate-500"> + {event.companions.length}</span>
          )}
        </span>
      );
    case 'face.unknown_present':
      return (
        <span>
          <code className="text-amber-600">face.unknown</code> track #
          {event.trackId}
        </span>
      );
    case 'face.lost':
      return (
        <span>
          <code className="text-slate-500">face.lost</code>{' '}
          {event.profileId ?? '—'}
        </span>
      );
  }
}


function Histogram({ values }: { values: number[] }) {
  const bins = useMemo(() => {
    // 10 bins between 0 and 1.
    const counts = Array.from({ length: 10 }, () => 0);
    for (const v of values) {
      const idx = Math.max(0, Math.min(9, Math.floor(v * 10)));
      counts[idx] += 1;
    }
    const max = Math.max(1, ...counts);
    return counts.map((c, i) => ({
      label: `${(i / 10).toFixed(1)}-${((i + 1) / 10).toFixed(1)}`,
      count: c,
      h: c / max,
    }));
  }, [values]);

  return (
    <div className="mt-3 grid grid-cols-10 gap-1 items-end h-32">
      {bins.map((b) => (
        <div key={b.label} className="flex flex-col items-center">
          <div
            className={cn(
              'w-full rounded-t-md',
              b.count === 0 ? 'bg-slate-200' : 'bg-emerald-500',
            )}
            style={{ height: `${Math.max(2, b.h * 100)}%` }}
            title={`${b.label}: ${b.count}`}
          />
          <span className="mt-1 text-[10px] text-slate-500 tabular-nums">
            {b.label.split('-')[0]}
          </span>
        </div>
      ))}
    </div>
  );
}
