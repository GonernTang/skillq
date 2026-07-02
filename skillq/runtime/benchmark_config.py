"""Shared benchmark YAML resolution — used by both ``skillq paper run``
and ``run_benchmark.py``.

Step 8 (2026-07-02): extracted from ``experiments/run/run_benchmark.py``
so ``skillq paper run --benchmark tb2 --variant full`` can resolve the
merged YAML directly without going through the wrapper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Repo-root-relative paths, resolved at import time.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

BENCHMARK_VARIANTS: dict[tuple[str, str], str] = {
    ("tb2", "small10"):         "experiments/configs/tb2_skillq_small10.yaml",
    ("tb2", "small10_v2"):      "experiments/configs/tb2_skillq_small10_v2.yaml",
    ("tb2", "full"):             "experiments/configs/tb2_skillq_full.yaml",
    ("tb2", "fromscratch"):     "experiments/configs/tb2_skillq_fromscratch.yaml",
    ("tb2", "fromscratch_resume"): "experiments/configs/tb2_skillq_fromscratch_resume.yaml",
    ("tb2", "fromscratch_r2"):  "experiments/configs/tb2_skillq_fromscratch_r2.yaml",
    ("tb2", "e2e"):             "experiments/configs/tb2_skillq_e2e.yaml",
    ("swebenchpro", "full"):     "experiments/configs/swebenchpro_skillq.yaml",
}


def resolve_merged_yaml_path(benchmark: str, variant: str) -> Path:
    """Return the absolute path to the merged YAML for (benchmark, variant)."""
    try:
        rel = BENCHMARK_VARIANTS[(benchmark, variant)]
    except KeyError:
        valid = ", ".join(f"{b}/{v}" for b, v in sorted(BENCHMARK_VARIANTS))
        raise SystemExit(
            f"unknown (benchmark, variant) {benchmark!r}/{variant!r}; "
            f"valid: {valid}"
        )
    return (_REPO_ROOT / rel).resolve()


def parse_overrides(items: list[str] | None) -> dict[str, Any]:
    """Parse ``--method-override key=value`` items into a nested dict."""
    if not items:
        return {}
    out: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(
                f"--method-override expects key=value (got: {item!r})"
            )
        key, raw = item.split("=", 1)
        key, raw = key.strip(), raw.strip()
        if raw.lower() in {"true", "false"}:
            value: Any = raw.lower() == "true"
        else:
            try:
                value = int(raw)
            except ValueError:
                try:
                    value = float(raw)
                except ValueError:
                    value = raw
        parts = key.split(".")
        cursor = out
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return out


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge: ``override`` wins on conflicts."""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def split_method_subtree(
    cfg: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Pop the ``method`` subtree out of a merged job YAML.

    Returns ``(job_cfg, method_cfg)``. ``method_cfg`` is ``None``
    if the merged YAML had no ``method:`` key.
    """
    if "method" not in cfg:
        return cfg, None
    method_cfg = cfg.pop("method")
    if not isinstance(method_cfg, dict):
        raise SystemExit(
            f"'method:' subtree must be a mapping; got {type(method_cfg).__name__}"
        )
    return cfg, method_cfg


def write_method_yaml(
    method_cfg: dict[str, Any],
    out_path: Path,
    *,
    fresh_start: bool = False,
    runtime: str = "new",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply CLI-level adjustments and write the method-config YAML."""
    overrides = overrides or {}
    merged = deep_merge(method_cfg, overrides)
    if fresh_start:
        merged["reuse_q_table"] = False
    if runtime != "new":
        merged["runtime"] = runtime
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        yaml.safe_dump(merged, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
    return merged


__all__ = [
    "BENCHMARK_VARIANTS",
    "resolve_merged_yaml_path",
    "parse_overrides",
    "deep_merge",
    "split_method_subtree",
    "write_method_yaml",
]
