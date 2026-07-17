"""One declarative spec module per experiment family (A-G). Each module exposes:

  FAMILY_ID, EXECUTION_MODE ("bilevel" or "fixed_tax"), BASE_INSTANCES,
  PER_SUBPROBLEM_TIME_LIMIT_SECONDS, PER_RUN_WALL_CLOCK_CAP_SECONDS, build_design_matrix()

`build_design_matrix()` returns a list of dict rows (one design point each); every row has at
least: family_id, design_point_id, run_code, base_instance_id, factor_levels (dict),
technology_menu, transport_menu, seed, fixed_tax_index, mip_gap, dbp_relative_gap.
"""
