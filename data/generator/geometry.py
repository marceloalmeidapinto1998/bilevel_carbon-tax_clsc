from __future__ import annotations

import math
import random
from typing import Iterable

def _labels(prefix: str, count: int) -> list[str]:
    return [f"{prefix}{index}" for index in range(1, count + 1)]


def _nested_pairs_to_dict(
    pairs: Iterable[tuple[str, str]],
    distance_lookup: dict[tuple[str, str], float],
) -> dict[str, dict[str, float]]:
    nested: dict[str, dict[str, float]] = {}
    for origin, destination in pairs:
        nested.setdefault(origin, {})[destination] = distance_lookup[(origin, destination)]
    return nested


def _sample_coordinates(
    rng: random.Random,
    labels: Iterable[str],
    span_km: float,
) -> dict[str, dict[str, float]]:
    return {
        label: {
            "x": round(rng.uniform(0.0, span_km), 3),
            "y": round(rng.uniform(0.0, span_km), 3),
        }
        for label in labels
    }


def _distance_km(
    node_a: str,
    node_b: str,
    coordinates: dict[str, dict[str, float]],
) -> float:
    ax, ay = coordinates[node_a]["x"], coordinates[node_a]["y"]
    bx, by = coordinates[node_b]["x"], coordinates[node_b]["y"]
    return round(max(10.0, math.dist((ax, ay), (bx, by))), 3)


def _connect_layers(
    origins: list[str],
    destinations: list[str],
    coordinates: dict[str, dict[str, float]],
    *,
    neighbors_per_origin: int,
) -> tuple[list[list[str]], dict[tuple[str, str], float]]:
    neighbors = min(max(1, neighbors_per_origin), len(destinations))
    arcs: set[tuple[str, str]] = set()
    distance_lookup: dict[tuple[str, str], float] = {}

    for origin in origins:
        ranked_destinations = sorted(
            destinations,
            key=lambda destination: _distance_km(origin, destination, coordinates),
        )
        for destination in ranked_destinations[:neighbors]:
            pair = (origin, destination)
            arcs.add(pair)
            distance_lookup[pair] = _distance_km(origin, destination, coordinates)

    for destination in destinations:
        if any(pair[1] == destination for pair in arcs):
            continue
        closest_origin = min(
            origins,
            key=lambda origin: _distance_km(origin, destination, coordinates),
        )
        pair = (closest_origin, destination)
        arcs.add(pair)
        distance_lookup[pair] = _distance_km(closest_origin, destination, coordinates)

    ordered_pairs = sorted(arcs)
    return [[origin, destination] for origin, destination in ordered_pairs], distance_lookup


def _distances_for_arcs(
    arcs: list[list[str]],
    coordinates: dict[str, dict[str, float]],
) -> dict[tuple[str, str], float]:
    return {
        (origin, destination): _distance_km(origin, destination, coordinates)
        for origin, destination in arcs
    }


def _unique_arcs(*arc_groups: Iterable[list[str]]) -> list[list[str]]:
    arcs: set[tuple[str, str]] = set()
    for group in arc_groups:
        for origin, destination in group:
            if origin != destination:
                arcs.add((origin, destination))
    return [[origin, destination] for origin, destination in sorted(arcs)]


def _complete_cross_arcs(origins: Iterable[str], destinations: Iterable[str]) -> list[list[str]]:
    return [
        [origin, destination]
        for origin in origins
        for destination in destinations
        if origin != destination
    ]


def _build_item_flow_tuples(items: Iterable[str], arcs: Iterable[list[str]]) -> list[list[str]]:
    return [
        [item, origin, destination]
        for item in items
        for origin, destination in arcs
    ]


def _nested_arc_parameter(
    arcs: Iterable[list[str]],
    values: dict[tuple[str, str], float],
) -> dict[str, dict[str, float]]:
    return _nested_pairs_to_dict((tuple(pair) for pair in arcs), values)


def _build_product_technology_pairs(
    products: list[str],
    technologies: list[str],
) -> list[list[str]]:
    if len(products) == 1 or len(technologies) == 1:
        return [[product, technology] for product in products for technology in technologies]

    pairs = {
        (products[index % len(products)], technology)
        for index, technology in enumerate(technologies)
    }
    pairs.update(
        (product, technologies[index % len(technologies)])
        for index, product in enumerate(products)
    )
    return [[product, technology] for product, technology in sorted(pairs)]


def _products_by_technology(
    pairs: list[list[str]],
    technologies: list[str],
) -> dict[str, list[str]]:
    products_by_technology = {technology: [] for technology in technologies}
    for product, technology in pairs:
        products_by_technology.setdefault(technology, []).append(product)
    return products_by_technology


def _technology_pairs_by_product(
    pairs: list[list[str]],
    products: list[str],
) -> dict[str, list[str]]:
    technologies_by_product = {product: [] for product in products}
    for product, technology in pairs:
        technologies_by_product.setdefault(product, []).append(technology)
    return technologies_by_product
