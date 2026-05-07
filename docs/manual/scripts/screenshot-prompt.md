# Prompt — cattura screenshot per il manuale CARA

> Da dare a Claude with browser access (Claude in Chrome) o a un altro
> agente che può controllare un browser. Self-contained — non
> richiede contesto aggiuntivo.

---

## Briefing

Sei un agente con accesso al browser. Devi catturare ~25 screenshot
dell'applicazione **CARA** (un'AI di casa self-hosted) per illustrare
il manuale del programmatore.

**URL applicazione**: `https://192.168.1.23:8455/`

**Credenziali admin**:
- Email: `pedotoa@gmail.com`
- Password: `caracasa2026`

**Lingua UI**: italiano.

**Salva i file in**: `~/Downloads/cara-manual-screenshots/` (o cartella
equivalente accessibile). Per ogni screenshot ti dico il **nome esatto
da usare**.

**Risoluzione consigliata**:
- Pagine desktop: viewport 1280×800, screenshot della viewport (non
  full-page).
- Pagina /pair: viewport 390×844 (mobile).

**Tema**: scegli il tema che è il default al login (probabilmente
night mode). Niente di critico, basta che sia coerente fra tutti gli
screenshot.

---

## Setup iniziale

1. Apri `https://192.168.1.23:8455/` in una scheda nuova.
2. Se compare un warning di certificato SSL, clicca "Avanzate" →
   "Procedi a 192.168.1.23". Il sito usa cert mkcert locale.
3. Vedi la pagina di login. **Cattura screenshot** prima di loggarti
   → `00-login.png`
4. Compila email + password con le credenziali sopra. Click "Accedi".
5. Aspetta 5 secondi che la home page carichi.

---

## Catalogo degli screenshot

Per ogni voce: navigi all'URL indicato, aspetti 2-3 secondi, catturi.

### Pagine utente principali

| Filename | URL | Note |
|---|---|---|
| `01-home.png` | `https://192.168.1.23:8455/` | Home (dovrebbe avere greeting + voce) |
| `06-chat-empty.png` | `https://192.168.1.23:8455/chat` | Pagina chat vuota |
| `08-memoria.png` | `https://192.168.1.23:8455/me/memory` | Lista fact memoria |
| `10-wallet.png` | `https://192.168.1.23:8455/wallet` | Wallet con widget |
| `16-integrazioni.png` | `https://192.168.1.23:8455/me/integrazioni` | Connect Google etc |
| `16-proposte.png` | `https://192.168.1.23:8455/me/proposte` | Proposte da email |
| `28-tasks.png` | `https://192.168.1.23:8455/tasks` | Lista task |
| `28-shopping.png` | `https://192.168.1.23:8455/shopping` | Lista spesa |
| `28-notes.png` | `https://192.168.1.23:8455/notes` | Note rapide |
| `05-settings.png` | `https://192.168.1.23:8455/settings` | Pagina impostazioni utente |

### Admin pages

| Filename | URL | Note |
|---|---|---|
| `20-admin.png` | `https://192.168.1.23:8455/admin` | Dashboard admin (settings + flag) |
| `20-admin-skills.png` | `https://192.168.1.23:8455/admin/skills` | Skill Factory list |
| `20-admin-memory.png` | `https://192.168.1.23:8455/admin/memory` | Roster utenti + counts fact |
| `20-admin-smart-home.png` | `https://192.168.1.23:8455/admin/smart-home` | Entities HA + scenes |
| `20-admin-proactivity.png` | `https://192.168.1.23:8455/admin/proactivity` | Lista 10 rules |
| `20-admin-devices.png` | `https://192.168.1.23:8455/admin/devices` | Lista device paired |
| `20-admin-diagnostics.png` | `https://192.168.1.23:8455/admin/diagnostics` | Health check sistema |

### Setup wizard (8 step)

Prima resetta il wizard chiamando l'endpoint di reset:

1. Apri DevTools (F12) → Console
2. Esegui questo codice JavaScript per resettare il wizard:

```javascript
fetch('/api/v1/setup/reset', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${localStorage.getItem('cara.access_token')}`
  }
}).then(r => r.json()).then(console.log);
```

3. Naviga a `https://192.168.1.23:8455/admin/setup`
4. Catturi gli 8 step uno per volta. Per ogni step:
   - Cattura PRIMA di compilare i campi (mostra il form vuoto)
   - Click "Avanti →" o "Salta" per passare al successivo
   - Aspetta 1 secondo per il transizione

| Filename | Step | Azione per arrivare |
|---|---|---|
| `18-2-step-1-admin.png` | 1. Amministratore | (parte da qui) |
| `18-2-step-2-tls.png` | 2. Sicurezza | Click "Salta" su step 1 (admin esiste già) |
| `18-2-step-3-family.png` | 3. Famiglia | Click "Salta" su step 2 |
| `18-2-step-4-voice.png` | 4. Voce | Click "Avanti →" su step 3 (vuoto) |
| `18-2-step-5-llm.png` | 5. Intelligenza | Click "Avanti →" su step 4 |
| `18-2-step-6-integrations.png` | 6. Integrazioni | Click "Avanti →" su step 5 |
| `18-2-step-7-google-cloud.png` | 7. Google e Cloud | Click "Avanti →" su step 6 |
| `18-2-step-8-feature-flags.png` | 8. Privacy | Click "Avanti →" su step 7 |

### Pagina /pair (mobile)

Apri una **nuova scheda incognito** (così non sei loggato), poi:

1. Cambia viewport a 390×844 (Chrome DevTools → Toggle device toolbar
   → iPhone 12)
2. Vai a `https://192.168.1.23:8455/pair`
3. Aspetta 3 secondi che il codice 6 cifre appaia
4. **Cattura** → `15-3-pair-page.png`

### Debug overlay

1. Torna alla scheda loggata.
2. Vai a `https://192.168.1.23:8455/chat`.
3. Premi `Ctrl+Shift+D` (o `Cmd+Shift+D` su Mac). Si apre un pannello
   debug.
4. Manda un messaggio breve (es. "ciao") per generare eventi.
5. Aspetta che il pannello mostri 5-6 righe di eventi.
6. **Cattura** → `21-3-debug-overlay.png`

### PWA install banner (se possibile)

1. Vai a `https://192.168.1.23:8455/settings`.
2. Scorri in fondo alla pagina, sezione "Informazioni".
3. Click pulsante "Installa CARA come app".
4. Aspetta che il banner appaia in basso a destra.
5. **Cattura** → `19-3-install-banner.png`

### Cert lock chiuso

1. Click sull'icona lucchetto a sinistra dell'URL (Chrome / Edge).
2. Si apre un popup "Connessione sicura — certificato valido".
3. **Cattura** della pagina con il popup aperto → `19-3-cert-lock.png`

---

## Convenzioni di anonimizzazione

- **Email**: `pedotoa@gmail.com` è OK (è documentata pubblicamente
  in CLAUDE.md). Se vedi altre email reali della famiglia, blur o
  sostituisci con `xxxxxxxx@xxx.xxx`.
- **Token / API key / VAPID key visibili** nei campi password: blur
  o riempi con `xxxxxxxx`.
- **IP esterni** (es. quello pubblico WireGuard): mask con
  `xxx.xxx.xxx.xxx`. L'IP `192.168.1.23` è OK (LAN documentata).
- **Niente cursore mouse** negli screenshot (sposta cursore fuori
  prima di catturare).
- **Niente bookmark bar Chrome** né altre cornici browser visibili
  (Ctrl+Shift+B per nascondere).

---

## Output finale

Quando hai finito:

1. Genera un report in `cattura-report.txt` nella stessa cartella, con:
   ```
   filename | status (ok/skipped/failed) | nota
   00-login.png | ok |
   18-2-step-1-admin.png | ok |
   18-2-step-2-tls.png | failed | wizard non parte da admin
   ...
   ```

2. Assicurati che ogni PNG sia ≤ 2MB. Se necessario passali per
   `pngquant --quality=80-95`.

3. Crea uno ZIP `cara-manual-screenshots-YYYYMMDD.zip` contenente
   tutti i PNG + il report.

---

## Cosa fare se qualcosa non funziona

- **Login fallisce con "Failed to fetch"**: il browser non si fida del
  cert. Apri `http://192.168.1.23/cara-ca.crt`, scarica e installa la
  CA come "Trusted Root". Poi riavvia il browser.
- **Pagina admin redirect a `/chat`**: l'utente che hai loggato non è
  admin. Verifica le credenziali.
- **`/pair` mostra errore di connessione**: il backend Redis è giù —
  segnala lo screenshot come "skipped".
- **Pagina vuota / errore JS**: aspetta 5 secondi extra, ricarica.

Se uno screenshot specifico è impossibile, **non bloccare** la
sessione — passa al successivo e segnalo nel report.

---

## Tempo stimato

~30 minuti per tutta la catena, di cui 10 min di setup (apertura,
login, install CA se necessario) e 20 min di cattura sequenziale.

Buon lavoro.
