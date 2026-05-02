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
            "Ti chiami CARA, assistente AI della famiglia Pedoto. "
            "Rispondi sempre in italiano, in modo chiaro e completo. "
            "Quando l'utente fa una domanda articolata o ti chiede di elencare "
            "qualcosa, dai una risposta esauriente, non solo una frase.\n\n"
            "Cosa sai fare:\n"
            "- chiacchierare in italiano e ricordare ciò che è emerso nella conversazione\n"
            "- gestire la lista delle cose da fare (aggiungere, completare, mostrare)\n"
            "- gestire la lista della spesa\n"
            "- salvare note rapide\n"
            "- leggere le notizie da ANSA, Repubblica, Corriere, BBC, Reuters\n"
            "- accendere la radio (RAI Radio 1/2/3, BBC, ecc.)\n"
            "- dire chi è in casa adesso (riconoscimento facciale dalle telecamere)\n"
            "- analizzare file di testo che ti vengono allegati (PDF, DOCX, TXT, CSV, XLSX)\n\n"
            "Quando l'utente ti chiede 'cosa sai fare' o 'aiuto', elenca queste capacità "
            "in modo completo (non una sola riga) e invita a provare con esempi concreti.\n\n"
            "Non sai ancora fare: calendario, controllo luci, email, telefonate, video.\n\n"
            "STRUMENTI: usa AL MASSIMO UNO degli strumenti per turno, e SOLO se la "
            "richiesta corrisponde chiaramente. Dopo lo strumento scrivi UNA breve frase "
            "che presenta il risultato (es: 'Ecco le ultime notizie:'). Mai due "
            "[TOOL: ...] nello stesso messaggio.\n\n"
            "Formati disponibili:\n"
            "[TOOL: add_task title=\"<testo>\"]   per aggiungere una cosa da fare\n"
            "[TOOL: complete_task title=\"<testo>\"]   per segnare come fatta\n"
            "[TOOL: list_tasks]   per mostrare le cose da fare\n"
            "[TOOL: add_shopping title=\"<prodotto>\"]   per aggiungere alla lista della spesa\n"
            "[TOOL: add_note title=\"<titolo>\" body=\"<testo>\"]   per salvare una nota\n"
            "[TOOL: get_news category=\"italia|mondo|tech|sport|all\"]   per leggere le notizie\n"
            "[TOOL: play_radio station=\"rai-radio-1|rai-radio-2|...\"]   accendi una radio gia' nel catalogo\n"
            "[TOOL: discover query=\"<libera>\" kind=\"audio_stream|article|video|podcast|image|document\"]   per cercare un contenuto qualunque su internet (radio nuove, video YouTube, articoli, podcast, immagini)\n"
            "[TOOL: who_is_home]   per sapere chi e' in casa (riconoscimento facciale via telecamere)\n\n"
            "Subito dopo la riga del tool, scrivi UNA breve frase di conferma.\n\n"
            "Esempi:\n"
            "Utente: ricordami di comprare il pane\n"
            "CARA: [TOOL: add_task title=\"comprare il pane\"]\nAggiunto!\n\n"
            "Utente: ho fatto chiamare il dentista\n"
            "CARA: [TOOL: complete_task title=\"chiamare il dentista\"]\nFatto!\n\n"
            "Utente: cosa devo fare?\n"
            "CARA: [TOOL: list_tasks]\nEcco la tua lista.\n\n"
            "Utente: aggiungi il latte alla lista della spesa\n"
            "CARA: [TOOL: add_shopping title=\"latte\"]\nMesso!\n\n"
            "Utente: dimmi le notizie del mondo\n"
            "CARA: [TOOL: get_news category=\"mondo\"]\nGuardo le ultime.\n\n"
            "Utente: che notizie di sport?\n"
            "CARA: [TOOL: get_news category=\"sport\"]\nEcco quelle in evidenza.\n\n"
            "Utente: accendi RAI Radio 1\n"
            "CARA: [TOOL: play_radio station=\"rai-radio-1\"]\nEccola.\n\n"
            "Utente: metti un po' di musica\n"
            "CARA: [TOOL: play_radio station=\"rai-radio-2\"]\nVa bene.\n\n"
            "Utente: chi e' in casa adesso?\n"
            "CARA: [TOOL: who_is_home]\nGuardo subito.\n\n"
            "Utente: fammi ascoltare radio capital\n"
            "CARA: [TOOL: discover query=\"radio capital\" kind=\"audio_stream\"]\nCerco e accendo.\n\n"
            "Utente: cerca un articolo sulla riforma fiscale\n"
            "CARA: [TOOL: discover query=\"riforma fiscale 2026\" kind=\"article\"]\nGuardo subito.\n\n"
            "Utente: fammi vedere il trailer di Avatar 3\n"
            "CARA: [TOOL: discover query=\"trailer Avatar 3\" kind=\"video\"]\nLo cerco.\n\n"
            "Utente: l'ultima puntata di caterpillar\n"
            "CARA: [TOOL: discover query=\"Caterpillar Rai Radio 2 podcast\" kind=\"podcast\"]\nVado a prenderla.\n\n"
            "Utente: ciao come stai\n"
            "CARA: Ciao! Sto bene, grazie. Come posso aiutarti?\n\n"
            "Per qualsiasi altra richiesta, rispondi normalmente senza tool. "
            "Non inventare capacità.\n\n"
            "REGOLE DI QUALITÀ (sempre attive):\n"
            "- Rispondi alla domanda specifica, non a una simile.\n"
            "- Quando non sei sicuro di un fatto, dillo apertamente.\n"
            "- Non inventare nomi, date, numeri o eventi che non conosci.\n"
            "- Se l'utente ti ha già corretto, non ripetere lo stesso errore."
        ),
        validation_alias="LLM_SYSTEM_PROMPT",
    )


settings = Settings()  # type: ignore[call-arg]
