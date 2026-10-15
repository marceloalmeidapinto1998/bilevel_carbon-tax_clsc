"""The supply-chain MILP shared by the follower and the leader HPR: its variables,
constraint blocks (C1)-(C10), and the cost and emission expressions.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math
from typing import Iterable

import gurobipy as gp
from gurobipy import GRB

from clsc.config.constants import WEEKS_PER_YEAR
from .instance_data import InstanceData


@dataclass(slots=True)
class _SupplyChainModel:
    model: gp.Model
    cost_expr: gp.LinExpr
    emissions_expr: gp.LinExpr
    # Discounted emission aggregate the follower is taxed on. Is the same
    # object as emissions_expr when the instance carries no interest rate.
    tax_base_expr: gp.LinExpr


def total_emissions_upper_bound(instance: InstanceData) -> float:
    params = instance.parameters
    factories = instance.sets["F"]
    warehouses = instance.sets["W"]
    periods = instance.sets["T"]
    products = instance.sets["P"]
    raw_materials = instance.sets["U"]
    suppliers = instance.sets["S"]
    production_pairs = instance.sets.get("H_prod", tuple((p, g) for p in products for g in instance.sets["G"]))
    remanufacturing_pairs = instance.sets.get("H_rem", tuple((p, l) for p in products for l in instance.sets["L"]))
    modes = instance.sets["M"]
    airports = instance.sets.get("AIR", tuple())
    seaports = instance.sets.get("PORT", tuple())

    open_bound = len(periods) * embodied_emission_share_per_period(params) * (
        sum(params["e_open_f"][factory] * params["A_f"][factory] for factory in factories)
        + sum(params["e_open_w"][warehouse] * params["A_w"][warehouse] for warehouse in warehouses)
    )
    production_bound = len(periods) * len(factories) * sum(
        params["e_prod_g"][technology]
        * params["omega_p"][product]
        * params["bar_p_g"][technology]
        for product, technology in production_pairs
    )
    remanufacturing_bound = len(periods) * len(factories) * sum(
        params["e_rem_l"][technology]
        * params["omega_p"][product]
        * params["bar_q_l"][technology]
        for product, technology in remanufacturing_pairs
    )
    raw_material_bound = 0.0
    if "e_raw_s_u" in params and "bar_s_s_u" in params:
        raw_material_bound = len(periods) * sum(
            params["e_raw_s_u"][supplier][raw_material]
            * params["omega_u"][raw_material]
            * params["bar_s_s_u"][supplier][raw_material]
            for supplier in suppliers
            for raw_material in raw_materials
        )

    transport_bound = 0.0
    transport_arcs = instance.sets["A"]
    distance = params["d_i_j"]
    mode_family = params.get("mode_family_m", {})
    for origin, destination in transport_arcs:
        for mode in _allowed_modes(
            origin,
            destination,
            modes,
            airports=airports,
            seaports=seaports,
            mode_family=mode_family,
        ):
            if params.get("ccamax_m", {}).get(mode, 0.0) > 0.0:
                weight_bound = params["ccamax_m"][mode]
            else:
                weight_bound = max(
                    max(params.get("ecmax_i", {}).values(), default=0.0),
                    params["bar_X_m"][mode] * _trip_big_m(params, mode, origin=origin, destination=destination),
                )
            transport_bound += (
                len(periods)
                * params["e_ship_m"][mode]
                * params.get("road_return_factor_m", {}).get(mode, 1.0)
                * distance[origin][destination]
                * weight_bound
            )

    return float(open_bound + production_bound + remanufacturing_bound + raw_material_bound + transport_bound)


# Valid inequalities that tighten the model's linear relaxation without changing its integer solutions.
#
# remanufacturing_capacity
#     The flow through a remanufacturing technology is linked to its installation by
#     ``throughput <= capacity * use``, and the capacity follows the demand for final products while the
#     recovered products that can be collected are a small fraction of it. The relaxation then pays a
#     sliver of the technology, and the integer solution all of it. The recovered products that reach a
#     factory in a period were collected at the retailers in that period (nothing is stored), so the flow
#     is also bounded by what can be collected, and that bound replaces the capacity in the link when it is
#     smaller.
#
# (A candidate that was measured and dropped: a trip on an arc needs a vehicle at its origin, written
# against the per-arc mode binary the model then had. With the trip big-M the relaxation does not feel
# it, and with a big-M tight enough to matter, which is not a valid bound, it closed only one to five
# points of the gap.)
FORMULATION_STRENGTHENING_OPTIONS = ("remanufacturing_capacity",)
DEFAULT_FORMULATION_STRENGTHENING: tuple[str, ...] = FORMULATION_STRENGTHENING_OPTIONS


def build_supply_chain_model(
    instance: InstanceData, *, model_name: str, strengthening: Iterable[str] | None = None,
) -> _SupplyChainModel:
    strengthening = frozenset(DEFAULT_FORMULATION_STRENGTHENING if strengthening is None else strengthening)
    unknown = strengthening - set(FORMULATION_STRENGTHENING_OPTIONS)
    if unknown:
        raise ValueError(f"unknown formulation strengthening {sorted(unknown)}; options: {FORMULATION_STRENGTHENING_OPTIONS}")
    model = gp.Model(model_name)
    params = instance.parameters

    suppliers = instance.sets["S"]
    factories = instance.sets["F"]
    warehouses = instance.sets["W"]
    retailers = instance.sets["R"]
    airports = instance.sets.get("AIR", tuple())
    seaports = instance.sets.get("PORT", tuple())
    hubs = (*airports, *seaports)
    products = instance.sets["P"]
    recovered_products = instance.sets.get("K", instance.sets.get("RP", tuple(params.get("bom_rem_r_p", {}).keys())))
    raw_materials = instance.sets["U"]
    modes = instance.sets["M"]
    production_technologies = instance.sets["G"]
    remanufacturing_technologies = instance.sets["L"]
    periods = instance.sets["T"]

    flow_raw, flow_fp, flow_rp = _flow_sets(instance)
    flow_tuples = tuple(dict.fromkeys((*flow_raw, *flow_fp, *flow_rp)))
    transport_arcs = tuple(instance.sets.get("A", tuple(dict.fromkeys((o, d) for _, o, d in flow_tuples))))
    mode_family = params.get("mode_family_m", {})
    allowed_modes = {
        (o, d): _allowed_modes(o, d, modes, airports=airports, seaports=seaports, mode_family=mode_family)
        for o, d in transport_arcs
    }
    flow_by_arc: dict[tuple[str, str], list[str]] = defaultdict(list)
    for item, origin, destination in flow_tuples:
        flow_by_arc[(origin, destination)].append(item)

    raw_in, raw_out = _flow_indices(flow_raw)
    fp_in, fp_out = _flow_indices(flow_fp)
    rp_in, rp_out = _flow_indices(flow_rp)
    weights = _item_weights(params, raw_materials, products, recovered_products)
    distances = params["d_i_j"]
    return_yield = params["ret_yield_rp_p"]

    production_pairs = set(instance.sets.get("H_prod", tuple((p, g) for p in products for g in production_technologies)))
    remanufacturing_pairs = set(instance.sets.get("H_rem", tuple((p, l) for p in products for l in remanufacturing_technologies)))
    production_products_by_technology = _products_by_technology(production_pairs, production_technologies)
    remanufacturing_products_by_technology = _products_by_technology(remanufacturing_pairs, remanufacturing_technologies)
    production_technologies_by_product = _technologies_by_product(production_pairs, products)
    remanufacturing_technologies_by_product = _technologies_by_product(remanufacturing_pairs, products)
    vehicle_pairs = tuple(
        sorted(
            {
                (origin, mode)
                for origin, destination in transport_arcs
                for mode in allowed_modes[(origin, destination)]
                if _mode_family(mode, mode_family) == "truck"
            }
        )
    )
    truck_transport_keys = tuple(
        (o, d, m, t)
        for o, d in transport_arcs
        for m in allowed_modes[(o, d)]
        if _mode_family(m, mode_family) == "truck"
        for t in periods
    )

    y_s = model.addVars(suppliers, vtype=GRB.BINARY, name="y_s")
    y_f = model.addVars(factories, vtype=GRB.BINARY, name="y_f")
    y_w = model.addVars(warehouses, vtype=GRB.BINARY, name="y_w")
    y_h = model.addVars(hubs, vtype=GRB.BINARY, name="y_h")
    u_prod = model.addVars(((f, g) for f in factories for g in production_technologies), vtype=GRB.BINARY, name="u_prod")
    u_rem = model.addVars(((f, l) for f in factories for l in remanufacturing_technologies), vtype=GRB.BINARY, name="u_rem")
    installed_area = model.addVars((*factories, *warehouses), lb=0.0, name="YC")
    use_rem = model.addVars(
        ((f, l, t) for f in factories for l in remanufacturing_technologies for t in periods),
        vtype=GRB.BINARY,
        name="use_rem",
    )
    trip = model.addVars(truck_transport_keys, vtype=GRB.INTEGER, lb=0.0, name="trip")
    vehicle = model.addVars(vehicle_pairs, vtype=GRB.INTEGER, lb=0.0, name="vehicle")
    q = model.addVars(
        ((p, f, g, t) for p, g in sorted(production_pairs) for f in factories for t in periods),
        lb=0.0,
        name="q",
    )
    rem = model.addVars(
        ((p, f, l, t) for p, l in sorted(remanufacturing_pairs) for f in factories for t in periods),
        lb=0.0,
        name="rem",
    )
    inv_w = model.addVars(((p, w, t) for p in products for w in warehouses for t in periods), lb=0.0, name="inv_w")
    x = model.addVars(
        ((item, o, d, m, t) for item, o, d in flow_tuples for m in allowed_modes[(o, d)] for t in periods),
        lb=0.0,
        name="x",
    )

    # Present-value weights on recurring flows (see discount_factors), and the
    # per-period rental charge for capital held over the horizon (see
    # capital_multipliers). Both collapse to 1.0 on an instance carrying no
    # interest_rate, leaving its objective exactly as first recorded.
    discount = discount_factors(params, periods)
    annuity = sum(discount[t] for t in periods)
    capital = capital_multipliers(params, periods)

    inventory_cost = _inventory_cost(
        params,
        products,
        warehouses,
        periods,
        inv_w,
        discount,
    )
    cost_expr = (
        # Supplier selection is free in both Mota et al. (2018) and Tautenhain
        # et al. (2021), and the generator no longer emits f_s -- the default
        # in _apply_parameter_defaults is 0.0. The term is retained so that
        # instances archived before 2026-08-11, which do carry an f_s, still
        # reproduce their recorded objective exactly.
        gp.quicksum(params["f_s"].get(s, 0.0) * y_s[s] for s in suppliers)
        + capital[ASSET_CLASS_FACILITY] * (
            gp.quicksum(params.get("c_area_f", {}).get(f, 0.0) * installed_area[f] for f in factories)
            + gp.quicksum(params.get("c_area_w", {}).get(w, 0.0) * installed_area[w] for w in warehouses)
        )
        + annuity * gp.quicksum(params["f_h"][h] * y_h[h] for h in hubs)
        # The fleet's purchase price is charged here at its rental equivalent.
        # Mota's investment ceiling (eq. 31) still binds the raw outlay -- see
        # the truck_investment_budget constraint, which must not carry this
        # factor: a budget limits what you spend, not what you consume.
        + capital[ASSET_CLASS_VEHICLE] * _transport_fixed_cost(params, vehicle)
        + capital[ASSET_CLASS_TECHNOLOGY] * (
            gp.quicksum(params["i_prod_g"][g] * u_prod[f, g] for f in factories for g in production_technologies)
            + gp.quicksum(params["i_rem_l"][l] * u_rem[f, l] for f in factories for l in remanufacturing_technologies)
        )
        + _labour_cost(
            params,
            factories=factories,
            warehouses=warehouses,
            production_technologies=production_technologies,
            remanufacturing_technologies=remanufacturing_technologies,
            vehicle_pairs=vehicle_pairs,
            annuity=annuity,
            y_f=y_f,
            y_w=y_w,
            installed_area=installed_area,
            u_prod=u_prod,
            u_rem=u_rem,
            vehicle=vehicle,
        )
        + gp.quicksum(discount[t] * params["c_prod_g"][g] * q[p, f, g, t] for p, f, g, t in q.keys())
        + gp.quicksum(discount[t] * params["c_rem_l"][l] * rem[p, f, l, t] for p, f, l, t in rem.keys())
        + inventory_cost
        + gp.quicksum(discount[t] * params["rmc_s_u"][s][u] * x[u, s, d, m, t] for u, s, d in flow_raw if s in suppliers for m in allowed_modes[(s, d)] for t in periods)
        + gp.quicksum(discount[t] * params["rpc_rp"][rp] * x[rp, r, d, m, t] for rp, r, d in flow_rp if r in retailers for m in allowed_modes[(r, d)] for t in periods)
        + _transport_variable_cost(params, flow_tuples, allowed_modes, weights, distances, periods, mode_family, x, trip, discount)
        + gp.quicksum(
            discount[t]
            * params["c_handle_m"][m]
            * ((1 if o in hubs else 0) + (1 if d in hubs else 0))
            * weights[item]
            * x[item, o, d, m, t]
            for item, o, d in flow_tuples
            if o in hubs or d in hubs
            for m in allowed_modes[(o, d)]
            for t in periods
        )
    )

    embodied_share = embodied_emission_share_per_period(params)
    embodied_emissions = (
        gp.quicksum(params["e_open_f"][f] * installed_area[f] for f in factories)
        + gp.quicksum(params["e_open_w"][w] * installed_area[w] for w in warehouses)
    )

    def _emissions(weight: dict[str, float]) -> gp.LinExpr:
        """Total emissions, with ``weight[t]`` applied to every per-period term.

        Construction emissions are amortised like the facility's capital: each
        period carries the share of the building's embodied emissions that it
        consumes (see embodied_emission_share_per_period), weighted like any
        other per-period emission.
        """
        return (
            sum(weight[t] for t in periods) * embodied_share * embodied_emissions
            + gp.quicksum(
                weight[t] * params["e_prod_g"][g] * params["omega_p"][p] * q[p, f, g, t]
                for p, f, g, t in q.keys()
            )
            + gp.quicksum(
                weight[t] * params["e_rem_l"][l] * params["omega_p"][p] * rem[p, f, l, t]
                for p, f, l, t in rem.keys()
            )
            + gp.quicksum(
                weight[t] * params["e_raw_s_u"][s][u] * params["omega_u"][u] * x[u, s, d, m, t]
                for u, s, d in flow_raw if s in suppliers for m in allowed_modes[(s, d)] for t in periods
            )
            + gp.quicksum(
                weight[t]
                * params["e_ship_m"][m]
                * params.get("road_return_factor_m", {}).get(m, 1.0)
                * weights[item] * distances[o][d] * x[item, o, d, m, t]
                for item, o, d in flow_tuples for m in allowed_modes[(o, d)] for t in periods
            )
        )

    # emissions_expr is the PHYSICAL total the regulator minimises and every
    # result reports: undiscounted, because a tonne of CO2e in the final period
    # accumulates in the atmosphere exactly like one in the first.
    emissions_expr = _emissions({t: 1.0 for t in periods})
    # tax_base_expr is what the OPERATOR pays tax on: the present value of the
    # tax bill, so per-period emissions carry the same discount weights as every
    # other monetary flow. Identical to emissions_expr when ir = 0.
    tax_base_expr = _emissions(discount) if is_discounted(params) else emissions_expr

    def fs(index: dict[tuple[str, str], list[tuple[str, str]]], item: str, node: str, period: str) -> gp.LinExpr:
        return gp.quicksum(x[item, o, d, m, period] for o, d in index.get((item, node), ()) for m in allowed_modes[(o, d)])

    _add_inventory_and_flow_constraints(
        model, params, products, raw_materials, recovered_products, factories, warehouses, retailers, hubs,
        periods, production_technologies, remanufacturing_technologies, production_pairs,
        remanufacturing_pairs, production_products_by_technology, remanufacturing_products_by_technology,
        production_technologies_by_product, remanufacturing_technologies_by_product,
        return_yield, raw_in, raw_out, fp_in, fp_out, rp_in, rp_out, fs, y_s, y_f, y_w, u_prod, u_rem,
        use_rem, q, rem, inv_w, installed_area,
        "remanufacturing_capacity" in strengthening,
    )
    _add_transport_constraints(
        model, params, transport_arcs, allowed_modes, flow_by_arc, weights, periods,
        suppliers, factories, warehouses, airports, seaports, hubs, y_s, y_f, y_w, y_h, trip, vehicle, x,
    )
    _add_valid_inequalities(
        model,
        factories,
        production_technologies,
        remanufacturing_technologies,
        y_f,
        u_prod,
        u_rem,
    )
    return _SupplyChainModel(
        model=model,
        cost_expr=cost_expr,
        emissions_expr=emissions_expr,
        tax_base_expr=tax_base_expr,
    )


def _flow_sets(instance: InstanceData):
    return (
        tuple(instance.sets["FLOW_RAW"]),
        tuple(instance.sets["FLOW_FP"]),
        tuple(instance.sets["FLOW_RP"]),
    )


def _transport_fixed_cost(params, vehicle) -> gp.LinExpr:
    # Outsourced (air/sea) contracts carry no separate fixed cost here: that
    # payment is represented once, by the hub access fee f_h, matching Mota
    # et al.'s single bundled cfp_i (see sample_transport_fixed_cost).
    return gp.quicksum(params["f_mode_m"][mode] * vehicle[origin, mode] for origin, mode in vehicle.keys())


def _transport_variable_cost(
    params, flow_tuples, allowed_modes, weights, distances, periods, mode_family, x, trip, discount,
) -> gp.LinExpr:
    truck_trip_cost = params.get("c_trip_m", {})
    road_return_factor = params.get("road_return_factor_m", {})
    flow_cost = gp.quicksum(
        discount[period]
        * params["c_ship_m"][mode] * weights[item] * distances[origin][destination] * x[item, origin, destination, mode, period]
        for item, origin, destination in flow_tuples
        for mode in allowed_modes[(origin, destination)]
        if _mode_family(mode, mode_family) != "truck"
        for period in periods
    )
    trip_cost = gp.quicksum(
        discount[period]
        * truck_trip_cost.get(mode, params["c_ship_m"][mode] * params["bar_X_m"][mode])
        * road_return_factor.get(mode, 2.0)
        * distances[origin][destination]
        * trip[origin, destination, mode, period]
        for origin, destination, mode, period in trip.keys()
        if _mode_family(mode, mode_family) == "truck"
    )
    return flow_cost + trip_cost


def _add_inventory_and_flow_constraints(
    model, params, products, raw_materials, recovered_products, factories, warehouses, retailers, hubs,
    periods, production_technologies, remanufacturing_technologies, production_pairs,
    remanufacturing_pairs, production_products_by_technology, remanufacturing_products_by_technology,
    production_technologies_by_product, remanufacturing_technologies_by_product,
    return_yield, raw_in, raw_out, fp_in, fp_out, rp_in, rp_out, fs, y_s, y_f, y_w, u_prod, u_rem,
    use_rem, q, rem, inv_w, installed_area, bound_remanufacturing_by_collection,
) -> None:
    initial_inventory = params["i_p_n_0"]
    for product in products:
        for factory in factories:
            for period in periods:
                model.addConstr(
                    fs(fp_in, product, factory, period)
                    + gp.quicksum(q[product, factory, g, period] for g in production_technologies_by_product.get(product, ()))
                    + gp.quicksum(rem[product, factory, l, period] for l in remanufacturing_technologies_by_product.get(product, ()))
                    == fs(fp_out, product, factory, period)
                )
        for warehouse in warehouses:
            for period_index, period in enumerate(periods):
                previous = initial_inventory[product][warehouse] if period_index == 0 else inv_w[product, warehouse, periods[period_index - 1]]
                model.addConstr(inv_w[product, warehouse, period] == previous + fs(fp_in, product, warehouse, period) - fs(fp_out, product, warehouse, period))
        for retailer in retailers:
            for period in periods:
                model.addConstr(fs(fp_in, product, retailer, period) == params["d_r_p_t"][retailer][product][period])
        for hub in hubs:
            for period in periods:
                model.addConstr(fs(fp_in, product, hub, period) == fs(fp_out, product, hub, period))

    # Supply capacity and minimum order (Mota et al. 2018, eq. 10-11; Tautenhain et al. 2021, eq. 1-2):
    # a selected supplier ships between its minimum order and its capacity of every raw material in
    # every period.
    for supplier in params.get("bar_s_s_u", {}):
        for raw_material in raw_materials:
            for period in periods:
                shipped = fs(raw_out, raw_material, supplier, period)
                model.addConstr(shipped <= params["bar_s_s_u"][supplier][raw_material] * y_s[supplier])
                model.addConstr(shipped >= params["scmin_s_u"][supplier][raw_material] * y_s[supplier])
    for raw_material in raw_materials:
        for factory in factories:
            for period in periods:
                model.addConstr(
                    gp.quicksum(
                        _input_requirement(params, raw_material, product, g) * q[product, factory, g, period]
                        for product, g in production_pairs
                    )
                    == fs(raw_in, raw_material, factory, period)
                )
        for hub in hubs:
            for period in periods:
                model.addConstr(fs(raw_in, raw_material, hub, period) == fs(raw_out, raw_material, hub, period))

    return_lag = _return_lags(params, products)
    remanufacturing_bound = (
        _remanufacturing_flow_bounds(
            params, products, recovered_products, retailers, periods, return_yield, return_lag,
        )
        if bound_remanufacturing_by_collection
        else None
    )
    _add_technology_constraints(
        model, params, products, factories, periods, production_technologies, remanufacturing_technologies,
        production_pairs, remanufacturing_pairs, production_products_by_technology, remanufacturing_products_by_technology,
        production_technologies_by_product,
        remanufacturing_technologies_by_product, y_f, u_prod, u_rem, use_rem, q, rem,
        remanufacturing_bound,
    )
    for retailer in retailers:
        for recovered_product in recovered_products:
            for period_index, period in enumerate(periods):
                collected = fs(rp_out, recovered_product, retailer, period)
                minimum_return = gp.quicksum(
                    return_yield[recovered_product][product]
                    * _return_fraction(params, "ret_min_frac_r_p_t", retailer, product, period)
                    * _lagged_demand(params, retailer, product, periods, period_index, return_lag[product])
                    for product in products
                )
                maximum_return = gp.quicksum(
                    return_yield[recovered_product][product]
                    * _return_fraction(params, "ret_max_frac_r_p_t", retailer, product, period)
                    * _lagged_demand(params, retailer, product, periods, period_index, return_lag[product])
                    for product in products
                )
                model.addConstr(collected >= minimum_return)
                model.addConstr(
                    collected <= maximum_return
                )
    for recovered_product in recovered_products:
        for warehouse in warehouses:
            for period in periods:
                model.addConstr(fs(rp_in, recovered_product, warehouse, period) == fs(rp_out, recovered_product, warehouse, period))
        for hub in hubs:
            for period in periods:
                model.addConstr(fs(rp_in, recovered_product, hub, period) == fs(rp_out, recovered_product, hub, period))
        for factory in factories:
            for period in periods:
                model.addConstr(
                    gp.quicksum(
                        params["bom_rem_r_p"][recovered_product][product] * rem[product, factory, l, period]
                        for product, l in remanufacturing_pairs
                    )
                    == fs(rp_in, recovered_product, factory, period)
                )
    _add_inventory_capacity_constraints(
        model,
        params,
        products,
        warehouses,
        periods,
        y_w,
        inv_w,
    )

    # Floor-area requirement YCT_it: a flow-based handling term at
    # both factories and warehouses, plus a stock-based storage term at
    # warehouses only -- mirrors Mota et al. (2018)'s general facility-area
    # expression (their Eq. 16), adapted to this model's flow-direction
    # convention. Factories use X^out
    # (the only nonzero flow direction for finished products under the
    # greenfield convention, equal to q^p+q^r there);
    # warehouses use X^in, mirroring Mota's own indexing, alongside their
    # existing stock term. fs/fp_in/fp_out are already in scope here.
    item_area = _item_area_map(params, products, recovered_products=())
    item_flow_area = _item_flow_area_map(params, products)
    min_area_f = params.get("Amin_f", {factory: 0.0 for factory in factories})
    min_area_w = params.get("Amin_w", {warehouse: 0.0 for warehouse in warehouses})

    for factory in factories:
        model.addConstr(installed_area[factory] >= min_area_f.get(factory, 0.0) * y_f[factory])
        model.addConstr(installed_area[factory] <= params["A_f"][factory] * y_f[factory])
        for period in periods:
            used_area = gp.quicksum(
                item_flow_area.get(product, 0.0) * fs(fp_out, product, factory, period)
                for product in products
            )
            model.addConstr(used_area <= installed_area[factory])

    for warehouse in warehouses:
        model.addConstr(installed_area[warehouse] >= min_area_w.get(warehouse, 0.0) * y_w[warehouse])
        model.addConstr(installed_area[warehouse] <= params["A_w"][warehouse] * y_w[warehouse])
        for period in periods:
            used_area = gp.quicksum(
                item_flow_area.get(product, 0.0) * fs(fp_in, product, warehouse, period)
                + item_area.get(product, 0.0) * inv_w[product, warehouse, period]
                for product in products
            )
            model.addConstr(used_area <= installed_area[warehouse])


def _add_technology_constraints(
    model, params, products, factories, periods, production_technologies, remanufacturing_technologies,
    production_pairs, remanufacturing_pairs, production_products_by_technology, remanufacturing_products_by_technology,
    production_technologies_by_product,
    remanufacturing_technologies_by_product, y_f, u_prod, u_rem, use_rem, q, rem,
    remanufacturing_bound=None,
) -> None:
    production_pairs = tuple(production_pairs)
    remanufacturing_pairs = tuple(remanufacturing_pairs)
    for factory in factories:
        for technology in production_technologies:
            model.addConstr(u_prod[factory, technology] <= y_f[factory])
        for technology in remanufacturing_technologies:
            model.addConstr(u_rem[factory, technology] <= y_f[factory])
            for period in periods:
                model.addConstr(use_rem[factory, technology, period] <= u_rem[factory, technology])

        for technology in production_technologies:
            for period in periods:
                compatible_products = production_products_by_technology.get(technology, ())
                throughput = gp.quicksum(q[product, factory, technology, period] for product in compatible_products)
                model.addConstr(throughput <= params["bar_p_g"][technology] * u_prod[factory, technology])
                if compatible_products:
                    model.addConstr(throughput >= params["pcmin_g"][technology] * u_prod[factory, technology])
        for technology in remanufacturing_technologies:
            for period in periods:
                compatible_products = remanufacturing_products_by_technology.get(technology, ())
                throughput = gp.quicksum(rem[product, factory, technology, period] for product in compatible_products)
                capacity = params["bar_q_l"][technology]
                if remanufacturing_bound is not None:
                    # What can be collected in the period, if smaller than the capacity (see
                    # FORMULATION_STRENGTHENING_OPTIONS); every term is at least zero, so the sum bounds the throughput.
                    collectable = sum(remanufacturing_bound[product, period] for product in compatible_products)
                    capacity = min(capacity, collectable)
                model.addConstr(throughput <= capacity * use_rem[factory, technology, period])
                if compatible_products:
                    model.addConstr(throughput >= params["pcmin_l"][technology] * use_rem[factory, technology, period])

        for product in products:
            model.addConstr(
                gp.quicksum(u_prod[factory, technology] for technology in production_technologies_by_product.get(product, ()))
                <= 1
            )
            model.addConstr(
                gp.quicksum(u_rem[factory, technology] for technology in remanufacturing_technologies_by_product.get(product, ()))
                <= 1
            )


def _remanufacturing_flow_bounds(
    params, products, recovered_products, retailers, periods, return_yield, return_lag,
) -> dict[tuple[str, str], float]:
    """An upper bound on ``rem[product, factory, technology, period]``, in units of the product.

    The recovered product ``rp`` that reaches factories in a period is at most what the retailers can
    collect: ``sum_r sum_p yield[rp][p] * ret_max[r][p][t] * lagged_demand`` (the collection constraint),
    because recovered products are not stored and flow only from retailers to factories. A factory uses
    ``bom[rp][p] * rem[p, ...]`` of it for each product, so ``rem[p, ...] <= collectable[rp, t] / bom[rp][p]``
    for every ``rp`` the product needs. The smallest of those is returned. A product no recovered product
    can make has a bound of 0.
    """
    bill = params.get("bom_rem_r_p", {})
    collectable = {}
    for recovered_product in recovered_products:
        for period_index, period in enumerate(periods):
            collectable[recovered_product, period] = sum(
                return_yield[recovered_product][product]
                * _return_fraction(params, "ret_max_frac_r_p_t", retailer, product, period)
                * _lagged_demand(params, retailer, product, periods, period_index, return_lag[product])
                for retailer in retailers
                for product in products
            )
    bounds: dict[tuple[str, str], float] = {}
    tolerance = 1.0 + 1e-9  # the bound is a mathematical one; keep float noise from touching a feasible point
    for product in products:
        for period in periods:
            limits = [
                collectable[recovered_product, period] / bill[recovered_product][product]
                for recovered_product in recovered_products
                if bill.get(recovered_product, {}).get(product, 0.0) > 0.0
            ]
            bounds[product, period] = (min(limits) * tolerance + 1e-9) if limits else 0.0
    return bounds


def _add_inventory_capacity_constraints(
    model, params, products, warehouses, periods, y_w, inv_w,
) -> None:
    capacity = params["icmax_p_n"]
    minimum = params.get("icmin_p_n", {})
    for product in products:
        for warehouse in warehouses:
            for period in periods:
                model.addConstr(inv_w[product, warehouse, period] <= capacity[product][warehouse] * y_w[warehouse])
                if minimum:
                    model.addConstr(inv_w[product, warehouse, period] >= minimum[product][warehouse] * y_w[warehouse])


def _item_area_map(params, products, recovered_products) -> dict[str, float]:
    if "apu_q" in params:
        return {item: float(area) for item, area in params["apu_q"].items()}
    item_area = {product: float(area) for product, area in params.get("apu_p", {}).items()}
    item_area.update(
        {
            recovered_product: float(area)
            for recovered_product, area in params.get(
                "apu_rp",
                _derive_recovered_product_area(params, products, recovered_products),
            ).items()
        }
    )
    return item_area


def _item_flow_area_map(params, products) -> dict[str, float]:
    flow_area = params.get("apur_p", {})
    return {product: float(flow_area.get(product, 0.0)) for product in products}


def _derive_recovered_product_area(params, products, recovered_products) -> dict[str, float]:
    product_area = params.get("apu_p", {})
    remanufacturing_bom = params.get("bom_rem_r_p", {})
    return {
        recovered_product: sum(
            remanufacturing_bom.get(recovered_product, {}).get(product, 0.0)
            * product_area.get(product, 0.0)
            for product in products
        )
        for recovered_product in recovered_products
    }


def _add_transport_constraints(
    model, params, transport_arcs, allowed_modes, flow_by_arc, weights, periods,
    suppliers, factories, warehouses, airports, seaports, hubs, y_s, y_f, y_w, y_h, trip, vehicle, x,
) -> None:
    """Transport constraints, as in Mota et al. (2018), eq. 24-28.

    Several modes may serve the same arc in the same period, and no binary selects a mode: a truck
    mode carries what its integer trips allow (eq. 24-25), and trips need both endpoints installed
    (eq. 26-27, ``trip <= BigM * Y``). Air and sea carry at most the capacity contracted per arc and
    period (eq. 28); their flows are tied to the installed hubs at both ends through the same capacity,
    which stands in for Mota's node-throughput link (eq. 12-13, not imposed here, see below).
    """
    mode_family = params.get("mode_family_m", {})

    def endpoint_activity(origin, destination):
        # Installation binaries of the arc's endpoints; retailers are always present and have none.
        return [
            _entity_activity(node, suppliers, factories, warehouses, hubs, y_s, y_f, y_w, y_h)
            for node in (origin, destination)
            if node in suppliers or node in factories or node in warehouses or node in hubs
        ]

    for origin, destination in transport_arcs:
        activity = endpoint_activity(origin, destination)
        for mode in allowed_modes[(origin, destination)]:
            family = _mode_family(mode, mode_family)
            contracted_cap = params.get("ccamax_m", {}).get(mode, 0.0)
            for period in periods:
                transported_weight = gp.quicksum(
                    weights[item] * x[item, origin, destination, mode, period]
                    for item in flow_by_arc.get((origin, destination), ())
                )
                if family == "truck":
                    trips = trip[origin, destination, mode, period]
                    model.addConstr(transported_weight <= params["bar_X_m"][mode] * trips)
                    if params.get("ctmin_m", {}).get(mode, 0.0) > 0.0:
                        model.addConstr(transported_weight >= params["ctmin_m"][mode] * trips)
                    big_m = _trip_big_m(params, mode, origin=origin, destination=destination)
                    for installed in activity:
                        model.addConstr(trips <= big_m * installed)
                else:
                    capacity = contracted_cap if contracted_cap > 0.0 else params["bar_X_m"][mode]
                    if activity:
                        for installed in activity:
                            model.addConstr(transported_weight <= capacity * installed)
                    else:
                        model.addConstr(transported_weight <= capacity)

    _add_truck_fleet_constraints(
        model,
        params,
        transport_arcs,
        allowed_modes,
        periods,
        suppliers,
        factories,
        warehouses,
        hubs,
        y_s,
        y_f,
        y_w,
        y_h,
        mode_family,
        trip,
        vehicle,
    )

    # (C8) minimum flow: every open/selected node must carry positive flow of
    # some item in some period, ruling out degenerate open-but-unused nodes.
    openable_nodes = (*suppliers, *factories, *warehouses, *hubs)
    for entity in openable_nodes:
        incident_flow = gp.quicksum(
            x[item, origin, destination, mode, period]
            for origin, destination in transport_arcs
            if origin == entity or destination == entity
            for item in flow_by_arc.get((origin, destination), ())
            for mode in allowed_modes[(origin, destination)]
            for period in periods
        )
        model.addConstr(
            incident_flow >= _entity_activity(entity, suppliers, factories, warehouses, hubs, y_s, y_f, y_w, y_h),
            name=f"min_flow[{entity}]",
        )

    # Node throughput capacity (Mota et al. 2018, eq. 12-13, parameter ecmax_i)
    # is deliberately NOT imposed. Entity capacity is expressed through installed
    # floor area instead -- YCT_it <= YC_i in (C4), with YCT accumulating both
    # per-period throughput (apur_p) and stored stock (apu_p). Tautenhain et al.
    # (2021), the direct methodological reference, likewise drops the flow-based
    # capacity and keeps only the area mechanism. Imposing both duplicated the
    # same limit; with ecmax_i set two orders of magnitude above any attainable
    # flow it never bound, and only injected a 7e6 big-M that pushed the
    # constraint-matrix range past the solver's conditioning threshold.
    _add_intermodal_hub_constraints(
        model,
        transport_arcs,
        allowed_modes,
        flow_by_arc,
        periods,
        airports,
        seaports,
        mode_family,
        x,
    )


def _add_valid_inequalities(
    model,
    factories,
    production_technologies,
    remanufacturing_technologies,
    y_f,
    u_prod,
    u_rem,
) -> None:
    """(C10) Valid inequalities.

    Only the technology-demand inequality is implemented: every open factory installs at
    least one production OR remanufacturing technology. Production alone is
    not implied by C1-C9 -- a factory engaged purely in remanufacturing can
    satisfy the minimum-flow constraint (C8) via q^r without ever installing lambda^p. (The
    other candidate inequality, installed capacity >= peak demand, is not
    a valid inequality in general -- inventory banking lets a network cover
    a single period's peak demand with less installed capacity than that
    inequality requires -- so it is deliberately not implemented.)
    """
    if not production_technologies and not remanufacturing_technologies:
        return
    for factory in factories:
        model.addConstr(
            gp.quicksum(u_prod[factory, technology] for technology in production_technologies)
            + gp.quicksum(u_rem[factory, technology] for technology in remanufacturing_technologies)
            >= y_f[factory],
            name=f"vi_tech_demand[{factory}]",
        )


def _add_truck_fleet_constraints(
    model,
    params,
    transport_arcs,
    allowed_modes,
    periods,
    suppliers,
    factories,
    warehouses,
    hubs,
    y_s,
    y_f,
    y_w,
    y_h,
    mode_family,
    trip,
    vehicle,
) -> None:
    if len(vehicle) == 0:
        return

    model.addConstr(
        gp.quicksum(params["f_mode_m"][mode] * vehicle[origin, mode] for origin, mode in vehicle.keys())
        <= params.get("truck_investment_budget", 1.0e12),
        name="truck_investment_budget",
    )

    max_vehicle = params.get("max_vehicle_i_m", {})
    road_return_factor = params.get("road_return_factor_m", {})
    speed = params.get("speed_km_h_m", {})
    max_hours = params.get("max_driving_hours_m", {})
    distances = params["d_i_j"]

    for origin, mode in vehicle.keys():
        activity = _entity_activity(origin, suppliers, factories, warehouses, hubs, y_s, y_f, y_w, y_h)
        configured_max = max_vehicle.get(origin, {}).get(mode)
        if configured_max is None:
            configured_max = _trip_big_m(params, mode, origin=origin)
        model.addConstr(vehicle[origin, mode] <= configured_max * activity)
        outbound_trip_vars = [
            trip[origin, destination, mode, period]
            for arc_origin, destination in transport_arcs
            if arc_origin == origin and mode in allowed_modes[(arc_origin, destination)]
            for period in periods
        ]
        if outbound_trip_vars:
            model.addConstr(vehicle[origin, mode] <= configured_max * gp.quicksum(outbound_trip_vars))
        else:
            model.addConstr(vehicle[origin, mode] == 0.0)

        if _mode_family(mode, mode_family) != "truck":
            continue
        mode_speed = float(speed.get(mode, 0.0))
        mode_hours = float(max_hours.get(mode, 0.0))
        for period in periods:
            outbound_trips = (
                (destination, trip[origin, destination, mode, period])
                for arc_origin, destination in transport_arcs
                if arc_origin == origin and mode in allowed_modes[(arc_origin, destination)]
            )
            if mode_speed > 0.0 and mode_hours > 0.0:
                model.addConstr(
                    gp.quicksum(
                        road_return_factor.get(mode, 2.0)
                        * distances[origin][destination]
                        / mode_speed
                        * trip_var
                        for destination, trip_var in outbound_trips
                    )
                    <= mode_hours * vehicle[origin, mode]
                )
            else:
                model.addConstr(
                    gp.quicksum(trip_var for _destination, trip_var in outbound_trips)
                    <= _trip_big_m(params, mode, origin=origin) * vehicle[origin, mode]
                )


def _trip_big_m(
    params,
    mode: str,
    *,
    origin: str | None = None,
    destination: str | None = None,
) -> int:
    configured = params.get("trip_big_m_m", {}).get(mode)
    capacity = max(float(params["bar_X_m"].get(mode, 1.0)), 1.0)
    candidate_bounds: list[int] = []
    if configured is not None:
        candidate_bounds.append(max(1, int(math.ceil(float(configured)))))

    endpoint_caps = [
        float(params.get("ecmax_i", {}).get(node, 0.0))
        for node in (origin, destination)
        if node is not None and params.get("ecmax_i", {}).get(node) is not None
    ]
    if endpoint_caps:
        candidate_bounds.append(max(1, int(math.ceil(min(endpoint_caps) / capacity)) + 1))

    if params.get("ccamax_m", {}).get(mode, 0.0) > 0.0:
        candidate_bounds.append(max(1, int(math.ceil(float(params["ccamax_m"][mode]) / capacity)) + 1))
    elif not candidate_bounds:
        flow_bound = max(params.get("ecmax_i", {}).values(), default=capacity)
        candidate_bounds.append(max(1, int(math.ceil(flow_bound / capacity)) + 1))

    return min(candidate_bounds)


def _add_intermodal_hub_constraints(
    model, transport_arcs, allowed_modes, flow_by_arc, periods, airports, seaports, mode_family, x,
) -> None:
    for transfer_hubs, transfer_family, name_prefix in (
        (airports, "air", "airport"),
        (seaports, "sea", "seaport"),
    ):
        hub_set = set(transfer_hubs)
        if not hub_set:
            continue

        items_by_hub: dict[str, set[str]] = {hub: set() for hub in transfer_hubs}
        for origin, destination in transport_arcs:
            items = flow_by_arc.get((origin, destination), ())
            if origin in hub_set:
                items_by_hub[origin].update(items)
            if destination in hub_set:
                items_by_hub[destination].update(items)

        for hub in transfer_hubs:
            for item in sorted(items_by_hub[hub]):
                for period in periods:
                    access_in = gp.quicksum(
                        x[item, origin, hub, mode, period]
                        for origin, destination in transport_arcs
                        if destination == hub
                        and origin not in hub_set
                        and item in flow_by_arc.get((origin, destination), ())
                        for mode in allowed_modes[(origin, destination)]
                        if _mode_family(mode, mode_family) != transfer_family
                    )
                    transfer_out = gp.quicksum(
                        x[item, hub, destination, mode, period]
                        for origin, destination in transport_arcs
                        if origin == hub
                        and destination in hub_set
                        and item in flow_by_arc.get((origin, destination), ())
                        for mode in allowed_modes[(origin, destination)]
                        if _mode_family(mode, mode_family) == transfer_family
                    )
                    transfer_in = gp.quicksum(
                        x[item, origin, hub, mode, period]
                        for origin, destination in transport_arcs
                        if destination == hub
                        and origin in hub_set
                        and item in flow_by_arc.get((origin, destination), ())
                        for mode in allowed_modes[(origin, destination)]
                        if _mode_family(mode, mode_family) == transfer_family
                    )
                    access_out = gp.quicksum(
                        x[item, hub, destination, mode, period]
                        for origin, destination in transport_arcs
                        if origin == hub
                        and destination not in hub_set
                        and item in flow_by_arc.get((origin, destination), ())
                        for mode in allowed_modes[(origin, destination)]
                        if _mode_family(mode, mode_family) != transfer_family
                    )

                    model.addConstr(
                        access_in == transfer_out,
                        name=f"{name_prefix}_access_to_transfer[{item},{hub},{period}]",
                    )
                    model.addConstr(
                        transfer_in == access_out,
                        name=f"{name_prefix}_transfer_to_access[{item},{hub},{period}]",
                    )


def _entity_activity(entity: str, suppliers, factories, warehouses, hubs, y_s, y_f, y_w, y_h):
    if entity in suppliers:
        return y_s[entity]
    if entity in factories:
        return y_f[entity]
    if entity in warehouses:
        return y_w[entity]
    if entity in hubs:
        return y_h[entity]
    return 1.0


def _labour_cost(
    params,
    *,
    factories,
    warehouses,
    production_technologies,
    remanufacturing_technologies,
    vehicle_pairs,
    annuity,
    y_f,
    y_w,
    installed_area,
    u_prod,
    u_rem,
    vehicle,
) -> gp.LinExpr:
    """Recurring labour cost (Mota et al. 2018, eq. 43, terms 10-13).

    Four crews attach to network-design variables and are paid every period:
    a fixed crew per opened facility, a crew proportional to installed floor
    area, a crew per installed technology, and a driver per owned truck. Each
    costs ``workers * lc_i * wwh * wpt`` per period. Because the crew sizes do
    not vary over the horizon, the per-period total is multiplied by the
    annuity factor rather than by ``|T|`` -- the same present-value weighting
    every other recurring flow receives.

    Returns an empty expression when the instance carries no labour data, so
    instances generated before these parameters existed keep their original
    objective.
    """
    labour_cost_by_entity = params.get("labour_cost_i") or {}
    if not labour_cost_by_entity:
        return gp.LinExpr(0.0)

    hours = float(params.get("weekly_working_hours", 0.0)) * float(params.get("weeks_per_period", 0.0))
    if hours <= 0.0:
        return gp.LinExpr(0.0)

    rate = annuity * hours

    def wage(entity: str) -> float:
        return float(labour_cost_by_entity.get(entity, 0.0))

    fixed_workers = params.get("workers_fixed_i") or {}
    workers_per_sqm = params.get("workers_per_sqm_i") or {}
    workers_prod = params.get("workers_prod_g") or {}
    workers_rem = params.get("workers_rem_l") or {}
    workers_mode = params.get("workers_mode_m") or {}

    facility_crew = gp.quicksum(
        rate * wage(f) * float(fixed_workers.get(f, 0.0)) * y_f[f] for f in factories
    ) + gp.quicksum(
        rate * wage(w) * float(fixed_workers.get(w, 0.0)) * y_w[w] for w in warehouses
    )
    area_crew = gp.quicksum(
        rate * wage(i) * float(workers_per_sqm.get(i, 0.0)) * installed_area[i]
        for i in (*factories, *warehouses)
    )
    technology_crew = gp.quicksum(
        rate * wage(f) * float(workers_prod.get(g, 0.0)) * u_prod[f, g]
        for f in factories
        for g in production_technologies
    ) + gp.quicksum(
        rate * wage(f) * float(workers_rem.get(l, 0.0)) * u_rem[f, l]
        for f in factories
        for l in remanufacturing_technologies
    )
    fleet_crew = gp.quicksum(
        rate * wage(origin) * float(workers_mode.get(mode, 0.0)) * vehicle[origin, mode]
        for origin, mode in vehicle_pairs
    )
    return facility_crew + area_crew + technology_crew + fleet_crew


def discount_factors(params, periods) -> dict[str, float]:
    """Present-value weight for each period, ``t = 1..|T|``.

    Follows Mota et al. (2018), eq. 41: every recurring per-period monetary
    flow is discounted at the interest rate ``ir``. Capital carries no weight
    from this function -- it is charged as a per-period rental by
    ``capital_multipliers``, which builds on the annuity computed here.
    Emissions are NOT
    discounted -- Mota's environmental objective (eq. 46) is a plain sum over
    ``t`` -- but the carbon-tax *payment* is, because it is money. That
    asymmetry is the point: the regulator counts physical tonnes, the operator
    counts the present value of its tax bill.

    ``ir = 0.1`` is an ANNUAL rate. Mota calibrated it for a model whose
    periods are years ("ten years with yearly increments"), which his
    depreciation schedule corroborates -- 5%/12.5%/20% per period are textbook
    20-, 8- and 5-year asset lives. Tautenhain et al. carry that value into a
    generator whose periods are 17.33 weeks without rescaling it, and never
    address the mismatch; read literally there, 10% per four-month period
    compounds to 33.1% a year, which is not a cost of capital any firm faces.
    The rate is therefore compounded to the period length rather than applied
    per period:

        weight(t) = (1 + ir) ** (-t * weeks_per_period / 52)

    ``weeks_per_period`` defaults to 52, i.e. periods ARE years and the
    expression collapses to the textbook ``(1 + ir)^-t``. A missing or
    non-positive ``interest_rate`` yields unit weights, so any instance
    generated before the parameter existed reproduces its original objective
    exactly.
    """
    rate = float(params.get("interest_rate", 0.0) or 0.0)
    if rate <= 0.0:
        return {period: 1.0 for period in periods}
    weeks = float(params.get("weeks_per_period") or WEEKS_PER_YEAR)
    years_per_period = weeks / WEEKS_PER_YEAR
    return {
        period: (1.0 + rate) ** (-(index + 1) * years_per_period)
        for index, period in enumerate(periods)
    }


def is_discounted(params) -> bool:
    return float(params.get("interest_rate", 0.0) or 0.0) > 0.0


ASSET_CLASS_FACILITY = "facility"


ASSET_CLASS_TECHNOLOGY = "technology"


ASSET_CLASS_VEHICLE = "vehicle"


# Mirrors clsc.generator.tautenhain_data.ASSET_LIFE_YEARS, for instances that
# predate the parameter. Recovered from Mota's depreciation schedule: his
# 5%/12.5%/20% per yearly period are 20-, 8- and 5-year straight-line lives,
# and in each class the ten-year depreciation plus the salvage value sums to
# exactly 1.0, which is what identifies the life as the underlying invariant.
DEFAULT_ASSET_LIFE_YEARS = {
    ASSET_CLASS_FACILITY: 20.0,
    ASSET_CLASS_TECHNOLOGY: 8.0,
    ASSET_CLASS_VEHICLE: 5.0,
}


def capital_recovery_factor(rate_per_period: float, life_periods: float) -> float:
    """Level per-period charge that repays one unit of capital over its life.

    The textbook CRF, ``i / (1 - (1+i)^-n)``. At ``i = 0`` it degenerates to
    straight-line depreciation ``1/n``, which is the correct limit.
    """
    if life_periods <= 0.0:
        return 1.0
    if rate_per_period <= 0.0:
        return 1.0 / life_periods
    return rate_per_period / (1.0 - (1.0 + rate_per_period) ** (-life_periods))


def capital_multipliers(params, periods) -> dict[str, float]:
    """Coefficient each one-off capital cost carries in the follower's objective.

    Mota et al. (2018) buy an asset outright at ``t=0`` -- eq. 41 subtracts
    ``FCI`` undiscounted -- and sell the unconsumed remainder back at the
    horizon, through eq. 42's salvage term. Charging the full purchase price
    WITHOUT that recovery, which is what this model did until 2026-08-11, is
    half of the convention, and it makes the price of capital depend on the
    horizon: a factory used for one year cost exactly what one used for four
    years cost. Since ``|T|`` is an experimental factor here, that alone put a
    3.5x swing in the capex:opex ratio across its levels, for no economic
    reason.

    We charge instead for the asset-years actually consumed: a level per-period
    rental ``CRF * FCI``, whose present value over the horizon is
    ``CRF * FCI * annuity``. That is the same economics as Mota's buy-and-sell
    pair, it needs no assumption about reselling a purpose-built facility at
    book value after one year, and it makes capex:opex invariant in ``|T|`` by
    construction. Salvage is then not omitted but structurally absent: nothing
    is bought outright, so there is no residual to recover.

    The depreciation tax shield is NOT applied. With revenue constant the
    objective reduces to cost minimisation and Mota's ``(1-tr)`` divides out,
    leaving a relative discount on capital of ``tr/(1-tr)`` per unit
    depreciated; at these asset lives that is worth about 2% of FCI, second
    order against everything else here.

    A missing or non-positive ``interest_rate`` returns unit multipliers, so
    any instance generated before this existed reproduces its original
    objective exactly.
    """
    lives = params.get("asset_life_years") or DEFAULT_ASSET_LIFE_YEARS
    rate = float(params.get("interest_rate", 0.0) or 0.0)
    if rate <= 0.0:
        return {asset_class: 1.0 for asset_class in lives}
    weeks = float(params.get("weeks_per_period") or WEEKS_PER_YEAR)
    years_per_period = weeks / WEEKS_PER_YEAR
    rate_per_period = (1.0 + rate) ** years_per_period - 1.0
    annuity = sum(discount_factors(params, periods).values())
    return {
        asset_class: annuity
        * capital_recovery_factor(rate_per_period, float(life) / years_per_period)
        for asset_class, life in lives.items()
    }


def embodied_emission_share_per_period(params) -> float:
    """Share of a facility's embodied (construction) emissions charged to each period.

    Straight-line over the facility's asset life, ``years_per_period / life``: the
    emissions counterpart of the capital rental in ``capital_multipliers``. Charging
    the full embodied emissions inside a horizon of one to four years, while capital
    is charged only for the asset-years consumed, would make the share of construction
    in E and in the tax base, and so the leader's optimal tax, depend on ``|T|`` for
    no physical reason. No interest is applied: a tonne of CO2e does not earn interest.
    The tax on each period's share is discounted like every other per-period payment.
    """
    lives = params.get("asset_life_years") or DEFAULT_ASSET_LIFE_YEARS
    weeks = float(params.get("weeks_per_period") or WEEKS_PER_YEAR)
    return (weeks / WEEKS_PER_YEAR) / float(lives[ASSET_CLASS_FACILITY])


def _inventory_cost(params, products, warehouses, periods, inv_w, discount):
    product_holding_cost = params["h_p"]
    return gp.quicksum(
        discount[t] * product_holding_cost[p] * inv_w[p, w, t]
        for p in products
        for w in warehouses
        for t in periods
    )


def _input_requirement(params: dict[str, object], raw_material: str, product: str, technology: str) -> float:
    return params["a_in_u_p_g"][raw_material][product].get(technology, 0.0)


def _return_lags(params: dict[str, object], products: Iterable[str]) -> dict[str, int]:
    configured = params.get("theta_p", {})
    return {product: int(configured.get(product, 1)) for product in products}


def _lagged_demand(
    params: dict[str, object],
    retailer: str,
    product: str,
    periods: tuple[str, ...],
    period_index: int,
    lag: int,
) -> float:
    lagged_index = period_index - lag
    if lagged_index < 0:
        return 0.0
    return params["d_r_p_t"][retailer][product][periods[lagged_index]]


def _return_fraction(
    params: dict[str, object],
    parameter_name: str,
    retailer: str,
    product: str,
    period: str,
) -> float:
    if parameter_name in params:
        return float(params[parameter_name][retailer][product][period])
    return float(params["rho_r_p_t"][retailer][product][period])


def _products_by_technology(pairs: Iterable[tuple[str, str]], technologies: Iterable[str]) -> dict[str, tuple[str, ...]]:
    mapping: dict[str, list[str]] = {technology: [] for technology in technologies}
    for product, technology in pairs:
        mapping.setdefault(technology, []).append(product)
    return {technology: tuple(products) for technology, products in mapping.items()}


def _technologies_by_product(pairs: Iterable[tuple[str, str]], products: Iterable[str]) -> dict[str, tuple[str, ...]]:
    mapping: dict[str, list[str]] = {product: [] for product in products}
    for product, technology in pairs:
        mapping.setdefault(product, []).append(technology)
    return {product: tuple(technologies) for product, technologies in mapping.items()}


def _flow_indices(flow_tuples: Iterable[tuple[str, str, str]]):
    incoming: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    outgoing: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for item, origin, destination in flow_tuples:
        outgoing[(item, origin)].append((origin, destination))
        incoming[(item, destination)].append((origin, destination))
    return incoming, outgoing


def _item_weights(params: dict[str, object], raw_materials, products, recovered_products) -> dict[str, float]:
    weights: dict[str, float] = {}
    weights.update({raw_material: float(params["omega_u"][raw_material]) for raw_material in raw_materials})
    weights.update({product: float(params["omega_p"][product]) for product in products})
    for recovered_product in recovered_products:
        weights[recovered_product] = float(params["omega_rp"][recovered_product])
    return weights


def _allowed_modes(
    origin: str,
    destination: str,
    modes: tuple[str, ...],
    *,
    airports: tuple[str, ...],
    seaports: tuple[str, ...],
    mode_family: dict[str, str],
) -> tuple[str, ...]:
    if origin in airports and destination in airports:
        required_family = "air"
    elif origin in seaports and destination in seaports:
        required_family = "sea"
    else:
        required_family = "truck"
    allowed = tuple(mode for mode in modes if mode_family.get(mode, mode) == required_family)
    return allowed or tuple(modes)


def _mode_family(mode: str, mode_family: dict[str, str]) -> str:
    return mode_family.get(mode, mode)
