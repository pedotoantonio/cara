// BarcodeScanner — legge il codice a barre di un prodotto con la
// fotocamera e lo risolve via Open Food Facts (backend /diet/barcode).
//
// Usa la BarcodeDetector API nativa del browser (Chrome/Android, anche
// dentro la PWA): nessuna dipendenza npm aggiuntiva. Dove non è
// supportata (Firefox/Safari/desktop senza flag) mostra un fallback a
// inserimento manuale del codice, così la funzione resta usabile.
//
// Flusso: scan → lookup prodotto → scegli porzione (g) → log come pasto.
// Le calorie sono calcolate dal backend (kcal/100g × porzione).

import { useEffect, useRef, useState } from 'react';

import {
  type BarcodeProduct,
  type MealType,
  MEAL_LABEL,
  logBarcode,
  lookupBarcode,
} from '../../api/diet';
import { BottomSheet, Button, Icon } from '../../design';

// Minimal typing for the experimental BarcodeDetector API.
interface DetectedBarcode {
  rawValue: string;
}
interface BarcodeDetectorLike {
  detect: (source: CanvasImageSource) => Promise<DetectedBarcode[]>;
}
type BarcodeDetectorCtor = new (opts?: { formats?: string[] }) => BarcodeDetectorLike;

const MEALS: MealType[] = ['colazione', 'spuntino', 'pranzo', 'cena'];

const NUTRISCORE_COLOR: Record<string, string> = {
  a: '#15803d', b: '#65a30d', c: '#ca8a04', d: '#ea580c', e: '#dc2626',
};

interface Props {
  open: boolean;
  onClose: () => void;
  defaultMeal?: MealType;
  onLogged?: () => void;
}

type Phase = 'scanning' | 'manual' | 'product' | 'done';

export function BarcodeScanner({ open, onClose, defaultMeal = 'spuntino', onLogged }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number | null>(null);
  const detectorRef = useRef<BarcodeDetectorLike | null>(null);

  const [phase, setPhase] = useState<Phase>('scanning');
  const [error, setError] = useState<string | null>(null);
  const [manualCode, setManualCode] = useState('');
  const [product, setProduct] = useState<BarcodeProduct | null>(null);
  const [portion, setPortion] = useState(100);
  const [meal, setMeal] = useState<MealType>(defaultMeal);
  const [busy, setBusy] = useState(false);

  const supported =
    typeof window !== 'undefined' && 'BarcodeDetector' in window;

  // Start / stop the camera with the sheet lifecycle.
  useEffect(() => {
    if (!open) return;
    setPhase(supported ? 'scanning' : 'manual');
    setError(null);
    setProduct(null);
    setPortion(100);
    setMeal(defaultMeal);
    if (supported) void startCamera();
    return () => stopCamera();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function startCamera() {
    try {
      const Ctor = (window as unknown as { BarcodeDetector: BarcodeDetectorCtor })
        .BarcodeDetector;
      detectorRef.current = new Ctor({
        formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128'],
      });
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'environment' },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      tick();
    } catch {
      setError('Fotocamera non disponibile — inserisci il codice a mano');
      setPhase('manual');
    }
  }

  function stopCamera() {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }

  function tick() {
    const detector = detectorRef.current;
    const video = videoRef.current;
    if (!detector || !video) return;
    detector
      .detect(video)
      .then((codes) => {
        if (codes.length > 0 && codes[0].rawValue) {
          stopCamera();
          void resolve(codes[0].rawValue);
        } else {
          rafRef.current = requestAnimationFrame(tick);
        }
      })
      .catch(() => {
        rafRef.current = requestAnimationFrame(tick);
      });
  }

  async function resolve(code: string) {
    setBusy(true);
    setError(null);
    try {
      const p = await lookupBarcode(code);
      setProduct(p);
      // Default portion: a sensible 30g for spreads/snacks, else 100g.
      setPortion(p.kcal_per_100g && p.kcal_per_100g > 400 ? 30 : 100);
      setPhase('product');
    } catch (e) {
      setError(
        e instanceof Error && e.message !== 'HTTP 404'
          ? e.message
          : `Prodotto ${code} non trovato in Open Food Facts`,
      );
      setPhase(supported ? 'scanning' : 'manual');
      if (supported) void startCamera();
    } finally {
      setBusy(false);
    }
  }

  async function confirmLog() {
    if (!product) return;
    setBusy(true);
    setError(null);
    try {
      await logBarcode({ barcode: product.barcode, portion_g: portion, meal_type: meal });
      setPhase('done');
      onLogged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Errore salvataggio');
    } finally {
      setBusy(false);
    }
  }

  function close() {
    stopCamera();
    onClose();
  }

  const estKcal =
    product?.kcal_per_100g != null
      ? Math.round((product.kcal_per_100g * portion) / 100)
      : null;

  return (
    <BottomSheet
      open={open}
      onClose={close}
      title="Scansiona prodotto"
      subtitle="Inquadra il codice a barre"
    >
      {phase === 'scanning' && (
        <div className="space-y-3">
          <div className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl bg-black">
            <video
              ref={videoRef}
              playsInline
              muted
              className="h-full w-full object-cover"
            />
            {/* scan reticle */}
            <div className="pointer-events-none absolute inset-0 grid place-items-center">
              <div className="h-24 w-3/4 rounded-xl border-2 border-ivory/80 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]" />
            </div>
          </div>
          <p className="text-center text-sm text-fg-muted">
            Tieni fermo sul codice…
          </p>
          {error && <p className="text-center text-sm text-amber-600">{error}</p>}
          <Button variant="ghost" fullWidth onClick={() => { stopCamera(); setPhase('manual'); }}>
            Inserisci il codice a mano
          </Button>
        </div>
      )}

      {phase === 'manual' && (
        <div className="space-y-4">
          {!supported && (
            <p className="text-sm text-fg-muted">
              La scansione dalla fotocamera non è supportata su questo
              browser. Inserisci il codice a barre manualmente.
            </p>
          )}
          <input
            inputMode="numeric"
            value={manualCode}
            onChange={(e) => setManualCode(e.target.value.replace(/\D/g, ''))}
            placeholder="es. 8001505005707"
            className="w-full rounded-2xl bg-surface1 px-4 py-3 text-base ring-1 ring-fg/10 focus:outline-none focus:ring-accent/40"
          />
          {error && <p className="text-sm text-alert">{error}</p>}
          <div className="flex gap-2">
            {supported && (
              <Button variant="ghost" fullWidth onClick={() => { setError(null); setPhase('scanning'); void startCamera(); }}>
                Usa fotocamera
              </Button>
            )}
            <Button
              variant="primary"
              fullWidth
              loading={busy}
              disabled={manualCode.length < 6 || busy}
              onClick={() => void resolve(manualCode)}
            >
              Cerca
            </Button>
          </div>
        </div>
      )}

      {phase === 'product' && product && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            {product.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={product.image_url}
                alt={product.name}
                className="h-16 w-16 rounded-xl object-cover ring-1 ring-fg/10"
              />
            ) : (
              <div className="grid h-16 w-16 place-items-center rounded-xl bg-surface2 text-fg-muted">
                <Icon name="scan" size={28} />
              </div>
            )}
            <div className="min-w-0">
              <p className="truncate font-semibold text-fg">{product.name}</p>
              {product.brand && (
                <p className="truncate text-sm text-fg-muted">{product.brand}</p>
              )}
              <div className="mt-1 flex items-center gap-2 text-xs text-fg-muted">
                {product.kcal_per_100g != null && (
                  <span>{product.kcal_per_100g} kcal/100g</span>
                )}
                {product.nutriscore && (
                  <span
                    className="rounded px-1.5 py-0.5 font-bold uppercase text-ivory"
                    style={{ background: NUTRISCORE_COLOR[product.nutriscore] || '#94a3b8' }}
                  >
                    {product.nutriscore}
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* macros */}
          {(product.protein_g != null || product.carbs_g != null || product.fat_g != null) && (
            <div className="grid grid-cols-3 gap-2 text-center text-sm">
              <Macro label="Proteine" v={product.protein_g} />
              <Macro label="Carboidrati" v={product.carbs_g} />
              <Macro label="Grassi" v={product.fat_g} />
            </div>
          )}

          <div>
            <label className="mb-1 block text-sm text-fg-muted">Porzione (g)</label>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={2000}
                value={portion}
                onChange={(e) => setPortion(Math.max(1, Math.min(2000, Number(e.target.value) || 0)))}
                className="w-28 rounded-xl bg-surface1 px-3 py-2 text-base ring-1 ring-fg/10 focus:outline-none focus:ring-accent/40"
              />
              {estKcal != null && (
                <span className="text-lg font-semibold text-fg">≈ {estKcal} kcal</span>
              )}
            </div>
          </div>

          <div className="flex gap-1.5 overflow-x-auto no-scrollbar">
            {MEALS.map((m) => (
              <button
                key={m}
                onClick={() => setMeal(m)}
                className={`shrink-0 rounded-full px-3 h-8 text-sm transition ${
                  meal === m ? 'bg-accent text-ivory' : 'bg-surface2 text-fg-muted'
                }`}
              >
                {MEAL_LABEL[m]}
              </button>
            ))}
          </div>

          {error && <p className="text-sm text-alert">{error}</p>}

          <div className="flex gap-2 pt-1">
            <Button variant="ghost" fullWidth onClick={() => { setError(null); setPhase(supported ? 'scanning' : 'manual'); if (supported) void startCamera(); }}>
              Scansiona un altro
            </Button>
            <Button variant="primary" fullWidth loading={busy} onClick={() => void confirmLog()}>
              Registra
            </Button>
          </div>
        </div>
      )}

      {phase === 'done' && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-ok">
            <Icon name="check" size={20} />
            <span className="font-semibold">Prodotto registrato</span>
          </div>
          <div className="flex gap-2">
            <Button
              variant="ghost"
              fullWidth
              onClick={() => { setProduct(null); setError(null); setPhase(supported ? 'scanning' : 'manual'); if (supported) void startCamera(); }}
            >
              Scansiona un altro
            </Button>
            <Button variant="primary" fullWidth onClick={close}>
              Fatto
            </Button>
          </div>
        </div>
      )}
    </BottomSheet>
  );
}

function Macro({ label, v }: { label: string; v: number | null }) {
  return (
    <div className="rounded-xl bg-surface1 py-2 ring-1 ring-fg/10">
      <div className="font-semibold text-fg">{v != null ? `${v}g` : '–'}</div>
      <div className="text-xs text-fg-muted">{label}</div>
    </div>
  );
}
