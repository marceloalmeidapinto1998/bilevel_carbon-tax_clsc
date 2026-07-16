from __future__ import annotations

from pathlib import Path

import pytest

from data.generator import build_base_benchmark_specs, generate_instance
from src.models.instance import PRODUCT_ROTATION_PER_PERIOD, InstanceData, InstanceValidationError


def test_instance_loader_reads_committed_std_base_instance() -> None:
    instance = InstanceData.from_file(
        Path("data/instances/base/STD_I17_M4_T3.json"),
    )

    assert instance.name == "STD_I17_M4_T3"
    assert instance.lower_tax_index == 0
    assert instance.upper_tax_index == 20
    assert instance.sets["N"] == (
        *instance.sets["S"],
        *instance.sets["F"],
        *instance.sets["W"],
        *instance.sets["R"],
        *instance.sets["AIR"],
        *instance.sets["PORT"],
    )
    assert instance.sets["V"] == instance.sets["W"]
    assert instance.sets["K"] == instance.sets["RP"]
    assert instance.sets["AIR"]
    assert instance.sets["PORT"]
    assert instance.sets["RP"]
    assert instance.sets["M_RD"] == ("mrd1", "mrd2")
    assert instance.sets["M_A"] == ("ma1", "ma2")
    assert instance.sets["M_S"] == ("ms1", "ms2")
    assert instance.sets["M"] == (*instance.sets["M_RD"], *instance.sets["M_A"], *instance.sets["M_S"])
    assert instance.sets["FLOW_RAW"]
    assert all(isinstance(instance.parameters["theta_p"][product], int) for product in instance.sets["P"])
    assert all(instance.parameters["theta_p"][product] >= 1 for product in instance.sets["P"])
    assert instance.tax_rate(20) == 0.2
    for product in instance.sets["P"]:
        assert instance.parameters["apur_p"][product] == pytest.approx(
            instance.parameters["apu_p"][product] / PRODUCT_ROTATION_PER_PERIOD
        )


def test_instance_loader_canonicalizes_legacy_n_and_k_aliases() -> None:
    spec = next(item for item in build_base_benchmark_specs(seed_base=5) if item.name == "STD_I17_M4_T3")
    payload = generate_instance(spec.to_config()).to_dict()
    payload["sets"]["N"] = [*payload["sets"]["F"], *payload["sets"]["W"]]
    payload["sets"].pop("V")
    payload["sets"]["K"] = ["raw", "fp", "rp"]

    instance = InstanceData.from_dict(payload)

    assert instance.sets["N"] == (
        *instance.sets["S"],
        *instance.sets["F"],
        *instance.sets["W"],
        *instance.sets["R"],
        *instance.sets["AIR"],
        *instance.sets["PORT"],
    )
    assert instance.sets["K"] == instance.sets["RP"]


def test_instance_loader_backfills_missing_n_from_i() -> None:
    spec = next(item for item in build_base_benchmark_specs(seed_base=9) if item.name == "STD_I17_M4_T3")
    payload = generate_instance(spec.to_config()).to_dict()
    payload["sets"].pop("N")

    instance = InstanceData.from_dict(payload)

    assert instance.sets["N"] == instance.sets["I"]


def test_instance_loader_derives_missing_product_rotation_area() -> None:
    spec = next(item for item in build_base_benchmark_specs(seed_base=9) if item.name == "STD_I17_M8_T3")
    payload = generate_instance(spec.to_config()).to_dict()
    payload["parameters"].pop("apur_p")

    instance = InstanceData.from_dict(payload)

    for product in instance.sets["P"]:
        expected_rate = instance.parameters["apu_p"][product] / PRODUCT_ROTATION_PER_PERIOD
        assert instance.parameters["apur_p"][product] == pytest.approx(expected_rate)


def test_instance_loader_derives_missing_recovered_product_area() -> None:
    spec = next(item for item in build_base_benchmark_specs(seed_base=9) if item.name == "STD_I17_M8_T3")
    payload = generate_instance(spec.to_config()).to_dict()
    payload["parameters"].pop("apu_rp")
    payload["parameters"].pop("apu_q")

    instance = InstanceData.from_dict(payload)

    for recovered_product in instance.sets["RP"]:
        expected_area = sum(
            instance.parameters["bom_rem_r_p"][recovered_product][product]
            * instance.parameters["apu_p"][product]
            for product in instance.sets["P"]
        )
        assert instance.parameters["apu_rp"][recovered_product] == pytest.approx(expected_area)
        assert instance.parameters["apu_q"][recovered_product] == pytest.approx(expected_area)


def test_instance_loader_rejects_flow_outside_transport_arc_set() -> None:
    spec = next(item for item in build_base_benchmark_specs(seed_base=11) if item.name == "STD_I17_M4_T3")
    payload = generate_instance(spec.to_config()).to_dict()
    invalid_flow = list(payload["sets"]["FLOW_FP"][0])
    invalid_flow[1] = payload["sets"]["S"][0]
    invalid_flow[2] = payload["sets"]["R"][0]
    payload["sets"]["FLOW_FP"][0] = invalid_flow

    with pytest.raises(InstanceValidationError, match="FLOW_FP contains arc outside A"):
        InstanceData.from_dict(payload)


def test_instance_loader_rejects_missing_mode_family_coverage() -> None:
    spec = next(item for item in build_base_benchmark_specs(seed_base=13) if item.name == "STD_I17_M4_T3")
    payload = generate_instance(spec.to_config()).to_dict()
    payload["parameters"]["mode_family_m"].pop(payload["sets"]["M"][0])

    with pytest.raises(InstanceValidationError, match="Incomplete mode parameter coverage"):
        InstanceData.from_dict(payload)


def test_instance_loader_rejects_unsupported_raw_material_flow_units() -> None:
    spec = next(item for item in build_base_benchmark_specs(seed_base=15) if item.name == "STD_I17_M4_T3")
    payload = generate_instance(spec.to_config()).to_dict()
    payload["metadata"].setdefault("unit_convention", {})["raw_material_flow"] = "kg"

    with pytest.raises(InstanceValidationError, match="kg-based raw-material flows are not supported"):
        InstanceData.from_dict(payload)


def test_instance_loader_rejects_legacy_process_emission_units() -> None:
    spec = next(item for item in build_base_benchmark_specs(seed_base=17) if item.name == "STD_I17_M4_T3")
    payload = generate_instance(spec.to_config()).to_dict()
    payload["metadata"].setdefault("unit_convention", {})[
        "production_emission_intensity"
    ] = "kg CO2e/unit"

    with pytest.raises(InstanceValidationError, match="Regenerate legacy per-unit instances"):
        InstanceData.from_dict(payload)
