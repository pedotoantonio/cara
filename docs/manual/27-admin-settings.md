# Cap 27 — Riferimento `admin_settings`

> *Sintesi 30 secondi.* Tutti i flag e parametri runtime modificabili
> dall'admin via `/admin/settings`. Vivono in tabella `admin_settings`
> come key-value JSONB. I default sono in `cara.services.admin_settings:DEFAULTS`.

A differenza di `.env` (cap 26), modificare un `admin_setting` **non
richiede restart**. L'effetto è hot.

## 27.1 Feature flags master

| Key | Default | Descrizione |
|---|---|---|
| `internet_enabled` | `False` | Master switch contenuti web |
| `news_enabled` | `False` | Aggregatore news |
| `video_enabled` | `False` | Discovery video |
| `radio_enabled` | `False` | Discovery radio internet |
| `habit_learning_enabled` | `False` | Detector pattern ricorrenti |
| `proactive_suggestions_enabled` | `False` | Engine proattività attivo |
| `telegram_bot_enabled` | `False` | Bot Telegram |
| `facial_recognition_enabled` | `True` | Frigate-faces integration |
| `voice_recognition_enabled` | `True` | Web Speech API client-side |
| `smart_home_enabled` | `False` | HA adapter |
| `push_notifications_enabled` | `False` | Push scheduler attivo |
| `cloud_llm_enabled` | `False` | Anthropic Haiku — DEFERRED |
| `validation_enabled` | `False` | LLM validation pipeline |
| `cognitive_mode` | `False` | Modalità ragionamento approfondito |

## 27.2 LLM tuning

| Key | Default | Descrizione |
|---|---|---|
| `llm_quality_mode` | `"fast"` | `"fast"` (1.5B) / `"quality"` (3B) |
| `llm_system_prompt` | `None` | Override del prompt base |
| `llm_max_new_tokens` | `None` | Override env |
| `llm_validation_prompt` | `None` | Per validation pipeline |
| `llm_validation_max_tokens` | `None` | |
| `llm_cognitive_prompt` | `None` | Per cognitive mode |
| `tone_preset` | `"default"` | `"default"`/`"privacy"`/`"playful"` |

Modificare `llm_system_prompt` o `tone_preset` triggera flush KV cache.

## 27.3 Voce TTS

| Key | Default | Descrizione |
|---|---|---|
| `voice_name` | `None` | Es. `"it_IT-paola-medium"` |
| `voice_rate` | `None` | 0.5-2.0 |
| `voice_pitch` | `None` | 0.0-2.0 |
| `voice_volume` | `None` | 0.0-1.0 |
| `tts_user_overrides` | `{}` | Dict di anglicismi custom |
| `tts_streaming_enabled` | `False` | Streaming sentence-by-sentence |

## 27.4 CDA — Content Discovery

| Key | Default | Descrizione |
|---|---|---|
| `cda_enabled` | `True` | Master switch del discover tool |
| `cda_replace_legacy_pages` | `False` | Radio/News leggono da KB CDA invece di feed RSS hardcoded |
| `cda_ytdlp_youtube_enabled` | `False` | yt-dlp per stream YouTube |
| `cda_safe_search_for_minors` | `True` | Forza safe search per teen/child |
| `cda_domain_blacklist` | `None` | Lista domini sempre bloccati |
| `cda_domain_whitelist_for_child` | `None` | Allowlist per role child |
| `cda_agent_loop_enabled` | `True` | Forza grounding su query info-need |

## 27.5 Skill Factory

| Key | Default | Descrizione |
|---|---|---|
| `skill_author_enabled` | `False` | Abilita Skill Author Phase D (cloud LLM) |
| `skill_author_prompt` | `None` | Override del prompt LLM authoring |
| `skill_author_provider` | `None` | Provider |
| `skill_author_model` | `None` | Modello |
| `skill_dispatcher_tier2_enabled` | `True` | Cosine matching skill |
| `skill_dispatcher_tier3_enabled` | `False` | LLM classifier (costoso) |
| `skill_dispatcher_tier2_threshold` | `0.65` | Soglia cosine per match |

## 27.6 Setup wizard

| Key | Default | Descrizione |
|---|---|---|
| `setup_state` | `None` | Dict opaque per progress wizard |

Struttura:

```json
{
  "completed": false,
  "current_step": "tls",
  "version": 1,
  "completed_steps": ["admin"],
  "completed_at": null,
  "completed_by_user_id": null,
  "env_dirty": true,
  "cert_fingerprint": "..."
}
```

## 27.7 Identità + locale

| Key | Default | Descrizione |
|---|---|---|
| `timezone` | `"Europe/Rome"` | Timezone IANA |
| `language` | `"it"` | `"it"`/`"en"` (futuro) |
| `family_name` | `None` | Nome famiglia ("Famiglia Pedoto") |
| `family_glossary` | `None` | Lista nomi/cognomi per NER |
| `family_size` | `None` | Numero membri |

## 27.8 Smart home

| Key | Default | Descrizione |
|---|---|---|
| `ha_url` | `None` | URL Home Assistant |
| `ha_token` | `None` | Long-Lived Access Token (plaintext, ATM) |
| `frigate_url` | `None` | URL Frigate |
| `frigate_faces_url` | `None` | URL frigate-faces |

## 27.9 Esempio uso programmatico

```python
from cara.services import admin_settings

# Get singolo
val = await admin_settings.get(session, "internet_enabled")
# False

# Get con env fallback
val = await admin_settings.get_with_env_fallback(
    session, "llm_max_new_tokens",
    env_default=settings.llm_max_new_tokens,
)

# Get all (per UI admin)
all_settings = await admin_settings.get_all(session)
# {"internet_enabled": False, "news_enabled": False, ...}

# Set
await admin_settings.set(
    session, "internet_enabled", True,
    actor_user_id=admin.id,
)
await session.commit()
```

`set` raise `ValueError` se la chiave non è in DEFAULTS — anti-typo.

## 27.10 Aggiungere una nuova setting

1. Aggiungi a `DEFAULTS` in `cara/services/admin_settings.py`:

```python
DEFAULTS: dict[str, Any] = {
    # ...esistenti...
    "my_new_flag": False,
}
```

2. Usa in codice:

```python
if await admin_settings.get(session, "my_new_flag"):
    # logic conditional
```

3. Esponi in UI admin (`AdminPage.tsx`) o setup wizard (cap 18).

4. Test smoke che il toggle persiste.

Niente migration richiesta — `admin_settings` è una tabella key-value
generica.

---

[← Cap 26 Variabili .env](26-env-vars.md) · [README](README.md) · [Cap 28 Riferimento API REST →](28-api-rest.md)
