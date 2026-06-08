"""``mg/experiments/ablation.py`` — ablation matrix for the four-layer method.

Each cell of the ablation matrix toggles a single component of the
paper method. The driver writes the corresponding ``MethodConfig`` to
a per-cell YAML and invokes ``mg paper run -c <job.yaml> --method-config <cell.yaml>``.

Cells (all on/off against the default hyperparameters):

  - ``with_ucb``         — c_ucb=0.5 (default) vs c_ucb=0.0
  - ``with_verifier``    — verifier_model=gpt-4o vs verifier disabled
                           (replaces r_learning with 0)
  - ``with_near_miss``   — theta_near_miss=0.5 vs theta_near_miss=10
                           (effectively disables Layer 4)
  - ``with_rejuvenate``  — n_stale=80 (default) vs n_stale=0
                           (rejuvenation still active, no staleness)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

# Make ``mg.*`` importable when this file is run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mg.paper_mode.config import MethodConfig  # noqa: E402


def _config_diff(base: MethodConfig, **overrides: Any) -> MethodConfig:
    """Return a copy of ``base`` with the given overrides applied."""
    data = asdict(base) if hasattr(base, "model_dump") else base.__dict__.copy()
    data.update(overrides)
    return MethodConfig.model_validate(data)


def _write_method_config(cfg: MethodConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    import yaml

    path.write_text(
        yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ablation")
    parser.add_argument("--job-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output/ablation"))
    args = parser.parse_args(argv)

    base = MethodConfig()
    cells: list[tuple[str, MethodConfig]] = [
        ("with_ucb", base),
        ("no_ucb", _config_diff(base, c_ucb=0.0)),
        ("with_verifier", base),
        ("no_verifier", _config_diff(base, beta=0.0)),  # disables r_learning term
        ("with_near_miss", base),
        ("no_near_miss", _config_diff(base, theta_near_miss=10.0)),
    ]

    cfg_dir = args.output_dir / "method_configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, Any]] = []
    for cell_name, cell_cfg in cells:
        cfg_path = cfg_dir / f"{cell_name}.yaml"
        _write_method_config(cell_cfg, cfg_path)

        cmd = [
            sys.executable,
            "-m",
            "mg.cli",
            "paper",
            "run",
            "-c",
            str(args.job_config),
            "--method-config",
            str(cfg_path),
        ]
        print(f"[ablation] {' '.join(cmd)}")
        result = subprocess.run(cmd)
        summary.append(
            {
                "cell": cell_name,
                "returncode": result.returncode,
                "method_config": str(cfg_path),
            }
        )

    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
