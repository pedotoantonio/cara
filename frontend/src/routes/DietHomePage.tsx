// DietHomePage — la home di /diet (CARA Nutrizione).
//
// Tre viste: Oggi (timeline pasti + acqua/caffè), Settimana (barre
// frequenze + resoconto), Catalogo (alimenti per status). Mobile-first,
// italiano. Disclaimer sempre visibile: NON è un dispositivo medico.

import { useState } from 'react';

import { DISCLAIMER } from '../api/diet';
import { DietEnergy } from '../components/diet/DietEnergy';
import { DietFoods } from '../components/diet/DietFoods';
import { DietToday } from '../components/diet/DietToday';
import { DietWeek } from '../components/diet/DietWeek';

type Tab = 'oggi' | 'energia' | 'settimana' | 'catalogo';

const TABS: { key: Tab; label: string }[] = [
  { key: 'oggi', label: 'Oggi' },
  { key: 'energia', label: 'Energia' },
  { key: 'settimana', label: 'Settimana' },
  { key: 'catalogo', label: 'Catalogo' },
];

export function DietHomePage() {
  const [tab, setTab] = useState<Tab>('oggi');

  return (
    <main className="min-h-dvh bg-bg text-fg px-4 pt-6 pb-24 max-w-2xl mx-auto">
      <header className="mb-4">
        <h1 className="text-3xl font-bold tracking-tight">Nutrizione</h1>
        <p className="text-fg-muted mt-1">
          Il tuo piano per frequenze settimanali e porzioni.
        </p>
      </header>

      {/* Disclaimer obbligatorio */}
      <div className="mb-4 rounded-2xl bg-amber-50 dark:bg-amber-500/10 ring-1 ring-amber-300/40 px-4 py-3 text-xs text-amber-800 dark:text-amber-200">
        {DISCLAIMER}
      </div>

      {/* Tabs */}
      <div className="flex gap-1.5 mb-5 overflow-x-auto no-scrollbar">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`shrink-0 rounded-full px-4 h-9 text-sm font-medium transition ${
              tab === t.key ? 'bg-accent text-ivory' : 'bg-surface2 text-fg-muted'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'oggi' && <DietToday />}
      {tab === 'energia' && <DietEnergy />}
      {tab === 'settimana' && <DietWeek />}
      {tab === 'catalogo' && <DietFoods />}
    </main>
  );
}
