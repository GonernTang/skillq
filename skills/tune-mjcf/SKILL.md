---
name: tune-mjcf
description: Tune a MuJoCo MJCF model's simulation speed by increasing the integration timestep while preserving trajectory fidelity. Use when the user wants a faster simulation, asks to "speed up" / "tune" / "optimize" an MJCF, or needs to hit a target simulation-time-percentage without exceeding a state-difference tolerance.
---

# Tuning MuJoCo MJCF Simulation Speed

Speed up a MuJoCo simulation by raising the integration timestep in the MJCF `<option>` element, while keeping final-state deviation within tolerance. Smaller timesteps = more accurate but slower; larger timesteps = faster but may diverge or lose accuracy.

## Procedure

1. **Read the model.** Load the MJCF and locate the `<option timestep="...">` attribute. Record the current (default) value as `t0`.
2. **Establish a reference trajectory.** Run the simulation for the required duration using a fixed random seed and `t0`. Record the final state vector (qpos, qvel, and any relevant sensors/actuators) as `S_ref`. Also record the wall-clock simulation time as `T_ref`.
3. **Define the success criteria.**
   - **Tolerance:** `tol` — max allowed per-element difference between candidate final state and `S_ref` (commonly `1e-5` for tight fidelity, looser if the task allows).
   - **Speedup target:** e.g. ≥ X% of the reference simulation time consumed, or a fixed wall-clock budget.
4. **Sweep candidate timesteps.** Starting from `t0`, try progressively larger values (e.g. `t0 * 2`, `t0 * 3`, `t0 * 4`, …) — use binary search once you have two bracketing values (one passing, one failing). For each candidate `t_cand`:
   - Reset the model and run with the **same random seed** and same duration.
   - Compute the per-element max difference `max|S - S_ref|`.
   - Check for `NaN` / `Inf` in the final state (divergence) and intermediate states if practical.
5. **Pick the largest timestep that passes.** The optimal `t` is the largest candidate where `max|S - S_ref| < tol` AND no `NaN`/`Inf` appeared AND the measured simulation time meets the speedup target. If `t0` already exceeds the target, no change is needed.
6. **Edit the MJCF.** Update `<option timestep="...">` to the chosen value and save.
7. **Verify.** Re-run end-to-end with the new timestep and the original seed; confirm the state difference vs. `S_ref` is within tolerance, no `NaN`/`Inf`, and wall-clock time meets the target.

## Pitfalls

- **Larger timesteps can also need more substeps / iterations** to stay stable. If the integrator becomes unstable (NaN), also reduce `solver` iterations or switch to `solver="RK4"` before further increasing `timestep`.
- **Don't change contact parameters or geometry** — fidelity comparisons must differ *only* in timestep.
- **Re-seed for every run**; otherwise measurement noise drowns the real difference.
- **Final-state comparison is necessary but not always sufficient.** For chaotic systems, also sample intermediate states to catch trajectory drift.