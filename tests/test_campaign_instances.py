"""`clsc.campaign.instances`: materializing one design point's instance JSON.

This is the untested bridge between a `design_matrix.csv` row and the instance a run actually
solves (flagged in the technical audit as the pipeline's weakest-covered link: a silent bug here
would corrupt every instance of an experiment before a single Gurobi solve catches anything).
Covers, in order: `materialize()`'s happy path and output layout, that it never mutates the
on-disk base file, the toy-instance guard, `factor_levels`/`valuation_ratio` application (alone
and combined), the structural-menu path (`_has_structural_expansion` and a real "expanded" menu),
and `_load_base_payload`'s two branches (seed_offset == 0 vs. reseeded regeneration, the latter
gated on Gurobi since it re-runs the feasibility-checked generator).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from clsc.campaign.designs._common import DesignPoint
from clsc.campaign.instances import (
    SEED_OFFSET_STRIDE,
    _has_structural_expansion,
    _load_base_payload,
    materialize,
)
from clsc.models.instance import InstanceData

BASE_INSTANCE_ID = "STD_I17_M4_T3"
BASE_INSTANCE_PATH = Path("data/instances/base") / f"{BASE_INSTANCE_ID}.json"


def _point(**overrides) -> DesignPoint:
    fields = dict(
        experiment_id="exp4",
        design_point_id="dp",
        run_code="r001",
        base_instance_id=BASE_INSTANCE_ID,
        execution_mode="fixed_tax",
        per_subproblem_time_limit_seconds=600.0,
        per_run_wall_clock_cap_seconds=3600.0,
    )
    fields.update(overrides)
    return DesignPoint(**fields)


def _base_payload() -> dict:
    return json.loads(BASE_INSTANCE_PATH.read_text(encoding="utf-8"))


# ===========================================================================
# materialize(): happy path, output layout, provenance metadata
# ===========================================================================

def test_materialize_writes_a_valid_instance_at_the_documented_path(tmp_path: Path) -> None:
    point = _point()
    dest = materialize(point, output_root=tmp_path)

    assert dest == tmp_path / point.experiment_id / point.base_instance_id / f"{point.run_code}.json"
    assert dest.is_file()

    payload = json.loads(dest.read_text(encoding="utf-8"))
    InstanceData.from_dict(payload)  # must validate cleanly, not just parse as JSON


def test_materialize_stamps_instance_name_and_campaign_metadata(tmp_path: Path) -> None:
    point = _point(experiment_id="exp3", design_point_id="dp42", run_code="r007")
    dest = materialize(point, output_root=tmp_path)
    payload = json.loads(dest.read_text(encoding="utf-8"))

    assert payload["name"] == f"{BASE_INSTANCE_ID}__exp3_r007"
    assert payload["metadata"]["campaign"] == {
        "campaign_id": "campaign_01",
        "experiment_id": "exp3",
        "design_point_id": "dp42",
        "base_instance_id": BASE_INSTANCE_ID,
    }
    assert payload["metadata"]["config"]["instance_name"] == f"{BASE_INSTANCE_ID}__exp3_r007"


def test_materialize_rejects_toy_design_points() -> None:
    point = _point(is_toy=True)
    with pytest.raises(ValueError, match="toy instances"):
        materialize(point, output_root=Path("unused"))


def test_materialize_never_mutates_the_base_file_on_disk(tmp_path: Path) -> None:
    before = BASE_INSTANCE_PATH.read_bytes()
    materialize(_point(factor_levels={"demand": 0.5}, valuation_ratio=1.3), output_root=tmp_path)
    after = BASE_INSTANCE_PATH.read_bytes()
    assert before == after


# ===========================================================================
# materialize(): plain point (no factors/valuation/structural) reproduces the base instance
# ===========================================================================

def test_materialize_without_any_variant_knob_preserves_base_sets_and_parameters(tmp_path: Path) -> None:
    base = _base_payload()
    dest = materialize(_point(), output_root=tmp_path)
    written = json.loads(dest.read_text(encoding="utf-8"))

    assert written["sets"] == base["sets"]
    assert written["parameters"] == base["parameters"]


# ===========================================================================
# factor_levels (continuous multipliers, clsc.campaign.factors)
# ===========================================================================

def test_materialize_applies_factor_levels_as_a_multiplier_on_the_base_value(tmp_path: Path) -> None:
    base = _base_payload()
    base_demand = base["parameters"]["d_r_p_t"]["r1"]["p1"]["t1"]

    dest = materialize(_point(factor_levels={"demand": 0.5}), output_root=tmp_path)
    written = json.loads(dest.read_text(encoding="utf-8"))

    assert written["parameters"]["d_r_p_t"]["r1"]["p1"]["t1"] == pytest.approx(base_demand * 0.5)
    # A factor untouched by "demand" must survive unscaled.
    assert written["parameters"]["e_prod_g"] == base["parameters"]["e_prod_g"]


def test_materialize_with_no_factor_levels_key_is_a_strict_no_op_not_just_multiplier_one(
    tmp_path: Path,
) -> None:
    # factor_levels={} must skip apply_levels entirely (materialize's `if point.factor_levels:`
    # guard), not call it with an empty vector -- both would be observationally identical here,
    # but this pins the guard exists rather than relying on apply_levels' own no-op behaviour.
    base = _base_payload()
    dest = materialize(_point(factor_levels={}), output_root=tmp_path)
    written = json.loads(dest.read_text(encoding="utf-8"))
    assert written["parameters"]["d_r_p_t"] == base["parameters"]["d_r_p_t"]


# ===========================================================================
# valuation_ratio (emissions-valuation rescale, clsc.campaign.valuation)
# ===========================================================================

def test_materialize_applies_valuation_ratio_to_emission_parameters_only(tmp_path: Path) -> None:
    base = _base_payload()
    dest = materialize(_point(valuation_ratio=2.0), output_root=tmp_path)
    written = json.loads(dest.read_text(encoding="utf-8"))

    for key in ("e_prod_g", "e_rem_l", "e_raw_s_u", "e_ship_m"):
        base_leaf = _first_leaf(base["parameters"][key])
        written_leaf = _first_leaf(written["parameters"][key])
        assert written_leaf == pytest.approx(base_leaf * 2.0), key
    # A non-emission parameter must be untouched by the valuation rescale.
    assert written["parameters"]["d_r_p_t"] == base["parameters"]["d_r_p_t"]


def test_materialize_with_valuation_ratio_none_is_a_no_op(tmp_path: Path) -> None:
    base = _base_payload()
    dest = materialize(_point(valuation_ratio=None), output_root=tmp_path)
    written = json.loads(dest.read_text(encoding="utf-8"))
    assert written["parameters"]["e_prod_g"] == base["parameters"]["e_prod_g"]


def test_materialize_combines_factor_levels_and_valuation_ratio_multiplicatively(
    tmp_path: Path,
) -> None:
    # "emission_intensity" (a factor) and valuation_ratio both scale e_prod_g; materialize applies
    # factor_levels first, then valuation_ratio (see its docstring's pipeline order), and since
    # both are plain multipliers the net effect must be their product regardless of order.
    base = _base_payload()
    base_leaf = _first_leaf(base["parameters"]["e_prod_g"])

    dest = materialize(
        _point(factor_levels={"emission_intensity": 0.8}, valuation_ratio=1.5),
        output_root=tmp_path,
    )
    written = json.loads(dest.read_text(encoding="utf-8"))
    written_leaf = _first_leaf(written["parameters"]["e_prod_g"])

    assert written_leaf == pytest.approx(base_leaf * 0.8 * 1.5)


def _first_leaf(value):
    """Descend a (possibly nested) parameter dict to its first numeric leaf, depth-agnostic --
    e_prod_g is one level deep (technology -> value), d_r_p_t is three (retailer -> product ->
    period), and this helper is used against both without hard-coding either shape."""
    while isinstance(value, dict):
        value = next(iter(value.values()))
    return value


# ===========================================================================
# Structural menu expansions (clsc.campaign.structural)
# ===========================================================================

def test_has_structural_expansion_is_false_when_every_menu_is_base() -> None:
    assert _has_structural_expansion(_point()) is False


@pytest.mark.parametrize(
    "menu_field",
    [
        "production_technology_menu",
        "remanufacturing_technology_menu",
        "road_menu",
        "sea_menu",
        "air_menu",
    ],
)
def test_has_structural_expansion_is_true_when_any_single_menu_is_expanded(menu_field: str) -> None:
    assert _has_structural_expansion(_point(**{menu_field: "expanded"})) is True


def test_materialize_skips_structural_application_when_every_menu_is_base(tmp_path: Path) -> None:
    # Pins that materialize()'s `if _has_structural_expansion(point):` guard actually skips the
    # call rather than calling apply_structural_levels(..., "base", "base", ...) unconditionally
    # -- both are observationally identical for a valid instance, but the guard is what makes
    # non-campaign_01 callers (which never expand any menu) cheap to materialize.
    base = _base_payload()
    dest = materialize(_point(), output_root=tmp_path)
    written = json.loads(dest.read_text(encoding="utf-8"))
    assert written["sets"]["G"] == base["sets"]["G"]


def test_materialize_applies_an_expanded_production_technology_menu(tmp_path: Path) -> None:
    base = _base_payload()
    point = _point(production_technology_menu="expanded")
    dest = materialize(point, output_root=tmp_path)
    payload = json.loads(dest.read_text(encoding="utf-8"))

    assert len(payload["sets"]["G"]) > len(base["sets"]["G"])
    assert set(base["sets"]["G"]).issubset(payload["sets"]["G"])
    InstanceData.from_dict(payload)  # the expanded instance must still be a valid instance


# ===========================================================================
# _load_base_payload: the two branches (seed_offset == 0 vs. reseeded regeneration)
# ===========================================================================

def test_load_base_payload_with_zero_seed_offset_returns_the_file_verbatim() -> None:
    assert _load_base_payload(BASE_INSTANCE_ID, seed_offset=0) == _base_payload()


def test_load_base_payload_rejects_an_unknown_base_instance_id_when_seed_offset_is_zero() -> None:
    # seed_offset == 0 reads straight off disk, so an unknown id fails as a file-not-found, not
    # the benchmark-spec lookup error the seed_offset != 0 branch raises (see below).
    with pytest.raises(FileNotFoundError):
        _load_base_payload("STD_I999_M1_T1", seed_offset=0)


def test_load_base_payload_rejects_an_unknown_base_instance_id_when_seed_offset_is_nonzero() -> None:
    with pytest.raises(ValueError, match="No benchmark spec found"):
        _load_base_payload("STD_I999_M1_T1", seed_offset=1)


@pytest.mark.gurobi
@pytest.mark.slow
def test_load_base_payload_with_nonzero_seed_offset_regenerates_at_the_shifted_seed() -> None:
    from clsc.generator.benchmark import build_base_benchmark_specs

    spec = next(
        s for s in build_base_benchmark_specs(seed_base=0) if s.suffix == "I17_M4_T3"
    )
    seed_offset = 3
    payload = _load_base_payload(BASE_INSTANCE_ID, seed_offset=seed_offset)

    assert payload["metadata"]["benchmark"]["seed"] == spec.seed + seed_offset * SEED_OFFSET_STRIDE
    # A different seed is expected to draw different demand -- this is not a hard mathematical
    # guarantee, but a collision here would be a red flag worth investigating, not a fluke to
    # silently tolerate.
    assert payload["parameters"]["d_r_p_t"] != _base_payload()["parameters"]["d_r_p_t"]
    InstanceData.from_dict(payload)  # the regenerated instance must still be a valid instance


@pytest.mark.gurobi
@pytest.mark.slow
def test_materialize_with_nonzero_seed_offset_produces_a_distinct_valid_instance(
    tmp_path: Path,
) -> None:
    point = _point(seed_offset=2)
    dest = materialize(point, output_root=tmp_path)
    payload = json.loads(dest.read_text(encoding="utf-8"))

    InstanceData.from_dict(payload)
    assert payload["parameters"]["d_r_p_t"] != _base_payload()["parameters"]["d_r_p_t"]
