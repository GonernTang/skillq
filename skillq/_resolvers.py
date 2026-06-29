"""OmegaConf resolver registration for the skillq CLI.

Stock OmegaConf 2.3 ships only the ``oc.*`` resolvers (``oc.env``,
``oc.create``, ``oc.select`` …). Several of the existing skillq
configs reference two extra resolvers that lqrl's configs also use:

- ``${now:%Y-%m-%d__%H-%M-%S}`` — render the current time with
  ``strftime``. Used in ``job_name`` so each run gets a unique
  directory.
- ``${abspath:path}`` — resolve a path to an absolute one. Used
  for ``mounts_json.source`` so a bind mount works regardless of
  the process cwd.

Without these, ``OmegaConf.to_container(resolve=True)`` raises
``UnsupportedInterpolationType`` the moment the CLI loads a config
that uses them. We register the resolvers at import time; the
:mod:`skillq.cli` module imports :mod:`skillq` (which imports this
module) before parsing any job-config YAML, so the registrations
are guaranteed to be in place.

Idempotent: re-registration is a no-op (matches the upstream
``register_new_resolver`` semantics).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from omegaconf import OmegaConf


def _now(fmt: str) -> str:
    return datetime.now().strftime(fmt)


def _abspath(p: str) -> str:
    return str(Path(p).expanduser().resolve())


def register() -> None:
    """Register the ``now`` and ``abspath`` resolvers if missing.

    Safe to call multiple times — OmegaConf silently ignores
    re-registration of the same name.
    """
    if not OmegaConf.has_resolver("now"):
        OmegaConf.register_new_resolver("now", _now)
    if not OmegaConf.has_resolver("abspath"):
        OmegaConf.register_new_resolver("abspath", _abspath)


# Auto-register on import so `import skillq` (which `skillq.cli` does
# at the top of its build_parser) is enough to bring the resolvers
# online. Scripts that want to control the timing can call
# ``register()`` themselves explicitly.
register()
