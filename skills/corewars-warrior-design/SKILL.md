---
name: corewars-warrior-design
description: Structured procedure for designing a CoreWars Redcode warrior that beats multiple opponents. Use when the task is to build a Redcode warrior that must achieve required win-rates against a fixed roster of opponents (e.g., stone bombers, paper replicators, vampires, snakes, g2-clear). Provides opponent classification, counter-strategy selection, hybrid warrior construction, and iterative pmars tuning with explicit diagnostic checks and stop signals.
---

# CoreWars Warrior Design (Multi-Opponent)

## When to use

The task is to design a single Redcode warrior that must meet per-opponent win-rate thresholds against several distinct opponents. Symptoms that this skill applies:
- Multiple opponents listed, each with a different strategic archetype
- A win-rate threshold per opponent (e.g., >60%, >80%)
- "Hybrid" / "combine strategies" / "best warrior" framing
- pmars or pMARS is the available simulator

## Diagnostic checklist (run BEFORE writing the warrior)

1. **Classify every opponent by archetype.** For each opponent source file, identify the dominant strategy: stone bomber, paper replicator, vampire, imp ring, scanner/clear, snake, g2-clear, etc. A single warrior cannot counter all archetypes well — you must know what you are countering.
2. **Map each archetype to a known weakness.** Bombers are slow/predictable → countered by a scanner or quick imp ring. Paper replicators are vulnerable to imp spirals and SPL/SPL 0 bombs that disrupt their copy loop. Vampires die to a core-clear (DJN / SPL 0 carpet) or imp gate. Snakes fold to anti-vampire or anti-imp tactics. g2-clear loses to imps or self-copying warriors.
3. **Test the opponent list head-to-head with simple baseline warriors** (a single imp ring, a single stone bomber, a single scanner, a single SPL 0 carpet) using `pmars -b -r 100`. Record win-rates. This produces a known lower bound per opponent and reveals which archetypes actually need a custom counter.
4. **Pick the minimum number of counter-modules** whose combined baseline win-rates already meet every threshold. If a single module beats ≥3 opponents past threshold, do not add a second module yet.
5. **Confirm pmars version + flags** (`-b` for no extra output, `-r N` rounds) and that the warrior length / starting offset fit the standard 8000-core ICWS'94 rules before iterating.

## Procedure

1. **Analyze**: For each opponent, read the Redcode and identify (a) launch mechanism, (b) attack pattern, (c) one exploitable weakness.
2. **Select counters**: From the weakness map, pick one counter per opponent-archetype. Prefer counters that overlap (one module that hurts two archetypes) before adding new modules.
3. **Compose a hybrid**: Implement each counter as a labeled Redcode block. Use `ORG` / `EQU` so the blocks do not overwrite each other. Add a small decoy or padding region so bombers wasting cycles on decoys gives the active counters time.
4. **Submit under one warrior file**: All counters live in one source the harness compiles. Keep total length well under the core size.
5. **Iterate against the roster**: After every edit, run `pmars -b -r 100 warrior.red opponent.red` for each opponent. Log win-rate per opponent in a table.
6. **Tune**: Adjust constants (step size, gate distance, spl bomb spacing, imp-gate spacing) and re-test. Change one thing at a time so you can attribute gains.
7. **Stop** at the thresholds; do not chase the last 5% on one opponent if it costs >10% on another.

## Common pitfalls to avoid

- **Single-architecture bias**: Designing only a scanner (or only an imp spiral) and hoping it beats everything. It will not.
- **Modules that overwrite each other**: Two counters landing in the same core cells with no `ORG` separation → one silently kills the other.
- **Tuning one opponent at a time**: A "fix" that lifts win-rate vs. the snake by 20% but drops vs. the replicator by 30% is a net loss.
- **Skipping the baseline measurement**: Without per-opponent baseline numbers you cannot tell whether a new warrior is better than a one-line imp ring.
- **Trusting single-run results**: One `pmars` run is noise — always use `-r 100` (or more) and look at the average.
- **Filling the core**: A warrior that occupies most of the 8000-core gives scanners a free kill. Keep it compact.

## Stop signal

**If after 3 full iterations of the hybrid warrior you have not raised the *minimum* per-opponent win-rate above the required threshold for at least one opponent that was below threshold, abandon the current architecture and switch to a different dominant counter** (e.g., if your scanner-led hybrid is stuck, switch to an imp-gate-led hybrid). Do not write a 4th, 5th, 6th, 7th version of the same architecture — that is the debug spiral that wastes hours. After a successful architecture switch, rerun the full roster and only then resume tuning.

If `pmars` itself is unavailable in the sandbox, stop immediately and surface the missing tool rather than guessing win-rates.