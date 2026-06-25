"""``skillq/experiments/run/beta_sweep.py`` — sweep the β hyperparameter of Eq. 6.

The paper's Sec. 4.5 reports a sweet spot at ``β ≈ 0.3-0.5``; this
driver runs the same Terminal-Bench 2.0 job with seven β values
(0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0) and dumps a summary table.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.skillq_runtime.config import MethodConfig  # noqa: E402

BETA_VALUES = [0.0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="beta_sweep")
    parser.add_argument("--job-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("output/beta_sweep"))
    args = parser.parse_args(argv)

    cfg_dir = args.output_dir / "method_configs"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, Any]] = []
    for beta in BETA_VALUES:
        cfg = MethodConfig(beta=beta)
        cfg_path = cfg_dir / f"beta_{beta:.2f}.yaml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        import yaml

        cfg_path.write_text(
            yaml.safe_dump(cfg.model_dump(mode="json"), sort_keys=False),
            encoding="utf-8",
        )
        cmd = [
            sys.executable,
            "-m",
            "paper.cli",
            "paper",
            "run",
            "-c",
            str(args.job_config),
            "--method-config",
            str(cfg_path),
        ]
        print(f"[beta_sweep] β={beta:.2f} → {' '.join(cmd)}")
        result = subprocess.run(cmd)
        summary.append({"beta": beta, "returncode": result.returncode})

    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
