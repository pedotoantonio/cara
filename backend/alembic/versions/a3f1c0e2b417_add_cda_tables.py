"""add cda tables (content_items, query_log, user_preferences, domain_trust)

Revision ID: a3f1c0e2b417
Revises: d1b1194eb064
Create Date: 2026-05-02 16:00:00.000000

CDA = Content Discovery Agent. See /opt/cara/docs/cda-extension-spec.md.

Seeds the radio stations and news feeds that today live in
`cara/services/{radio,news}.py` as initial entries in `cda_content_items`,
so the new KB-driven UI starts non-empty even before the first user query.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a3f1c0e2b417"
down_revision: str | None = "d1b1194eb064"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---- seed data (mirrored from cara/services/{radio,news}.py) -----------

RADIO_SEED = [
    ("rai-radio-1",       "RAI Radio 1",        "https://icestreaming.rai.it/1.mp3", "icestreaming.rai.it", "it"),
    ("rai-radio-2",       "RAI Radio 2",        "https://icestreaming.rai.it/2.mp3", "icestreaming.rai.it", "it"),
    ("rai-radio-3",       "RAI Radio 3",        "https://icestreaming.rai.it/3.mp3", "icestreaming.rai.it", "it"),
    ("rai-gr-parlamento", "RAI GR Parlamento",  "https://icestreaming.rai.it/4.mp3", "icestreaming.rai.it", "it"),
    ("rai-isoradio",      "RAI Isoradio",       "https://icestreaming.rai.it/5.mp3", "icestreaming.rai.it", "it"),
    ("bbc-world-service", "BBC World Service",  "https://stream.live.vc.bbcmedia.co.uk/bbc_world_service", "bbcmedia.co.uk", "en"),
    ("bbc-radio-1",       "BBC Radio 1",        "https://stream.live.vc.bbcmedia.co.uk/bbc_radio_one",     "bbcmedia.co.uk", "en"),
    ("bbc-radio-4",       "BBC Radio 4",        "https://stream.live.vc.bbcmedia.co.uk/bbc_radio_fourfm",  "bbcmedia.co.uk", "en"),
]

NEWS_SEED = [
    ("ansa-top",          "ANSA — Top",          "https://www.ansa.it/sito/ansait_rss.xml",                            "ansa.it",         ["italia"]),
    ("ansa-mondo",        "ANSA — Mondo",        "https://www.ansa.it/sito/notizie/mondo/mondo_rss.xml",                "ansa.it",         ["mondo"]),
    ("ansa-economia",     "ANSA — Economia",     "https://www.ansa.it/sito/notizie/economia/economia_rss.xml",          "ansa.it",         ["economia"]),
    ("ansa-tech",         "ANSA — Tecnologia",   "https://www.ansa.it/sito/notizie/tecnologia/tecnologia_rss.xml",      "ansa.it",         ["tech"]),
    ("ansa-sport",        "ANSA — Sport",        "https://www.ansa.it/sito/notizie/sport/sport_rss.xml",                "ansa.it",         ["sport"]),
    ("repubblica-home",   "Repubblica",          "https://www.repubblica.it/rss/homepage/rss2.0.xml",                   "repubblica.it",   ["italia"]),
    ("corriere-home",     "Corriere della Sera", "https://xml2.corriereobjects.it/rss/homepage.xml",                    "corriere.it",     ["italia"]),
    ("rainews-home",      "RAI News",            "https://www.rainews.it/rss/home",                                     "rainews.it",      ["italia"]),
    ("bbc-world",         "BBC — World",         "http://feeds.bbci.co.uk/news/world/rss.xml",                          "bbc.com",         ["mondo"]),
    ("ilsole24ore-home",  "Il Sole 24 Ore",      "https://www.ilsole24ore.com/rss/italia.xml",                          "ilsole24ore.com", ["italia"]),
    ("reuters-world",     "Reuters World",       "https://feeds.reuters.com/Reuters/worldNews",                         "reuters.com",     ["mondo"]),
]

DOMAIN_TRUST_SEED = [
    # news IT
    ("rai.it",         "news_it",   1.00),
    ("ansa.it",        "news_it",   1.00),
    ("repubblica.it",  "news_it",   0.95),
    ("corriere.it",    "news_it",   0.95),
    ("ilsole24ore.com","news_it",   0.90),
    ("rainews.it",     "news_it",   1.00),
    # news intl
    ("bbc.com",        "news_intl", 1.00),
    ("reuters.com",    "news_intl", 1.00),
    # radio IT
    ("icestreaming.rai.it", "radio_it", 1.00),
    ("rtl.it",         "radio_it",  0.95),
    ("radiodeejay.it", "radio_it",  0.90),
    ("virginradio.it", "radio_it",  0.90),
    ("radio105.net",   "radio_it",  0.90),
    ("rds.it",         "radio_it",  0.90),
    ("kissskiss.it",   "radio_it",  0.85),
    # video
    ("youtube.com",    "video",     0.90),
    ("raiplay.it",     "video",     0.95),
    ("vimeo.com",      "video",     0.85),
    # tutorial / Q&A
    ("stackoverflow.com","tutorial",0.95),
    ("github.com",     "tutorial",  0.95),
    ("wikihow.com",    "tutorial",  0.70),
]


def upgrade() -> None:
    # ---- cda_content_items ---------------------------------------------
    op.create_table(
        "cda_content_items",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("query_normalized", sa.Text, nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("title", sa.Text),
        sa.Column("source_domain", sa.String(255)),
        sa.Column("metadata", postgresql.JSONB,
                  server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("confidence_score", sa.Float, server_default="0.5", nullable=False),
        sa.Column("success_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("failure_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, server_default=sa.true(), nullable=False),
        sa.Column("discovered_via", sa.String(64)),
        sa.Column("discovered_by_user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("discovered_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("query_normalized", "url", name="uq_cda_items_query_url"),
    )
    op.create_index(
        "idx_cda_query_active", "cda_content_items", ["query_normalized"],
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "idx_cda_type_query", "cda_content_items", ["content_type", "query_normalized"],
    )

    # ---- cda_query_log -------------------------------------------------
    op.create_table(
        "cda_query_log",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("raw_query", sa.Text, nullable=False),
        sa.Column("normalized_query", sa.Text),
        sa.Column("intent", postgresql.JSONB),
        sa.Column("resolved_content_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("cda_content_items.id", ondelete="SET NULL")),
        sa.Column("outcome", sa.String(32)),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("cached", sa.Boolean, server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "idx_cda_log_user_time", "cda_query_log",
        ["user_id", sa.text("created_at DESC")],
    )

    # ---- cda_user_preferences -----------------------------------------
    op.create_table(
        "cda_user_preferences",
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("preference_type", sa.String(64), nullable=False),
        sa.Column("preference_value", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("sample_count", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "preference_type", "preference_value",
                                name="pk_cda_user_preferences"),
    )

    # ---- cda_domain_trust ----------------------------------------------
    op.create_table(
        "cda_domain_trust",
        sa.Column("domain", sa.String(255), primary_key=True),
        sa.Column("category", sa.String(32)),
        sa.Column("base_score", sa.Float, server_default="0.5", nullable=False),
        sa.Column("notes", sa.Text),
    )

    # ---- seed: domain trust --------------------------------------------
    op.bulk_insert(
        sa.table(
            "cda_domain_trust",
            sa.column("domain"), sa.column("category"), sa.column("base_score"),
        ),
        [
            {"domain": d, "category": c, "base_score": s}
            for (d, c, s) in DOMAIN_TRUST_SEED
        ],
    )

    # ---- seed: content items (radio + news) ----------------------------
    # Radio: query_normalized = lowercased name, url = stream.
    radio_rows = []
    for sid, name, url, dom, lang in RADIO_SEED:
        radio_rows.append({
            "query_normalized": name.lower(),
            "content_type": "audio_stream",
            "url": url,
            "title": name,
            "source_domain": dom,
            "metadata": {
                "seed_id": sid,
                "language": lang,
                "codec": "mp3",
                "bitrate_kbps": 128,
            },
            "confidence_score": 0.9,
            "success_count": 1,
            "discovered_via": "seed",
        })
    # News: query_normalized = display_name lowercased; url = RSS feed (used by
    # the article discovery to fetch latest items without a search round-trip).
    news_rows = []
    for sid, name, url, dom, cats in NEWS_SEED:
        news_rows.append({
            "query_normalized": name.lower(),
            "content_type": "article_feed",
            "url": url,
            "title": name,
            "source_domain": dom,
            "metadata": {
                "seed_id": sid,
                "categories": cats,
                "language": "it" if dom.endswith(".it") else "en",
                "kind": "rss",
            },
            "confidence_score": 0.9,
            "success_count": 1,
            "discovered_via": "seed",
        })
    if radio_rows or news_rows:
        op.bulk_insert(
            sa.table(
                "cda_content_items",
                sa.column("query_normalized"),
                sa.column("content_type"),
                sa.column("url"),
                sa.column("title"),
                sa.column("source_domain"),
                sa.column("metadata", postgresql.JSONB),
                sa.column("confidence_score"),
                sa.column("success_count"),
                sa.column("discovered_via"),
            ),
            radio_rows + news_rows,
        )


def downgrade() -> None:
    op.drop_table("cda_user_preferences")
    op.drop_table("cda_domain_trust")
    op.drop_index("idx_cda_log_user_time", table_name="cda_query_log")
    op.drop_table("cda_query_log")
    op.drop_index("idx_cda_type_query", table_name="cda_content_items")
    op.drop_index("idx_cda_query_active", table_name="cda_content_items")
    op.drop_table("cda_content_items")
