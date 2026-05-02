"""Radio station catalogue.

A small, hand-curated list of public Italian / European radio streams.
We expose a flat list to the frontend; the actual audio stream is consumed
by the browser's `<audio>` element directly (no proxying through the
backend) — this keeps CARA out of the bandwidth path.

Stations are returned in a stable order: news first, then music.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RadioStation:
    id: str
    name: str
    url: str          # direct stream URL (mp3/aac); browser plays it
    genre: str        # news | talk | music | sport
    country: str      # IT | UK | INT
    description: str


_CATALOGUE: list[RadioStation] = [
    RadioStation(
        id="rai-radio-1",
        name="RAI Radio 1",
        url="https://icestreaming.rai.it/1.mp3",
        genre="news",
        country="IT",
        description="Notizie, attualità e diretta dei principali eventi.",
    ),
    RadioStation(
        id="rai-radio-2",
        name="RAI Radio 2",
        url="https://icestreaming.rai.it/2.mp3",
        genre="music",
        country="IT",
        description="Intrattenimento e musica.",
    ),
    RadioStation(
        id="rai-radio-3",
        name="RAI Radio 3",
        url="https://icestreaming.rai.it/3.mp3",
        genre="talk",
        country="IT",
        description="Cultura, musica classica e approfondimenti.",
    ),
    RadioStation(
        id="rai-gr-parlamento",
        name="RAI GR Parlamento",
        url="https://icestreaming.rai.it/4.mp3",
        genre="news",
        country="IT",
        description="Diretta delle sedute parlamentari.",
    ),
    RadioStation(
        id="rai-isoradio",
        name="RAI Isoradio",
        url="https://icestreaming.rai.it/5.mp3",
        genre="news",
        country="IT",
        description="Informazione viabilità e traffico.",
    ),
    RadioStation(
        id="bbc-world-service",
        name="BBC World Service",
        url="https://stream.live.vc.bbcmedia.co.uk/bbc_world_service",
        genre="news",
        country="UK",
        description="News and analysis from around the world (English).",
    ),
    RadioStation(
        id="bbc-radio-1",
        name="BBC Radio 1",
        url="https://stream.live.vc.bbcmedia.co.uk/bbc_radio_one",
        genre="music",
        country="UK",
        description="Pop, dance, hits.",
    ),
    RadioStation(
        id="bbc-radio-4",
        name="BBC Radio 4",
        url="https://stream.live.vc.bbcmedia.co.uk/bbc_radio_fourfm",
        genre="talk",
        country="UK",
        description="Speech-based station: news, drama, comedy.",
    ),
]


def all_stations() -> list[RadioStation]:
    return list(_CATALOGUE)


def find_station(query: str) -> RadioStation | None:
    """Fuzzy match by id, name, or substring of either."""
    q = query.lower().strip()
    if not q:
        return None
    # Exact id wins
    for s in _CATALOGUE:
        if s.id == q:
            return s
    # Exact name (case-insensitive)
    for s in _CATALOGUE:
        if s.name.lower() == q:
            return s
    # Substring search
    for s in _CATALOGUE:
        if q in s.id.lower() or q in s.name.lower():
            return s
    return None
