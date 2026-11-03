from __future__ import annotations

from pathlib import Path

from academics.vc import VcStore
from academics.vc.content import load_content


def test_content_pack_loads_with_all_core_items() -> None:
    content = load_content()
    assert len(content.topics) == 20
    assert len(content.cards) >= 50
    assert len(content.drills) >= 24
    assert len(content.cases) >= 4
    assert len(content.glossary) >= 40
    assert content.topic("VC04").title_fr.startswith("Pre-money")
    assert content.card("VC04-C001").topic_id == "VC04"
    assert content.drill("VC04-D001").answer == 10
    assert content.case("VC07-CASE04").topic_id == "VC07"


def test_empty_store_is_created_in_tmp_path(tmp_path: Path) -> None:
    store = VcStore(tmp_path / "vc")
    assert store.home.is_dir()
    assert store.load_progress() == {}
    assert store.load_reviews() == []
    assert store.load_active_session() is None
    assert store.load_settings()["language"] == "fr"
