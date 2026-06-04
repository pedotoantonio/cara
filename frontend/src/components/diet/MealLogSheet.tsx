// MealLogSheet — logga un pasto da testo libero o voce (STT Whisper).
//
// L'utente scrive (o detta) cosa ha mangiato; il backend lo interpreta
// con l'LLM locale e risponde con item, porzioni e avvisi (manca la
// verdura, ricordati la frutta, ecc.). Mobile-first, italiano.

import { useRef, useState } from 'react';

import { transcribeAudio } from '../../api/asr';
import {
  MEAL_LABEL,
  logMeal,
  type MealLogResult,
  type MealType,
} from '../../api/diet';
import { BottomSheet, Button, Badge, Icon } from '../../design';

const MEALS: MealType[] = ['colazione', 'spuntino', 'pranzo', 'cena'];

interface Props {
  open: boolean;
  onClose: () => void;
  defaultMeal?: MealType;
  onLogged?: (r: MealLogResult) => void;
}

export function MealLogSheet({ open, onClose, defaultMeal = 'cena', onLogged }: Props) {
  const [meal, setMeal] = useState<MealType>(defaultMeal);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MealLogResult | null>(null);

  const recRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);

  async function toggleRecord() {
    if (recording) {
      recRef.current?.stop();
      return;
    }
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream, { mimeType: 'audio/webm' });
      chunksRef.current = [];
      rec.ondataavailable = (e) => e.data.size && chunksRef.current.push(e.data);
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        if (blob.size < 1200) return;
        setBusy(true);
        try {
          const asr = await transcribeAudio(blob, 'it');
          if (asr.text) setText((prev) => (prev ? `${prev} ${asr.text}` : asr.text));
        } catch (e) {
          setError(e instanceof Error ? e.message : 'Errore trascrizione');
        } finally {
          setBusy(false);
        }
      };
      recRef.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      setError('Microfono non disponibile');
    }
  }

  async function submit() {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const r = await logMeal({ free_text: text.trim(), meal_type: meal });
      setResult(r);
      onLogged?.(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Errore salvataggio');
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setText('');
    setResult(null);
    setError(null);
  }

  return (
    <BottomSheet
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Logga un pasto"
      subtitle="Scrivi o detta cosa hai mangiato"
    >
      {result ? (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-ok">
            <Icon name="check" size={20} />
            <span className="font-semibold">{MEAL_LABEL[result.log.meal_type]} registrato</span>
          </div>

          {result.log.parsed_items.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {result.log.parsed_items.map((it, i) => (
                <Badge key={i} tone={it.protein_category ? 'accent' : 'neutral'}>
                  {it.food}
                  {it.portion_g ? ` · ${it.portion_g}g` : ''}
                </Badge>
              ))}
            </div>
          )}

          <div className="flex flex-wrap gap-2 text-xs">
            <Chip ok={result.carb_present} label="carboidrato" />
            <Chip ok={result.vegetable_present} label="verdura" />
            <Chip ok={result.fruit_present} label="frutta" />
          </div>

          {result.warnings.length > 0 && (
            <ul className="space-y-1.5">
              {result.warnings.map((w, i) => (
                <li key={i} className="flex gap-2 text-sm text-amber-700 dark:text-amber-300">
                  <span aria-hidden>⚠️</span>
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          )}

          <div className="flex gap-2 pt-2">
            <Button variant="ghost" fullWidth onClick={reset}>
              Logga un altro
            </Button>
            <Button
              variant="primary"
              fullWidth
              onClick={() => {
                reset();
                onClose();
              }}
            >
              Fatto
            </Button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
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

          <div className="relative">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={3}
              placeholder="es. insalata con tonno 250g e pane integrale"
              className="w-full rounded-2xl bg-surface1 ring-1 ring-fg/10 px-4 py-3 pr-12 text-base resize-none focus:outline-none focus:ring-accent/40"
            />
            <button
              onClick={toggleRecord}
              aria-label={recording ? 'Ferma' : 'Detta'}
              className={`absolute right-2 bottom-2 h-9 w-9 rounded-full grid place-items-center transition ${
                recording ? 'bg-alert text-ivory animate-pulse' : 'bg-surface2 text-fg-muted'
              }`}
            >
              <Icon name="mic" size={18} />
            </button>
          </div>

          {error && <p className="text-sm text-alert">{error}</p>}

          <Button
            variant="primary"
            fullWidth
            size="lg"
            loading={busy}
            disabled={!text.trim() || busy}
            onClick={submit}
          >
            Registra pasto
          </Button>
        </div>
      )}
    </BottomSheet>
  );
}

function Chip({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 h-6 ${
        ok ? 'bg-ok/15 text-ok' : 'bg-surface2 text-fg-muted'
      }`}
    >
      {ok ? '✓' : '–'} {label}
    </span>
  );
}
