"""Prompt-building helpers extracted from `chat.py`.

These are the pure functions that turn a typed request into the string
the LLM consumes:

- `render_qwen_prompt(messages)` → Qwen2.5 chat template.
- `runtime_context_message()` → a system message with today's date/time
  + day-name + days-to-next-Christmas / -New-Year (the 1.5B can't do
  date arithmetic, see comment in the function).
- Persona tone directives + Italian weekday/month names.

Kept under-200 lines so the file stays diff-friendly. No imports from
SQLAlchemy / FastAPI / RKLLM here — these helpers are deterministic
text builders the chat hot path stitches together.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from cara.schemas.chat import ChatMessage


_IM_START = "<|im_start|>"
_IM_END = "<|im_end|>"


def render_qwen_prompt(messages: list[ChatMessage]) -> str:
    """Format `messages` using Qwen2.5's chat template + open the assistant turn."""
    parts: list[str] = []
    for m in messages:
        parts.append(f"{_IM_START}{m.role}\n{m.content}{_IM_END}\n")
    parts.append(f"{_IM_START}assistant\n")
    return "".join(parts)


# Persona tone presets — appended to the system prompt and (in privacy mode)
# also drop the historical messages from the prompt, mirroring Lumo's three
# tones (normale / neutro / sarcastico). Reset on every restart of the
# backend container is fine: this is intentionally non-persistent at the
# message layer (the key is in admin_settings, but no per-conversation
# override).
TONE_DIRECTIVE: dict[str, str] = {
    "default": "",
    "privacy": (
        "\n\n## MODALITÀ PRIVACY ATTIVA\n"
        "Non usare il nome dell'utente. Non fare riferimento alla cronologia. "
        "Rispondi al turno corrente con il minimo di informazioni necessarie. "
        "Niente domande personali, niente memorie."
    ),
    "playful": (
        "\n\n## MODALITÀ SCHERZOSA ATTIVA\n"
        "Aggiungi un tocco di leggerezza e ironia gentile alle risposte, ma "
        "senza esagerare. Niente sarcasmo cattivo, niente prese in giro. "
        "Pensa a una zia simpatica che racconta cose. Resta concisa."
    ),
}


WEEKDAYS_IT: list[str] = [
    "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica",
]
MONTHS_IT: list[str] = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]


# Used after CDA grounding to constrain the second-pass output. See the
# `_GROUNDING` agent-loop block in chat.py.
AGENT_GROUNDING_SUFFIX = (
    "## REGOLE PER LA RISPOSTA — RISPETTA TUTTE\n"
    "1. Usa SOLO le informazioni dell'articolo qui sopra. Non aggiungere fatti, "
    "termini o dettagli che non sono testualmente nell'articolo.\n"
    "2. Rispondi in italiano corretto, in 2 frasi MASSIME (max 60 parole).\n"
    "3. NON inventare parole nuove, NON italianizzare termini stranieri, "
    "NON tradurre se non serve.\n"
    "4. Se l'articolo NON contiene la risposta, dì esattamente: "
    "\"Non ho trovato la risposta nell'articolo.\" e fermati.\n"
    "5. NON emettere [TOOL: ...] in questa risposta.\n"
    "6. NON citare la fonte con frasi tipo \"(fonte: ...)\" — viene aggiunta "
    "automaticamente.\n"
    "7. Inizia direttamente con la risposta, senza preamboli."
)


def runtime_context_message() -> str:
    """Date, time and timezone — injected into the prompt as a system message
    on every turn so the model knows where/when it is.

    Without this, the 1.5B happily anchors to its training-data cutoff
    (e.g. "oggi è il 28 settembre 2023") and refuses date queries on the
    grounds that "non ho accesso alla data corrente".

    We pre-compute common derivations (current month name, days to Christmas,
    days to next New Year's Eve) because the 1.5B can't do date arithmetic
    reliably — observed in QA "tra quanto tempo è Natale?" → "tra 19 giorni
    e 4 giorni" (nonsense), and "in che mese siamo?" → "siamo in marzo"
    even with the date already shown.
    """
    now = datetime.now(ZoneInfo("Europe/Rome"))
    today_date = now.date()

    # Next Christmas / New Year (this year if not yet passed, else next year).
    christmas_year = now.year if today_date <= date(now.year, 12, 25) else now.year + 1
    days_to_xmas = (date(christmas_year, 12, 25) - today_date).days
    new_year_target = (
        date(now.year + 1, 1, 1) if today_date > date(now.year, 1, 1)
        else date(now.year, 1, 1)
    )
    days_to_new_year = (new_year_target - today_date).days

    return (
        "## CONTESTO RUNTIME (informazioni precise, NON cercare su internet, NON ricalcolare)\n"
        f"- Oggi è {WEEKDAYS_IT[now.weekday()]} {now.day} {MONTHS_IT[now.month - 1]} {now.year}.\n"
        f"- Mese corrente: {MONTHS_IT[now.month - 1]}. Anno corrente: {now.year}.\n"
        f"- Ora attuale: {now.hour:02d}:{now.minute:02d} (fuso Europe/Rome, Italia).\n"
        f"- Giorni mancanti al prossimo Natale (25 dicembre): {days_to_xmas}.\n"
        f"- Giorni mancanti al prossimo Capodanno (1 gennaio): {days_to_new_year}.\n"
        "Per domande su \"che giorno/ora/mese/anno è\", \"tra quanto tempo è Natale\", "
        "\"tra quanto è Capodanno\" rispondi DIRETTAMENTE con il dato sopra, "
        "SENZA usare il tool discover e SENZA fare aritmetica tu stesso."
    )
