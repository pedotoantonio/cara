# Cap 14 — Workflow (Receipt, Bill, Recipe)

> *Sintesi 30 secondi.* Un workflow è una pipeline strutturata
> `classify → extract → propose → execute` che gestisce contenuti
> complessi tipo scontrini, bollette, ricette. CARA ne ha tre concreti
> + un sistema di "auto-confirm trust streak" che evita di chiedere
> conferma se hai già accettato 3 volte di seguito lo stesso pattern.

## 14.1 Cos'è un workflow

Un **workflow** è diverso da una **skill**:

| | Skill | Workflow |
|---|---|---|
| Definizione | JSON in DB | Classe Python |
| Pattern | Lineare (step1 → step2 → step3) | 4 fasi strutturate |
| Input | Testo utente | Bytes / URL / OCR text |
| Output | Risposta canned | Lista azioni proposte |
| User confirm | Implicito | Esplicito (con auto-confirm streak) |

Esempio: scontrino della spesa.

```
1. CLASSIFY    → "questo testo è uno scontrino?" → confidence 0.92
2. EXTRACT     → ocr → riconosci items + prezzi + categorie
3. PROPOSE     → 5 azioni: aggiungi expense (cat=alimentari, 23.50€), ...
4. EXECUTE     → l'utente conferma → tutte le azioni vengono eseguite
```

CARA ha 3 workflow oggi: **Receipt** (scontrino), **Bill** (bolletta),
**Recipe** (ricetta).

## 14.2 Pattern unificato — `cara.workflows.base`

**File**: `cara/workflows/base.py`.

Il `Workflow` Protocol:

```python
class Workflow(Protocol):
    name: str         # "receipt"
    version: str      # "1.0.0"

    async def classify(self, input: WorkflowInput) -> ClassifyResult:
        """Decide se il workflow gestisce questo input."""

    async def extract(self, input: WorkflowInput, hint: ClassifyResult) -> StructuredData:
        """Estrai i dati strutturati."""

    async def propose(self, data: StructuredData, *, user_id: int) -> list[ProposedAction]:
        """Quali azioni applicheresti."""

    async def execute(self, actions: list[ProposedAction], *,
                      user_id: int, session: AsyncSession) -> ExecutionResult:
        """Applicale (in transazione)."""
```

**Dataclass tipi**:

```python
@dataclass
class WorkflowInput:
    kind: str                # "image_bytes" | "url" | "text" | ...
    payload: Any              # bytes / str / dict
    user_id: int
    conversation_id: str | None

@dataclass
class ClassifyResult:
    matches: bool
    confidence: float        # 0.0..1.0
    reason: str              # human-readable
    hints: dict             # info passati a extract()

@dataclass
class StructuredData:
    kind: str               # "receipt" | "bill" | "recipe"
    data: dict              # forma libera per workflow
    confidence: float
    raw_text: str | None    # source da cui è stato estratto

@dataclass
class ProposedAction:
    tool: str                # "add_expense" | "add_shopping_bulk" | ...
    args: dict
    summary: str            # cosa farà, in 1 riga IT
    reversible: bool        # bool: può essere annullata?

class ExecutionResult:
    @classmethod
    def success(cls, executed: list, failed: list = ()) -> ExecutionResult: ...
    @classmethod
    def failure(cls, error: str, partial: list = ()) -> ExecutionResult: ...
```

**Registry**: `WorkflowRegistry` ha tutti i workflow registrati.
`classify_first_match(input, min_confidence=0.5)` itera e ritorna il
primo che matcha.

## 14.3 ReceiptWorkflow — scontrini

**File**: `cara/workflows/receipt.py`.

**Input**: `image_bytes` (foto scontrino) o `text` (raw OCR).

**Classify**:
- Cerca pattern italiani tipici scontrino: TOTALE, IVA, P.IVA,
  data formato `gg/mm/aaaa`, importi in `€,XX`
- Confidence basato su quanti pattern matchano

**Extract**:
- OCR via `cara.ai.ocr` (Tesseract italian + preprocessing)
- Parser regex IT per linee items: `nome ... NUM,NUM`
- Detect totale, IVA, store name (top-3 righe in font grande)
- Categoria spesa: euristica su keyword (`pasta`, `pane` → alimentari;
  `farmaco` → salute; ecc.)

**Propose**: una `add_expense` per ogni item (o uno aggregato se
items > 20).

```python
# Esempio output
[
  ProposedAction(tool="add_expense", args={
      "amount_cents": 350, "category": "alimentari", "vendor": "Conad",
      "description": "pasta De Cecco 500g", "spent_on": "2026-05-07"
  }, summary="Aggiungi spesa: pasta 3.50€ (alimentari)", reversible=True),
  # ... altri items
]
```

**Execute**: transazione DB. Tutti gli `add_expense` insieme; rollback
se uno fallisce.

## 14.4 BillWorkflow — bollette

**File**: `cara/workflows/bill.py`.

**Input**: PDF / immagine / text di una bolletta luce/gas/acqua/internet.

**Classify**: pattern provider noti (Enel, ENI, A2A, TIM, Vodafone),
"cliente", "scadenza", "totale da pagare".

**Extract**:
- Provider name (top of page)
- Totale (cerca "TOTALE DA PAGARE" + amount)
- Scadenza (cerca "Scadenza" + data)
- Numero contratto (se presente)
- Periodo (es. "marzo 2026")

**Propose**: due azioni:

```python
[
  ProposedAction(tool="add_task", args={
      "title": f"Pagare bolletta {provider} {periodo} ({total}€)",
      "due_date": "2026-05-25T23:59:00"
  }, summary="Crea task pagamento", reversible=True),
  ProposedAction(tool="add_pending_expense", args={
      "amount_cents": ...,
      "category": "utenze",
      "vendor": provider,
      "description": f"bolletta {periodo}",
      "spent_on": "2026-05-25"  # data scadenza, da rifinire al pagamento
  }, summary="Pre-registra spesa pending", reversible=True),
]
```

## 14.5 RecipeWorkflow — ricette

**File**: `cara/workflows/recipe.py`.

**Input**:
- **URL** (link a ricetta) → trafilatura
- **Foto** (cookbook scansionato) → OCR
- **Testo** (utente ha incollato la ricetta)

**Classify**: pattern "ingredienti" + "preparazione" + lista bullet.

**Extract**: titolo + lista ingredienti + numero porzioni + tempi.

**Propose**: una `add_shopping_bulk` con la lista ingredienti pulita
(rimuovi quantità e unità, lascia solo nome).

```python
[
  ProposedAction(tool="add_shopping_bulk", args={
      "titles": ["pasta", "pomodoro", "basilico", "mozzarella"]
  }, summary="Aggiungi 4 ingredienti alla spesa", reversible=True),
]
```

## 14.6 Auto-confirm trust streak

**File**: `cara/workflows/auto_confirm.py` + `cara/models/workflow_trust.py`.

**Idea**: se l'utente ha accettato 3 volte di seguito un workflow per
lo stesso "pattern" senza modifiche, smetti di chiedere conferma.

**Esempio**: Antonio scannerizza 3 scontrini Conad di seguito con
ReceiptWorkflow. Tutti accettati senza modifiche. Al quarto, CARA
applica direttamente senza confirm.

**Modello DB**:

```python
class WorkflowTrust(Base):
    user_id: int
    workflow_name: str        # "receipt"
    signature: str            # hash del pattern (vendor=Conad, count=~10 items)
    streak_count: int         # 3+ → auto-confirm
    last_confirmed_at: datetime
    enabled: bool
```

**Signature**: hash deterministico basato su vendor + numero items
+ categoria predominante. Cosi due scontrini Conad simili hanno la
stessa signature; uno scontrino Esselunga ha signature diversa.

**API**:

```python
from cara.workflows.auto_confirm import should_auto_confirm

if await should_auto_confirm(session, user_id, workflow_name, signature):
    # esegui direttamente
else:
    # chiedi conferma all'utente
```

**Reset**: `auto_confirm_revoke(user_id, workflow_name, signature)` —
se l'utente disconferma una volta, lo streak ricade a 0.

## 14.7 Endpoint REST — `cara.api.v1.workflows`

**File**: `cara/api/v1/workflows.py`.

| Endpoint | Method | Cosa fa |
|---|---|---|
| `/workflows/run` | POST | Esegui pipeline completa (classify→propose) |
| `/workflows/execute` | POST | Conferma + esegui le proposed actions |
| `/workflows/trust` | GET | Lista trust streak utente |
| `/workflows/trust/{id}` | DELETE | Revoca trust per signature |

### POST /workflows/run

Body:

```json
{
  "kind": "image_bytes",
  "payload": "<base64 PNG>",
  "conversation_id": "uuid-opt"
}
```

Response:

```json
{
  "matched_workflow": "receipt",
  "confidence": 0.92,
  "structured_data": { "store": "Conad", "items": [...] },
  "proposed_actions": [
    {"tool": "add_expense", "args": {...}, "summary": "...", "reversible": true}
  ],
  "auto_confirm": false,
  "signature": "sha256:abc..."
}
```

Se `auto_confirm=true`, le actions sono già state eseguite (e
`/run` ritorna anche `executed`). Altrimenti il frontend mostra
preview e chiede conferma.

### POST /workflows/execute

Body:

```json
{
  "matched_workflow": "receipt",
  "actions": [...],     // dalla response di /run, eventualmente editate
  "signature": "sha256:abc..."
}
```

Esegue le actions in transazione. Aggiorna lo streak counter.

## 14.8 Frontend — `WorkflowPreview`

**File**: `frontend/src/components/WorkflowPreview.tsx`.

Quando un workflow è attivato (es. utente ha caricato una foto), il
componente:

1. Mostra le proposed actions in card preview
2. Per ogni action: checkbox (default ON) + edit del summary
3. Pulsante "Esegui" → `/workflows/execute` con array filtrato
4. Mostra risultato (success/fail per action)

UX: l'utente può deselezionare azioni che non vuole, o editare i
parametri, prima di eseguire.

## 14.9 Tutorial — workflow custom

Esempio: "ParcheggioWorkflow" che riceve foto del biglietto parcheggio
e crea un task "scadenza parcheggio".

**1. Crea la classe**:

```python
# cara/workflows/parking.py
import re
from cara.workflows.base import (
    Workflow, WorkflowInput, ClassifyResult, StructuredData,
    ProposedAction, ExecutionResult,
)

class ParkingWorkflow:
    name = "parking"
    version = "0.1.0"

    async def classify(self, input: WorkflowInput) -> ClassifyResult:
        text = input.payload if input.kind == "text" else ""
        if input.kind == "image_bytes":
            from cara.ai.ocr import OCRService
            text = (await OCRService().recognize(input.payload)).text

        markers = ("parcheggio", "ZTL", "scadenza", "h:", "min")
        matches = sum(1 for m in markers if m.lower() in text.lower())
        return ClassifyResult(
            matches=matches >= 3,
            confidence=min(0.4 + 0.15 * matches, 0.95),
            reason=f"{matches}/{len(markers)} markers",
            hints={"raw_text": text},
        )

    async def extract(self, input, hint):
        text = hint.hints.get("raw_text", "")
        # cerca formato "23/05/2026 14:30" come scadenza
        m = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{1,2}[:.]\d{2})", text)
        scadenza = m.group(0) if m else None
        return StructuredData(
            kind="parking",
            data={"scadenza": scadenza},
            confidence=0.8 if scadenza else 0.3,
            raw_text=text,
        )

    async def propose(self, data, *, user_id):
        if not data.data.get("scadenza"):
            return []
        return [ProposedAction(
            tool="add_task",
            args={
                "title": f"Scadenza parcheggio {data.data['scadenza']}",
                "due_date": _to_iso(data.data["scadenza"]),
            },
            summary=f"Crea task: scadenza {data.data['scadenza']}",
            reversible=True,
        )]

    async def execute(self, actions, *, user_id, session):
        from cara.services.tasks import create_task
        executed, failed = [], []
        for a in actions:
            try:
                t = await create_task(session, user_id=user_id, **a.args)
                executed.append({"tool": a.tool, "id": str(t.id)})
            except Exception as exc:
                failed.append({"tool": a.tool, "error": str(exc)})
        await session.commit()
        return ExecutionResult.success(executed=executed, failed=failed)
```

**2. Registra**: edita `cara/workflows/__init__.py`:

```python
from cara.workflows.parking import ParkingWorkflow
from cara.workflows.base import get_default_registry

get_default_registry().register(ParkingWorkflow())
```

**3. Test unit**:

```python
@pytest.mark.asyncio
async def test_parking_classify_with_markers():
    wf = ParkingWorkflow()
    result = await wf.classify(WorkflowInput(
        kind="text",
        payload="Parcheggio ZTL — Scadenza 23/05/2026 h:14:30",
        user_id=1, conversation_id=None,
    ))
    assert result.matches
    assert result.confidence >= 0.7
```

**4. Restart + test live**:

```bash
docker restart cara-backend
# Carica una foto di parcheggio o testo OCR
curl -sk -X POST -H "Authorization: Bearer $TOK" \
  -F file=@parcheggio.jpg \
  https://192.168.1.23:8455/api/v1/workflows/run
```

## 14.10 Errori comuni

| Sintomo | Causa | Risoluzione |
|---|---|---|
| `classify` ritorna sempre `matches=False` | Markers troppo specifici | Allenta i pattern |
| OCR text vuoto | Tesseract non installato in container | Verifica `cv2` + `pytesseract` su immagine Docker |
| `execute` rollback su 1 errore | Transazione atomica voluta | Se vuoi best-effort, splitta in più transazioni |
| Auto-confirm fira sbagliato | Signature troppo generica | Aggiungi più feature alla signature (vendor + day_of_week + ...) |

---

[← Cap 13 CDA](13-cda.md) · [README](README.md) · [Cap 15 Multi-device →](15-multi-device.md)
