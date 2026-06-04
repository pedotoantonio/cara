"""Open Food Facts (OFF) client for barcode → nutrition lookup.

CARA Nutrizione lets you log a packaged product by scanning its barcode.
The scan happens client-side (browser BarcodeDetector); the resulting
EAN/UPC is sent here, and we resolve it to {name, brand, kcal/100g,
macros} via the free Open Food Facts API.

Why OFF (see REPORT in chat history): free, open data (ODbL), 2.8M+
products with strong Italian coverage and 680k+ barcodes — the only
option that fits CARA's privacy-first / self-hostable stance. We keep
the existing CREA catalog for raw ingredients (pasta, verdure, carne);
OFF covers branded/packaged goods by barcode.

Design mirrors `services/weather.py`:
  * httpx.AsyncClient, lazily created, injectable for tests
  * Redis cache (long TTL — product facts barely change), all errors
    swallowed into a graceful "not found" so logging never hard-fails.

Calories remain SECONDARY/indicative in CARA, consistent with the rest
of the diet module.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

import httpx
import structlog

log = structlog.get_logger(__name__)

# v2 product endpoint. We request only the fields we use to keep the
# payload small and fast on the NanoPC link.
_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"
_FIELDS = (
    "code,product_name,product_name_it,brands,quantity,"
    "nutriments,nutriscore_grade,image_front_small_url"
)

# OFF asks API consumers to send a descriptive User-Agent.
_USER_AGENT = "CARA-HomeAssistant/1.0 (self-hosted family; nutrition barcode lookup)"
_DEFAULT_TIMEOUT = httpx.Timeout(8.0, connect=4.0)

_CACHE_PREFIX = "cara:off:"
# Product facts are stable; cache a week. A miss is also cached (shorter)
# so a wrong/unknown barcode doesn't hammer OFF on every retry.
_CACHE_TTL_HIT = 7 * 24 * 3600
_CACHE_TTL_MISS = 6 * 3600


@dataclass
class OffProduct:
    barcode: str
    name: str
    brand: str | None
    quantity: str | None          # e.g. "500 g" as printed on the pack
    kcal_per_100g: int | None
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    fiber_g: float | None
    nutriscore: str | None        # a..e
    image_url: str | None
    found: bool = True


def _num(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_product(barcode: str, data: dict) -> OffProduct | None:
    """Map an OFF product payload to OffProduct. None if no usable name."""
    product = data.get("product") or {}
    name = (
        product.get("product_name_it")
        or product.get("product_name")
        or ""
    ).strip()
    if not name:
        return None

    nutr = product.get("nutriments") or {}
    # OFF gives kcal as "energy-kcal_100g"; fall back to kJ → kcal.
    kcal = _num(nutr.get("energy-kcal_100g"))
    if kcal is None:
        kj = _num(nutr.get("energy_100g"))
        kcal = round(kj / 4.184) if kj is not None else None

    brand = (product.get("brands") or "").split(",")[0].strip() or None

    return OffProduct(
        barcode=barcode,
        name=name,
        brand=brand,
        quantity=(product.get("quantity") or "").strip() or None,
        kcal_per_100g=round(kcal) if kcal is not None else None,
        protein_g=_num(nutr.get("proteins_100g")),
        carbs_g=_num(nutr.get("carbohydrates_100g")),
        fat_g=_num(nutr.get("fat_100g")),
        fiber_g=_num(nutr.get("fiber_100g")),
        nutriscore=(product.get("nutriscore_grade") or "").strip().lower() or None,
        image_url=product.get("image_front_small_url") or None,
        found=True,
    )


class OffClient:
    """Thin facade over the Open Food Facts product API + Redis cache."""

    def __init__(
        self,
        redis_client=None,  # noqa: ANN001
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._redis = redis_client
        self._http = http_client

    async def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=_DEFAULT_TIMEOUT, headers={"User-Agent": _USER_AGENT}
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ----------------------------------------------------------------- cache
    async def _cache_get(self, barcode: str) -> OffProduct | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(_CACHE_PREFIX + barcode)
        except Exception as exc:  # noqa: BLE001 — cache is best-effort
            log.debug("off.cache.get_failed", error=str(exc))
            return None
        if not raw:
            return None
        try:
            payload = json.loads(raw)
            return OffProduct(**payload)
        except Exception:  # noqa: BLE001
            return None

    async def _cache_set(self, product: OffProduct, *, ttl: int) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(
                _CACHE_PREFIX + product.barcode,
                json.dumps(asdict(product)),
                ex=ttl,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("off.cache.set_failed", error=str(exc))

    # ----------------------------------------------------------------- lookup
    async def lookup(self, barcode: str) -> OffProduct | None:
        """Resolve a barcode to a product. None if genuinely not found.

        Network/parse errors are swallowed and logged → None, so the
        caller (and the user) gets a clean "prodotto non trovato"
        instead of a 500.
        """
        barcode = (barcode or "").strip()
        if not barcode.isdigit() or not (6 <= len(barcode) <= 14):
            return None

        cached = await self._cache_get(barcode)
        if cached is not None:
            return cached if cached.found else None

        client = await self._client()
        try:
            r = await client.get(
                _PRODUCT_URL.format(barcode=barcode),
                params={"fields": _FIELDS},
            )
        except httpx.HTTPError as exc:
            log.warning("off.lookup.http_failed", barcode=barcode, error=str(exc))
            return None

        if r.status_code == 404:
            await self._cache_set(_miss(barcode), ttl=_CACHE_TTL_MISS)
            return None
        try:
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("off.lookup.bad_response", barcode=barcode, error=str(exc))
            return None

        # OFF returns {"status": 0} for unknown barcodes (HTTP 200).
        if data.get("status") == 0:
            await self._cache_set(_miss(barcode), ttl=_CACHE_TTL_MISS)
            return None

        product = _parse_product(barcode, data)
        if product is None:
            await self._cache_set(_miss(barcode), ttl=_CACHE_TTL_MISS)
            return None

        await self._cache_set(product, ttl=_CACHE_TTL_HIT)
        log.info("off.lookup.hit", barcode=barcode, name=product.name,
                 kcal=product.kcal_per_100g)
        return product


def _miss(barcode: str) -> OffProduct:
    """A negative-cache marker (found=False)."""
    return OffProduct(
        barcode=barcode, name="", brand=None, quantity=None,
        kcal_per_100g=None, protein_g=None, carbs_g=None, fat_g=None,
        fiber_g=None, nutriscore=None, image_url=None, found=False,
    )


# Module-level singleton, redis attached lazily (same pattern as cda
# rate_limit). The diet API builds its own redis client on first use.
_singleton: OffClient | None = None


def get_off_client(redis_client=None) -> OffClient:  # noqa: ANN001
    global _singleton
    if _singleton is None:
        _singleton = OffClient(redis_client=redis_client)
    elif redis_client is not None and _singleton._redis is None:
        _singleton._redis = redis_client
    return _singleton
