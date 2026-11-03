"""Deterministic tests for the new VC08 anti-dilution and VC04 cap-table drills."""

from academics.vc.content import load_content
from academics.vc.drills import grade_drill


def test_vc08_full_ratchet_conversion_price() -> None:
    content = load_content()
    drill = content.drill("VC08-D001")
    assert grade_drill(drill, "1.0")["accepted"] is True
    assert grade_drill(drill, "2.0")["accepted"] is False  # old price, not ratcheted


def test_vc08_price_drop() -> None:
    content = load_content()
    drill = content.drill("VC08-D002")
    assert grade_drill(drill, "1.5")["accepted"] is True


def test_vc08_weighted_average_price() -> None:
    content = load_content()
    drill = content.drill("VC08-D003")
    assert grade_drill(drill, "4.0")["accepted"] is True
    # boundary: rounding tolerance
    assert grade_drill(drill, "4.01")["accepted"] is True


def test_vc08_full_ratchet_share_count() -> None:
    content = load_content()
    drill = content.drill("VC08-D004")
    assert grade_drill(drill, "4000000")["accepted"] is True
    assert grade_drill(drill, "2000000")["accepted"] is False


def test_vc04_dilution_after_round() -> None:
    content = load_content()
    drill = content.drill("VC04-D007")
    assert grade_drill(drill, "45")["accepted"] is True
    assert grade_drill(drill, "35")["accepted"] is False  # subtracted instead of multiplied


def test_vc04_cap_table_unallocated() -> None:
    content = load_content()
    drill = content.drill("VC04-D008")
    assert grade_drill(drill, "5")["accepted"] is True


def test_vc04_price_per_share() -> None:
    content = load_content()
    drill = content.drill("VC04-D009")
    assert grade_drill(drill, "2.0")["accepted"] is True
    assert grade_drill(drill, "0.5")["accepted"] is False  # inverted division