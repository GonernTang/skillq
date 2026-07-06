---
name: constraint-scheduling
description: Model and solve scheduling problems with hard/soft constraints — job-shop, shift/timetable, resource allocation, and task-with-deadlines. Use when the user needs to assign tasks to time slots or resources subject to rules (no overlaps, capacities, deadlines, precedence, availability) and wants a feasible or optimal schedule. Covers choosing a solver (CP-SAT, greedy, ILP), formulating variables/constraints/objective, and validating results.
---

# Constraint Scheduling

## Overview

Scheduling = assign **tasks** to **time** and/or **resources** so that all **hard constraints** hold and **soft constraints** (preferences) are optimized. This skill gives a repeatable workflow: classify the problem, pick a solver, formulate the model, solve, and validate.

Do not hand-roll a bespoke backtracking search when a constraint solver will do it faster and more correctly. Reach for a modeling library first.

## Workflow

1. **Classify the problem** (see decision table) to pick the solver and formulation.
2. **Enumerate the pieces**: tasks, time horizon, resources, then hard vs soft constraints.
3. **Choose a solver** and formulate variables → constraints → objective.
4. **Solve**, then **validate** the output against every hard constraint independently.
5. If infeasible, **relax** soft constraints or report the minimal conflicting set.

## Step 1 — Classify

| Signal in the request | Problem class | Default approach |
|---|---|---|
| Machines process jobs in sequence, minimize makespan | Job-shop / flow-shop | CP-SAT with interval vars |
| Assign staff to shifts, coverage + fairness rules | Rostering / shift scheduling | CP-SAT (booleans) |
| Fit classes/exams into rooms & periods, no clashes | Timetabling | CP-SAT / graph coloring |
| Tasks with durations, deadlines, precedence, one worker | Single-machine sequencing | CP-SAT or greedy (EDF) |
| Fixed capacity resource, tasks consume amounts over time | Cumulative scheduling | CP-SAT `AddCumulative` |
| Purely "pick items under a budget", no time | Not scheduling → knapsack/ILP | ILP (PuLP/OR-Tools) |

## Step 2 — Enumerate the pieces

Before writing any model, write down explicitly:

- **Tasks**: id, duration, release time, deadline, precedence edges.
- **Horizon**: discrete slots (e.g., 15-min buckets, days) or continuous minutes.
- **Resources**: machines/people/rooms, their capacities and availability windows.
- **Hard constraints** (MUST hold): no-overlap per resource, precedence, capacity, availability, deadlines that are contractual.
- **Soft constraints** (optimize): minimize makespan/lateness, balance load, honor preferences, minimize gaps. Each gets a weight in the objective.

Ambiguity to resolve with the user before modeling: is a stated deadline hard or soft? Is time discrete or continuous? Are resources interchangeable?

## Step 3 — Choose a solver

- **OR-Tools CP-SAT** (default, recommended): best for scheduling with intervals, no-overlap, cumulative, and mixed hard/soft. Handles most real problems and returns optimal or best-effort with a time limit.
- **ILP (PuLP / OR-Tools linear)**: when the model is naturally linear and you need MILP tooling or an existing LP stack.
- **Greedy heuristics**: when the problem is simple, huge, or only needs "good enough" fast. Examples: Earliest-Deadline-First (EDF) for single machine, list scheduling for parallel machines. Always note greedy is not guaranteed optimal.
- **Backtracking / custom CSP**: only for tiny or highly irregular constraints a solver can't express.

Rule of thumb: start with CP-SAT. Drop to greedy only if scale or latency forbids it, and say so.

## Step 4 — Formulate (CP-SAT patterns)

### Interval-based (job-shop, one task per resource at a time)

```python
from ortools.sat.python import cp_model

model = cp_model.CpModel()
horizon = sum(durations)

starts, ends, intervals = {}, {}, {}
for t in tasks:
    starts[t] = model.NewIntVar(release[t], horizon, f"start_{t}")
    ends[t]   = model.NewIntVar(0, horizon, f"end_{t}")
    intervals[t] = model.NewIntervalVar(starts[t], dur[t], ends[t], f"iv_{t}")

# Hard: no two tasks on the same machine overlap
for m in machines:
    model.AddNoOverlap([intervals[t] for t in tasks if machine[t] == m])

# Hard: precedence  a -> b
for a, b in precedence:
    model.Add(starts[b] >= ends[a])

# Hard: deadlines
for t in tasks:
    if deadline[t] is not None:
        model.Add(ends[t] <= deadline[t])

# Soft: minimize makespan
makespan = model.NewIntVar(0, horizon, "makespan")
model.AddMaxEquality(makespan, [ends[t] for t in tasks])
model.Minimize(makespan)

solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 10.0
status = solver.Solve(model)
```

### Cumulative (shared resource with capacity)

```python
# Tasks consume `demand[t]` of a resource with total `capacity`
model.AddCumulative([intervals[t] for t in tasks],
                    [demand[t] for t in tasks], capacity)
```

### Assignment booleans (shift/timetable)

```python
# x[w, s] = 1 if worker w takes shift s
x = {(w, s): model.NewBoolVar(f"x_{w}_{s}") for w in workers for s in shifts}
# Coverage: each shift filled by exactly `need[s]`
for s in shifts:
    model.Add(sum(x[w, s] for w in workers) == need[s])
# One shift per worker per day
for w in workers:
    for d in days:
        model.Add(sum(x[w, s] for s in shifts_on(d)) <= 1)
# Soft: honor preferences
model.Maximize(sum(pref[w, s] * x[w, s] for w in workers for s in shifts))
```

### Weighted soft objective

Combine multiple soft goals with weights; scale so higher-priority terms dominate:

```python
model.Minimize(100 * total_lateness + 10 * makespan + 1 * total_gaps)
```

## Step 5 — Solve & validate

- Set `max_time_in_seconds` so the solver returns even on hard instances.
- Check `status` ∈ {`OPTIMAL`, `FEASIBLE`}; treat `INFEASIBLE` as a modeling result, not a crash.
- **Independently validate** the extracted schedule against every hard constraint with plain code (do not trust the solver blindly during development):

```python
assert status in (cp_model.OPTIMAL, cp_model.FEASIBLE)
sched = {t: solver.Value(starts[t]) for t in tasks}
# re-check no-overlap, precedence, deadlines by hand
for a, b in precedence:
    assert sched[b] >= sched[a] + dur[a]
```

## Handling infeasibility

When there is no valid schedule:

1. Confirm it's truly infeasible (not a modeling bug — check units, horizon, off-by-one on deadlines).
2. Identify the conflict: temporarily convert hard constraints to soft with penalty vars and see which get violated, or use CP-SAT's `AddAssumptions` + `SufficientAssumptionsForInfeasibility` to get a minimal conflict set.
3. Report to the user *which* constraints conflict and offer relaxations (extend horizon, add resources, drop a deadline).

## Common pitfalls

- **Discretization**: continuous time forced into slots too coarse → false infeasibility; too fine → slow. Choose the granularity of the smallest meaningful unit.
- **Hard vs soft mix-up**: putting a preference as a hard constraint makes problems infeasible. Confirm each rule's strictness.
- **No time limit**: CP-SAT can run long on large instances — always cap it.
- **Objective scaling**: unweighted multi-objective sums let a trivial term override an important one. Use clearly separated weights or lexicographic optimization.
- **Trusting output**: always validate independently until the model is proven.
- **Reinventing the solver**: a custom backtracker is almost always slower and buggier than CP-SAT for these problems.

## Quick reference

- Default solver: **OR-Tools CP-SAT** (`pip install ortools`).
- Job-shop → interval vars + `AddNoOverlap`.
- Capacity resource → `AddCumulative`.
- Assignment → boolean vars + coverage/exclusivity sums.
- Simple single-machine + deadlines → greedy **EDF** is often optimal.
- Always: enumerate hard vs soft, cap solve time, validate the result.