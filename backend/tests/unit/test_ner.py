"""Unit tests for `cara.ai.ner`. spaCy mocked — no 600 MB model needed."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from cara.ai.ner import NERResult, NERService


# --------------------------------------------------------------- spaCy stubs


@dataclass
class FakeEnt:
    """Quacks like a spaCy entity span."""
    text: str
    label_: str
    start_char: int
    end_char: int


class FakeDoc:
    def __init__(self, ents):
        self.ents = ents


def make_fake_nlp(ents_for_text):
    """Build a spaCy-like callable that returns `ents_for_text(text)`."""
    nlp = MagicMock()
    nlp.side_effect = lambda text: FakeDoc(ents_for_text(text))
    return nlp


# --------------------------------------------------------------- spaCy detection


def test_spacy_persons_locations_orgs() -> None:
    def ents(text):
        return [
            FakeEnt("Antonio", "PER", text.index("Antonio"), text.index("Antonio") + 7),
            FakeEnt("Roma", "LOC", text.index("Roma"), text.index("Roma") + 4),
            FakeEnt("Conad", "ORG", text.index("Conad"), text.index("Conad") + 5),
        ]

    svc = NERService(nlp=make_fake_nlp(ents))
    out = svc.extract("Antonio è andato al Conad di Roma.")
    assert any(e.label == "PER" and e.text == "Antonio" for e in out.entities)
    assert any(e.label == "LOC" for e in out.entities)
    assert any(e.label == "ORG" for e in out.entities)


def test_spacy_label_normalisation() -> None:
    """PERSON → PER, GPE → LOC, anything else → MISC."""
    def ents(_):
        return [FakeEnt("X", "PERSON", 0, 1), FakeEnt("Y", "GPE", 2, 3),
                FakeEnt("Z", "WORK_OF_ART", 4, 5)]

    svc = NERService(nlp=make_fake_nlp(ents))
    out = svc.extract("X Y Z")
    labels = {e.label for e in out.entities}
    assert "PER" in labels
    assert "LOC" in labels
    assert "MISC" in labels


def test_spacy_failure_does_not_crash_extraction() -> None:
    nlp = MagicMock()
    nlp.side_effect = RuntimeError("spaCy died")
    svc = NERService(nlp=nlp)
    # Regex still runs.
    out = svc.extract("scrivimi a foo@example.com")
    assert any(e.label == "EMAIL" for e in out.entities)


# --------------------------------------------------------------- regex detectors


def test_email_detector() -> None:
    svc = NERService(nlp=make_fake_nlp(lambda _t: []))
    out = svc.extract("contattami a antonio.pedoto@gmail.com domani")
    emails = [e for e in out.entities if e.label == "EMAIL"]
    assert len(emails) == 1
    assert emails[0].text == "antonio.pedoto@gmail.com"


def test_phone_detector_italian_mobile() -> None:
    svc = NERService(nlp=make_fake_nlp(lambda _t: []))
    out = svc.extract("chiamami al 333 1234567 oggi")
    phones = [e for e in out.entities if e.label == "PHONE"]
    assert len(phones) == 1


def test_phone_detector_with_country_code() -> None:
    svc = NERService(nlp=make_fake_nlp(lambda _t: []))
    out = svc.extract("Il numero è +39 333 1234567.")
    phones = [e for e in out.entities if e.label == "PHONE"]
    assert len(phones) == 1


def test_iban_detector() -> None:
    svc = NERService(nlp=make_fake_nlp(lambda _t: []))
    out = svc.extract("Bonifica su IT60X0542811101000000123456 entro venerdì.")
    ibans = [e for e in out.entities if e.label == "IBAN"]
    assert len(ibans) == 1


def test_codice_fiscale_detector() -> None:
    svc = NERService(nlp=make_fake_nlp(lambda _t: []))
    out = svc.extract("Il CF è PDTNTN85L20H501Z grazie")
    cfs = [e for e in out.entities if e.label == "CF"]
    assert len(cfs) == 1


def test_url_detector() -> None:
    svc = NERService(nlp=make_fake_nlp(lambda _t: []))
    out = svc.extract("vedi https://example.com/page?id=123")
    urls = [e for e in out.entities if e.label == "URL"]
    assert len(urls) == 1


def test_ip_detector() -> None:
    svc = NERService(nlp=make_fake_nlp(lambda _t: []))
    out = svc.extract("Il server è 192.168.1.23 oggi")
    ips = [e for e in out.entities if e.label == "IP"]
    assert len(ips) == 1


# --------------------------------------------------------------- family glossary


def test_glossary_matches_aliases() -> None:
    """The glossary catches informal forms spaCy might miss."""
    svc = NERService(
        nlp=make_fake_nlp(lambda _t: []),
        family_glossary={"Antonio Pedoto": ["Tonio", "papà"]},
    )
    out = svc.extract("Tonio dice che papà torna alle 19.")
    fam = [e for e in out.entities if e.label == "FAMILY"]
    # Both "Tonio" and "papà" should be captured as FAMILY entities.
    assert len(fam) == 2
    sources = {e.source for e in fam}
    assert all(s.startswith("glossary:Antonio Pedoto") for s in sources)


def test_glossary_update_replaces_layer() -> None:
    svc = NERService(
        nlp=make_fake_nlp(lambda _t: []),
        family_glossary={"Marco": ["Marchetto"]},
    )
    out = svc.extract("ciao Marchetto")
    assert any(e.label == "FAMILY" for e in out.entities)

    svc.update_family_glossary({"Sara": ["Sari"]})
    out = svc.extract("ciao Marchetto e Sari")
    fam_texts = {e.text for e in out.entities if e.label == "FAMILY"}
    # Marchetto no longer recognised, Sari is.
    assert "Marchetto" not in fam_texts
    assert any(t.lower() == "sari" for t in fam_texts)


# --------------------------------------------------------------- overlap dedup


def test_overlap_dedup_spacy_beats_glossary() -> None:
    """If spaCy finds 'Antonio Pedoto' and glossary also matches the
    'Antonio' substring inside it, glossary loses (priority spacy > glossary)."""
    def ents(text):
        # spaCy spans the whole "Antonio Pedoto" — covers the inner alias.
        idx = text.index("Antonio Pedoto")
        return [FakeEnt("Antonio Pedoto", "PER", idx, idx + len("Antonio Pedoto"))]

    svc = NERService(
        nlp=make_fake_nlp(ents),
        family_glossary={"Antonio Pedoto": ["Antonio"]},
    )
    out = svc.extract("Antonio Pedoto è arrivato.")
    # Only the spaCy span should remain; the glossary's inner Antonio
    # is dropped because of overlap.
    pers = [e for e in out.entities if e.label in {"PER", "FAMILY"}]
    assert len(pers) == 1
    assert pers[0].source == "spacy"


# --------------------------------------------------------------- result helpers


def test_result_helpers_persons_locations_orgs_haspii() -> None:
    def ents(text):
        return [
            FakeEnt("Marco", "PER", 0, 5),
            FakeEnt("Roma", "LOC", 6, 10),
            FakeEnt("Conad", "ORG", 11, 16),
        ]

    svc = NERService(nlp=make_fake_nlp(ents))
    r = svc.extract("Marco Roma Conad ha email foo@bar.com da +39 333 1234567 oggi.")
    assert isinstance(r, NERResult)
    assert any(e.text == "Marco" for e in r.persons)
    assert any(e.text == "Roma" for e in r.locations)
    assert any(e.text == "Conad" for e in r.organizations)
    assert r.has_pii is True


def test_empty_input_returns_empty_result() -> None:
    svc = NERService(nlp=make_fake_nlp(lambda _t: []))
    r = svc.extract("")
    assert r.text == ""
    assert r.entities == []


def test_entities_are_sorted_by_start() -> None:
    def ents(text):
        return [
            FakeEnt("Marco", "PER", text.index("Marco"), text.index("Marco") + 5),
        ]
    svc = NERService(nlp=make_fake_nlp(ents))
    out = svc.extract("ciao Marco scrivimi a foo@bar.com")
    # entities should appear in left-to-right order regardless of detector
    # order.
    starts = [e.start for e in out.entities]
    assert starts == sorted(starts)
