"""skillq/experiments — Terminal-Bench 2.0 / TB Pro / SWE-Bench Pro drivers.

Layout (mirrors ``lqrl/scripts/`` ):

    experiments/
    ├── prebuild/    core ops: prebuild_images.py (vendored from upstream)
    ├── run/         benchmark drivers (run_benchmark.py, run_terminalbench.py)
    │                + parameter sweeps (beta_sweep.py, kappa_sweep.py)
    │                + ablation matrix (ablation.py)
    ├── smoke/       end-to-end smoke test (run_smoke.sh + configs)
    ├── configs/     per-benchmark / per-mode YAML configs
    ├── __init__.py  (this file)
    └── RUNNING.md   user-facing Chinese documentation

Each script in this directory is a thin driver that produces a single
job-config YAML and invokes either ``skillq skillsvote run`` or
``skillq paper run`` against it. The drivers are deliberately
*read-only* with respect to the library: the only side effect is
producing job output under the ``output/`` directory tree.
"""

from __future__ import annotations
