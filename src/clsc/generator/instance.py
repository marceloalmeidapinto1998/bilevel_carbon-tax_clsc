from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - only needed for optional YAML output
    yaml = None

from .config import GeneratorConfig, _tax_rate_to_tax_index
from .models import GeneratedInstance
from .geometry import _build_item_flow_tuples, _build_product_technology_pairs, _complete_cross_arcs, _connect_layers, _labels, _nested_arc_parameter, _products_by_technology, _sample_coordinates, _unique_arcs
from .sampling import _sample_bom_and_product_profiles, _sample_demand, _sum_product_demand_by_period
from . import tautenhain_data as taut

def generate_instance(config: GeneratorConfig) -> GeneratedInstance:
    rng = random.Random(config.seed)

    suppliers = _labels("s", config.suppliers)
    factories = _labels("f", config.factories)
    warehouses = _labels("w", config.warehouses)
    retailers = _labels("r", config.retailers)
    airports = _labels("air", config.airports)
    seaports = _labels("port", config.seaports)
    products = _labels("p", config.products)
    recovered_products = _labels("rp", config.products)
    raw_materials = _labels("u", config.raw_materials)
    trucks = _labels("mrd", config.trucks)
    airplanes = _labels("ma", config.airplanes)
    boats = _labels("ms", config.boats)
    modes = [*trucks, *airplanes, *boats]
    production_technologies = _labels("g", config.production_technologies)
    remanufacturing_technologies = _labels("l", config.remanufacturing_technologies)
    production_pairs = _build_product_technology_pairs(products, production_technologies)
    remanufacturing_pairs = _build_product_technology_pairs(products, remanufacturing_technologies)
    production_products_by_technology = _products_by_technology(
        production_pairs,
        production_technologies,
    )
    remanufacturing_products_by_technology = _products_by_technology(
        remanufacturing_pairs,
        remanufacturing_technologies,
    )
    periods = [f"t{index}" for index in range(1, config.periods + 1)]
    all_entities = [*suppliers, *factories, *warehouses, *retailers, *airports, *seaports]

    coordinates = _sample_coordinates(
        rng,
        all_entities,
        config.coordinate_span_km,
    )
    arcs_sf, _ = _connect_layers(
        suppliers,
        factories,
        coordinates,
        neighbors_per_origin=config.connectivity.sf_neighbors,
    )
    arcs_fw, _ = _connect_layers(
        factories,
        warehouses,
        coordinates,
        neighbors_per_origin=config.connectivity.fw_neighbors,
    )
    arcs_wr, _ = _connect_layers(
        warehouses,
        retailers,
        coordinates,
        neighbors_per_origin=len(retailers),
    )
    arcs_rf, _ = _connect_layers(
        retailers,
        factories,
        coordinates,
        neighbors_per_origin=len(factories),
    )

    arcs_fr, _ = _connect_layers(
        factories,
        retailers,
        coordinates,
        neighbors_per_origin=len(retailers),
    )
    arcs_rw, _ = _connect_layers(
        retailers,
        warehouses,
        coordinates,
        neighbors_per_origin=len(warehouses),
    )
    arcs_wf, _ = _connect_layers(
        warehouses,
        factories,
        coordinates,
        neighbors_per_origin=config.connectivity.rf_neighbors,
    )
    hubs = [*airports, *seaports]
    arcs_s_hub, _ = _connect_layers(
        suppliers,
        hubs,
        coordinates,
        neighbors_per_origin=min(2, len(hubs)),
    )
    arcs_hub_f, _ = _connect_layers(
        hubs,
        factories,
        coordinates,
        neighbors_per_origin=config.connectivity.sf_neighbors,
    )
    arcs_f_hub, _ = _connect_layers(
        factories,
        hubs,
        coordinates,
        neighbors_per_origin=min(2, len(hubs)),
    )
    arcs_w_hub, _ = _connect_layers(
        warehouses,
        hubs,
        coordinates,
        neighbors_per_origin=min(2, len(hubs)),
    )
    arcs_hub_w, _ = _connect_layers(
        hubs,
        warehouses,
        coordinates,
        neighbors_per_origin=config.connectivity.fw_neighbors,
    )
    arcs_hub_r, _ = _connect_layers(
        hubs,
        retailers,
        coordinates,
        neighbors_per_origin=len(retailers),
    )
    arcs_r_hub, _ = _connect_layers(
        retailers,
        hubs,
        coordinates,
        neighbors_per_origin=len(hubs),
    )
    arcs_air_air = _complete_cross_arcs(airports, airports)
    arcs_port_port = _complete_cross_arcs(seaports, seaports)

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
    transport_arcs = _unique_arcs(raw_arcs, final_product_arcs, recovered_product_arcs)
    # Tautenhain et al. use a generalized tuple system for feasible item flows.
    # We keep that structure through the FLOW_* sets and assign every feasible
    # transport arc a distance sampled from Tautenhain's uniform range
    # (dist_ij ~ U[DISTANCE_RANGE], generator supp. Table 3) -- NOT the Euclidean
    # distance between the sampled coordinates. Euclidean distances obey the triangle
    # inequality, which makes every intermodal hub route (A -> hub -> hub -> B)
    # provably >= the direct truck arc A -> B and so leaves the air/sea modes
    # structurally unusable (the follower, minimising cost, never routes through a
    # hub); Tautenhain's uniform distances do not obey it, so hub routing can win.
    # Coordinates are kept solely to decide which arcs exist (nearest-neighbour
    # layering in _connect_layers above), not for arc distance. A dedicated RNG
    # keeps every other sampled parameter byte-identical to the coordinate-based
    # generator, isolating the distance change. Distances are symmetric per
    # unordered node pair (a physical distance), matching Mota et al.'s table.
    distance_rng = random.Random(f"{config.seed}:transport-distance")
    _pair_distance_km: dict[frozenset[str], float] = {}
    dist_transport: dict[tuple[str, str], float] = {}
    for origin, destination in transport_arcs:
        pair_key = frozenset((origin, destination))
        if pair_key not in _pair_distance_km:
            _pair_distance_km[pair_key] = taut.sample_distance_km(
                distance_rng, lower=taut.DISTANCE_RANGE[0], upper=taut.DISTANCE_RANGE[1]
            )
        dist_transport[(origin, destination)] = _pair_distance_km[pair_key]
    demand, return_min_rate, return_max_rate = _sample_demand(rng, retailers, products, periods)
    return_lag = {
        product: taut.sample_return_lag_period(rng, planning_periods=len(periods))
        for product in products
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
        raw_materials,
        products,
        recovered_products,
        production_technologies,
        production_pairs,
    )
    product_rotation_area = {
        product: round(area / taut.PRODUCT_ROTATION_PER_PERIOD, 6)
        for product, area in product_unit_area.items()
    }

    product_demand_by_period = _sum_product_demand_by_period(demand, retailers, products, periods)
    factory_area: dict[str, float] = {}
    factory_area_min: dict[str, float] = {}
    factory_area_max: dict[str, float] = {}
    warehouse_area: dict[str, float] = {}
    warehouse_area_min: dict[str, float] = {}
    warehouse_area_max: dict[str, float] = {}
    factory_area_cost: dict[str, float] = {}
    warehouse_area_cost: dict[str, float] = {}

    for factory in factories:
        factory_area_min[factory] = round(rng.uniform(*taut.FACTORY_AREA_MIN_RANGE), 2)
        factory_area_max[factory] = round(rng.uniform(*taut.FACTORY_AREA_MAX_RANGE), 2)
        factory_area[factory] = factory_area_max[factory]
        factory_area_cost[factory] = taut.sample_area_installation_cost(rng)

    for warehouse in warehouses:
        warehouse_area_min[warehouse] = round(rng.uniform(*taut.WAREHOUSE_AREA_MIN_RANGE), 2)
        warehouse_area_max[warehouse] = round(rng.uniform(*taut.WAREHOUSE_AREA_MAX_RANGE), 2)
        warehouse_area[warehouse] = warehouse_area_max[warehouse]
        warehouse_area_cost[warehouse] = taut.sample_area_installation_cost(rng)

    production_capacity = {
        technology: taut.sample_technology_capacity(
            rng,
            [
                product_demand_by_period[product][period_index]
                for product in production_products_by_technology[technology]
                for period_index in range(len(periods))
            ],
            facility_count=len(factories),
        )
        for technology in production_technologies
    }
    remanufacturing_capacity = {
        technology: taut.sample_technology_capacity(
            rng,
            [
                product_demand_by_period[product][period_index]
                for product in remanufacturing_products_by_technology[technology]
                for period_index in range(len(periods))
            ],
            facility_count=len(factories),
        )
        for technology in remanufacturing_technologies
    }
    production_minimum_use = {
        technology: taut.sample_minimum_technology_use(capacity=production_capacity[technology])
        for technology in production_technologies
    }
    remanufacturing_minimum_use = {
        technology: taut.sample_minimum_technology_use(capacity=remanufacturing_capacity[technology])
        for technology in remanufacturing_technologies
    }

    production_install_cost = {
        technology: taut.sample_technology_install_cost(rng, capacity=production_capacity[technology])
        for technology in production_technologies
    }
    remanufacturing_install_cost = {
        technology: taut.sample_technology_install_cost(rng, capacity=remanufacturing_capacity[technology])
        for technology in remanufacturing_technologies
    }
    production_cost = {
        technology: round(rng.uniform(*taut.TECH_OPERATING_COST_RANGE), 4)
        for technology in production_technologies
    }
    remanufacturing_cost = {
        technology: round(rng.uniform(*taut.TECH_OPERATING_COST_RANGE), 4)
        for technology in remanufacturing_technologies
    }

    # Labour (Mota eq. 43, terms 10-13). lc_i is drawn for every entity, but
    # only facilities, technologies and owned vehicles actually incur a crew.
    labour_cost = {entity: taut.sample_labour_cost(rng) for entity in all_entities}
    fixed_workers = {
        **{factory: taut.sample_fixed_workers(rng, factory=True) for factory in factories},
        **{warehouse: taut.sample_fixed_workers(rng, factory=False) for warehouse in warehouses},
    }
    workers_per_sqm = {
        entity: taut.WORKERS_PER_SQM for entity in (*factories, *warehouses)
    }
    production_workers = {
        technology: taut.technology_workers(production_cost[technology])
        for technology in production_technologies
    }
    remanufacturing_workers = {
        technology: taut.technology_workers(remanufacturing_cost[technology])
        for technology in remanufacturing_technologies
    }

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
        transport_emission[mode] = round(
            rng.uniform(*taut.TRANSPORT_EMISSION_RANGE_PER_KGKM),
            6,
        )

    # Tautenhain et al. use ReCiPe-style environmental categories; this
    # carbon-tax model keeps only the climate-change category in kg CO2-eq.
    # Process intensities are stored per kg of output mass; the follower model
    # multiplies them by product unit weights.
    production_emission = {
        technology: round(
            rng.uniform(*taut.PROCESS_EMISSION_RANGE_PER_KG_MASS),
            4,
        )
        for technology in production_technologies
    }
    remanufacturing_emission = {
        technology: round(
            rng.uniform(*taut.PROCESS_EMISSION_RANGE_PER_KG_MASS),
            4,
        )
        for technology in remanufacturing_technologies
    }

    inventory_capacity_by_product_node: dict[str, dict[str, float]] = {
        product: {} for product in products
    }
    for product in products:
        for warehouse in warehouses:
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
        for product in products
    }

    supplier_capacity_by_material = {
        supplier: {
            material: float(
                3
                * taut.ceil_nonnegative(
                    sum(
                        production_capacity[technology]
                        * technology_input_requirement[material][product][technology]
                        for product in products
                        for technology in production_products_by_technology
                        if product in production_products_by_technology[technology]
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
        for recovered_product in recovered_products
    }
    hub_operating_cost = {
        hub: taut.sample_hub_operating_cost(rng)
        for hub in hubs
    }
    initial_inventory: dict[str, dict[str, float]] = {}
    for product in products:
        # Factories carry no inventory and recovered items are never held in
        # stock anywhere (Mota et al. 2018 / Tautenhain et al. 2021 inventory
        # policy); only warehouses hold finished-product inventory.
        initial_inventory[product] = {warehouse: 0.0 for warehouse in warehouses}

    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": config.seed,
        "sampling_rules_module": "clsc.generator.tautenhain_data",
        "config": config.to_dict(),
        "node_coordinates": coordinates,
        "transport_mode_family": transport_family,
        "unit_convention": {
            "raw_material_flow": "item_units",
            "raw_material_cost": "USD/raw-material unit",
            "raw_material_emission_intensity": "kg CO2e/kg",
            "production_emission_intensity": "kg CO2e/kg",
            "remanufacturing_emission_intensity": "kg CO2e/kg",
        },
        "derived_unit_profiles": {
            "return_yield_rp_p": return_yield_matrix,
        },
        "carbon_tax_units": {
            "underline_tax_rate_overline_tax_rate": "USD/kg CO2e",
            "tax_index_step": "0.01 USD/kg CO2e",
            "tau_formula_usd_per_kg_co2e": "0.01 * tax_index",
        },
    }

    sets = {
        "S": suppliers,
        "F": factories,
        "W": warehouses,
        "R": retailers,
        "AIR": airports,
        "PORT": seaports,
        "I": all_entities,
        "P": products,
        "K": recovered_products,
        "RP": recovered_products,
        "U": raw_materials,
        "M_RD": trucks,
        "M_A": airplanes,
        "M_S": boats,
        "M": modes,
        "G": production_technologies,
        "L": remanufacturing_technologies,
        "T": periods,
        "N": all_entities,
        "V": list(warehouses),
        "A": transport_arcs,
        "A_sf": arcs_sf,
        "A_fw": arcs_fw,
        "A_wr": arcs_wr,
        "A_rf": arcs_rf,
        "A_fr": arcs_fr,
        "A_rw": arcs_rw,
        "A_wf": arcs_wf,
        "A_s_hub": arcs_s_hub,
        "A_hub_f": arcs_hub_f,
        "A_f_hub": arcs_f_hub,
        "A_w_hub": arcs_w_hub,
        "A_hub_w": arcs_hub_w,
        "A_hub_r": arcs_hub_r,
        "A_r_hub": arcs_r_hub,
        "A_air_air": arcs_air_air,
        "A_port_port": arcs_port_port,
        "FLOW_RAW": _build_item_flow_tuples(raw_materials, raw_arcs),
        "FLOW_FP": _build_item_flow_tuples(products, final_product_arcs),
        "FLOW_RP": _build_item_flow_tuples(recovered_products, recovered_product_arcs),
        "H_prod": production_pairs,
        "H_rem": remanufacturing_pairs,
    }

    parameters = {
        "c_area_f": factory_area_cost,
        "c_area_w": warehouse_area_cost,
        # No "f_s": selecting a supplier is free in both sources. See the note
        # beside SUPPLIER_MIN_FRACTION_RANGE in tautenhain_data.
        "i_prod_g": production_install_cost,
        "i_rem_l": remanufacturing_install_cost,
        "c_prod_g": production_cost,
        "c_rem_l": remanufacturing_cost,
        "h_p": holding_cost_product,
        "rpc_rp": recovery_cost_recovered,
        "rmc_s_u": raw_material_cost,
        "c_ship_m": transport_cost,
        "c_trip_m": transport_trip_cost,
        "f_mode_m": transport_fixed_cost,
        "c_handle_m": hub_handling_cost,
        "f_h": hub_operating_cost,
        "mode_family_m": transport_family,
        "road_return_factor_m": road_return_factor,
        "speed_km_h_m": speed_km_h,
        "max_driving_hours_m": max_driving_hours,
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
        "labour_cost_i": labour_cost,
        "workers_fixed_i": fixed_workers,
        "workers_per_sqm_i": workers_per_sqm,
        "workers_prod_g": production_workers,
        "workers_rem_l": remanufacturing_workers,
        "workers_mode_m": {
            mode: taut.mode_workers(transport_family[mode]) for mode in modes
        },
        "weekly_working_hours": taut.WEEKLY_WORKING_HOURS,
        "weeks_per_period": taut.WEEKS_PER_PERIOD,
        "trip_big_m_m": trip_big_m,
        "bar_s_s_u": supplier_capacity_by_material,
        "scmin_s_u": supplier_minimum_order_by_material,
        "bar_p_g": production_capacity,
        "bar_q_l": remanufacturing_capacity,
        "pcmin_g": production_minimum_use,
        "pcmin_l": remanufacturing_minimum_use,
        "icmax_p_n": inventory_capacity_by_product_node,
        "icmin_p_n": inventory_minimum_by_product_node,
        "i_p_n_0": initial_inventory,
        "A_f": factory_area,
        "A_w": warehouse_area,
        "Amin_f": factory_area_min,
        "Amin_w": warehouse_area_min,
        "apu_u": raw_material_area,
        "apu_p": product_unit_area,
        "apur_p": product_rotation_area,
        "apu_rp": recovered_product_area,
        "apu_q": {
            **raw_material_area,
            **product_unit_area,
            **recovered_product_area,
        },
        "bar_X_m": transport_capacity,
        "ctmin_m": transport_min_capacity,
        "ccamax_m": contracted_capacity,
        # ecmax_i (Mota's node throughput capacity) is intentionally not emitted:
        # entity capacity is carried by the installed-area mechanism (YCT <= YC),
        # as in Tautenhain et al. (2021). See _add_flow_constraints in
        # src/clsc/models/subproblems.py.
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
        "e_open_f": {factory: taut.ENTITY_INSTALL_EMISSION_PER_AREA for factory in factories},
        "e_open_w": {warehouse: taut.ENTITY_INSTALL_EMISSION_PER_AREA for warehouse in warehouses},
        "e_prod_g": production_emission,
        "e_rem_l": remanufacturing_emission,
        "e_raw_s_u": raw_material_emission,
        "e_ship_m": transport_emission,
        "underline_tax_rate": config.tax_lower,
        "overline_tax_rate": config.tax_upper,
        "underline_tax_index": _tax_rate_to_tax_index(config.tax_lower),
        "overline_tax_index": _tax_rate_to_tax_index(config.tax_upper),
        "d_i_j": _nested_arc_parameter(transport_arcs, dist_transport),
    }

    return GeneratedInstance(
        name=config.instance_name,
        metadata=metadata,
        sets=sets,
        parameters=parameters,
    )


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
