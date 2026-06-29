"""L2 run — placeholder.

L2 is the "run the trial" layer; the actual logic lives in
:mod:`skillq.runtime` (Step 4: ``bridge.py`` → ``steps.py``). The
Q-update is a single step function in that pipeline
(``step_q_update``). This package exists to make the 4-layer
directory layout symmetric and to provide a stable import surface
for future L2-specific helpers (e.g., per-trial telemetry
aggregators).
"""