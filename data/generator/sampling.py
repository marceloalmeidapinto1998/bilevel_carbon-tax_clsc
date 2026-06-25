from __future__ import annotations

import random

from .geometry import _technology_pairs_by_product
from . import tautenhain_data as taut

def _sample_demand(
    rng: random.Random,
    retailers: list[str],
    products: list[str],
    periods: list[str],
) -> tuple[
    dict[str, dict[str, dict[str, int]]],
    dict[str, dict[str, dict[str, float]]],
    dict[str, dict[str, dict[str, float]]],
]:
    demand: dict[str, dict[str, dict[str, int]]] = {}
    return_min_rate: dict[str, dict[str, dict[str, float]]] = {}
    return_max_rate: dict[str, dict[str, dict[str, float]]] = {}

    for retailer in retailers:
        demand[retailer] = {}
        return_min_rate[retailer] = {}
        return_max_rate[retailer] = {}
        for product in products:
            demand[retailer][product] = {}
            return_min_rate[retailer][product] = {}
            return_max_rate[retailer][product] = {}
            for period in periods:
                demand[retailer][product][period] = taut.ceil_nonnegative(
                    rng.uniform(*taut.DEMAND_RANGE)
                )
                max_fraction = round(
                    rng.uniform(*taut.RETURN_RATE_RANGE),
                    4,
                )
                return_max_rate[retailer][product][period] = max_fraction
                return_min_rate[retailer][product][period] = round(
                    rng.uniform(0.0, max_fraction),
                    4,
                )

    return demand, return_min_rate, return_max_rate


def _sample_bom_and_product_profiles(
    rng: random.Random,
    raw_materials: list[str],
    products: list[str],
    recovered_products: list[str],
    production_technologies: list[str],
    production_pairs: list[list[str]],
) -> tuple[
    dict[str, dict[str, dict[str, float]]],
    dict[str, dict[str, float]],
    dict[str, float],
    dict[str, float],
    dict[str, float],
    dict[str, float],
    dict[str, dict[str, float]],
    dict[str, dict[str, float]],
    dict[str, float],
    dict[str, float],
]:
    technology_input_requirement: dict[str, dict[str, dict[str, float]]] = {}
    average_input_requirement: dict[str, dict[str, float]] = {}
    compatible_technologies = _technology_pairs_by_product(production_pairs, products)
    raw_material_weight = {
        material: round(rng.uniform(*taut.RAW_WEIGHT_RANGE), 4) for material in raw_materials
    }
    raw_material_area = {
        material: round(rng.uniform(*taut.RAW_AREA_RANGE), 6) for material in raw_materials
    }
    product_unit_weight: dict[str, float] = {}
    product_unit_area: dict[str, float] = {}
    remanufacturing_bom_matrix: dict[str, dict[str, float]] = {
        recovered_product: {
            final_product: round(rng.uniform(*taut.BOM_REM_RANGE), 4)
            for final_product in products
        }
        for recovered_product in recovered_products
    }
    return_yield_matrix: dict[str, dict[str, float]] = {
        recovered_product: {
            final_product: 1.0 if recovered_product.removeprefix("rp") == final_product.removeprefix("p") else 0.0
            for final_product in products
        }
        for recovered_product in recovered_products
    }
    recovered_product_weight: dict[str, float] = {}
    recovered_product_area: dict[str, float] = {}

    for material in raw_materials:
        technology_input_requirement[material] = {}
        average_input_requirement[material] = {}
        for product in products:
            compatible = compatible_technologies[product]
            technology_input_requirement[material][product] = {}
            for technology in production_technologies:
                technology_input_requirement[material][product][technology] = (
                    round(rng.uniform(*taut.BOM_PROD_RANGE), 4)
                    if technology in compatible
                    else 0.0
                )
            average_input_requirement[material][product] = round(
                sum(
                    technology_input_requirement[material][product][technology]
                    for technology in compatible
                )
                / len(compatible),
                4,
            )

    for product in products:
        product_unit_weight[product] = round(
            sum(
                average_input_requirement[material][product] * raw_material_weight[material]
                for material in raw_materials
            ),
            4,
        )
        product_unit_area[product] = round(
            sum(
                average_input_requirement[material][product] * raw_material_area[material]
                for material in raw_materials
            ),
            6,
        )
    for recovered_product in recovered_products:
        recovered_product_weight[recovered_product] = round(
            sum(
                remanufacturing_bom_matrix[recovered_product][product]
                * product_unit_weight[product]
                for product in products
            ),
            4,
        )
        recovered_product_area[recovered_product] = round(
            sum(
                remanufacturing_bom_matrix[recovered_product][product]
                * product_unit_area[product]
                for product in products
            ),
            6,
        )

    return (
        technology_input_requirement,
        average_input_requirement,
        raw_material_weight,
        raw_material_area,
        product_unit_weight,
        product_unit_area,
        remanufacturing_bom_matrix,
        return_yield_matrix,
        recovered_product_weight,
        recovered_product_area,
    )


def _sum_product_demand_by_period(
    demand: dict[str, dict[str, dict[str, int]]],
    retailers: list[str],
    products: list[str],
    periods: list[str],
) -> dict[str, list[float]]:
    return {
        product: [
            float(sum(demand[retailer][product][period] for retailer in retailers))
            for period in periods
        ]
        for product in products
    }


