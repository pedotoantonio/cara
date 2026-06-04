"""Structured transcription of the dietista plan (single source of truth).

Everything in FOOD_ITEMS / DIET_RULES / RECIPES is a faithful transcription
of the two source PDFs:
  * "Indicazioni generali.pdf"
  * "Piano alimentare Antonio Pedoto.pdf"   (Dott.ssa Elena Poletti)

Two fields are EXTERNAL enrichment, by explicit choice (the PDFs don't
contain them), and are marked as such in each item's `notes`:
  * `kcal_per_100g`  → CREA food-composition table (indicative; the plan
                       treats calories as a SECONDARY metric).
  * `season_months`  → conventional Italian seasonal calendar.

To keep the catalog DRY, kcal and seasonality are looked up by name from
the KCAL_CREA / SEASON_IT maps below and merged in `build_food_items()`.
No food is invented: only items named in the PDFs are seeded.
"""

from __future__ import annotations

from typing import Any

# ─── EXTERNAL enrichment maps (NOT from the PDFs) ──────────────────

# kcal/100g — CREA (Centro di Ricerca Alimenti e Nutrizione) indicative
# values, raw/edible portion. Calories are a secondary metric here.
KCAL_CREA: dict[str, int] = {
    # carni
    "petto di pollo": 100, "petto di tacchino": 107, "vitello": 92,
    "manzo magro": 103, "maiale magro": 110, "coniglio": 118, "cavallo": 110,
    "prosciutto crudo magro dop": 159, "prosciutto cotto magro dop": 132,
    "coscia di pollo": 120, "coscia di tacchino": 121, "gallina": 194,
    "hamburger di carne magra": 172, "fagiano": 144, "lepre": 113,
    "cinghiale": 107, "capriolo": 120, "daino": 120,
    "salame": 400, "mortadella": 317, "pancetta": 337, "salsiccia": 304,
    "wurstel": 270, "coppa": 450, "ciccioli": 480, "cotechino": 307,
    "zampone": 320, "oca": 373, "anatra": 159, "paté di fegato": 327,
    # pesce
    "merluzzo": 71, "nasello": 71, "mormora": 90, "sogliola": 83,
    "trota": 86, "palombo": 80, "dentice": 100, "spigola": 82, "orata": 121,
    "rombo": 81, "scorfano": 82, "ombrina": 86, "seppia": 72, "calamaro": 68,
    "polpo": 57, "salmone selvaggio": 185, "tinca": 78, "tonno fresco": 159,
    "aragosta": 85, "pesce spada": 118, "acciuga": 96, "alice": 96,
    "carpa": 138, "sardine": 129, "salmone allevato": 198, "sgombro": 170,
    "gamberi": 71, "anguilla": 261, "aringa": 217, "baccalà": 122,
    "stoccafisso": 117, "scampi": 92, "ostriche": 69, "vongole": 72,
    "cozze": 84, "granchio": 84,
    # legumi (secchi)
    "fagioli secchi": 291, "piselli secchi": 286, "lenticchie secche": 325,
    "soia": 398,
    # uova
    "uova": 128, "albume": 43,
    # formaggi
    "ricotta vaccina": 146, "fiocchi di formaggio magro": 98,
    "caciottina fresca": 380, "stracchino": 300, "crescenza": 281,
    "fior di latte": 268, "feta": 250, "formaggio spalmabile light": 180,
    "mozzarella": 253, "parmigiano": 387, "grana": 384, "pecorino": 387,
    "gorgonzola": 324, "taleggio": 315, "groviera": 389, "robiola": 305,
    "asiago": 380, "emmenthal": 403, "scamorza": 334, "provolone": 366,
    "formaggini": 309, "burrini": 700, "mascarpone": 450, "caciocavallo": 439,
    # cereali / pane
    "pasta integrale": 348, "riso integrale": 337, "farro": 335, "orzo": 319,
    "quinoa": 343, "cous cous integrale": 376, "grano saraceno": 314,
    "miglio": 360, "pane integrale": 224, "fette biscottate": 408,
    # condimenti
    "olio extra vergine di oliva": 899, "olio di girasole": 899,
    "olio di mais": 899, "olio di soia": 899, "olio di arachidi": 899,
    "burro": 758, "lardo": 891, "strutto": 891, "panna": 337,
    "margarina": 760, "olio di palma": 899, "olio di cocco": 892,
    "maionese": 655, "brodo di carne non sgrassato": 36,
    # frutta
    "amarene": 38, "ananas": 40, "cachi": 70, "ciliegie": 38, "fico": 47,
    "more": 36, "susine": 42, "banana": 65, "kiwi": 44, "mandarini": 72,
    "mandaranci": 53, "mango": 53, "melograno": 63, "uva": 64,
    "albicocche": 28, "arance": 47, "fragole": 27, "lamponi": 34, "mele": 45,
    "melone": 33, "mirtilli": 25, "pesca": 27, "pompelmo": 26, "prugna": 42,
    "pere": 41, "cocomero": 16,
    # verdura
    "zucchine": 11, "peperoni": 22, "spinaci": 31, "zucca": 18,
    "cipolla rossa": 26, "pomodorini": 19, "olive": 145, "carota": 35,
    "sedano": 20, "patate": 85, "polenta": 362,
    # colazione / spuntino
    "yogurt greco": 133, "skyr": 63, "latte scremato": 36, "miele": 304,
    "marmellata": 222, "crema 100% frutta secca": 600, "burro chiarificato": 900,
    "cereali": 370, "noci": 689, "mandorle": 603, "nocciole": 655,
    "cioccolato fondente": 545, "cocco": 364, "cracker": 428, "gallette": 387,
    "taralli": 470, "grissini": 433, "pop-corn": 387, "barretta ai cereali": 400,
    "biscotti secchi": 416, "biscotti frollini": 470, "succo di frutta": 46,
}

# Italian seasonal calendar — months (1-12) when the produce is in season
# in Italy. None = available year-round or exotic/import (no strict season).
SEASON_IT: dict[str, list[int] | None] = {
    # frutta
    "amarene": [5, 6, 7], "ciliegie": [5, 6, 7], "ananas": None,
    "cachi": [10, 11, 12], "fico": [8, 9], "more": [7, 8, 9],
    "susine": [7, 8, 9], "banana": None, "kiwi": [11, 12, 1, 2, 3, 4],
    "mandarini": [11, 12, 1, 2], "mandaranci": [11, 12, 1], "mango": None,
    "melograno": [10, 11, 12], "uva": [9, 10, 11], "albicocche": [6, 7],
    "arance": [12, 1, 2, 3, 4], "fragole": [4, 5, 6], "lamponi": [6, 7, 8, 9],
    "mele": [8, 9, 10, 11, 12, 1, 2, 3], "melone": [6, 7, 8, 9],
    "mirtilli": [6, 7, 8, 9], "pesca": [6, 7, 8, 9],
    "pompelmo": [12, 1, 2, 3, 4], "prugna": [7, 8, 9],
    "pere": [8, 9, 10, 11, 12], "cocomero": [6, 7, 8],
    # verdura
    "zucchine": [5, 6, 7, 8, 9, 10], "peperoni": [6, 7, 8, 9, 10],
    "spinaci": [10, 11, 12, 1, 2, 3, 4], "zucca": [9, 10, 11, 12, 1],
    "cipolla rossa": None, "pomodorini": [6, 7, 8, 9], "olive": [10, 11],
    "carota": None, "sedano": None, "patate": None,
}

# Fruit explicitly flagged "esotica" by the plan ("limitare frutta esotica").
ESOTICI = {"ananas", "banana", "mango", "mandaranci"}


# ─── Helpers ───────────────────────────────────────────────────────


def _enrich(name: str, base_note: str) -> dict[str, Any]:
    """Attach external kcal + seasonality (with provenance) to a food."""
    key = name.lower()
    notes = [base_note]
    kcal = KCAL_CREA.get(key)
    season = SEASON_IT.get(key, "__missing__")
    if kcal is not None:
        notes.append(f"kcal/100g {kcal} (CREA, esterno, indicativo)")
    months = None
    if season != "__missing__":
        months = season
        notes.append("stagionalità: calendario IT (esterno)")
    if key in ESOTICI:
        notes.append("frutta esotica — da limitare")
    return {
        "kcal_per_100g": kcal,
        "season_months": months,
        "notes": " · ".join(notes),
    }


def _items(
    names: list[str],
    *,
    status: str,
    protein_category: str | None,
    default_portion_g: int | None = None,
    portion_primo_g: int | None = None,
    portion_secondo_g: int | None = None,
    note: str,
) -> list[dict[str, Any]]:
    out = []
    for n in names:
        item = {
            "name": n,
            "status": status,
            "protein_category": protein_category,
            "default_portion_g": default_portion_g,
            "portion_primo_g": portion_primo_g,
            "portion_secondo_g": portion_secondo_g,
        }
        item.update(_enrich(n, note))
        out.append(item)
    return out


# ─── FOOD_ITEMS (transcribed from the PDFs) ────────────────────────

FOOD_ITEMS: list[dict[str, Any]] = []

# CARNI — porzioni di categoria: primo 100g / secondo 220g (affettato 80/150)
FOOD_ITEMS += _items(
    ["coniglio", "petto di pollo", "petto di tacchino", "vitello",
     "manzo magro", "maiale magro", "cavallo"],
    status="consigliato", protein_category="carne",
    default_portion_g=220, portion_primo_g=100, portion_secondo_g=220,
    note="carne — taglio magro (consigliato)",
)
FOOD_ITEMS += _items(
    ["prosciutto crudo magro dop", "prosciutto cotto magro dop"],
    status="consigliato", protein_category="carne",
    default_portion_g=150, portion_primo_g=80, portion_secondo_g=150,
    note="affettato DOP magro — max 1 affettato/sett",
)
FOOD_ITEMS += _items(
    ["coscia di pollo", "coscia di tacchino", "gallina",
     "hamburger di carne magra", "fagiano", "lepre", "cinghiale",
     "capriolo", "daino"],
    status="da_moderare", protein_category="carne",
    default_portion_g=220, portion_primo_g=100, portion_secondo_g=220,
    note="carne da moderare — max 1 ogni 15 giorni, in sostituzione",
)
FOOD_ITEMS += _items(
    ["salame", "mortadella", "pancetta", "salsiccia", "wurstel", "coppa",
     "ciccioli", "cotechino", "zampone", "oca", "anatra", "paté di fegato"],
    status="sconsigliato", protein_category="carne",
    note="carne sconsigliata dal piano",
)

# PESCE — porzioni di categoria: primo 125g / secondo 250g
FOOD_ITEMS += _items(
    ["merluzzo", "nasello", "mormora", "sogliola", "trota", "palombo",
     "dentice", "spigola", "orata", "rombo", "scorfano", "ombrina",
     "salmone selvaggio", "tinca", "tonno fresco"],
    status="consigliato", protein_category="pesce",
    default_portion_g=250, portion_primo_g=125, portion_secondo_g=250,
    note="pesce consigliato (pescato, non allevato)",
)
FOOD_ITEMS += _items(
    ["seppia", "calamaro", "polpo", "aragosta"],
    status="consigliato", protein_category="pesce",
    default_portion_g=250, portion_primo_g=125, portion_secondo_g=250,
    note="mollusco/crostaceo consigliato — max 1 volta/sett tra molluschi e crostacei",
)
FOOD_ITEMS += _items(
    ["pesce spada", "acciuga", "alice", "carpa", "sardine",
     "salmone allevato", "sgombro", "gamberi"],
    status="da_moderare", protein_category="pesce",
    default_portion_g=250, portion_primo_g=125, portion_secondo_g=250,
    note="pesce da moderare — max 1 ogni 15 giorni, in sostituzione",
)
FOOD_ITEMS += _items(
    ["anguilla", "aringa", "baccalà", "stoccafisso", "scampi", "ostriche",
     "vongole", "cozze", "granchio"],
    status="sconsigliato", protein_category="pesce",
    note="pesce/prodotto ittico sconsigliato dal piano",
)

# LEGUMI — solo quelli citati nel piano. Primo 35g secco/100 fresco;
# secondo 70g secco/220 fresco.
FOOD_ITEMS += _items(
    ["fagioli secchi", "lenticchie secche", "piselli secchi", "soia"],
    status="consigliato", protein_category="legumi",
    default_portion_g=70, portion_primo_g=35, portion_secondo_g=70,
    note="legumi (grammatura a secco; freschi 100g primo / 220g secondo)",
)

# UOVA — primo 100g (2 uova) / secondo 200g (4 uova, fino a 4 con albume)
FOOD_ITEMS += _items(
    ["uova"],
    status="consigliato", protein_category="uova",
    default_portion_g=100, portion_primo_g=100, portion_secondo_g=200,
    note="6-8 uova/sett come pietanza + max 1-2 'nascoste'; pasta all'uovo = 1 uovo",
)
FOOD_ITEMS += _items(
    ["albume"],
    status="consigliato", protein_category="uova",
    default_portion_g=150,
    note="albume senza grassi — utilizzabile più liberamente",
)

# FORMAGGI — 4 gruppi con porzioni specifiche (override per-alimento).
FOOD_ITEMS += _items(
    ["ricotta vaccina", "fiocchi di formaggio magro"],
    status="consigliato", protein_category="formaggio",
    default_portion_g=50, portion_primo_g=25, portion_secondo_g=50,
    note="formaggio magro — unico secondo, -1 cucchiaino olio; max 2 formaggi/sett",
)
FOOD_ITEMS += _items(
    ["caciottina fresca", "stracchino", "crescenza", "fior di latte", "feta",
     "formaggio spalmabile light", "mozzarella"],
    status="consigliato", protein_category="formaggio",
    default_portion_g=200, portion_primo_g=100, portion_secondo_g=200,
    note="formaggio fresco — unico secondo, -1 cucchiaino olio; max 2 formaggi/sett",
)
FOOD_ITEMS += _items(
    ["parmigiano", "grana", "pecorino", "gorgonzola", "taleggio", "groviera",
     "robiola", "asiago", "emmenthal", "scamorza", "provolone", "formaggini"],
    status="da_moderare", protein_category="formaggio",
    default_portion_g=150, portion_primo_g=80, portion_secondo_g=150,
    note="formaggio stagionato/grasso — unico secondo, -1 cucchiaino olio; max 2/sett",
)
FOOD_ITEMS += _items(
    ["burrini", "mascarpone", "caciocavallo"],
    status="sconsigliato", protein_category="formaggio",
    note="formaggio sconsigliato dal piano",
)

# CEREALI / CARBOIDRATI — primo 70g; pane 60g (45g cereale / 40g forno a cena)
FOOD_ITEMS += _items(
    ["pasta integrale", "riso integrale", "farro", "orzo", "quinoa",
     "cous cous integrale", "grano saraceno", "miglio"],
    status="consigliato", protein_category=None,
    default_portion_g=70, portion_primo_g=70,
    note="cereale del primo (70g) — variare spesso; farine poco raffinate",
)
FOOD_ITEMS += _items(
    ["pane integrale"],
    status="consigliato", protein_category=None,
    default_portion_g=60,
    note="pane 60g col secondo (no pane se primo); =5 fette biscottate=7 biscotti secchi=40g cereali",
)

# CONDIMENTI
FOOD_ITEMS += _items(
    ["olio extra vergine di oliva"],
    status="consigliato", protein_category=None,
    default_portion_g=10,
    note="olio EVO a crudo, 2-3 cucchiaini/pasto (1 cucchiaino ~5g)",
)
FOOD_ITEMS += _items(
    ["olio di girasole", "olio di mais", "olio di soia", "olio di arachidi"],
    status="da_moderare", protein_category=None,
    note="condimento da moderare",
)
FOOD_ITEMS += _items(
    ["burro", "lardo", "strutto", "panna", "margarina", "olio di palma",
     "olio di cocco", "maionese", "brodo di carne non sgrassato"],
    status="sconsigliato", protein_category=None,
    note="condimento sconsigliato dal piano (anche fritti)",
)

# VERDURA — di stagione, almeno 200g cotta / 100g insalata
FOOD_ITEMS += _items(
    ["zucchine", "peperoni", "spinaci", "zucca", "cipolla rossa",
     "pomodorini", "carota", "sedano", "olive"],
    status="consigliato", protein_category=None,
    default_portion_g=200,
    note="verdura di stagione (≥200g cotta o ≥100g insalata)",
)
FOOD_ITEMS += _items(
    ["patate", "polenta"],
    status="da_moderare", protein_category=None,
    default_portion_g=200,
    note="contorno alternativo 1 volta/sett (no pane); 200g patate o 220g polenta cotta",
)

# FRUTTA — 100g / 150g / 300g; 2-3 porzioni/giorno
FOOD_ITEMS += _items(
    ["amarene", "ananas", "cachi", "ciliegie", "fico", "more", "susine",
     "banana", "kiwi", "mandarini", "mandaranci", "mango", "melograno", "uva"],
    status="consigliato", protein_category=None, default_portion_g=100,
    note="frutta — porzione ~100g",
)
FOOD_ITEMS += _items(
    ["albicocche", "arance", "fragole", "lamponi", "mele", "melone",
     "mirtilli", "pesca", "pompelmo", "prugna", "pere"],
    status="consigliato", protein_category=None, default_portion_g=150,
    note="frutta — porzione ~150g",
)
FOOD_ITEMS += _items(
    ["cocomero"],
    status="consigliato", protein_category=None, default_portion_g=300,
    note="frutta — porzione ~300g",
)

# COLAZIONE / SPUNTINO
FOOD_ITEMS += _items(
    ["yogurt greco", "skyr"],
    status="consigliato", protein_category=None, default_portion_g=150,
    note="solo latte e fermenti; linee proteiche non zuccherate ok",
)
FOOD_ITEMS += _items(
    ["latte scremato"],
    status="consigliato", protein_category=None, default_portion_g=200,
    note="una tazza ~200ml",
)
FOOD_ITEMS += _items(
    ["noci", "mandorle", "nocciole"],
    status="consigliato", protein_category=None, default_portion_g=20,
    note="frutta secca — spuntino 20g",
)
FOOD_ITEMS += _items(
    ["crema 100% frutta secca", "miele", "marmellata", "burro chiarificato"],
    status="consigliato", protein_category=None, default_portion_g=10,
    note="colazione, un velo; marmellata <35g zuccheri/100g",
)
FOOD_ITEMS += _items(
    ["cereali"],
    status="consigliato", protein_category=None, default_portion_g=40,
    note="colazione 40g; max 10-15g zuccheri/100g",
)
FOOD_ITEMS += _items(
    ["cioccolato fondente"],
    status="consigliato", protein_category=None, default_portion_g=20,
    note="fondente >85%, 20g; spuntino",
)
FOOD_ITEMS += _items(
    ["cocco"],
    status="consigliato", protein_category=None, default_portion_g=20,
    note="cocco fresco 25g / rapè 20g",
)
FOOD_ITEMS += _items(
    ["cracker", "gallette", "taralli", "grissini", "pop-corn"],
    status="consigliato", protein_category=None, default_portion_g=30,
    note="prodotti da forno — spuntino 30g; farine poco raffinate",
)
FOOD_ITEMS += _items(
    ["barretta ai cereali", "biscotti secchi", "biscotti frollini"],
    status="consigliato", protein_category=None,
    note="spuntino/colazione; biscotti secchi <30kcal, frollini 30-45kcal",
)
FOOD_ITEMS += _items(
    ["succo di frutta"],
    status="da_moderare", protein_category=None, default_portion_g=200,
    note="spremuta/succo 200ml — max 1-2 volte/sett",
)


# ─── Food group classification (for fruit/veg counting + intake) ───
# Coarse group per item. Protein foods derive from protein_category;
# the rest from curated name sets (the names above). Used to count
# fruit servings reliably and to break down intake.

_GROUP_FRUTTA = {
    "amarene", "ananas", "cachi", "ciliegie", "fico", "more", "susine",
    "banana", "kiwi", "mandarini", "mandaranci", "mango", "melograno", "uva",
    "albicocche", "arance", "fragole", "lamponi", "mele", "melone", "mirtilli",
    "pesca", "pompelmo", "prugna", "pere", "cocomero",
}
_GROUP_VERDURA = {
    "zucchine", "peperoni", "spinaci", "zucca", "cipolla rossa", "pomodorini",
    "carota", "sedano", "olive", "patate", "polenta",
}
_GROUP_CEREALE = {
    "pasta integrale", "riso integrale", "farro", "orzo", "quinoa",
    "cous cous integrale", "grano saraceno", "miglio", "pane integrale",
    "cereali", "cracker", "gallette", "taralli", "grissini", "pop-corn",
    "fette biscottate",
}
_GROUP_CONDIMENTO = {
    "olio extra vergine di oliva", "olio di girasole", "olio di mais",
    "olio di soia", "olio di arachidi", "burro", "lardo", "strutto", "panna",
    "margarina", "olio di palma", "olio di cocco", "maionese",
    "brodo di carne non sgrassato", "burro chiarificato",
}
_GROUP_LATTICINI = {"yogurt greco", "skyr", "latte scremato"}
_GROUP_FRUTTA_SECCA = {"noci", "mandorle", "nocciole", "crema 100% frutta secca", "cocco"}
_GROUP_DOLCE = {
    "cioccolato fondente", "miele", "marmellata", "barretta ai cereali",
    "biscotti secchi", "biscotti frollini",
}
_GROUP_BEVANDA = {"succo di frutta"}


def _food_group(item: dict[str, Any]) -> str:
    pc = item["protein_category"]
    if pc == "formaggio":
        return "latticini"
    if pc in ("legumi", "pesce", "carne", "uova"):
        return "proteina"
    name = item["name"]
    if name in _GROUP_FRUTTA:
        return "frutta"
    if name in _GROUP_VERDURA:
        return "verdura"
    if name in _GROUP_CEREALE:
        return "cereale"
    if name in _GROUP_CONDIMENTO:
        return "condimento"
    if name in _GROUP_LATTICINI:
        return "latticini"
    if name in _GROUP_FRUTTA_SECCA:
        return "frutta_secca"
    if name in _GROUP_DOLCE:
        return "dolce"
    if name in _GROUP_BEVANDA:
        return "bevanda"
    return "altro"


for _item in FOOD_ITEMS:
    _item["food_group"] = _food_group(_item)


# ─── DIET_RULES (editable; transcribed from the PDFs) ──────────────
# period: week (frequency) | day (intake) | None (textual guideline)

DIET_RULES: list[dict[str, Any]] = [
    # Frequenze proteiche (su ~14 pasti principali/sett)
    {"category": "legumi", "target_min": 3, "target_max": 4, "period": "week",
     "portion_primo_g": 35, "portion_secondo_g": 70,
     "portion_note": "Primo 35g secchi/100g freschi · Secondo 70g secchi/220g freschi"},
    {"category": "pesce", "target_min": 3, "target_max": 4, "period": "week",
     "portion_primo_g": 125, "portion_secondo_g": 250,
     "portion_note": "Primo 125g · Secondo 250g · max 1 volta molluschi/crostacei"},
    {"category": "carne", "target_min": 3, "target_max": 4, "period": "week",
     "portion_primo_g": 100, "portion_secondo_g": 220,
     "portion_note": "Primo 100g (affettato 80g) · Secondo 220g (affettato 150g) · max 1 affettato"},
    {"category": "uova", "target_min": 1, "target_max": 2, "period": "week",
     "portion_primo_g": 100, "portion_secondo_g": 200,
     "portion_note": "Primo 100g (2 uova) · Secondo fino a 200g (4 uova con albume) · 6-8 uova/sett tot"},
    {"category": "formaggio", "target_min": 0, "target_max": 2, "period": "week",
     "portion_primo_g": None, "portion_secondo_g": None,
     "portion_note": "Massimo 2/sett · unico secondo (no carne/pesce/uova) · -1 cucchiaino olio"},
    # Regole speciali / modificatori di contesto
    {"category": "pizza_piadina", "target_min": 0, "target_max": 1, "period": "week",
     "portion_note": "1/sett, piatto unico, conta come FORMAGGIO; stesso giorno → secondo con verdura + ½ pane"},
    {"category": "dolce", "target_min": 0, "target_max": 1, "period": "week",
     "portion_note": "1/sett, preferibilmente in giornate senza altri extra"},
    {"category": "aperitivo", "target_min": 0, "target_max": 2, "period": "week",
     "portion_note": "max 1-2/sett; 3-4 pezzetti focaccia/pizzette; pasto dopo = secondo+verdura, no pane; no salatini/salse"},
    {"category": "patate_polenta", "target_min": 0, "target_max": 1, "period": "week",
     "portion_secondo_g": 200,
     "portion_note": "200g patate o 220g polenta cotta 1/sett come contorno, no pane; gnocchi 200g 1/15gg al posto della pasta"},
    {"category": "ristorante", "target_min": None, "target_max": None, "period": None,
     "portion_note": "max 2 portate, verdura sempre presente, poco pane, secondi semplici"},
    {"category": "allenamento_serale", "target_min": None, "target_max": None, "period": None,
     "portion_note": "salta spuntino pomeriggio, cena 18:00-18:30, spuntino (frutta + 1 opzione) al rientro"},
    # Intake giornaliero
    {"category": "acqua", "target_min": 1500, "target_max": 2000, "period": "day",
     "portion_note": "1,5-2 L/giorno frazionati; infusi non zuccherati ok"},
    {"category": "caffe", "target_min": 0, "target_max": 3, "period": "day",
     "portion_note": "max 2-3 tazzine non zuccherate/giorno"},
    {"category": "olio", "target_min": 2, "target_max": 3, "period": "day",
     "portion_note": "olio EVO a crudo, 2-3 cucchiaini per pasto principale"},
    {"category": "frutta", "target_min": 2, "target_max": 3, "period": "day",
     "portion_note": "2-3 porzioni/giorno, preferibilmente di stagione; limitare esotica"},
    # Indicazioni generali (testuali, non numeriche)
    {"category": "indicazione_olio_crudo", "period": None,
     "portion_note": "Preferire olio EVO a crudo rispetto a burro/strutto/margarina/oli tropicali o di semi"},
    {"category": "indicazione_cotture", "period": None,
     "portion_note": "Cotture senza grassi aggiunti: forno, piastra, vapore"},
    {"category": "indicazione_masticare", "period": None,
     "portion_note": "Mangiare lentamente e masticare adeguatamente"},
    {"category": "indicazione_sale_zucchero", "period": None,
     "portion_note": "Limitare sale e zucchero discrezionali"},
    {"category": "indicazione_stile_vita", "period": None,
     "portion_note": "Stile di vita attivo: scale, bici, a piedi, parcheggiare lontano"},
    {"category": "indicazione_etichette", "period": None,
     "portion_note": "Leggere sempre attentamente le etichette nutrizionali"},
    {"category": "indicazione_grammature", "period": None,
     "portion_note": "Le grammature sono a crudo e al netto degli scarti"},
    {"category": "indicazione_primo_no_pane", "period": None,
     "portion_note": "Col primo piatto (cereale 70g + proteina) niente pane aggiunto"},
    {"category": "indicazione_verdura", "period": None,
     "portion_note": "Verdura di stagione sempre presente: ≥200g ortaggi cotti o ≥100g insalata"},
]


# ─── RECIPES ───────────────────────────────────────────────────────

RECIPES: list[dict[str, Any]] = [
    {
        "name": "Pancake",
        "ingredients": [
            {"item": "farina integrale (o farro/grano saraceno/riso e nocciole/castagne)", "qty": "35g"},
            {"item": "uovo", "qty": "1"},
            {"item": "acqua o latte", "qty": "q.b."},
            {"item": "lievito", "qty": "1 cucchiaino"},
        ],
        "steps": (
            "In una ciotola mescola la farina e il lievito, aggiungi l'uovo e, "
            "solo infine, acqua o latte poco per volta per regolare la consistenza "
            "della pastella (non troppo liquida se li vuoi 'cicciotti'). In una "
            "padella antiaderente già calda versa un mestolino di pastella e cuoci "
            "entrambi i lati; ripeti fino a finirla. La porzione comprende tutti i "
            "pancake ottenuti. Per renderli più morbidi: monta a neve l'albume "
            "prima di incorporarlo, oppure aggiungi un cucchiaio di ricotta o "
            "yogurt greco nell'impasto."
        ),
        "source": "Piano alimentare Antonio Pedoto — Dott.ssa Elena Poletti",
    },
]
