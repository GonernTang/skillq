"""One-off debug script for the claude-PATH issue (#11).

Monkey-patches Harbor's ``DockerEnvironment`` to set
``keep_containers=True`` (so the trial container survives the
smoke) and then runs the paper job. After the smoke prints
its result, the script stays alive for ~5 min so a separate
shell can `docker exec` into the surviving container and
inspect ``echo $PATH``, ``env``, etc.

Usage::

    # terminal A: run the smoke trial (it blocks at the end of the trial)
    bash experiments/smoke/run_smoke.sh

    # terminal B: while terminal A is still alive
    docker ps                                       # find the trial container
    CID=$(docker ps -qf ancestor=skills_vote/gcode-to-text:20260604)
    docker exec -it $CID bash -c 'echo "PATH=$PATH"; which claude; env | sort'
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

# Make sure we pick up the .env before importing mg.
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(".env").resolve(), override=True)

# ---------------------------------------------------------------------------
# Monkey-patch BEFORE importing paper.paper_mode.bridge
# ---------------------------------------------------------------------------
import harbor.environments.docker.docker as _docker_mod  # noqa: E402

_orig_docker_init = _docker_mod.DockerEnvironment.__init__


def _patched_docker_init(self, *args, **kwargs):
    # Force keep_containers=True so the trial container survives the
    # smoke for post-mortem inspection. This is a debug-only
    # override — never enable in production (leaks disk / network).
    kwargs["keep_containers"] = True
    _orig_docker_init(self, *args, **kwargs)


_docker_mod.DockerEnvironment.__init__ = _patched_docker_init

# Now import the bridge (this will register paper's machinery).
from skillq.paper_mode.config import MethodConfig  # noqa: E402
from skillq.paper_mode.bridge import run_paper_job_sync  # noqa: E402


SMOKE_CONFIG = "experiments/smoke/fix-git_skillq_smoke.yaml"
METHOD_CONFIG = "experiments/smoke/method.yaml"
HOLD_SECONDS = int(os.environ.get("DEBUG_HOLD_SEC", "300"))


async def main() -> int:
    method = MethodConfig.model_validate(
        # Use OmegaConf so ${oc.env:...} gets resolved.
        __import__("omegaconf").OmegaConf.load(METHOD_CONFIG)
    )
    print(f"[debug_smoke] method.hook_top_k = {method.hook_top_k}")
    print(f"[debug_smoke] method.embedder_model = {method.embedder_model}")
    print(f"[debug_smoke] running paper job, then holding for {HOLD_SECONDS}s...")
    from skillq.paper_mode.bridge import run_paper_job
    rc = await run_paper_job(SMOKE_CONFIG, method)
    print(f"[debug_smoke] paper job returned {rc}; holding for post-mortem exec")
    print(f"[debug_smoke] in another terminal: docker ps ; docker exec -it <id> bash")
    # Block the event loop for HOLD_SECONDS so the script stays alive.
    for _ in range(HOLD_SECONDS):
        await asyncio.sleep(1)
    print("[debug_smoke] hold elapsed; exiting.")
    return rc


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
