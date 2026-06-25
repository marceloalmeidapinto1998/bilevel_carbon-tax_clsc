"""Configuration, I/O helpers, path layout, and logging."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ENUM_REL = Path("enum_lf_lex_exact") / "enumeration_solutions.json"
LF_LEX_REL = Path("lf_lex_exact") / "solution.json"

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AnalysisConfig:
    results_base: Path = Path("results/runs/base")
    scenario: str | None = None
    eps: float = 1e-6
    baseline_tau: int = 0
    structural_families: tuple[str, ...] = (
        "y_s", "y_f", "y_w", "y_h", "u_prod", "u_rem", "contract",
    )
    log_level: str = "INFO"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["results_base"] = str(self.results_base)
        data["structural_families"] = list(self.structural_families)
        return data


DEFAULT = AnalysisConfig()


# ---------------------------------------------------------------------------
# Path layout
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class InstancePaths:
    instance: str
    root: Path          # results/base/{inst}/lf_lex_exact/network
    manifest: Path
    log: Path
    alignment_json: Path
    figures: Path


def instance_output_root(instance: str, cfg: AnalysisConfig) -> Path:
    if cfg.scenario:
        # scenarios live under results/runs/experiments/scenarios/<type>/...
        return (cfg.results_base.parent / "experiments" / "scenarios" / cfg.scenario
                / instance / "lf_lex_exact" / "network")
    return cfg.results_base / instance / "lf_lex_exact" / "network"


def ensure_output_dirs(instance: str, cfg: AnalysisConfig) -> InstancePaths:
    root = instance_output_root(instance, cfg)
    figures = root / "figures"
    root.mkdir(parents=True, exist_ok=True)
    figures.mkdir(exist_ok=True)
    return InstancePaths(
        instance=instance,
        root=root,
        manifest=root / "manifest.json",
        log=root / "log.txt",
        alignment_json=root / "alignment.json",
        figures=figures,
    )


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_enumeration_payload(instance: str, cfg: AnalysisConfig) -> dict[str, Any]:
    path = cfg.results_base / instance / ENUM_REL
    if not path.is_file():
        raise FileNotFoundError(f"Enumeration payload not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_lf_lex_payload(instance: str, cfg: AnalysisConfig) -> dict[str, Any] | None:
    path = cfg.results_base / instance / LF_LEX_REL
    if not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def enum_path(instance: str, cfg: AnalysisConfig) -> Path:
    return cfg.results_base / instance / ENUM_REL


def lf_lex_path(instance: str, cfg: AnalysisConfig) -> Path:
    return cfg.results_base / instance / LF_LEX_REL


def discover_instances(cfg: AnalysisConfig) -> list[str]:
    if not cfg.results_base.is_dir():
        return []
    found: list[str] = []
    for child in sorted(cfg.results_base.iterdir()):
        if not child.is_dir():
            continue
        if (child / ENUM_REL).is_file():
            found.append(child.name)
    return found


def sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def get_logger() -> logging.Logger:
    return logging.getLogger("network")


def attach_file_handler(log_path: Path, level: str = "INFO") -> logging.FileHandler:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger = get_logger()
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    return handler


def detach_handler(handler: logging.Handler) -> None:
    logger = get_logger()
    handler.flush()
    handler.close()
    logger.removeHandler(handler)


def ensure_stream_handler(level: str = "INFO") -> None:
    logger = get_logger()
    if any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
           for h in logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(level.upper())

