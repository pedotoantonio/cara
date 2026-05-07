# Cap 6 — AI / LLM

> *Sintesi 30 secondi.* CARA usa un modello Qwen 2.5-1.5B quantizzato a
> 8 bit, eseguito sulla NPU del processore RK3588 via il runtime
> RKLLM. Genera ~9 token/secondo, con prima latenza di 2-16 secondi.
> Questo capitolo spiega come funziona la pipeline AI dal prompt al
> token.

## 6.1 Il modello: Qwen 2.5-1.5B-Instruct w8a8 hybrid-0.5

**Cosa è**: un modello linguistico di piccola taglia (1.5 miliardi di
parametri) della serie Qwen 2.5 di Alibaba, fine-tuned per
istruzioni in stile chat. Supporta italiano nativo (è uno dei pochi
modelli sotto 3B che lo fa decentemente).

**Quantizzazione w8a8 hybrid-0.5**:
- **w8a8** = peso 8 bit, attivazione 8 bit (intero quantizzato, non
  float)
- **hybrid-0.5** = il 50% degli strati resta float, gli altri sono
  quantizzati. Compromesso accuratezza/velocità ottimizzato per RK3588.

**File**: `data/models/qwen2.5-1.5b-instruct-w8a8.rkllm`, ~1.9 GB.

**Performance reali** sul NanoPC-T6 con NPU RK3588:

| Metrica | Cold (primo turno) | Warm (turni successivi) |
|---|---|---|
| Time-to-first-token (TTFT) | ~16 s | ~2 s |
| Token/secondo sustained | 5-9 tok/s | 7-9 tok/s |
| RAM occupata (NPU) | ~2.4 GB | invariata |

Il **warm path** sfrutta la KV cache (vedi 6.3), che evita di
ricalcolare il prefisso del prompt comune fra i turni.

## 6.2 Il runtime: RKLLM v1.1.0

**RKLLM** è il runtime di Rockchip per LLM su NPU RK3588. Espone una
libreria C `librkllmrt.so` con poche funzioni:

- `rkllm_init()` — carica il modello
- `rkllm_run()` — genera token in callback
- `rkllm_destroy()` — scarica
- `rkllm_load_lora()` (per LoRA, futuro)

CARA lo usa via **ctypes bindings** in `cara/ai/_rkllm_bindings.py`:

```python
import ctypes
from cara.ai._rkllm_bindings import RKLLMHandle, RKLLMInputType

lib = ctypes.CDLL("/usr/lib/rkllm/librkllmrt.so")
handle = RKLLMHandle()
lib.rkllm_init(ctypes.byref(handle), ...)
```

I bindings espongono anche `RKLLMPromptCacheParam` per la KV cache
(vedi 6.3).

> **⚠️ Attenzione** — `librkllmrt.so` v1.1.0 richiede **kernel custom
> 6.1.141-cara1** con driver `rknpu` v0.9.8. Non funziona sul kernel
> Debian standard. La procedura di flash è in `/home/apedo/CLAUDE.md`.

### Accesso al device

Il runtime comunica con la NPU via DRM ioctl su `/dev/dri/card0` (NON
via `/dev/rknpu`, che NON esiste su questo kernel). Il container
`cara-backend` quindi deve avere:

```yaml
devices:
  - /dev/dri/card0
group_add:
  - "44"  # gruppo 'video' che owns /dev/dri
```

Questa è l'unica concessione hardware del container.

## 6.3 KV cache — TTFT 8.3× più veloce

Il **prompt prefix** di una chat (system + tone + history) cambia
poco fra un turno e il successivo. Senza ottimizzazioni, ogni
inferenza ricalcola da capo l'attenzione su quei migliaia di token —
costo dominante.

La **KV cache** salva il key/value dell'attenzione del prefisso su un
file binario, e lo ricarica al turno successivo. Il modello salta la
fase di prefill e parte direttamente dal nuovo input.

**Modulo**: `cara/ai/kv_cache.py`.

```python
from cara.ai import kv_cache

# Path determinato da SHA-1 del conv_id (anonimizzato)
path = kv_cache.path_for_conversation(str(convo.id))
# /app/cache/kv/<sha1>.bin

# Passato a llm.generate() che lo wrap in RKLLMPromptCacheParam
async for chunk in llm_service.generate(prompt, prompt_cache_path=path):
    ...

# RKLLM scrive il file dopo il primo run, riusa nei successivi.
```

**Invalidation**: quando il system prompt cambia (admin edit), tutti
i file KV cache diventano sbagliati (il prefix non corrisponde più).
Il backend chiama `kv_cache.flush_all()` su:

- `PATCH /admin/settings` con chiavi `llm_system_prompt` o `tone`
- Cleanup janitor (file >30 min idle)

**Speedup misurato**: TTFT cold (turno 1) 16.5 s → warm (turno 2) 2.0
s. Verifica live nei log:

```
chat.turn  tokens=42 first_token_seconds=2.0 kv_cache_path=/app/cache/kv/abc.bin
```

> **💡 Suggerimento** — la KV cache sta in `/app/cache/kv/` (in-container,
> bind-mount opzionale). Spazio occupato: ~50 MB per conversazione
> attiva. `scripts/cleanup-kv-cache.sh` purga i file > 30 min idle.

## 6.4 Sampling — temperature, top_p, top_k, repeat_penalty

Il modello produce probabilità per ogni possibile token successivo.
Il sampler sceglie un token concreto. Quattro parametri:

| Parametro | Default CARA | Cosa fa |
|---|---|---|
| `temperature` | 0.45 | Più alta → output più creativo/random; più bassa → più deterministico |
| `top_p` | 0.85 | Considera solo i token cumulativamente al top 85% di prob |
| `top_k` | 40 | Considera solo i top 40 token più probabili |
| `repeat_penalty` | 1.05 | Penalizza ripetizioni di token già usati |

**Default scelti per CARA**: leggermente conservative. Generano
risposte coerenti, italiani naturali, raramente fantasiose. Per
modalità "playful" si potrebbe alzare temperature a 0.7+ ma non
abbiamo ancora un override.

**Override admin**: i parametri sono in `cara/config.py` con env
variables `LLM_TEMPERATURE`, `LLM_TOP_P`, ecc. — modificarli richiede
restart del backend.

## 6.5 System prompt segmentato

Il prompt è composto da tre layer ordinati:

```
+-----------------------------+
| 1. base (CARA persona)      |  ← stabile, KV-cacheable
+-----------------------------+
| 2. tone (default/privacy/   |
|    playful)                  |  ← stabile per tone, KV-cacheable
+-----------------------------+
| 3. facts top-k user         |  ← cambia ogni turno
+-----------------------------+
| 4. history user/assistant   |
+-----------------------------+
| 5. user message corrente    |
+-----------------------------+
```

I primi due **costituiscono il "stable prefix"** — è ciò che la KV
cache memorizza. Ogni turno aggiunge facts + history + new message,
ma il prefisso resta lo stesso.

**Modulo**: `cara/api/v1/_chat_system_prompt.py` espone:

```python
from cara.api.v1._chat_system_prompt import (
    stable_prefix,    # str: base + tone — KV cacheable
    fingerprint,       # str: SHA-1[:16] del prefix — per invalidation
    full_system_prompt,  # str: tutto, incluso facts dinamici
)
```

L'admin può sovrascrivere il `base` via `admin_settings.llm_system_prompt`
(textarea in `/admin`). Su modifica, `flush_all()` viene chiamato.

**Tone preset attuali** (definiti in `_chat_system_prompt.py`):

- **default** — assistente di casa caldo e diretto, riassume task ed
  aiuta con le faccende, ricorda i fatti famiglia
- **privacy** — niente cronologia, niente facts utente, risponde solo
  al turno corrente. Per ospiti / topic sensibili.
- **playful** — più scherzosa, niente facts (privacy ridotta), tono
  rilassato

## 6.6 Modalità: fast (1.5B) vs quality (3B)

Il flag `admin_settings.llm_quality_mode` controlla quale modello viene
caricato:

- **`fast`** (default) — Qwen 2.5-**1.5B**, ~9 tok/s, basso uso NPU
- **`quality`** — Qwen 2.5-**3B**, ~4 tok/s, doppio uso NPU

Lo switch è destroy + re-init: ~10 secondi di pausa in cui il backend
non risponde alle chat (gli altri endpoint sì).

> **⚠️ Attenzione** — il **3B sotto carico Frigate è inutilizzabile**:
> TTFT 23 secondi, 0.65 tok/s. Frigate occupa la GPU per
> object-detection e contende la memoria DDR. Tieni il 1.5B di default.

## 6.7 Concurrency — un turno alla volta

L'NPU non supporta inferenze parallele (almeno con RKLLM 1.1.0). CARA
serializza con un `asyncio.Lock` in `cara/ai/llm.py:LLMService`:

```python
async def generate(self, ...):
    async with self._gen_lock:  # serializza
        async for chunk in self._generate_locked(...):
            yield chunk
```

Implicazioni:

- Se due utenti chattano insieme, il secondo aspetta che il primo
  finisca un turno (di solito 5-15 secondi).
- `UVICORN_WORKERS=1` di default. **Non** alzare a 2: carica due
  modelli in NPU, raddoppia la memoria, e il lock non si applica
  cross-process.

## 6.8 LoRA fine-tune (futuro)

CARA ha la pipeline pronta per fare fine-tune LoRA del modello su dati
famiglia. Il fine-tune **non gira** sul NanoPC (manca CUDA); si fa su
RunPod/Vast.ai. Vedi `scripts/lora-train-runpod.sh` e
`docs/LORA-FINE-TUNE-PIPELINE.md`.

**Output atteso**: alza il tool-calling reliability dal 60-70% attuale
del base 1.5B all'85%+. Costa ~$5 di GPU rental per iterazione.

Procedura (riassunto):

```bash
# 1. Estrai dataset dal DB live di CARA
docker exec cara-backend python /app/scripts/export_lora_dataset.py \
  --output-dir /tmp/cara_lora --since-days 90

# 2. Copia su RunPod
rsync -avz /tmp/cara_lora user@runpod:/workspace/

# 3. Su RunPod, esegui il runbook
ssh user@runpod 'cd /workspace && bash lora-train-runpod.sh'

# 4. Scarica il .rkllm
scp user@runpod:/workspace/lora-out/cara-qwen-1p5b-lora.rkllm \
  data/models/

# 5. Riavvia CARA puntando al nuovo file
```

Vedi cap 25 (Estendere) per la procedura step-by-step.

## 6.9 Cloud LLM (DEFERRED)

CARA ha l'astrazione `cloud_llm` in `cara/services/cloud_llm.py` che
duplica l'interfaccia di `LLMService` ma chiama Anthropic Haiku. È
DEFERRED: **`cloud_llm_enabled=False`** di default.

Quando attivato (admin opt-in dal setup wizard step 7b):

- Email NLU layer 3 va in cloud (più precisione su intent ambigui)
- Skill Author Phase D usa cloud per generare nuove skill JSON

Ogni chiamata cloud:
- È auditata (chi, quando, quanti token)
- Rispetta il flag privacy (mai cloud per `tone=privacy`)
- Conta nel budget mensile dell'admin (limite configurabile in futuro)

Il cloud non viene mai contattato senza il flag esplicito ON. Il
modello locale resta sempre la fonte primaria di verità.

## 6.10 Come testare il LLM

Smoke test rapido dal vivo:

```bash
# Verifica che il modello sia caricato
curl -sk https://192.168.1.23:8455/api/v1/chat/health
# {"status":"ok","model_path":"qwen2.5-1.5b-instruct-w8a8.rkllm"}

# Manda un turno chat e misura TTFT
TOK=$(curl -sk -X POST https://192.168.1.23:8455/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"pedotoa@gmail.com","password":"caracasa2026"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

time curl -sk -N -X POST https://192.168.1.23:8455/api/v1/chat \
  -H "Authorization: Bearer $TOK" \
  -H "Content-Type: application/json" \
  -d '{"message":"Ciao, raccontami una barzelletta breve."}'
```

Il primo turno mostrerà TTFT cold (~16s); rifai immediatamente e vedrai
TTFT warm (~2s).

## 6.11 Estendere — sostituire il modello

Per usare un altro modello (es. Qwen 3B, Llama 3.2):

1. Scarica il `.rkllm` per RK3588 (deve essere convertito con
   `rkllm-toolkit` su x86, non sul NanoPC).
2. Mettilo in `data/models/`.
3. Aggiorna `cara/config.py:Settings.llm_model_path`.
4. Aggiorna `admin_settings` se rilevante.
5. Riavvia `cara-backend`.

Per **modelli completamente diversi** (Llama, Mistral) potrebbe servire
adattare il prompt template — Qwen usa `<|im_start|>` markers, Llama 3
usa `<|begin_of_text|>`. Vedi `_chat_prompt.py:render_qwen_prompt`.

---

[← Cap 5 Frontend deep](05-frontend-moduli.md) · [README](README.md) · [Cap 7 Voce, TTS, STT →](07-voce-tts-stt.md)
