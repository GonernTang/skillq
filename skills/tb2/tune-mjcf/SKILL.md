---
name: tune-mjcf
description: Speed up a MuJoCo MJCF simulation while preserving the exact state trajectory by tuning the solver and timestep without altering physics properties.
---

# Tuning MJCF for Speed Without Breaking Correctness

Goal: make a MuJoCo simulation faster while keeping its state trajectory (within a strict tolerance, e.g. 1e-5) bit-equivalent or near-bit-equivalent to the reference model.

## Procedure

1. **Profile the bottleneck**
   - Measure per-step cost (MuJoCo built-in timers, `mujoco.utils.timer_time`, or a manual `time.perf_counter` loop).
   - In most models the constraint solver dominates — not the integrator, not the broadphase.

2. **Pick the cheapest correct solver**
   - Allowed MJCF `<option solver="...">` values: `PGS` (Projected Gauss-Seidel), `CG` (Conjugate Gradient), `Newton`. Default is `Newton`.
   - Try `solver="PGS"` first with `iterations="1"`, then `solver="CG"` with `iterations="1"`. PGS is usually fastest on small/medium models; CG converges faster when there are many constraints.
   - Keep `iterations` as low as the model tolerates; this is a single most-effective knob.

3. **Optionally raise the timestep**
   - Increase `<option timestep="...">` (e.g. from 0.001 to 0.002 or 0.005) only if state still matches the reference.
   - A bigger timestep cuts step count but may push the integrator past its stability region — verify after each change.

4. **Validate against the reference model**
   - Run both models from randomized initial conditions for a representative horizon (many hundreds/thousands of steps).
   - Compare final `qpos`, `qvel`, `act`, and any other state fields you care about with `np.allclose(ref, tuned, atol=1e-5, rtol=0)`.
   - Check that no `NaN`/`Inf` appear in any state or sensor field.

5. **What NOT to touch**
   - Do **not** modify physical properties to "help" the simulation: no body masses, geom sizes, joint `damping`/`armature`, `solref`/`solimp` contact parameters, plugin config, actuator gains, or friction values. Any of these change the physics and silently invalidate correctness.
   - The only safe knobs are `<option solver>`, `<option iterations>`, and `<option timestep>`. Optionally `<option noslip_iterations>` / `<option cone>` are also pure solver tuning.

6. **Pick the best trade-off**
   - Among the candidates that pass the state match, choose the one with the largest wall-clock speedup.
   - Report the speedup factor and which knobs were changed.

## Minimal MJCF diff pattern

```xml
<option timestep="0.002" solver="PGS" iterations="1"/>
```

vs. the reference:

```xml
<option timestep="0.001" solver="Newton" iterations="100"/>
```

## Verification script outline

```python
import mujoco, numpy as np

ref = mujoco.MjModel.from_xml_string(REF_XML)
tuned = mujoco.MjModel.from_xml_string(TUNED_XML)

for trial in range(N_TRIALS):
    d_ref, d_tuned = mujoco.MjData(ref), mujoco.MjData(tuned)
    d_ref.qpos[:] = np.random.uniform(-0.1, 0.1, ref.nq)
    d_tuned.qpos[:] = d_ref.qpos[:]
    for _ in range(N_STEPS):
        mujoco.mj_step(ref, d_ref)
        mujoco.mj_step(tuned, d_tuned)
    assert np.allclose(d_ref.qpos, d_tuned.qpos, atol=1e-5, rtol=0)
    assert np.all(np.isfinite(d_tuned.qpos)) and np.all(np.isfinite(d_tuned.qvel))
```

## Failure modes to watch for

- **Trajectory drift with `CG`** at low iteration counts on models with friction cones or many contacts → fall back to `PGS`.
- **Explosions (NaN)** when raising timestep → reduce or revert.
- **Speedup but state diverges** → solver is too cheap; raise `iterations` or switch solver.