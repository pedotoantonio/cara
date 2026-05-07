# Cap 30 — Glossario

> Definizioni dei termini tecnici usati in CARA. Per ogni voce trovi
> la sezione canonica del manuale dove è spiegata in profondità.

## A

**Adapter** — Implementazione concreta di un Protocol (es.
`HomeAssistantAdapter` per smart home, `MQTTAdapter` futuro). Vedi
[12.1](12-smart-home.md#121-astrazione--carasmarthomebase).

**Admin settings** — Tabella `admin_settings` key-value JSONB, ospita
flag e parametri runtime modificabili dall'admin senza restart. Vedi
[Cap 27](27-admin-settings.md).

**AES-GCM** — Algoritmo di cifratura simmetrica usato per i token
OAuth at-rest. Chiave globale `OAUTH_ENCRYPTION_KEY`. Vedi
[19.4](19-sicurezza.md#194-aes-gcm-per-oauth-tokens).

**Alembic** — Strumento Python per gestire migration database
SQLAlchemy. File in `backend/alembic/versions/`. Vedi
[23.3](23-deploy.md#233-migration-alembic-in-produzione).

**Anglicismo** — Parola inglese entrata nell'italiano (weekend, email,
manager). Il TTSNormalizer ha ~300 sostituzioni fonetiche per farle
suonare bene a Piper italiano. Vedi
[7.3](07-voce-tts-stt.md#73-normalizzatore-anglicismi).

**Async-safe singleton** — Singleton process-wide protetto da
`asyncio.Lock` per serializzare le inferenze. `LLMService` lo è
(NPU non supporta concorrenza). Vedi
[6.7](06-ai-llm.md#67-concurrency--un-turno-alla-volta).

**Audit log** — Tabella `audit_log` append-only che registra ogni
operazione admin con actor + IP + diff. Vedi
[19.6](19-sicurezza.md#196-audit-log--audit_log-table).

**Auto-confirm streak** — Meccanismo per cui un workflow non chiede
conferma se l'utente ha già accettato 3 volte di seguito lo stesso
pattern. Vedi
[14.6](14-workflow.md#146-auto-confirm-trust-streak).

## B

**Bcrypt** — Hash function per password con cost factor 12. Vedi
[19.3](19-sicurezza.md#193-password--bcrypt).

**Bus famiglia (Family bus)** — Pub/sub Redis + WebSocket che
sincronizza gli eventi multi-device in tempo reale. Vedi
[Cap 17.3](17-notifiche-bus.md#173-family-bus--caraservicesfamily_bus).

## C

**Capability** — Vocabolario cross-vendor smart home (`ON_OFF`,
`BRIGHTNESS`, `COLOR`, ecc.). Permette di astrarre HA, MQTT, KNX
sotto la stessa NLU. Vedi
[12.1](12-smart-home.md#121-astrazione--carasmarthomebase).

**CDA (Content Discovery Agent)** — Pipeline che scopre contenuti web
dinamicamente: search → extract → verify → KB. Vedi
[Cap 13](13-cda.md).

**Celery** — Worker async distribuito. CARA ha 4 worker (beat, mail,
files, learn) per task in background pesanti.

**Cosine similarity** — Misura di similarità fra embedding vettoriali
(0 ortogonale, 1 identico). Usato per semantic facts retrieval e
Tier-2 skill dispatcher. Vedi
[8.3.3](08-memoria.md#833-retrieval--top-k-semantico).

## D

**DEFERRED** — Funzionalità progettata ma rinviata, con hooks
architetturali pronti ma flag OFF di default. Cloud LLM (Anthropic
Haiku) è DEFERRED. Vedi
[6.9](06-ai-llm.md#69-cloud-llm-deferred).

**Device** — Client paired con CARA che ha JWT lungo termine. Diverso
dall'utente: 1 utente → N device, 1 device → N utenti. Vedi
[Cap 15](15-multi-device.md).

**DRI** — Direct Rendering Infrastructure. La NPU RK3588 si accede via
ioctl su `/dev/dri/card0` (NON `/dev/rknpu`). Vedi
[6.2](06-ai-llm.md#62-il-runtime-rkllm-v110).

## E

**Embedding** — Rappresentazione vettoriale 384-dim di un testo,
prodotta da MiniLM multilingual. Usato per cosine similarity. Vedi
[8.3.3](08-memoria.md#833-retrieval--top-k-semantico).

**Episodic memory** — Tabella `events` append-only che registra
eventi puntuali nel tempo (chat turn, router miss, ha state changed).
Diversa dalla memoria semantica. Vedi
[8.2](08-memoria.md#82-memoria-episodica--caralearningepisodic).

**Executor (skill)** — Modulo che esegue un piano JSON di skill in
sequenza, risolvendo `{ref}`. Vedi
[9.3](09-skill-factory.md#93-executor--come-si-esegue-un-piano).

## F

**Fact** — Affermazione durevole su un utente (allergia, preferenza,
abitudine). Tabella `facts` con embedding JSONB. Iniettati nel
system prompt LLM. Vedi
[8.3](08-memoria.md#83-memoria-semantica--caralearningsemantic).

**FSM (Finite State Machine)** — Stato globale di CARA (`idle →
listening → thinking → speaking → idle`). Singleton in
`cara.core.state_machine`. Vedi
[4.9](04-backend-moduli.md#49-caracore--stato-globale).

**Fingerprint** — Hash SHA-256 di un cert (formato hex con `:`
separatori) usato per riconoscere visivamente la CA durante
installazione device.

## G

**Glossary (NER)** — Set di nomi/cognomi famiglia per riconoscimento
custom oltre a quello spaCy. Aggiornabile a runtime. Vedi
[8.1 NER](08-memoria.md).

## H

**HA (Home Assistant)** — Software open-source per smart home. CARA
si integra via REST API + WebSocket events. Vedi
[Cap 12](12-smart-home.md).

**Heartbeat (device)** — Endpoint `POST /devices/heartbeat` che un
device chiama periodicamente per dichiararsi online.

## I

**Intent router** — Tier-1 deterministico del chat router: regex
patterns IT → kind di intent (`answer_datetime`, `add_task`, ecc.).
Vedi `cara/services/intent_router.py`.

## J

**JWT (JSON Web Token)** — Token firmato HS256 con `JWT_SECRET`.
CARA ne usa 3 tipi: access (60min), refresh (30g), device (365g).
Vedi [19.2](19-sicurezza.md#192-jwt--autenticazione).

## K

**KV cache** — Memoria attenzione del modello LLM salvata su file per
riusare il prefisso comune fra turni. TTFT 8.3× più veloce sui turni
warm. Vedi [6.3](06-ai-llm.md#63-kv-cache--ttft-83-pi%C3%B9-veloce).

## L

**LLM (Large Language Model)** — In CARA: Qwen 2.5-1.5B-Instruct
quantizzato w8a8 hybrid-0.5, eseguito sulla NPU RK3588 via RKLLM.
Vedi [Cap 6](06-ai-llm.md).

**LoRA (Low-Rank Adaptation)** — Tecnica di fine-tune efficiente. CARA
ha pipeline pronta ma il training va su GPU x86 (no NPU). Vedi
[6.8](06-ai-llm.md#68-lora-fine-tune-futuro).

## M

**MinIO** — Storage S3-compatibile per upload utente. Container
`cara-minio`. Vedi [1.3](01-architettura.md#13-i-container-docker).

**mkcert** — Tool che genera una CA locale + cert firmato da quella
CA, perfetto per HTTPS LAN. Sostituisce self-signed. Vedi
[19.5](19-sicurezza.md#195-tls--mkcert--lets-encrypt).

## N

**NER (Named Entity Recognition)** — Identifica persone, luoghi,
organizzazioni, PII in un testo. CARA usa spaCy `it_core_news_lg` +
regex + family glossary. Vedi
[Cap 4.7](04-backend-moduli.md#47-caraai--aillmembeddings).

**NPU (Neural Processing Unit)** — Acceleratore hardware specializzato
per AI inference. Sul RK3588: 6 TOPS, 3 core. Esclusa dal driver
standard Debian — kernel custom richiesto.

## O

**OAuth** — Standard di autorizzazione delegata. CARA lo usa per
accesso a Google Calendar/Gmail con scope read-only quando possibile.
Vedi [Cap 16.2](16-integrazioni-google.md#162-oauth-flow--caraintegrationsgoogle_oauth).

## P

**Pairing (device)** — Flow di registrazione di un nuovo device:
codice 6 cifre, single-use, TTL 5 min, finalize admin → JWT. Vedi
[15.3](15-multi-device.md#153-pairing-flow--codice-6-cifre).

**Piper** — TTS (text-to-speech) open-source basato su VITS. Voci
italiane multiple. CPU-only, real-time factor ~0.5x. Vedi
[7.2](07-voce-tts-stt.md#72-piper-tts--dove-vivono-le-voci).

**Pipeline (router)** — Sequenza di Stage che routano un messaggio
chat. Tier-1 regex / Tier-2 cosine / Tier-3 LLM. Vedi
[Cap 4.12](04-backend-moduli.md#412-cararouter--pipeline-di-routing).

**Primitive** — Funzione async registrata che le skill JSON possono
chiamare (extract_list, summarize, read_url, ask_user, ecc.). Vedi
[9.2](09-skill-factory.md#92-le-primitive--il-vocabolario-delle-skill).

**Push (web push, VAPID)** — Notifica al browser anche con tab chiusa.
Generata server-side, firmata VAPID, cifrata con device key. Vedi
[Cap 17.2](17-notifiche-bus.md#172-web-push-vapid--caraservicespush).

**PWA (Progressive Web App)** — App web installabile come app nativa.
CARA ha manifest, service worker, shortcuts, e funziona offline (per
funzioni base). Vedi [Cap 5.7](05-frontend-moduli.md#57-pwa--manifest-install-shortcuts).

## R

**RKLLM** — Runtime di Rockchip per LLM su NPU. CARA usa v1.1.0 via
ctypes bindings su `librkllmrt.so`. Vedi
[6.2](06-ai-llm.md#62-il-runtime-rkllm-v110).

**Rule (proattività)** — Funzione async registrata che, su tick
scheduler, valuta condizioni e produce zero/uno/più Suggestion. Vedi
[Cap 11.1](11-proattivita.md#111-engine--caraservicesproactivityengine).

## S

**Sentence buffer** — Logica frontend/backend che tagliuzza il flusso
LLM token a frase intera per TTS streaming. Vedi
[7.4](07-voce-tts-stt.md#74-sentence-streaming--frasi-durante-la-generazione).

**Service worker** — Worker JavaScript del browser che intercetta
fetch + manda push + gestisce offline. CARA usa Workbox custom in
mode `injectManifest`. Vedi
[Cap 5.6](05-frontend-moduli.md#56-service-worker-e-offline--frontendsrc).

**Skill** — Riga della tabella `skills` con struttura JSON
(`name`, `intent_examples`, `slot_extraction`, `plan`,
`response_template`). Compone primitive in step lineari. Vedi
[Cap 9](09-skill-factory.md).

**SSE (Server-Sent Events)** — Protocollo HTTP per streaming
unidirezionale server→client. CARA lo usa per chat tokens +
audio_chunk. Vedi [1.6](01-architettura.md#16-cosa-succede-quando-arriva-una-richiesta-chat).

**Stable prefix** — Parte del prompt LLM che cambia di rado (base +
tone), KV-cacheable. Vedi
[6.5](06-ai-llm.md#65-system-prompt-segmentato).

**Surface** — Classe del device (mobile/desktop/wall/watch/tv) che
determina densità Wallet, capability voce, layout default. Vedi
[15.2](15-multi-device.md#152-surface--cosa-cambia).

## T

**Tier (skill dispatcher)** — Stadio del dispatcher: Tier-1 regex
(deterministico), Tier-2 cosine embedding, Tier-3 LLM classifier.
Vedi [9.5](09-skill-factory.md#95-dispatcher--tier-123).

**Tool calling** — Capacità del LLM di emettere `[TOOL: name args]`
parsato dal frontend e mappato a primitive backend. Reliability ~60-70%
sul 1.5B base, +25 punti con LoRA fine-tune. Vedi
[8.8](08-memoria.md#88-tool-call-metrics--funnel-a-4-gate).

**Trafilatura** — Libreria Python per estrarre testo principale da
HTML (article extraction). Usata da CDA + read_url primitive.

**TTFT (Time-To-First-Token)** — Tempo dal momento "premi invia" al
primo token visibile. Cold ~16s, warm ~2s. Vedi
[6.1 perf](06-ai-llm.md#61-il-modello-qwen-25-15b-instruct-w8a8-hybrid-05).

**TTS (Text-To-Speech)** — Sintesi vocale. CARA usa Piper. Vedi
[Cap 7](07-voce-tts-stt.md).

## V

**VAPID (Voluntary Application Server Identification)** — Standard
W3C per push notifications senza dipendenza da un terzo provider.
Vedi [17.2](17-notifiche-bus.md#172-web-push-vapid--caraservicespush).

## W

**Wake word** — Parola chiave ("CARA") che attiva l'ascolto. Web
Speech in continuous mode + filtro client-side. Off di default. Vedi
[7.7](07-voce-tts-stt.md#77-wake-word-cara).

**WebAudio queue** — Tecnica frontend per concatenare chunk audio
WAV senza gap audibile, schedulando ognuno con `audioContext.currentTime`.
Vedi [7.8](07-voce-tts-stt.md#78-webaudio-queue-per-playback).

**Widget** — Card del Wallet (today_summary, weather_now, quick_actions,
ecc.). Implementa `Widget` Protocol + render(`WidgetContext`) →
`WidgetData`. Vedi [Cap 10](10-wallet-widgets.md).

**Workflow** — Pipeline strutturata `classify → extract → propose →
execute` per contenuti complessi (scontrino, bolletta, ricetta).
Vedi [Cap 14](14-workflow.md).

---

[← Cap 29 Riferimento WebSocket](29-websocket.md) · [README](README.md) · [Cap 31 Troubleshooting →](31-troubleshooting.md)
