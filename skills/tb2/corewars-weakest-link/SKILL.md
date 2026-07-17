---
name: corewars-weakest-link
description: When designing a CoreWars warrior (or any multi-opponent tournament strategy), test against every target opponent early, identify the worst-performing matchup, and iterate on the weakest link before declaring the design done. Avoids blind spots where one opponent class (e.g. vampire/imp hybrids) dominates and crushes overall win rate.
---

## Why this matters

In CoreWars — and in any head-to-head tournament against a fixed opponent set — overall performance is gated by the **worst** matchup, not the average. A warrior that crushes four opponents but loses to one will lose the tournament if that one is on the slate. The classic failure mode: tuning for "average behavior" while ignoring specific archetypes (scanners, vampires, imp spirals, stone/silk, quickscan, vampire-imp hybrids like Snake). Designers ship a "good" design whose worst matchup is a structural mismatch, and the tournament is decided on that one column.

## Diagnostic checklist

Run these BEFORE committing to the final design:

1. **Full adversary roster covered?** Run your warrior against every opponent on the slate — including hybrid classes (vampire + imp, paper + stone, scanner + quickscan) — and record a per-opponent win/tie/loss count. No claim of "average win rate" is valid until every matchup has a data point.
2. **Worst matchup named?** Sort the per-opponent scores. Which one is lowest? What is the architectural mismatch (e.g. paper loses to scissors; scanner loses to imp-spiral; stone loses to vampire fang hijack; high process count loses to vampire/imp hybrid like Snake)?
3. **Counter hypothesis concretely tested?** For the worst matchup, is there at least one concrete counter — bombing loop, dedicated scanner, process-cap, decoy field — and has that mechanism been simulated against the actual opponent, not merely theorized?
4. **Gap is within budget?** Is the worst matchup within tolerance of the best matchup (rule of thumb: worst-loss-rate ≤ best-loss-rate + 30%, or worst matchup wins ≥ 40% of rounds)? If not, the weakest link dominates your tournament result regardless of how well you do elsewhere.

## Stop signal

**Reset action:** If the worst matchup exceeds a defined threshold — e.g. loses > 60% of rounds, or has a win rate more than 30 percentage points below the median matchup — do NOT submit the design. Pause, name the architectural gap explicitly, and iterate on the weakest link until it is within tolerance. Accept short-term losses on already-strong matchups if needed; the goal is to raise the floor, not the average.

The discipline is: **measure first, name the worst, iterate on the worst, ship only when every matchup is within budget.**