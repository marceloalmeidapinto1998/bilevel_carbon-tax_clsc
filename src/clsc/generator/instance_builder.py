from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - only needed for optional YAML output
    yaml = None


from .config import GeneratorConfig
from .generated_instance import GeneratedInstance
from .geometry import _build_item_flow_tuples, _build_product_technology_pairs, _complete_cross_arcs, _connect_layers, _labels, _nested_arc_parameter, _products_by_technology, _sample_coordinates, _unique_arcs
from .sampling import _sample_bom_and_product_profiles, _sample_demand, _sum_product_demand_by_period
from . import tautenhain_data as taut

@dataclass(frozen=True, slots=True)
class _Labels:
    """The instance's index sets, built from the configured counts (no sampling)."""

    suppliers: list[str]
    factories: list[str]
    warehouses: list[str]
    retailers: list[str]
    airports: list[str]
    seaports: list[str]
    hubs: list[str]
    products: list[str]
    recovered_products: list[str]
    raw_materials: list[str]
    trucks: list[str]
    airplanes: list[str]
    boats: list[str]
    modes: list[str]
    production_technologies: list[str]
    remanufacturing_technologies: list[str]
    production_pairs: list
    remanufacturing_pairs: list
    production_products_by_technology: dict
    remanufacturing_products_by_technology: dict
    periods: list[str]
    all_entities: list[str]


@dataclass(frozen=True, slots=True)
class _Network:
    """The transport arcs: one list per layer pair, and the unions used by the flow sets."""

    arcs_sf: list
    arcs_fw: list
    arcs_wr: list
    arcs_rf: list
    arcs_fr: list
    arcs_rw: list
    arcs_wf: list
    arcs_s_hub: list
    arcs_hub_f: list
    arcs_f_hub: list
    arcs_w_hub: list
    arcs_hub_w: list
    arcs_hub_r: list
    arcs_r_hub: list
    arcs_air_air: list
    arcs_port_port: list
    raw_arcs: list
    final_product_arcs: list
    recovered_product_arcs: list
    transport_arcs: list


def generate_instance(config: GeneratorConfig) -> GeneratedInstance:
    """Sample one instance from ``config``.

    The draws from ``rng`` happen in a fixed order -- coordinates, demand and returns, bills of
    materials, facility areas, technologies, labour, transport modes, process emissions,
    inventory, then suppliers and market -- and that order is what makes an instance reproducible
    from its seed. Each helper below draws its block in that order; do not reorder the calls.
    """
    rng = random.Random(config.seed)
    labels = _build_labels(config)

    coordinates = _sample_coordinates(rng, labels.all_entities, config.coordinate_span_km)
    network = _build_network(config, labels, coordinates)
    dist_transport = _sample_arc_distances(config, network.transport_arcs)

    demand, return_min_rate, return_max_rate = _sample_demand(rng, labels.retailers, labels.products, labels.periods)
    return_lag = {
        product: taut.sample_return_lag_period(rng, planning_periods=len(labels.periods))
        for product in labels.products
    }
    (
        technology_input_requirement,
        input_requirement,
        raw_material_weight,
        raw_material_area,
        product_unit_weight,
        product_unit_area,
        remanufacturing_bom_matrix,
        return_yield_matrix,
        recovered_product_weight,
        recovered_product_area,
    ) = _sample_bom_and_product_profiles(
        rng,
        labels.raw_materials,
        labels.products,
        labels.recovered_products,
        labels.production_technologies,
        labels.production_pairs,
    )
    product_rotation_area = {
        product: round(area / taut.PRODUCT_ROTATION_PER_PERIOD, 6)
        for product, area in product_unit_area.items()
    }
    product_demand_by_period = _sum_product_demand_by_period(
        demand, labels.retailers, labels.products, labels.periods,
    )

    areas = _sample_facility_areas(rng, labels)
    technologies = _sample_technologies(rng, labels, product_demand_by_period)
    labour = _sample_labour(rng, labels, technologies)
    transport = _sample_transport_modes(rng, labels.modes)
    process_emissions = _sample_process_emissions(rng, labels)
    inventory = _sample_inventory(rng, labels, product_demand_by_period, product_unit_weight)
    supply_and_market = _sample_supply_and_market(
        rng, labels, technologies["bar_p_g"], technology_input_requirement, remanufacturing_bom_matrix,
    )

    metadata = _build_metadata(config, coordinates, transport["mode_family_m"], return_yield_matrix)
    sets = _build_sets(labels, network)
    parameters = {
        "c_area_f": areas["c_area_f"],
        "c_area_w": areas["c_area_w"],
        # No "f_s": selecting a supplier is free in both sources. See the note
        # beside SUPPLIER_MIN_FRACTION_RANGE in tautenhain_data.
        "i_prod_g": technologies["i_prod_g"],
        "i_rem_l": technologies["i_rem_l"],
        "c_prod_g": technologies["c_prod_g"],
        "c_rem_l": technologies["c_rem_l"],
        "h_p": inventory["h_p"],
        "rpc_rp": supply_and_market["rpc_rp"],
        "rmc_s_u": supply_and_market["rmc_s_u"],
        "c_ship_m": transport["c_ship_m"],
        "c_trip_m": transport["c_trip_m"],
        "f_mode_m": transport["f_mode_m"],
        "c_handle_m": transport["c_handle_m"],
        "f_h": supply_and_market["f_h"],
        "mode_family_m": transport["mode_family_m"],
        "road_return_factor_m": transport["road_return_factor_m"],
        "speed_km_h_m": transport["speed_km_h_m"],
        "max_driving_hours_m": transport["max_driving_hours_m"],
        "truck_investment_budget": taut.TRUCK_INVESTMENT_BUDGET,
        "interest_rate": taut.INTEREST_RATE,
        # Stated on the instance rather than inferred by the model: both are
        # per-period quantities derived from WEEKS_PER_PERIOD, and an instance
        # that carries them can be reloaded years later without depending on
        # whatever the generator constants happen to say then.
        "product_rotation_per_period": taut.PRODUCT_ROTATION_PER_PERIOD,
        "asset_life_years": dict(taut.ASSET_LIFE_YEARS),
        # Labour: Mota eq. 43 charges each crew as workers * lc_i * wwh * wpt,
        # every period. wwh and wpt are emitted separately so the product is
        # auditable rather than pre-collapsed.
        "labour_cost_i": labour["labour_cost_i"],
        "workers_fixed_i": labour["workers_fixed_i"],
        "workers_per_sqm_i": labour["workers_per_sqm_i"],
        "workers_prod_g": labour["workers_prod_g"],
        "workers_rem_l": labour["workers_rem_l"],
        "workers_mode_m": {
            mode: taut.mode_workers(transport["mode_family_m"][mode]) for mode in labels.modes
        },
        "weekly_working_hours": taut.WEEKLY_WORKING_HOURS,
        "weeks_per_period": taut.WEEKS_PER_PERIOD,
        "trip_big_m_m": transport["trip_big_m_m"],
        "bar_s_s_u": supply_and_market["bar_s_s_u"],
        "scmin_s_u": supply_and_market["scmin_s_u"],
        "bar_p_g": technologies["bar_p_g"],
        "bar_q_l": technologies["bar_q_l"],
        "pcmin_g": technologies["pcmin_g"],
        "pcmin_l": technologies["pcmin_l"],
        "icmax_p_n": inventory["icmax_p_n"],
        "icmin_p_n": inventory["icmin_p_n"],
        "i_p_n_0": inventory["i_p_n_0"],
        "A_f": areas["A_f"],
        "A_w": areas["A_w"],
        "Amin_f": areas["Amin_f"],
        "Amin_w": areas["Amin_w"],
        "apu_u": raw_material_area,
        "apu_p": product_unit_area,
        "apur_p": product_rotation_area,
        "apu_rp": recovered_product_area,
        "apu_q": {
            **raw_material_area,
            **product_unit_area,
            **recovered_product_area,
        },
        "bar_X_m": transport["bar_X_m"],
        "ctmin_m": transport["ctmin_m"],
        "ccamax_m": transport["ccamax_m"],
        # ecmax_i (Mota's node throughput capacity) is intentionally not emitted:
        # entity capacity is carried by the installed-area mechanism (YCT <= YC),
        # as in Tautenhain et al. (2021). See _add_inventory_and_flow_constraints in
        # src/clsc/models/supply_chain.py.
        "a_in_u_p_g": technology_input_requirement,
        "bom_rem_r_p": remanufacturing_bom_matrix,
        "ret_yield_rp_p": return_yield_matrix,
        "omega_u": raw_material_weight,
        "omega_p": product_unit_weight,
        "omega_rp": recovered_product_weight,
        "d_r_p_t": demand,
        "rho_r_p_t": return_max_rate,
        "ret_min_frac_r_p_t": return_min_rate,
        "ret_max_frac_r_p_t": return_max_rate,
        "theta_p": return_lag,
        "e_open_f": {factory: taut.ENTITY_INSTALL_EMISSION_PER_AREA for factory in labels.factories},
        "e_open_w": {warehouse: taut.ENTITY_INSTALL_EMISSION_PER_AREA for warehouse in labels.warehouses},
        "e_prod_g": process_emissions["e_prod_g"],
        "e_rem_l": process_emissions["e_rem_l"],
        "e_raw_s_u": supply_and_market["e_raw_s_u"],
        "e_ship_m": transport["e_ship_m"],
        "underline_tax_rate": config.tax_lower,
        "overline_tax_rate": config.tax_upper,
        "d_i_j": _nested_arc_parameter(network.transport_arcs, dist_transport),
    }

    return GeneratedInstance(
        name=config.instance_name,
        metadata=metadata,
        sets=sets,
        parameters=parameters,
    )


def _build_labels(config: GeneratorConfig) -> _Labels:
    suppliers = _labels("s", config.suppliers)
    factories = _labels("f", config.factories)
    warehouses = _labels("w", config.warehouses)
    retailers = _labels("r", config.retailers)
    airports = _labels("air", config.airports)
    seaports = _labels("port", config.seaports)
    products = _labels("p", config.products)
    trucks = _labels("mrd", config.trucks)
    airplanes = _labels("ma", config.airplanes)
    boats = _labels("ms", config.boats)
    production_technologies = _labels("g", config.production_technologies)
    remanufacturing_technologies = _labels("l", config.remanufacturing_technologies)
    production_pairs = _build_product_technology_pairs(products, production_technologies)
    remanufacturing_pairs = _build_product_technology_pairs(products, remanufacturing_technologies)
    return _Labels(
        suppliers=suppliers,
        factories=factories,
        warehouses=warehouses,
        retailers=retailers,
        airports=airports,
        seaports=seaports,
        hubs=[*airports, *seaports],
        products=products,
        recovered_products=_labels("rp", config.products),
        raw_materials=_labels("u", config.raw_materials),
        trucks=trucks,
        airplanes=airplanes,
        boats=boats,
        modes=[*trucks, *airplanes, *boats],
        production_technologies=production_technologies,
        remanufacturing_technologies=remanufacturing_technologies,
        production_pairs=production_pairs,
        remanufacturing_pairs=remanufacturing_pairs,
        production_products_by_technology=_products_by_technology(production_pairs, production_technologies),
        remanufacturing_products_by_technology=_products_by_technology(
            remanufacturing_pairs, remanufacturing_technologies,
        ),
        periods=[f"t{index}" for index in range(1, config.periods + 1)],
        all_entities=[*suppliers, *factories, *warehouses, *retailers, *airports, *seaports],
    )


def _build_network(config: GeneratorConfig, labels: _Labels, coordinates) -> _Network:
    """Connect the layers by nearest neighbours (deterministic given the coordinates)."""
    connectivity = config.connectivity
    hubs = labels.hubs

    def connect(origins, destinations, neighbors):
        arcs, _ = _connect_layers(origins, destinations, coordinates, neighbors_per_origin=neighbors)
        return arcs

    arcs_sf = connect(labels.suppliers, labels.factories, connectivity.sf_neighbors)
    arcs_fw = connect(labels.factories, labels.warehouses, connectivity.fw_neighbors)
    arcs_wr = connect(labels.warehouses, labels.retailers, len(labels.retailers))
    arcs_rf = connect(labels.retailers, labels.factories, len(labels.factories))
    arcs_fr = connect(labels.factories, labels.retailers, len(labels.retailers))
    arcs_rw = connect(labels.retailers, labels.warehouses, len(labels.warehouses))
    arcs_wf = connect(labels.warehouses, labels.factories, connectivity.rf_neighbors)
    arcs_s_hub = connect(labels.suppliers, hubs, min(2, len(hubs)))
    arcs_hub_f = connect(hubs, labels.factories, connectivity.sf_neighbors)
    arcs_f_hub = connect(labels.factories, hubs, min(2, len(hubs)))
    arcs_w_hub = connect(labels.warehouses, hubs, min(2, len(hubs)))
    arcs_hub_w = connect(hubs, labels.warehouses, connectivity.fw_neighbors)
    arcs_hub_r = connect(hubs, labels.retailers, len(labels.retailers))
    arcs_r_hub = connect(labels.retailers, hubs, len(hubs))
    arcs_air_air = _complete_cross_arcs(labels.airports, labels.airports)
    arcs_port_port = _complete_cross_arcs(labels.seaports, labels.seaports)

    hub_transfer_arcs = _unique_arcs(arcs_air_air, arcs_port_port)
    raw_arcs = _unique_arcs(arcs_sf, arcs_s_hub, hub_transfer_arcs, arcs_hub_f)
    final_product_arcs = _unique_arcs(
        arcs_fw,
        arcs_wr,
        arcs_fr,
        arcs_f_hub,
        hub_transfer_arcs,
        arcs_w_hub,
        arcs_hub_w,
        arcs_hub_r,
    )
    recovered_product_arcs = _unique_arcs(
        arcs_rf,
        arcs_rw,
        arcs_wf,
        arcs_r_hub,
        arcs_w_hub,
        hub_transfer_arcs,
        arcs_hub_f,
        arcs_hub_w,
    )
    return _Network(
        arcs_sf=arcs_sf,
        arcs_fw=arcs_fw,
        arcs_wr=arcs_wr,
        arcs_rf=arcs_rf,
        arcs_fr=arcs_fr,
        arcs_rw=arcs_rw,
        arcs_wf=arcs_wf,
        arcs_s_hub=arcs_s_hub,
        arcs_hub_f=arcs_hub_f,
        arcs_f_hub=arcs_f_hub,
        arcs_w_hub=arcs_w_hub,
        arcs_hub_w=arcs_hub_w,
        arcs_hub_r=arcs_hub_r,
        arcs_r_hub=arcs_r_hub,
        arcs_air_air=arcs_air_air,
        arcs_port_port=arcs_port_port,
        raw_arcs=raw_arcs,
        final_product_arcs=final_product_arcs,
        recovered_product_arcs=recovered_product_arcs,
        transport_arcs=_unique_arcs(raw_arcs, final_product_arcs, recovered_product_arcs),
    )


def _sample_arc_distances(config: GeneratorConfig, transport_arcs) -> dict[tuple[str, str], float]:
    """Arc distances, from their own RNG so that no other parameter's draw depends on them.

    Tautenhain et al. use a generalized tuple system for feasible item flows. We keep that
    structure through the FLOW_* sets and assign every feasible transport arc a distance sampled
    from Tautenhain's uniform range (dist_ij ~ U[DISTANCE_RANGE], generator supp. Table 3) -- NOT
    the Euclidean distance between the sampled coordinates. Euclidean distances obey the triangle
    inequality, which makes every intermodal hub route (A -> hub -> hub -> B) provably >= the
    direct truck arc A -> B and so leaves the air/sea modes structurally unusable (the follower,
    minimising cost, never routes through a hub); Tautenhain's uniform distances do not obey it,
    so hub routing can win. Coordinates are kept solely to decide which arcs exist
    (nearest-neighbour layering in _build_network), not for arc distance. A dedicated RNG keeps
    every other sampled parameter byte-identical to the coordinate-based generator, isolating the
    distance change. Distances are symmetric per unordered node pair (a physical distance),
    matching Mota et al.'s table.
    """
    distance_rng = random.Random(f"{config.seed}:transport-distance")
    pair_distance_km: dict[frozenset[str], float] = {}
    dist_transport: dict[tuple[str, str], float] = {}
    for origin, destination in transport_arcs:
        pair_key = frozenset((origin, destination))
        if pair_key not in pair_distance_km:
            pair_distance_km[pair_key] = taut.sample_distance_km(
                distance_rng, lower=taut.DISTANCE_RANGE[0], upper=taut.DISTANCE_RANGE[1]
            )
        dist_transport[(origin, destination)] = pair_distance_km[pair_key]
    return dist_transport


def _sample_facility_areas(rng: random.Random, labels: _Labels) -> dict[str, dict[str, float]]:
    factory_area: dict[str, float] = {}
    factory_area_min: dict[str, float] = {}
    factory_area_max: dict[str, float] = {}
    warehouse_area: dict[str, float] = {}
    warehouse_area_min: dict[str, float] = {}
    warehouse_area_max: dict[str, float] = {}
    factory_area_cost: dict[str, float] = {}
    warehouse_area_cost: dict[str, float] = {}

    for factory in labels.factories:
        factory_area_min[factory] = round(rng.uniform(*taut.FACTORY_AREA_MIN_RANGE), 2)
        factory_area_max[factory] = round(rng.uniform(*taut.FACTORY_AREA_MAX_RANGE), 2)
        factory_area[factory] = factory_area_max[factory]
        factory_area_cost[factory] = taut.sample_area_installation_cost(rng)

    for warehouse in labels.warehouses:
        warehouse_area_min[warehouse] = round(rng.uniform(*taut.WAREHOUSE_AREA_MIN_RANGE), 2)
        warehouse_area_max[warehouse] = round(rng.uniform(*taut.WAREHOUSE_AREA_MAX_RANGE), 2)
        warehouse_area[warehouse] = warehouse_area_max[warehouse]
        warehouse_area_cost[warehouse] = taut.sample_area_installation_cost(rng)

    return {
        "A_f": factory_area,
        "A_w": warehouse_area,
        "Amin_f": factory_area_min,
        "Amin_w": warehouse_area_min,
        "c_area_f": factory_area_cost,
        "c_area_w": warehouse_area_cost,
    }


def _sample_technologies(rng: random.Random, labels: _Labels, product_demand_by_period) -> dict[str, dict]:
    """Capacities, minimum use, installation and operating costs of the technologies."""
    periods = labels.periods
    production_capacity = {
        technology: taut.sample_technology_capacity(
            rng,
            [
                product_demand_by_period[product][period_index]
                for product in labels.production_products_by_technology[technology]
                for period_index in range(len(periods))
            ],
            facility_count=len(labels.factories),
        )
        for technology in labels.production_technologies
    }
    remanufacturing_capacity = {
        technology: taut.sample_technology_capacity(
            rng,
            [
                product_demand_by_period[product][period_index]
                for product in labels.remanufacturing_products_by_technology[technology]
                for period_index in range(len(periods))
            ],
            facility_count=len(labels.factories),
        )
        for technology in labels.remanufacturing_technologies
    }
    production_minimum_use = {
        technology: taut.sample_minimum_technology_use(capacity=production_capacity[technology])
        for technology in labels.production_technologies
    }
    remanufacturing_minimum_use = {
        technology: taut.sample_minimum_technology_use(capacity=remanufacturing_capacity[technology])
        for technology in labels.remanufacturing_technologies
    }
    production_install_cost = {
        technology: taut.sample_technology_install_cost(rng, capacity=production_capacity[technology])
        for technology in labels.production_technologies
    }
    remanufacturing_install_cost = {
        technology: taut.sample_technology_install_cost(rng, capacity=remanufacturing_capacity[technology])
        for technology in labels.remanufacturing_technologies
    }
    production_cost = {
        technology: round(rng.uniform(*taut.TECH_OPERATING_COST_RANGE), 4)
        for technology in labels.production_technologies
    }
    remanufacturing_cost = {
        technology: round(rng.uniform(*taut.TECH_OPERATING_COST_RANGE), 4)
        for technology in labels.remanufacturing_technologies
    }
    return {
        "bar_p_g": production_capacity,
        "bar_q_l": remanufacturing_capacity,
        "pcmin_g": production_minimum_use,
        "pcmin_l": remanufacturing_minimum_use,
        "i_prod_g": production_install_cost,
        "i_rem_l": remanufacturing_install_cost,
        "c_prod_g": production_cost,
        "c_rem_l": remanufacturing_cost,
    }


def _sample_labour(rng: random.Random, labels: _Labels, technologies: dict[str, dict]) -> dict[str, dict]:
    """Labour (Mota eq. 43, terms 10-13). lc_i is drawn for every entity, but only facilities,
    technologies and owned vehicles actually incur a crew."""
    labour_cost = {entity: taut.sample_labour_cost(rng) for entity in labels.all_entities}
    fixed_workers = {
        **{factory: taut.sample_fixed_workers(rng, factory=True) for factory in labels.factories},
        **{warehouse: taut.sample_fixed_workers(rng, factory=False) for warehouse in labels.warehouses},
    }
    workers_per_sqm = {
        entity: taut.WORKERS_PER_SQM for entity in (*labels.factories, *labels.warehouses)
    }
    production_workers = {
        technology: taut.technology_workers(technologies["c_prod_g"][technology])
        for technology in labels.production_technologies
    }
    remanufacturing_workers = {
        technology: taut.technology_workers(technologies["c_rem_l"][technology])
        for technology in labels.remanufacturing_technologies
    }
    return {
        "labour_cost_i": labour_cost,
        "workers_fixed_i": fixed_workers,
        "workers_per_sqm_i": workers_per_sqm,
        "workers_prod_g": production_workers,
        "workers_rem_l": remanufacturing_workers,
    }


def _sample_transport_modes(rng: random.Random, modes: list[str]) -> dict[str, dict]:
    transport_capacity: dict[str, float] = {}
    transport_min_capacity: dict[str, float] = {}
    contracted_capacity: dict[str, float] = {}
    transport_fixed_cost: dict[str, float] = {}
    transport_cost: dict[str, float] = {}
    transport_trip_cost: dict[str, float] = {}
    road_return_factor: dict[str, float] = {}
    speed_km_h: dict[str, float] = {}
    max_driving_hours: dict[str, float] = {}
    trip_big_m: dict[str, int] = {}
    hub_handling_cost: dict[str, float] = {}
    transport_emission: dict[str, float] = {}
    transport_family: dict[str, str] = {}

    for index, mode in enumerate(modes):
        family = taut.resolve_mode_family(mode, {}, fallback_index=index)
        capacity_kg = taut.sample_transport_capacity_kg(rng, family)
        transport_family[mode] = family
        transport_capacity[mode] = round(capacity_kg, 2)
        transport_min_capacity[mode] = taut.TRANSPORT_MIN_CAPACITY_KG
        contracted_capacity[mode] = (
            taut.CONTRACTED_CAPACITY_KG if family in {"air", "sea"} else 0.0
        )
        transport_fixed_cost[mode] = taut.sample_transport_fixed_cost(rng, family)
        hub_handling_cost[mode] = taut.sample_hub_handling_cost(rng, family)
        transport_cost[mode] = taut.sample_transport_cost_per_kg_km(
            rng,
            family,
            capacity_kg=capacity_kg,
        )
        transport_trip_cost[mode] = (
            round(transport_cost[mode] * transport_capacity[mode], 6) if family == "truck" else 0.0
        )
        road_return_factor[mode] = taut.TRUCK_RETURN_DISTANCE_FACTOR if family == "truck" else 1.0
        speed_km_h[mode] = taut.TRUCK_SPEED_KM_H if family == "truck" else 0.0
        max_driving_hours[mode] = taut.MAX_DRIVING_HOURS_PER_PERIOD if family == "truck" else 0.0
        # Stored as a coarse mode-level fallback only. The follower model tightens
        # truck trip activation further with endpoint-specific flow bounds.
        trip_big_m[mode] = max(1, math.ceil(taut.MAX_ENTITY_FLOW_KG / capacity_kg) + 1)
        transport_emission[mode] = taut.sample_transport_emission_per_kg_km(rng, family)

    return {
        "mode_family_m": transport_family,
        "bar_X_m": transport_capacity,
        "ctmin_m": transport_min_capacity,
        "ccamax_m": contracted_capacity,
        "f_mode_m": transport_fixed_cost,
        "c_handle_m": hub_handling_cost,
        "c_ship_m": transport_cost,
        "c_trip_m": transport_trip_cost,
        "road_return_factor_m": road_return_factor,
        "speed_km_h_m": speed_km_h,
        "max_driving_hours_m": max_driving_hours,
        "trip_big_m_m": trip_big_m,
        "e_ship_m": transport_emission,
    }


def _sample_process_emissions(rng: random.Random, labels: _Labels) -> dict[str, dict[str, float]]:
    """Tautenhain et al. use ReCiPe-style environmental categories; this carbon-tax model keeps
    only the climate-change category in kg CO2-eq. Process intensities are stored per kg of output
    mass; the follower model multiplies them by product unit weights."""
    production_emission = {
        technology: round(
            rng.uniform(*taut.PROCESS_EMISSION_RANGE_PER_KG_MASS),
            4,
        )
        for technology in labels.production_technologies
    }
    remanufacturing_emission = {
        technology: round(
            rng.uniform(*taut.PROCESS_EMISSION_RANGE_PER_KG_MASS),
            4,
        )
        for technology in labels.remanufacturing_technologies
    }
    return {"e_prod_g": production_emission, "e_rem_l": remanufacturing_emission}


def _sample_inventory(
    rng: random.Random, labels: _Labels, product_demand_by_period, product_unit_weight,
) -> dict[str, dict]:
    inventory_capacity_by_product_node: dict[str, dict[str, float]] = {
        product: {} for product in labels.products
    }
    for product in labels.products:
        for warehouse in labels.warehouses:
            inventory_capacity_by_product_node[product][warehouse] = taut.sample_inventory_capacity_for_product(
                rng,
                product_demand_by_period[product],
            )

    inventory_minimum_by_product_node = {
        product: {
            node: taut.sample_minimum_inventory(capacity=capacity)
            for node, capacity in node_capacity.items()
        }
        for product, node_capacity in inventory_capacity_by_product_node.items()
    }
    holding_cost_product = {
        product: round(taut.STOCK_COST_BASE + product_unit_weight[product], 4)
        for product in labels.products
    }
    initial_inventory: dict[str, dict[str, float]] = {}
    for product in labels.products:
        # Factories carry no inventory and recovered items are never held in
        # stock anywhere (Mota et al. 2018 / Tautenhain et al. 2021 inventory
        # policy); only warehouses hold finished-product inventory.
        initial_inventory[product] = {warehouse: 0.0 for warehouse in labels.warehouses}
    return {
        "icmax_p_n": inventory_capacity_by_product_node,
        "icmin_p_n": inventory_minimum_by_product_node,
        "h_p": holding_cost_product,
        "i_p_n_0": initial_inventory,
    }


def _sample_supply_and_market(
    rng: random.Random,
    labels: _Labels,
    production_capacity,
    technology_input_requirement,
    remanufacturing_bom_matrix,
) -> dict[str, dict]:
    """Supplier capacities and prices, selling prices, recovery costs and hub operating costs."""
    suppliers, products, raw_materials = labels.suppliers, labels.products, labels.raw_materials
    supplier_capacity_by_material = {
        supplier: {
            material: float(
                3
                * taut.ceil_nonnegative(
                    sum(
                        production_capacity[technology]
                        * technology_input_requirement[material][product][technology]
                        for product in products
                        for technology in labels.production_products_by_technology
                        if product in labels.production_products_by_technology[technology]
                    )
                    / len(suppliers)
                )
            )
            for material in raw_materials
        }
        for supplier in suppliers
    }
    supplier_minimum_order_by_material = {
        supplier: {
            material: taut.sample_supplier_minimum_order(
                rng,
                capacity=supplier_capacity_by_material[supplier][material],
            )
            for material in raw_materials
        }
        for supplier in suppliers
    }
    raw_material_cost = {
        supplier: {
            material: taut.sample_raw_material_cost(rng)
            for material in raw_materials
        }
        for supplier in suppliers
    }
    raw_material_emission = {
        supplier: {
            material: round(
                rng.uniform(*taut.SUPPLIER_ACQUISITION_EMISSION_RANGE_PER_KG),
                4,
            )
            for material in raw_materials
        }
        for supplier in suppliers
    }
    selling_price = {
        product: taut.sample_selling_price(rng) for product in products
    }
    recovery_cost_recovered = {
        recovered_product: round(
            (
                sum(
                    remanufacturing_bom_matrix[recovered_product][product] * selling_price[product]
                    for product in products
                )
                / len(products)
            )
            * rng.uniform(*taut.RECOVERY_COST_FRACTION_RANGE),
            4,
        )
        for recovered_product in labels.recovered_products
    }
    hub_operating_cost = {
        hub: taut.sample_hub_operating_cost(rng)
        for hub in labels.hubs
    }
    return {
        "bar_s_s_u": supplier_capacity_by_material,
        "scmin_s_u": supplier_minimum_order_by_material,
        "rmc_s_u": raw_material_cost,
        "e_raw_s_u": raw_material_emission,
        "rpc_rp": recovery_cost_recovered,
        "f_h": hub_operating_cost,
    }


def _build_metadata(config: GeneratorConfig, coordinates, transport_family, return_yield_matrix) -> dict:
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": config.seed,
        "sampling_rules_module": "clsc.generator.tautenhain_data",
        "config": config.to_dict(),
        "node_coordinates": coordinates,
        "transport_mode_family": transport_family,
        "unit_convention": {
            "currency": "EUR",
            "raw_material_flow": "item_units",
            "raw_material_cost": "EUR/raw-material unit",
            "raw_material_emission_intensity": "kg CO2e/kg",
            "production_emission_intensity": "kg CO2e/kg",
            "remanufacturing_emission_intensity": "kg CO2e/kg",
            "installation_emission_intensity": "kg CO2e/m2",
            "transport_emission_intensity": "kg CO2e/(kg km), per mode family",
        },
        "derived_unit_profiles": {
            "return_yield_rp_p": return_yield_matrix,
        },
        "carbon_tax_units": {
            "underline_tax_rate_overline_tax_rate": "EUR/kg CO2e",
        },
    }


def _build_sets(labels: _Labels, network: _Network) -> dict:
    return {
        "S": labels.suppliers,
        "F": labels.factories,
        "W": labels.warehouses,
        "R": labels.retailers,
        "AIR": labels.airports,
        "PORT": labels.seaports,
        "I": labels.all_entities,
        "P": labels.products,
        "K": labels.recovered_products,
        "RP": labels.recovered_products,
        "U": labels.raw_materials,
        "M_RD": labels.trucks,
        "M_A": labels.airplanes,
        "M_S": labels.boats,
        "M": labels.modes,
        "G": labels.production_technologies,
        "L": labels.remanufacturing_technologies,
        "T": labels.periods,
        "N": labels.all_entities,
        "V": list(labels.warehouses),
        "A": network.transport_arcs,
        "A_sf": network.arcs_sf,
        "A_fw": network.arcs_fw,
        "A_wr": network.arcs_wr,
        "A_rf": network.arcs_rf,
        "A_fr": network.arcs_fr,
        "A_rw": network.arcs_rw,
        "A_wf": network.arcs_wf,
        "A_s_hub": network.arcs_s_hub,
        "A_hub_f": network.arcs_hub_f,
        "A_f_hub": network.arcs_f_hub,
        "A_w_hub": network.arcs_w_hub,
        "A_hub_w": network.arcs_hub_w,
        "A_hub_r": network.arcs_hub_r,
        "A_r_hub": network.arcs_r_hub,
        "A_air_air": network.arcs_air_air,
        "A_port_port": network.arcs_port_port,
        "FLOW_RAW": _build_item_flow_tuples(labels.raw_materials, network.raw_arcs),
        "FLOW_FP": _build_item_flow_tuples(labels.products, network.final_product_arcs),
        "FLOW_RP": _build_item_flow_tuples(labels.recovered_products, network.recovered_product_arcs),
        "H_prod": labels.production_pairs,
        "H_rem": labels.remanufacturing_pairs,
    }


def write_instance(instance: GeneratedInstance, output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = instance.to_dict()

    if destination.suffix.lower() == ".json":
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return destination
    if destination.suffix.lower() in {".yaml", ".yml"}:
        if yaml is None:
            raise RuntimeError("YAML output requires PyYAML to be installed")
        destination.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        return destination
    raise ValueError("output_path must end with .json, .yaml, or .yml")
