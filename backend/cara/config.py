"""Application settings, loaded from environment."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: str = Field(default="development", validation_alias="CARA_ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    database_url: str = Field(validation_alias="DATABASE_URL")

    redis_url: str = Field(validation_alias="REDIS_URL")

    # TTS (Piper) — server-side speech synthesis. Voices live as ONNX files in
    # `tts_voices_dir` and are downloaded on demand from HuggingFace
    # `rhasspy/piper-voices` the first time a voice is requested.
    tts_voices_dir: str = Field(default="/app/tts/piper/voices", validation_alias="TTS_VOICES_DIR")
    tts_default_voice: str = Field(
        default="piper:it_IT-paola-medium", validation_alias="TTS_DEFAULT_VOICE"
    )
    tts_cache_ttl_seconds: int = Field(default=3600, validation_alias="TTS_CACHE_TTL_SECONDS")
    tts_cache_max_chars: int = Field(default=400, validation_alias="TTS_CACHE_MAX_CHARS")
    tts_enabled: bool = Field(default=True, validation_alias="TTS_ENABLED")

    # Content Discovery Agent (CDA) — see /opt/cara/docs/cda-extension-spec.md.
    # Empty SearXNG URL falls back to the DDG HTML provider.
    cda_searxng_url: str = Field(default="", validation_alias="CDA_SEARXNG_URL")
    cda_default_search_timeout: float = Field(
        default=8.0, validation_alias="CDA_SEARCH_TIMEOUT"
    )

    minio_endpoint: str = Field(validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(validation_alias="MINIO_ROOT_USER")
    minio_secret_key: str = Field(validation_alias="MINIO_ROOT_PASSWORD")
    minio_bucket: str = Field(default="cara", validation_alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")

    chroma_host: str = Field(default="chroma", validation_alias="CHROMA_HOST")
    chroma_port: int = Field(default=8000, validation_alias="CHROMA_PORT")

    jwt_secret: str = Field(validation_alias="JWT_SECRET")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_access_ttl_minutes: int = Field(default=60, validation_alias="JWT_ACCESS_TTL_MINUTES")
    jwt_refresh_ttl_days: int = Field(default=30, validation_alias="JWT_REFRESH_TTL_DAYS")

    llm_model_path: str = Field(
        default="/app/models/qwen2.5-1.5b-instruct-w8a8.rkllm",
        validation_alias="LLM_MODEL_PATH",
    )
    llm_runtime_lib_path: str = Field(
        default="/usr/lib/rkllm/librkllmrt.so",
        validation_alias="LLM_RUNTIME_LIB_PATH",
    )
    llm_max_context_len: int = Field(default=4096, validation_alias="LLM_MAX_CONTEXT_LEN")
    llm_max_new_tokens: int = Field(default=900, validation_alias="LLM_MAX_NEW_TOKENS")
    llm_temperature: float = Field(default=0.7, validation_alias="LLM_TEMPERATURE")
    llm_top_k: int = Field(default=40, validation_alias="LLM_TOP_K")
    llm_top_p: float = Field(default=0.9, validation_alias="LLM_TOP_P")
    llm_repeat_penalty: float = Field(default=1.1, validation_alias="LLM_REPEAT_PENALTY")
    # 0 disables the LLM module entirely (useful for unit tests / dev without NPU).
    llm_enabled: bool = Field(default=True, validation_alias="LLM_ENABLED")

    # Self-critique pass. When the admin flag `validation_enabled` is on,
    # CARA runs a second short inference that judges its own reply against
    # the user's question and either approves it or rewrites it. Roughly
    # doubles latency, so it is opt-in.
    llm_validation_max_tokens: int = Field(
        default=160, validation_alias="LLM_VALIDATION_MAX_TOKENS"
    )
    # Full cognitive system prompt — mounted only when admin flag
    # `cognitive_mode` is ON. Designed for a 3B+ model; the 1.5B will not
    # follow it reliably. Configurable via LLM_COGNITIVE_PROMPT in .env.
    llm_cognitive_prompt: str = Field(
        default=(
            "Sei CARA, un agente cognitivo che migliora osservando ogni interazione. "
            "Per ogni risposta, internamente:\n"
            "1) Osserva l'intento esplicito e implicito dell'utente.\n"
            "2) Richiama eventuali correzioni o preferenze già emerse nella cronologia.\n"
            "3) Formula 2-3 ipotesi di risposta e scegli quella con confidenza più alta.\n"
            "4) Esplicita le assunzioni quando rilevanti.\n"
            "5) Dopo, valuta i segnali di feedback (correzioni, riformulazioni, frustrazione).\n\n"
            "Se la confidenza è bassa, dillo. Se non sai una cosa, ammettilo. "
            "Non inventare fatti. Non simulare conoscenza che non hai. "
            "Se l'utente ti ha già corretto in passato, non ripetere lo stesso errore."
        ),
        validation_alias="LLM_COGNITIVE_PROMPT",
    )

    llm_validation_prompt: str = Field(
        default=(
            "Sei un revisore della qualità delle risposte di un assistente AI. "
            "Hai davanti la domanda dell'utente e la risposta che l'assistente "
            "ha appena prodotto. Valuta se la risposta:\n"
            "1. risponde alla domanda in modo pertinente e coerente;\n"
            "2. è in italiano corretto, breve e comprensibile;\n"
            "3. non inventa fatti che non erano nel contesto;\n"
            "4. non è troncata, vuota o contiene frasi a metà.\n\n"
            "Se la risposta è BUONA, rispondi soltanto con:\n"
            "OK\n\n"
            "Se è inadeguata, rispondi con due righe:\n"
            "RIVEDI\n"
            "<la risposta corretta, sintetica e in italiano>\n\n"
            "Niente spiegazioni, niente preamboli."
        ),
        validation_alias="LLM_VALIDATION_PROMPT",
    )

    # frigate-faces integration (face recognition from house cameras).
    # Empty disables the integration; the family endpoints will return 503.
    frigate_faces_url: str = Field(
        default="http://frigate-faces:5051", validation_alias="FRIGATE_FACES_URL"
    )
    family_presence_window_minutes: int = Field(
        default=15, validation_alias="FAMILY_PRESENCE_WINDOW_MINUTES"
    )

    # Telegram bot (optional). If empty the bot module is not started.
    # Owner sets `CARA_TELEGRAM_BOT_TOKEN` in .env (token from @BotFather)
    # and `CARA_TELEGRAM_CHAT_OWNERS` (comma-separated chat IDs allowed).
    # Optionally bind chat_id → user via "chat_id:user_email,chat_id:user_email".
    cara_telegram_bot_token: str = Field(default="", validation_alias="CARA_TELEGRAM_BOT_TOKEN")
    cara_telegram_chat_owners: str = Field(
        default="", validation_alias="CARA_TELEGRAM_CHAT_OWNERS"
    )
    cara_telegram_chat_user_map: str = Field(
        default="", validation_alias="CARA_TELEGRAM_CHAT_USER_MAP"
    )
    llm_system_prompt: str = Field(
        default=(
            "Ti chiami CARA, assistente AI della famiglia Pedoto. Rispondi sempre "
            "in italiano, in modo chiaro e completo.\n\n"

            "## REGOLA #1 — INTERNET\n"
            "Se l'utente chiede qualcosa che NON sai dalla conversazione "
            "(meteo, prezzi, orari, eventi, attualità, definizioni, fatti, "
            "video / radio / podcast specifici), DEVI emettere immediatamente:\n"
            "[TOOL: discover query=\"<query di ricerca>\" kind=\"article|audio_stream|video|podcast|image|document\"]\n"
            "Tu PUOI accedere a internet con questo tool. Non dire mai \"non posso "
            "accedere a internet\" o \"come AI non ho informazioni in tempo reale\". "
            "USA discover. Punto.\n\n"

            "## STRUMENTI DISPONIBILI\n"
            "Usa AL MASSIMO UNO per turno. Subito dopo il tool, scrivi UNA breve "
            "frase che presenta il risultato.\n\n"
            "[TOOL: add_task title=\"...\"]                 — aggiungi una cosa da fare\n"
            "[TOOL: complete_task title=\"...\"]            — completa una task\n"
            "[TOOL: list_tasks]                           — mostra le cose da fare\n"
            "[TOOL: add_shopping title=\"...\"]             — aggiungi alla spesa\n"
            "[TOOL: add_note title=\"...\" body=\"...\"]      — salva una nota\n"
            "[TOOL: who_is_home]                          — chi è in casa adesso\n"
            "[TOOL: discover query=\"...\" kind=\"...\"]      — cerca su internet\n\n"

            "## ESEMPI\n"
            "U: ricordami di comprare il pane\n"
            "A: [TOOL: add_task title=\"comprare il pane\"]\nAggiunto.\n\n"
            "U: ho fatto chiamare il dentista\n"
            "A: [TOOL: complete_task title=\"chiamare il dentista\"]\nFatto.\n\n"
            "U: cosa devo fare?\n"
            "A: [TOOL: list_tasks]\nEcco la tua lista.\n\n"
            "U: aggiungi il latte alla spesa\n"
            "A: [TOOL: add_shopping title=\"latte\"]\nMesso.\n\n"
            "U: chi è in casa?\n"
            "A: [TOOL: who_is_home]\nGuardo subito.\n\n"
            "U: che tempo fa domani a Ferrara?\n"
            "A: [TOOL: discover query=\"meteo Ferrara domani\" kind=\"article\"]\nVado a vedere.\n\n"
            "U: chi ha vinto Sanremo?\n"
            "A: [TOOL: discover query=\"vincitore Sanremo 2026\" kind=\"article\"]\nCerco subito.\n\n"
            "U: cos'è un buco nero?\n"
            "A: [TOOL: discover query=\"cos'è un buco nero\" kind=\"article\"]\nTi cerco una spiegazione.\n\n"
            "U: fammi ascoltare RAI Radio 1\n"
            "A: [TOOL: discover query=\"RAI Radio 1\" kind=\"audio_stream\"]\nLa metto su.\n\n"
            "U: trailer di Avatar 3\n"
            "A: [TOOL: discover query=\"trailer Avatar 3\" kind=\"video\"]\nLo cerco.\n\n"
            "U: ultima puntata di Caterpillar\n"
            "A: [TOOL: discover query=\"Caterpillar Rai Radio 2 podcast\" kind=\"podcast\"]\nVado a prenderla.\n\n"
            "U: ciao come stai\n"
            "A: Ciao! Tutto bene, e tu? Come posso aiutarti?\n\n"

            "## CHE COSA SAI FARE (per quando ti chiedono)\n"
            "- chiacchierare e ricordare la conversazione\n"
            "- gestire la lista delle cose da fare\n"
            "- gestire la lista della spesa\n"
            "- salvare note\n"
            "- dirti chi è in casa (riconoscimento facciale)\n"
            "- analizzare file allegati (PDF, DOCX, TXT, CSV, XLSX)\n"
            "- cercare su internet: meteo, news, radio, podcast, video, articoli, "
            "definizioni, orari, prezzi e altro (con il tool discover)\n\n"

            "## REGOLE DI QUALITÀ\n"
            "- Rispondi alla domanda specifica, non a una simile.\n"
            "- Quando non sai un fatto preciso, USA discover (non rifiutare).\n"
            "- Non inventare nomi, date, numeri.\n"
            "- Se l'utente ti ha già corretto, non ripetere lo stesso errore."
        ),
        validation_alias="LLM_SYSTEM_PROMPT",
    )


settings = Settings()  # type: ignore[call-arg]
