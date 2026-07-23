"""Regression tests for doe_campaign_02's 5-way structural split (apply_structural_levels).

The bug this guards against (found 2026-07-09 during Family D): expanding two or more menus of the
same type together -- production+remanufacturing, or road+sea+air -- is applied as sequential
create_*_scenario_instance calls. The per-call rejection guards used to check the FULL profile set,
so the second call saw the modes/technologies added by the first and wrongly raised
"Source instance already contains scenario ...". Scenarios S1 (prod+road+sea) and S8 (all five)
failed on this. The fix scopes each guard to the subset being added in that call.
"""
from __future__ import annotations

from clsc.generator import build_base_benchmark_specs, generate_instance
from clsc.models.instance import InstanceData
from clsc.campaign.structural import apply_structural_levels


def _base_payload() -> dict:
    spec = next(item for item in build_base_benchmark_specs(seed_base=0) if item.name == "STD_I17_M4_T3")
    return generate_instance(spec.to_config()).to_dict()


def test_all_five_menus_expanded_together(  ) -> None:
    """S8-style: production+remanufacturing+road+sea+air all expanded must not raise."""
    payload = _base_payload()
    g0, l0 = len(payload["sets"]["G"]), len(payload["sets"]["L"])
    rd0, a0, s0 = (len(payload["sets"][k]) for k in ("M_RD", "M_A", "M_S"))

    out = apply_structural_levels(
        payload,
        production_technology_menu="expanded",
        remanufacturing_technology_menu="expanded",
        road_menu="expanded",
        sea_menu="expanded",
        air_menu="expanded",
    )
    InstanceData.from_dict(out)  # must validate

    assert len(out["sets"]["G"]) == g0 + 3
    assert len(out["sets"]["L"]) == l0 + 3
    assert len(out["sets"]["M_RD"]) == rd0 + 2
    assert len(out["sets"]["M_A"]) == a0 + 2
    assert len(out["sets"]["M_S"]) == s0 + 2
    assert out["sets"]["M"] == [*out["sets"]["M_RD"], *out["sets"]["M_A"], *out["sets"]["M_S"]]


def test_s1_style_partial_multi_menu() -> None:
    """S1-style: production + road + sea expanded (remanufacturing/air left at base)."""
    payload = _base_payload()
    g0, l0 = len(payload["sets"]["G"]), len(payload["sets"]["L"])
    rd0, a0, s0 = (len(payload["sets"][k]) for k in ("M_RD", "M_A", "M_S"))

    out = apply_structural_levels(
        payload,
        production_technology_menu="expanded",
        road_menu="expanded",
        sea_menu="expanded",
    )
    InstanceData.from_dict(out)

    assert len(out["sets"]["G"]) == g0 + 3       # production expanded
    assert len(out["sets"]["L"]) == l0           # remanufacturing untouched
    assert len(out["sets"]["M_RD"]) == rd0 + 2   # road expanded
    assert len(out["sets"]["M_S"]) == s0 + 2     # sea expanded
    assert len(out["sets"]["M_A"]) == a0         # air untouched


def test_all_base_is_noop() -> None:
    payload = _base_payload()
    before = (len(payload["sets"]["G"]), len(payload["sets"]["L"]),
              len(payload["sets"]["M_RD"]), len(payload["sets"]["M_A"]), len(payload["sets"]["M_S"]))
    out = apply_structural_levels(payload)  # all default "base"
    after = (len(out["sets"]["G"]), len(out["sets"]["L"]),
             len(out["sets"]["M_RD"]), len(out["sets"]["M_A"]), len(out["sets"]["M_S"]))
    assert before == after
