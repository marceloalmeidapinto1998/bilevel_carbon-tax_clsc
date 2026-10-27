# Instances

The instances are new samples drawn with the instance generator of Tautenhain et al. (2021), whose data are published as Tautenhain et al. (2020), with the departures listed below. They have the dimensions of the Tautenhain et al. test bed, plus three larger instances added by this repository. They are stored in `data/`, one JSON file per instance.

Departures from Tautenhain et al. that change the instances:

- **Transport emission factors per mode.** Tautenhain et al. draw the factor of every transport mode from one range, which spans the four case-study modes of Mota et al. (2018). Here each mode is drawn from its own case-study values (kg CO2e per kg·km): trucks between 4.34e-4 and 1.8013e-3, air 1.03e-3, sea 1.089e-5.
- **Climate change only.** Tautenhain et al.'s environmental objective sums seventeen normalised ReCiPe 2008 categories; the carbon tax prices only the climate-change category.
- **Facility construction cost** per m² from Mota et al. (2018), Table 8.

Each instance is named `STD_I<entities>_M<items>_T<periods>`: `I` is the number of entities, `M` the number of items (raw materials, final products and recovered products), and `T` the number of periods.

| Set | `I` | `M` | `T` | Instances | Source | Generated with |
|---|---|---|---|---|---|---|
| Standard | 17, 25 | 4, 8 | 3, 6, 12 | 12 (every combination) | Tautenhain et al. | `benchmark` |
| Escalation | 25, 25, 33 | 12, 16, 8 | 6, 6, 6 | 3: `STD_I25_M12_T6`, `STD_I25_M16_T6`, `STD_I33_M8_T6` | This repository | `escalation` |

**Entities**

| `I` | Suppliers | Factories | Warehouses | Retailers | Airports | Seaports | Source |
|---|---|---|---|---|---|---|---|
| 17 | 3 | 3 | 3 | 4 | 2 | 2 | Tautenhain et al. |
| 25 | 3 | 3 | 9 | 4 | 4 | 2 | Tautenhain et al. |
| 33 | 3 | 3 | 17 | 4 | 4 | 2 | This repository |

Retailers are the customers of Tautenhain et al.

**Items**

| `M` | Raw materials | Final products | Recovered products | Source |
|---|---|---|---|---|
| 4 | 2 | 1 | 1 | Tautenhain et al. |
| 8 | 4 | 2 | 2 | Tautenhain et al. |
| 12 | 6 | 3 | 3 | This repository |
| 16 | 8 | 4 | 4 | This repository |

Each final product has one recovered counterpart. The rows `M12` and `M16` follow the same rule as `M4` and `M8`: half of `M` are raw materials, a quarter are final products and a quarter are recovered products.

Every instance has 3 production and 3 remanufacturing technologies.

**Case study.** `data/case_study/MOTA2018.json` is the case study of Mota et al. (2018): an electronic-components producer in Verona expanding to markets in Europe and Brazil, with 3 suppliers, 3 factories (Verona's already installed), 9 warehouses (Verona's already installed), 7 markets, 4 airports and 2 seaports, 4 raw materials, 2 final and 2 recovered products, 4 production and 2 remanufacturing technologies, trucks of two kinds, planes and ships, and 10 yearly periods. It is built by `python -m clsc.generator.mota2018` from the tables of Mota et al. (2018) and of Tautenhain et al. (2020, section 3), which publishes the case's demand, distances and emission factors; each table is cited in the builder. Where the two sources differ the builder follows Mota et al., and what neither states is assumed; both lists are in the builder and in the instance's metadata. The case's flows are about a hundred times those of the generated instances. Its capacities count units rather than kilograms, its handling is charged per hub and unit, and its truck emissions count the outbound leg only, as in Mota et al.; the optional parameters `capacity_unit_m`, `c_handle_h`, `emission_return_factor_m` and `existing_i` express this, and the generated instances do not use them. The instance differs from Mota et al.'s model in its objective (cost plus the carbon tax, with capital at its rental equivalent, instead of the NPV after profit tax) and in taxing the climate-change category only.

**Calibrated instances.** `data/calibrated/CAL_<size>_r<k>.json` holds 39 instances: three replicates of the twelve standard sizes and one of the three escalation sizes. Each keeps the network, costs, demand and capacities of a generated instance and takes from the case study what it determines: production intensities of 375 to 536 kg CO2e per kg and remanufacturing intensities of 103 to 134, no emissions on purchased raw materials, a maximum return fraction of 1 with a minimum below 15%, and EUR 0.15 per returned unit. On the generated instances remanufacturing has no environmental advantage and stays under 1% of production, so a tax tests the method rather than the closed loop; the calibrated instances test both. They are written by

```bash
python -c "from clsc.generator.calibrated import write_calibrated_set; write_calibrated_set('data/calibrated')"
```

and the reasons for each change are in the docstring of `clsc.generator.calibrated`. The manuscript uses replicates 0 and 1 (24 instances).
