"""skillq/experiments — TB 2.0 / TB Pro / SWE-Bench Pro drivers.

Layout (post 4-layer refactor, 2026-06-29):

    experiments/
    ├── configs/     5 merged single-source-of-truth YAMLs
    │                (smoke/e2e/full/swebenchpro + tb_pro_skillsvote baseline)
    ├── run/         single-driver: run_benchmark.py + run_tb2_paper.sh
    ├── __init__.py  (this file)
    └── RUNNING.md   quick-start docs (post-refactor workflow)

The single-driver ``run_benchmark.py`` accepts ``--benchmark``,
``--variant``, ``--fresh-start``, ``--runtime``, and
``--method-override key=value`` flags. See RUNNING.md for the full
quick-start and experiments/configs/*.yaml for the canonical configs.
"""

from __future__ import annotations