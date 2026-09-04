from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from clsc.config.tax_grid import COARSE_SCALE_FACTOR as SCALE_FACTOR


DEFAULT_TRUCKS = 2


DEFAULT_AIRPLANES = 2


DEFAULT_BOATS = 2


DEFAULT_TRUCK_MODES = tuple(f"mrd{index}" for index in range(1, DEFAULT_TRUCKS + 1))


DEFAULT_AIRPLANE_MODES = tuple(f"ma{index}" for index in range(1, DEFAULT_AIRPLANES + 1))


DEFAULT_BOAT_MODES = tuple(f"ms{index}" for index in range(1, DEFAULT_BOATS + 1))


DEFAULT_TRANSPORT_MODES = (*DEFAULT_TRUCK_MODES, *DEFAULT_AIRPLANE_MODES, *DEFAULT_BOAT_MODES)


@dataclass(slots=True)
class ArcConnectivityConfig:
    sf_neighbors: int = 2
    fw_neighbors: int = 2
    wr_neighbors: int = 2
    rf_neighbors: int = 2

    def __post_init__(self) -> None:
        for field_name in ("sf_neighbors", "fw_neighbors", "wr_neighbors", "rf_neighbors"):
            value = getattr(self, field_name)
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")


@dataclass(slots=True)
class GeneratorConfig:
    suppliers: int = 3
    factories: int = 2
    warehouses: int = 3
    retailers: int = 4
    airports: int = 2
    seaports: int = 2
    products: int = 2
    raw_materials: int = 2
    production_technologies: int = 2
    remanufacturing_technologies: int = 2
    periods: int = 4
    seed: int | None = None
    instance_name: str = "base_case"
    coordinate_span_km: float = 750.0
    trucks: int = DEFAULT_TRUCKS
    airplanes: int = DEFAULT_AIRPLANES
    boats: int = DEFAULT_BOATS
    tax_lower: float = 0.0
    tax_upper: float = 0.2
    connectivity: ArcConnectivityConfig = field(default_factory=ArcConnectivityConfig)

    def __post_init__(self) -> None:
        for field_name in (
            "suppliers",
            "factories",
            "warehouses",
            "retailers",
            "airports",
            "seaports",
            "products",
            "raw_materials",
            "production_technologies",
            "remanufacturing_technologies",
            "periods",
            "trucks",
            "airplanes",
            "boats",
        ):
            value = getattr(self, field_name)
            if value <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.coordinate_span_km <= 0.0:
            raise ValueError("coordinate_span_km must be positive")
        if self.tax_lower < 0.0 or self.tax_upper < 0.0:
            raise ValueError("tax bounds must be nonnegative")
        if self.tax_upper < self.tax_lower:
            raise ValueError("tax_upper must be at least tax_lower")
        _tax_rate_to_tax_index(self.tax_lower)
        _tax_rate_to_tax_index(self.tax_upper)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tax_rate_to_tax_index(rate: float) -> int:
    scaled = round(float(rate) / SCALE_FACTOR)
    if abs(float(rate) - scaled * SCALE_FACTOR) > 1e-9:
        raise ValueError("tax bounds must be multiples of 0.01 USD/kg CO2e to match the scaled tax index")
    return int(scaled)
