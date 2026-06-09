"""paper/experiments — Terminal-Bench 2.0 driver and ablations.

Each script in this directory is a thin driver that produces a single
job-config YAML and invokes either ``paper lqrl run`` or ``paper paper run``
against it. The drivers are deliberately *read-only* with respect to
the library: the only side effect is producing job output under the
``output/`` directory tree.
"""

from __future__ import annotations
