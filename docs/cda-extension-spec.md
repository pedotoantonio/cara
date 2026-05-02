# CARA — Estensione v0.6: Content Discovery Agent (CDA)

> **Stato**: specifica · da implementare
> **Versione**: 0.6 (su CARA v0.5 attuale)
> **Stima**: 16–19 giorni di sviluppo distribuiti su 5 fasi
> **Obiettivo**: trasformare la gestione di contenuti media (radio, news, video, podcast,
> immagini, documenti) da pagine con catalogo predefinito a un agente intelligente
> che cerca, valida, riproduce e impara dai contenuti del web.

---

## 1. Sommario esecutivo

Il **Content Discovery Agent (CDA)** è un sotto-sistema CARA che riceve in input
una richiesta in linguaggio naturale, classifica l'intento e il formato target,
cerca il contenuto su internet, lo verifica, lo riproduce con il player nativo
del browser, e accumula esperienza per migliorare nel tempo.

L'utente non vede una "pagina Radio" e una "pagina News". Vede CARA che, su
richiesta vocale o scritta, **mette su qualunque cosa, da qualunque fonte, senza
configurazione preventiva**. La seconda volta che la stessa cosa viene chiesta,
la latenza collassa perché tutto è già nella knowledge base personale.

Le pagine `Radio` e `News` esistenti non vengono cancellate: vengono trasformate
da cataloghi statici a **viste sulla cronologia di scoperta** (la KB del CDA).
Non c'è perdita di funzionalità per chi era abituato a sfogliare; c'è guadagno
per chi vuole chiedere "metti Radio Capital" senza che Capital sia mai stata
preconfigurata.

### Cosa cambia

- **Rimosso**: liste hardcoded di stazioni e feed RSS predefiniti come unica
  fonte di catalogo.
- **Aggiunto**: pipeline intent → search → discovery → verification → playback
  → learning per ogni richiesta che non si risolve nel catalogo locale.
- **Trasformato**: pagine Radio/News diventano viste della KB personale per
  utente, alimentate dalle scoperte fatte (manualmente o tramite voce).

### Cosa NON cambia

- Tool calling esistente di CARA (`[TOOL: play_radio …]`, `[TOOL: get_news …]`):
  resta, e diventa il punto d'ingresso al CDA quando la richiesta non si
  risolve sui dati locali.
- Pagine UI come oggetti di prima classe — restano, riempite di contenuto
  diverso.
- Privacy first: ogni fetch web parte dal NanoPC, mai dal browser dell'utente.

---

## 2. Filosofia e principi cardine

1. **Niente cataloghi predefiniti rigidi.** Il sistema parte vuoto e si popola
   on-demand. Le 8 stazioni e gli 11 feed RSS attuali entrano in `cda_content_items`
   come "scoperte iniziali della famiglia" — non sono un sotto-sistema separato.

2. **Riconoscimento intent-then-format.** Capire prima cosa l'utente vuole
   (intent), poi quale formato consegna meglio quel valore (audio stream, video
   embed, articolo testuale, podcast, immagine, documento).

3. **Riproduzione nativa, non re-encoding.** CARA trova URL e li passa al player
   nativo del browser. HTML5 `<audio>` per stream, `<video>` per file diretti,
   `<iframe>` per embed sicuri (YouTube), `<img>` per immagini, `<iframe>` o
   download per PDF, lettura TTS via Piper per articoli.

4. **Apprendimento per esperienza.** Ogni richiesta soddisfatta diventa
   conoscenza. Confidence score evolve dai segnali comportamentali (durata
   ascolto, interruzioni rapide). Verifica notturna degli URL salvati.

5. **Trasparenza della fonte.** Ogni player mostra dominio + favicon + link
   "apri originale". Niente fake-ownership di contenuti altrui.

6. **Privacy del fetch.** User-agent neutro, no cookie persistenti, no account
   esterni richiesti. Lo storico ricerche per utente è privato.

---

## 3. Architettura tecnica

### 3.1 Struttura del modulo

```
backend/cara/cda/
├── __init__.py
├── orchestrator.py           # entrypoint async pipeline
├── intent.py                 # intent + format classifier (LLM tool-calling)
├── search/
│   ├── __init__.py
│   ├── base.py               # SearchProvider abstract base
│   ├── searxng.py            # SearXNG self-hosted (opzionale)
│   ├── brave.py              # Brave Search API
│   └── ddg.py                # DuckDuckGo HTML parsing fallback
├── discovery/
│   ├── __init__.py
│   ├── audio_stream.py       # icecast / shoutcast / m3u / m3u8 / pls / direct mp3
│   ├── video.py              # YouTube embed / yt-dlp fallback / direct mp4
│   ├── article.py            # readability + trafilatura extraction
│   ├── podcast.py            # RSS feed → episodi → MP3 URL
│   ├── image.py              # image search + MIME validation
│   └── document.py           # PDF / DOCX trovati via filetype:
├── verification/
│   ├── __init__.py
│   ├── stream_validator.py   # HEAD + first-bytes-flow check
│   ├── url_validator.py      # generic health (HTTP, content-length, mime)
│   └── content_classifier.py # mime sniffing + (per profili minori) safety check
├── memory/
│   ├── __init__.py
│   ├── content_kb.py         # CRUD su cda_content_items
│   ├── stream_health.py      # success/failure counter, confidence
│   └── user_preferences.py   # inferenza pattern temporali e ranking
├── playback/                  # solo per il caso "audio backend-side" futuro
│   └── ...
└── tasks/
    ├── refresh_streams.py    # job notturno: re-verifica URL salvati
    └── cleanup.py            # rimuovi item morti, deduplica
```

### 3.2 Pipeline a 7 step

```
[Richiesta utente: "fammi ascoltare RTL 102.5"]
      │
      ▼
1. INTENT CLASSIFIER         output: { intent, target_type, query, action, modifiers }
      │
      ▼
2. KB LOOKUP                 → trovato?  ──Yes──→ STEP 6 (skip search/discovery/verify)
      │  No
      ▼
3. WEB SEARCH                provider chain (SearXNG > Brave > DDG); query rewriting
      │
      ▼
4. DISCOVERY (per type)      audio_stream.py / video.py / article.py / ...
      │
      ▼
5. VERIFICATION              HEAD, MIME, prime byte di stream, sicurezza profilo
      │
      ▼
6. PLAYBACK                  payload SSE/JSON al frontend → player nativo
      │
      ▼
7. LEARNING                  upsert KB, increment counters, infer preferences
```

### 3.3 Sostituzione dei tool esistenti

Oggi:

```
[TOOL: play_radio station="rai-radio-1"]
[TOOL: get_news category="mondo"]
```

Con CDA:

```
[TOOL: play_radio query="RAI Radio 1"]               # query libera
[TOOL: get_news query="notizie del mondo oggi"]
[TOOL: play_video query="trailer Avatar 3"]          # nuovo
[TOOL: read_article query="editoriale del Corriere"] # nuovo
[TOOL: play_podcast query="ultima puntata Caterpillar"] # nuovo
```

Il backend del tool router non è più bound al catalogo: passa la query
all'orchestrator CDA, e l'orchestrator decide se la query risolve a un
content_item esistente o se serve una nuova ricerca.

---

## 4. Tipi di contenuto e modalità di riproduzione

### 4.1 Audio streaming (radio, podcast)

- **Discovery query**: `<nome stazione> live streaming url`,
  `<nome stazione> stream m3u`, `<nome>+icecast`.
- **Pattern di estrazione**: `.m3u`, `.m3u8` (HLS), `.pls`, `audio/mpeg`,
  `audio/aac`, redirect 302 → file media.
- **Verification**: HEAD ritorna 200, `content-type` audio*, primi 32 KB
  scaricati senza errore in <2 s.
- **Playback frontend**: `<MediaPlayer kind="audio">` con HTML5 `<audio>` +
  HLS.js per `.m3u8`. Visualizer onde sopra il volto di CARA, controlli
  minimal (play / pause / volume / stop / "apri originale").

### 4.2 Video

- **Default sicuro**: YouTube embed iframe `https://www.youtube.com/embed/<id>`.
- **Fallback**: `yt-dlp -f best -g <url>` per video su domini non-YouTube
  (es. RaiPlay), poi `<video src=...>` o HLS.js.
- **Mai** fare download e ridistribuzione; solo streaming on-demand.
- **Modalità "audio only"**: video con `style.display=none` per uso in cucina.
- **Playback frontend**: `<MediaPlayer kind="video">` fullscreen optional,
  controlli nativi, sottotitoli se disponibili, link al canale originale.

### 4.3 Articoli (news, blog)

- **Discovery query**: argomento + filtro temporale (`time_filter=today` →
  query con `oggi`).
- **Estrazione**: `trafilatura.extract(html)` (in fallback `readability-lxml`)
  → titolo, autore, data, contenuto pulito, immagine cover.
- **Validazione**: contenuto > 200 caratteri, lingua = preferenza utente,
  dominio non in blacklist.
- **Modalità**: 
  - Lettura ad alta voce via Piper (default)
  - Vista "reader mode" inline (`<ArticleReader>`)
  - Riassunto LLM locale (`[TOOL: read_article action="summarize"]`)
- **Highlight paragrafo letto**: cursore karaoke sincronizzato con boundary
  events (riusa l'event bus già esistente per Piper).

### 4.4 Podcast

- **Discovery**: feed RSS via search → `feedparser.parse(feed_url)` → lista
  episodi → match per "ultima puntata" / "puntata su X" / data.
- **Riproduzione**: episodio.enclosures[0].url → MP3 → `<MediaPlayer kind="audio">`.
- **Cache locale**: ultimi 50 episodi metadata per show, per supportare
  domande tipo "cosa ho appena ascoltato di Caterpillar".

### 4.5 Immagini

- **Discovery**: image search via Brave/DDG.
- **Verification**: `content-type: image/*`, dimensioni minime 200×200.
- **Playback**: `<ImageGallery>` con swipe, didascalia, link sorgente, opzione
  "salva nella memoria di famiglia".

### 4.6 Documenti

- **Discovery**: search con `filetype:pdf` (o docx/xlsx/...).
- **Playback**: `<iframe>` PDF viewer nativo del browser, link download.
- **Niente OCR** per ora — riusare `cara/services/files.py` se l'utente
  carica il documento dopo averlo trovato.

---

## 5. Intent classifier

### 5.1 Decisione architetturale

**NON usiamo un classificatore separato.** Il LLM esistente (Qwen2.5-1.5B su
NPU) ha già il system prompt con tool calling. Aggiungere un secondo passaggio
LLM solo per produrre JSON costerebbe **~3.5 s** sul modello attuale (TTFT 0.2 s
+ ~30 token a 9 tok/s). Inaccettabile.

**Soluzione**: estendere il tool catalog del system prompt con i nuovi tool del
CDA. Il LLM produce direttamente la chiamata strutturata; il backend la passa
all'orchestrator. Un upgrade futuro a 3B+ può aggiungere un passaggio di
classificazione raffinata (intent + ambiguity score).

### 5.2 Tool del CDA nel system prompt

```
[TOOL: play_radio query="<libera>"]                      # qualsiasi radio
[TOOL: play_video query="<libera>" [audio_only=true]]     # YouTube/RaiPlay/...
[TOOL: read_article query="<libera>" [action=read|show|summarize]]
[TOOL: play_podcast query="<libera>"]
[TOOL: show_image query="<libera>"]
[TOOL: find_document query="<libera>" [filetype=pdf]]
```

Quando la richiesta è ambigua (es. "metti la musica" senza specifica),
il LLM emette il tool con `query` vuota e CARA chiede chiarimento.

### 5.3 Disambiguazione lato orchestrator

Una richiesta `play_radio query=""` → prima di cercare, l'orchestrator:
1. Lookup `cda_user_preferences` per `preferred_radio` di questo utente.
2. Se nessuna preferenza, lookup ultima radio ascoltata da questo utente.
3. Se neanche quella, risposta conversazionale: "Quale radio? Le tue solite
   sono <top 3>".

---

## 6. Schema database

### 6.1 Nuove tabelle

```sql
-- Knowledge base dei contenuti scoperti
CREATE TABLE cda_content_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    query_normalized TEXT NOT NULL,           -- "rtl 102.5", lowercased trimmed
    content_type TEXT NOT NULL,               -- audio_stream | video | article | podcast | image | document
    url TEXT NOT NULL,
    title TEXT,
    source_domain TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,       -- bitrate, mime, lingua, durata, ecc.

    confidence_score REAL DEFAULT 0.5,        -- 0.0–1.0
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0,
    last_verified_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,

    discovered_via TEXT,                      -- search:brave | feed_rss | user_provided | seed
    discovered_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (query_normalized, url)
);
CREATE INDEX idx_cda_query_active ON cda_content_items (query_normalized) WHERE is_active;
CREATE INDEX idx_cda_type_query ON cda_content_items (content_type, query_normalized);

-- Log delle richieste (per analytics, debugging, inferenza preferenze)
CREATE TABLE cda_query_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    raw_query TEXT NOT NULL,
    normalized_query TEXT,
    intent JSONB,                             -- output dell'intent (tool args)
    resolved_content_id UUID REFERENCES cda_content_items(id) ON DELETE SET NULL,
    outcome TEXT,                             -- success | no_results | playback_failed | blocked
    duration_ms INTEGER,                      -- dalla query alla riproduzione
    cached BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_cda_log_user_time ON cda_query_log (user_id, created_at DESC);

-- Preferenze inferite per utente
CREATE TABLE cda_user_preferences (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    preference_type TEXT NOT NULL,            -- preferred_radio | preferred_news_source | ...
    preference_value TEXT NOT NULL,
    confidence REAL NOT NULL,
    sample_count INTEGER NOT NULL DEFAULT 0,
    last_observed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, preference_type, preference_value)
);

-- Score affidabilità domini (popolato all'avvio + adattivo per utente)
CREATE TABLE cda_domain_trust (
    domain TEXT PRIMARY KEY,
    category TEXT,                            -- news_it | news_intl | radio_it | radio_intl | tutorial | ...
    base_score REAL NOT NULL DEFAULT 0.5,
    notes TEXT
);
```

### 6.2 Migrazione delle scoperte iniziali

Le 8 stazioni hardcoded di `cara/services/radio.py` e gli 11 feed RSS di
`cara/services/news.py` vengono importati nella prima `alembic upgrade` come
righe `cda_content_items` con `discovered_via='seed'`, `confidence_score=0.9`.

Da quel momento, codice e UI possono leggere il "catalogo storico" dalla KB
invece che dalle costanti Python — il file `radio.py` e `news.py` resta come
dato statico solo per il bootstrap iniziale (idempotent).

### 6.3 Domain trust seed

```python
DEFAULT_DOMAINS = {
    # news IT
    "rai.it": ("news_it", 1.0),
    "ansa.it": ("news_it", 1.0),
    "repubblica.it": ("news_it", 0.95),
    "corriere.it": ("news_it", 0.95),
    "ilsole24ore.com": ("news_it", 0.9),
    # news intl
    "bbc.com": ("news_intl", 1.0),
    "reuters.com": ("news_intl", 1.0),
    # radio IT
    "rtl.it": ("radio_it", 0.95),
    "radiodeejay.it": ("radio_it", 0.9),
    "virginradio.it": ("radio_it", 0.9),
    "radio105.net": ("radio_it", 0.9),
    "rds.it": ("radio_it", 0.9),
    "kissskiss.it": ("radio_it", 0.85),
    "icestreaming.rai.it": ("radio_it", 1.0),
    # video
    "youtube.com": ("video", 0.9),
    "raiplay.it": ("video", 0.95),
    "vimeo.com": ("video", 0.85),
    # tutorial / Q&A
    "stackoverflow.com": ("tutorial", 0.95),
    "wikihow.com": ("tutorial", 0.7),
    "github.com": ("tutorial", 0.95),
}
```

---

## 7. Sistema di apprendimento

### 7.1 Segnali di successo / fallimento

Il frontend chiama nuovi endpoint dopo ogni interazione:

- `POST /api/v1/cda/feedback/started` — quando il player inizia a emettere
  audio/video. Avvia un timer.
- `POST /api/v1/cda/feedback/stopped` — quando finisce o viene fermato.
  Payload: `{content_id, played_seconds, reason}` con `reason` in
  `{user_stop, ended, error, switched}`.
- `POST /api/v1/cda/feedback/regenerated` — quando l'utente dice "no, l'altra".

Logica:

```
played_seconds >= 5     → success_count += 1
played_seconds < 2 AND  → failure_count += 1
  reason == user_stop
ended naturally         → success_count += 1, confidence boost piccolo
error                   → failure_count += 2, last_verified_at = NOW()
                          se failure_count - success_count >= 3 → is_active = FALSE
```

### 7.2 Inferenza preferenze utente

Job giornaliero su `cda_query_log`:

- Per ogni `(user_id, content_type)`: se gli ultimi 5 successi vengono dallo
  stesso `source_domain` → `cda_user_preferences[(user, preferred_<type>_source)]`
  = quel dominio, `confidence = 5/5 * decay_factor`.
- Confidence si aggiorna esponenzialmente: nuova osservazione contribuisce
  per 0.3, vecchio valore pesa 0.7.
- Mai applicare una preferenza con `confidence < 0.7`. Sempre log esplicito
  in audit_log: "applicato preferenza X per utente Y".

### 7.3 Verifica notturna

Job alle 03:00 (Celery beat):

```python
@app.task(name="cda.verify_streams")
async def verify_streams():
    items = await content_kb.list_active_recently_used(days=30)
    for item in items:
        if item.content_type in ("audio_stream", "video"):
            ok = await stream_validator.check(item.url)
        else:
            ok = await url_validator.check(item.url)
        if ok:
            item.last_verified_at = now()
        else:
            item.failure_count += 1
            if item.failure_count - item.success_count >= 3:
                item.is_active = False
                # programma re-discovery alla prossima richiesta
```

---

## 8. Sicurezza e policy

### 8.1 Whitelist / blacklist domini

Nuove righe in `admin_settings`:
- `cda_domain_whitelist`: lista di domini permessi (None = tutto permesso
  tranne blacklist). Per profili minori, l'admin può imporre whitelist.
- `cda_domain_blacklist`: lista globale.
- `cda_safe_search_for_minors`: bool, forza filtri SafeSearch su Brave/DDG
  per `User.role in {child, teen}`.

### 8.2 Content classifier per minori

Per `User.role == 'child'`, ogni contenuto trovato passa per:

1. Domain whitelist enforcement. Se domain non in whitelist → reject.
2. Per articoli/video: chiamata al LLM locale con prompt:
   `"Il seguente contenuto è adatto a un bambino di 8-12 anni? Rispondi SI/NO + motivo breve."`
   Cache per URL → outcome (1 settimana).
3. Reject silenzioso → CARA dice "non ho trovato qualcosa di adatto".

Per `User.role == 'teen'`: solo step 1+SafeSearch. Niente step 2.

### 8.3 Rate limiting

- Per utente: max 30 ricerche/min, 500/giorno.
- Per provider esterno: rispetto delle quote (Brave free = 2k/mese).
- Cache aggressiva: identici `(user_id, normalized_query)` entro 60 s ritornano
  il risultato della prima.

### 8.4 Audit log

Estendere `audit_log` esistente con nuovi `action`:
- `cda.search` — query effettuata
- `cda.playback.started` / `cda.playback.error`
- `cda.content.blocked` — minore + dominio bloccato (per review parentale)
- `cda.preference.inferred` — applicata preferenza salvata

Vista admin: `Pannello admin → Cronologia → Filtra "cda.*"`.

### 8.5 Privacy del fetch

- User-agent fisso: `CARA/0.6 (private home assistant; +https://example.local)`
- Mai cookie persistenti — `httpx.AsyncClient(cookies=None)` per ogni request.
- Mai login a servizi esterni dal NanoPC. YouTube via embed senza account.
- Storia ricerche: visibile solo all'utente che l'ha fatta + admin in vista
  aggregata anonimizzata.

### 8.6 Copyright

- Solo streaming on-demand, mai bulk download.
- Per video: preferire iframe ufficiale a stream estratto.
- `yt-dlp` come tool è legale (disponibile in repository Debian); estrarre
  stream YouTube viola i ToS ma non la legge USA/EU per uso personale —
  accettato per uso domestico, da disabilitare se CARA viene un giorno
  distribuita commercialmente. Toggle admin: `cda_ytdlp_youtube_enabled`
  (default: `false` per essere conservativi).

---

## 9. Cosa cambia nell'UI

### 9.1 Componenti nuovi (universali)

| Componente | Uso | Note |
|---|---|---|
| `<MediaPlayer kind="audio">` | radio + podcast | HLS.js per `.m3u8` |
| `<MediaPlayer kind="video">` | YouTube embed o HTML5 video | fullscreen opt |
| `<MediaPlayer kind="audio_only">` | traccia audio di un video | flag dell'audio kind |
| `<ArticleReader>` | reader mode pulito | TTS opzionale |
| `<ImageGallery>` | swipe immagini | mostra fonte |
| `<DocumentViewer>` | iframe PDF | download bottone |
| `<DiscoveryStatus>` | stato pipeline (sta cercando…) | sincronizzato col volto Edo: `thinking` → `happy/confused` |
| `<NowPlayingBar>` | barra fissa "in riproduzione" | replace `<RadioMiniBar>` esistente, generalizza |

### 9.2 Pagine cambiate

- **`RadioPage`** → diventa **"Le mie radio"**: lista derivata da
  `cda_content_items WHERE content_type='audio_stream'`, ordinata per
  `success_count` desc. Mostra le 8 stazioni seed + tutte le scoperte.
  Bottone "+ aggiungi" apre dialog "cerca una stazione".

- **`NewsPage`** → diventa **"Le mie news"**: idem, derivata da KB. Le
  6 categorie originali restano come chip filter (categorie ora sono
  metadata `cda_content_items.metadata.category`).

### 9.3 Pagina nuova

- **`/discoveries`** — vista cronologica unificata: tutto ciò che CARA ha
  trovato per me (radio, news, video, podcast). Filtri per tipo + per data.
  Tap su una entry = re-play.

### 9.4 Wake word integration

Il wake word "CARA" già attivo (Step 56) acquisisce nuove frasi:

- "CARA, accendi la radio"  → tool play_radio (eventualmente con disambiguazione)
- "CARA, le notizie"        → tool read_article preferred_news_source
- "CARA, fammi vedere…"     → tool play_video
- "CARA, basta"             → stop player attivo (qualsiasi tipo)

---

## 10. API REST

### 10.1 Nuovi endpoint

```
POST  /api/v1/cda/discover              # frontend invoca dopo che il LLM emette tool CDA
GET   /api/v1/cda/items                 # lista KB per utente, filtri (type, query, limit)
GET   /api/v1/cda/items/{id}            # dettaglio singolo
DELETE /api/v1/cda/items/{id}           # rimuovi dalla mia KB

POST  /api/v1/cda/feedback/started      # { content_id }
POST  /api/v1/cda/feedback/stopped      # { content_id, played_seconds, reason }
POST  /api/v1/cda/feedback/regenerated  # { content_id }

GET   /api/v1/cda/preferences           # mie preferenze inferite

# Admin only:
GET   /api/v1/admin/cda/items           # vista globale (tutti gli utenti)
PATCH /api/v1/admin/cda/items/{id}      # forza is_active, ban dominio
GET   /api/v1/admin/cda/blocked         # contenuti bloccati per minori (review)
```

### 10.2 Schema della response `discover`

```json
{
  "kind": "audio_stream",
  "url": "https://stream2.rtl.it:8000/tunein.mp3",
  "title": "RTL 102.5 Live",
  "source_domain": "rtl.it",
  "metadata": {
    "bitrate_kbps": 128,
    "codec": "mp3",
    "language": "it"
  },
  "confidence": 0.95,
  "cached": false,
  "duration_ms_to_resolve": 2840,
  "content_id": "uuid-...",
  "fallbacks": [
    { "url": "...", "title": "RTL 102.5 (alt)" }
  ]
}
```

Il frontend usa `kind` per scegliere il componente di playback giusto.
`fallbacks` (max 3) sono offerti se l'utente preme "no, l'altra".

---

## 11. Roadmap implementativa

### Fase A — Fondazioni e migrazione (3-4 giorni)

- Creare modulo `backend/cara/cda/` con scaffolding e interfacce astratte.
- Schema DB: `cda_content_items`, `cda_query_log`, `cda_user_preferences`,
  `cda_domain_trust`. Migration Alembic.
- **Migrazione seed**: in `alembic upgrade`, importare le 8 radio + 11 feed
  esistenti come `discovered_via='seed'`, confidence 0.9.
- Endpoint `GET /api/v1/cda/items` (lista KB utente).
- Componenti frontend universali: `<MediaPlayer>` (audio + video), `<ArticleReader>`.
- **Feature flag** `cda_enabled` in admin_settings (default false → CDA non
  intercetta, le pagine vecchie funzionano come prima). Quando true: i tool
  esistenti delegano all'orchestrator.

### Fase B — CDA core: audio_stream + article (5-6 giorni)

- `orchestrator.py` con pipeline a 7 step.
- Search providers: SearXNG (preferito, self-hosted) + Brave + DDG fallback.
  Setup container SearXNG su `proxy-net`.
- Discovery `audio_stream.py`: parsing m3u/m3u8/pls, regex su HTML per pattern
  noti, redirect chasing.
- Discovery `article.py`: `trafilatura` + `readability-lxml` come fallback.
- Verification: `stream_validator.py` (HEAD + first-bytes), `url_validator.py`.
- Endpoint `POST /api/v1/cda/discover`.
- Tool nuovi nel system prompt LLM: `play_radio query="..."` (free form),
  `read_article query="..."`.
- Wiring frontend: `<DiscoveryStatus>` con stati visivi sincronizzati con il
  volto Edo (energy=thinking → speaking → happy / confused).
- Smoke test E2E: "Cara fammi sentire Radio Capital" funziona da zero
  (Capital non è nei seed) in <5 s.

### Fase C — Estensione formati (3-4 giorni)

- Discovery `video.py` con YouTube embed default + `yt-dlp` fallback (toggle
  admin `cda_ytdlp_youtube_enabled`).
- Discovery `podcast.py` con `feedparser`.
- Discovery `image.py`, `document.py`.
- Refinement player: HLS.js, modalità audio_only, fullscreen toggle.
- Tool nuovi: `play_video`, `play_podcast`, `show_image`, `find_document`.

### Fase D — Apprendimento e UX (3 giorni)

- Endpoint feedback (`started`, `stopped`, `regenerated`) integrati al player.
- Job Celery `verify_streams` notturno + `infer_preferences` giornaliero.
- Pagina `/discoveries` (cronologia unificata).
- Trasformazione `RadioPage` e `NewsPage` in viste della KB.
- `<NowPlayingBar>` universale che sostituisce `<RadioMiniBar>`.

### Fase E — Sicurezza e policy (2 giorni)

- `cda_domain_whitelist` / `cda_domain_blacklist` in admin_settings.
- Content classifier per profili `child` (LLM safety check).
- SafeSearch forzato per `child`/`teen`.
- Rate limiting (Redis token bucket per `(user_id, minute)`).
- Audit_log esteso con `cda.*` action.
- Pannello admin: nuova sezione "Content Discovery" con whitelist editor,
  vista contenuti bloccati per review.

**Totale**: 16-19 giorni effettivi.

---

## 12. Strategia di migrazione

### 12.1 Coexistenza, non big bang

L'implementazione attuale (`RadioPage`, `NewsPage`, tool `play_radio`/`get_news`
con catalogo) **non viene mai spenta**. Viene **sostituita gradualmente** dalla
KB del CDA, con due schalter:

| Feature flag | Default | Effetto |
|---|---|---|
| `cda_enabled` | false | quando false: vecchio comportamento integro. quando true: CDA intercetta |
| `cda_replace_legacy_pages` | false | quando true: `RadioPage`/`NewsPage` leggono da KB; quando false: leggono dalle costanti hardcoded |

Si attivano in sequenza durante la Fase D, con possibilità di rollback.

### 12.2 Doppia coexistenza temporanea (Fase B-C)

Durante Fase B+C, sia il vecchio path sia il nuovo sono attivi. Quando il LLM
emette `[TOOL: play_radio station="rai-radio-1"]` (vecchio formato con
`station`), il backend usa il catalogo statico. Quando emette
`[TOOL: play_radio query="rai radio 1"]` (nuovo formato con `query`),
delega al CDA.

Il system prompt aggiorna gli esempi few-shot per privilegiare il nuovo
formato, ma il vecchio formato resta gestito (compatibility).

### 12.3 Migrazione utenti

- Le 8 radio + 11 feed RSS attuali entrano nella `cda_content_items` al primo
  `alembic upgrade` come `discovered_by_user_id = NULL` (seed di famiglia).
- Tutti gli utenti vedono questi item nella loro vista (filtrabile come
  "scoperte famiglia" vs "mie scoperte").
- Nessuna perdita: chi era abituato alla pagina Radio con catalogo, dopo Fase D
  vede esattamente le stesse 8 radio nella stessa pagina, con in più le voci
  scoperte tramite voce o digitando.

### 12.4 Rollback

- `cda_enabled = false` → CDA disabilitato, tool vecchi tornano al catalogo.
- `cda_replace_legacy_pages = false` → pagine tornano a leggere da costanti.
- KB resta in DB ma non viene letta. Drop facile via migration backward.

---

## 13. Test di accettazione

Questi test devono passare al termine delle 5 fasi:

1. **Prima richiesta zero-config** — utente nuovo dice "Cara fammi ascoltare
   Radio Capital" (non nel seed). Pipeline completa termina e il player
   parte in <5 s totali.

2. **Seconda richiesta istantanea** — stessa richiesta dello stesso o di un
   altro utente: <500 ms (cache hit nella KB).

3. **Auto-recovery URL morto** — disabilitiamo deliberatamente uno stream
   URL salvato. La richiesta successiva: l'utente percepisce un piccolo
   ritardo (~3 s di re-discovery), ma il contenuto parte. KB aggiornata.

4. **Apprendimento preferenze** — dopo 5 richieste mattutine "le news" in cui
   l'utente sceglie sempre `repubblica.it` come prima fonte, alla 6ª: il sistema
   propone direttamente Repubblica senza ricerca.

5. **Discovery sensibile al formato** — la query "Caterpillar" risolve a
   contenuti diversi a seconda del verbo: "ascolta" → podcast,
   "guarda" → video, "leggi" → articolo.

6. **Sicurezza minore** — profilo `child` chiede "video di paura": discovery
   tenta, classifier respinge, CARA dice "non ho trovato qualcosa adatto" e
   logga `cda.content.blocked` per review parentale.

7. **Trasparenza fonte** — ogni player mostra dominio + favicon + bottone
   "apri originale".

8. **Ambiguità → chiarimento** — "metti la musica" senza specifica → CARA
   chiede "Quale? Le tue solite sono A, B, C". Niente riproduzione random.

9. **Coexistenza con legacy** — con `cda_enabled=false`, comportamento
   identico a v0.5 attuale. Con `true`, le richieste vecchie funzionano
   ancora; le nuove free-form funzionano in aggiunta.

10. **Privacy fetch** — `tcpdump` su un fetch CDA mostra user-agent
    `CARA/0.6 (private home assistant; …)`, nessun cookie persistente.

---

## 14. Configurazione admin

Nuova sezione "Content Discovery" nel pannello admin (Estensione 4
preesistente). Aggiunge:

### 14.1 Feature flags

| Chiave | Default | Effetto |
|---|---|---|
| `cda_enabled` | false | master switch |
| `cda_replace_legacy_pages` | false | Radio/News leggono da KB |
| `cda_ytdlp_youtube_enabled` | false | usa yt-dlp per estrarre stream YouTube |
| `cda_safe_search_for_minors` | true | force SafeSearch per `child`/`teen` |
| `cda_domain_whitelist_for_child` | — | array di domini permessi per `child` |
| `cda_domain_blacklist_global` | — | array di domini sempre vietati |

### 14.2 Search provider config

| Chiave | Default | Note |
|---|---|---|
| `cda_search_provider_priority` | `["searxng", "brave", "ddg"]` | ordine di tentativi |
| `cda_searxng_url` | `http://searxng:8080` | container interno |
| `cda_brave_api_key` | — (env) | quota free 2k/mese |

### 14.3 KB management UI

- Vista globale `cda_content_items` (admin-only).
- Filtri per `is_active`, `content_type`, `confidence_score < x`.
- Azioni: forza inactive, edit URL, ban dominio.

### 14.4 Vista bloccati (review parentale)

Tabella di tutti i `cda.content.blocked` degli ultimi 30 giorni:
- Quando, chi (utente minore), cosa (query), perché (whitelist / classifier).
- Bottone "concedi" per aggiungere dominio in whitelist locale del minore.

---

## 15. Discussione tradeoff (sintesi finale)

Per chiusura della specifica, gli esiti delle quattro discussioni richieste:

### Q1 — Buttare via Radio/News esistenti?

**No.** Si trasformano in viste della KB (Fase D), non si rimuovono. Le
costanti seed restano nel codice come bootstrap idempotent. Cost di
rifattorizzazione contenuto, valore di compatibilità conservato.

### Q2 — Intent classifier LLM dedicato?

**No.** Sul 1.5B attuale aggiunge ~3.5 s. Riusiamo il tool calling esistente
estendendo i tool del system prompt. Quando passeremo a 3B+, può aggiungere
un classificatore raffinato come passaggio facoltativo. Per ora regole +
fallback conversazionale.

### Q3 — yt-dlp e zona grigia?

**Default sicuro: YouTube embed iframe.** yt-dlp solo come fallback per
domini non-YouTube, dietro toggle admin. Mai bulk download, mai
ridistribuzione. Se un giorno CARA verrà distribuita commercialmente,
toggle off rimuove il rischio.

### Q4 — Strategia di migrazione?

**Coexistenza con feature flag.** `cda_enabled` default false abilita il
nuovo path; le pagine legacy restano funzionali. `cda_replace_legacy_pages`
attivato in Fase D quando la KB è abbastanza popolata. Rollback in un
secondo togliendo il flag.

---

## 16. Dipendenze nuove

| Pacchetto | Licenza | Scopo |
|---|---|---|
| `trafilatura` | Apache 2.0 | estrazione articoli |
| `readability-lxml` | Apache 2.0 | fallback estrazione |
| `feedparser` | BSD | feed RSS podcast (già presente) |
| `yt-dlp` | The Unlicense | estrazione video non-YouTube |
| `hls.js` (frontend) | Apache 2.0 | playback `.m3u8` |
| Container SearXNG | AGPL-3.0 | search self-hosted |
| Brave Search API key | commerciale free 2k/mese | fallback search |

Tutte compatibili con la filosofia OSS di CARA (nessun copyleft viral
oltre il container SearXNG, che gira come servizio separato).

---

## 17. Stato d'arrivo dopo 5 fasi

- Una richiesta vocale tipo "Cara fammi ascoltare Radio Capital" funziona da
  zero anche se Capital non è mai stata configurata.
- "Cara leggimi un articolo di approfondimento sull'energia solare" trova un
  articolo, lo legge ad alta voce con Piper, sincronizza la lettura nel reader.
- "Cara fammi vedere il telegiornale RAI delle 20" apre RaiPlay nel player.
- Le pagine Radio/News diventano viste personali della KB: ognuno vede ciò
  che ha esplorato.
- Profilo bambino è protetto da whitelist + safety classifier.
- L'admin vede log di ogni cosa, può bannare domini, può rivedere i contenuti
  bloccati.
- KB cresce. La latenza media collassa. CARA si modella sulle abitudini
  reali della famiglia senza programmazione esplicita.
