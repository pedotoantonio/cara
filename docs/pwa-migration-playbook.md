# PWA v1 → v2 — Migration playbook

> Piano operativo per migrare la famiglia Pedoto dalla PWA v1 (su :8455)
> alla nuova PWA v2 (su :8456), senza interruzione del servizio e con
> rollback safety net.
>
> Stato: v2 deployata in parallelo a v1, ~80% feature parity. v1 resta
> intoccata come fallback. Migration **opt-in**, non forzata.

## Strategia: A/B graduale + opt-in banner

L'utente non viene **forzato** a migrare. Su v1 compare un banner
non-bloccante "Prova la nuova CARA" che linka a v2. Quando l'utente
si sente sicuro, installa v2 come PWA, disinstalla v1.

## Fase A — Banner v1 → v2 (questa PR)

**Obiettivo**: rendere v2 scopribile senza interrompere v1.

### A.1 Banner non-intrusivo

In `frontend/src/components/AppShell.tsx` (v1), aggiungere un piccolo
banner dismissible che appare nella top bar:

```tsx
{showV2Banner && (
  <div className="px-3 py-1.5 bg-emerald-500/10 border-b border-emerald-500/30 text-sm flex items-center justify-between">
    <span>
      ✨ <strong>Prova la nuova CARA</strong> — sfondo bianco, voce migliorata, più veloce.
    </span>
    <div className="flex gap-2">
      <a
        href="https://192.168.1.23:8456/"
        target="_blank"
        rel="noopener noreferrer"
        className="px-2 py-1 rounded bg-emerald-500 text-white text-xs"
      >
        Apri
      </a>
      <button
        onClick={dismissV2Banner}
        className="px-2 py-1 text-xs text-text-secondary"
      >
        Più tardi
      </button>
    </div>
  </div>
)}
```

Dismiss persistito in `localStorage` chiave `cara.v2_banner.dismissed`.
Re-mostra dopo 7 giorni (`cara.v2_banner.dismissed_at`).

### A.2 Admin feature flag

Setting nuovo `pwa_v2_banner_enabled: bool` in `admin_settings`,
default `true`. Admin può disabilitarlo da `/admin` se la migrazione
fallisce e non vuole mostrarlo più.

### A.3 Backend metric

Endpoint `POST /api/v1/migration/v2-banner-click` (auth user) che
incrementa contatore Redis `metrics:v2_banner_clicks:<user_id>` —
così l'admin vede quanti hanno effettivamente cliccato.

## Fase B — Famiglia testa v2 (1-2 settimane)

Antonio prova v2 quotidianamente. Marina, Sara, Matteo provano i
flussi principali (chat, task, spesa). Ilaria opzionale (test
accessibilità).

### Checklist test famiglia

Per ogni membro, almeno **3 sessioni** v2 in 1 settimana, coprendo:
- [ ] Login + permission onboarding (mic, push, geo, cam)
- [ ] Chat con voice + risposta TTS
- [ ] Aggiungere task con datepicker
- [ ] Aggiungere spesa
- [ ] Vedere meteo + calendario
- [ ] Vedere profilo persona
- [ ] Notifica push ricevuta su mobile
- [ ] Install PWA dal browser

Bug report → issue GitHub label `pwa-v2-migration`.

### Criteria di "pronta per rollover"

- 0 bug bloccanti rimasti
- ≥3 sessioni quotidiane per ogni membro famiglia per 7 giorni
  consecutivi senza problemi
- Bundle gz stabile <250 KB (oggi ~209 KB ✅)
- Lighthouse mobile PWA score ≥90 (verificare)

## Fase C — Rollover (1 giorno)

Quando la famiglia è confident:

1. **Disinstalla** PWA v1 dal telefono di ogni membro
2. **Installa** PWA v2 (`https://192.168.1.23:8456/`)
3. Verifica shortcuts Android funzionano (Voce / Task / Spesa / Ricordi)
4. v1 :8455 **resta acceso** come fallback per ~1 mese
5. Update CLAUDE.md "URL HTTPS" con :8456 come default

### Sostituzione icona PWA Android

Le PWA v1 e v2 hanno `start_url` diversi (`/?source=pwa` su v2 vs
`/` di v1) → Chrome le tratta come app diverse, niente conflitto.
Dovrebbe convivere senza problemi.

## Fase D — Decommissione v1 (1 mese dopo)

Quando v2 è in produzione famiglia da 1 mese senza issue:

1. Backup finale del codice v1 in branch `archive/v1-frontend`
2. Rimuovi service `frontend` da `docker-compose.yml`
3. Rimuovi server block `:8455` da `/opt/nginx-proxy/conf.d/default.conf`
4. Rimuovi port mapping `8455:8455` da nginx-proxy compose
5. `docker compose down frontend && docker volume prune`
6. Reinstrada `:8455` → redirect 301 verso `:8456` per qualsiasi
   link cached
7. Commit `chore(v1): decommission legacy frontend`

## Rollback safety

In ogni fase, v1 resta funzionante. Se v2 esplode in produzione:

1. Admin: disabilita banner v2 (admin_settings)
2. Famiglia: re-installa PWA v1
3. Tutto ritorna come prima senza data loss (entrambi condividono lo
   stesso backend + DB).

## Stato

- [x] v2 deployed su :8456 in parallelo a v1
- [x] v2 ~80% feature parity raggiunta
- [x] Bug critici risolti (note CRUD, ASR endpoint, voice loop convId)
- [ ] Banner v1 → v2 (questa PR)
- [ ] Test famiglia 1-2 settimane
- [ ] Rollover famiglia
- [ ] Decommissione v1 (1 mese dopo)
