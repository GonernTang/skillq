---
name: pipeline-stage-validation
description: When building multi-stage transformation pipelines (image-to-decision, parse-transform-emit, signal-to-netlist, lex-parse-codegen), validate each stage with minimal test cases before proceeding. Prevents building on flawed foundations and wasting hours debugging the wrong stage.
---

# Pipeline Stage Validation

## Failure Pattern

When constructing a multi-stage transformation pipeline, agents commonly:
1. Implement all stages sequentially in one pass.
2. Test only the final output.
3. Discover the final output is wrong but cannot localize the bug.
4. Spend hours iterating on the wrong stage, generating many near-identical versions.

This applies to any task where stage N+1 depends on stage N's output:
- Image analysis: image → grid → pieces → board state → decision
- Hardware synthesis: signal allocation → arithmetic → gate netlist → test
- Data processing: parse → transform → aggregate → report
- Compilation: lex → parse → type-check → codegen → link
- Any chain where a silent wrong intermediate produces a wrong final result

## Guard Rail Procedure

1. **Decompose the pipeline explicitly** — enumerate each transformation stage and what each consumes/produces. Write this down before coding.
2. **Identify the smallest verifiable unit per stage** — what minimal input/output pair exercises that stage in isolation?
3. **Build bottom-up** — implement and test stage 1 alone, then stage 1+2, then stage 1+2+3, etc. Never skip ahead.
4. **Persist intermediate outputs** — save stage 1, 2, …, N-1 outputs to disk. When the final stage fails, you can inspect these rather than guess where the bug lives.
5. **Localize before fixing** — when a later stage produces a wrong output, run the diagnostic checklist to identify the failing stage BEFORE editing code. Never patch stage N based on stage N+1's symptoms alone.

## Diagnostic Checklist

Before committing to a full implementation, run these checks:

1. **Stage 1 unit test**: Run stage 1 alone on the smallest possible input. Does its output match expectations? (e.g., a trivial input produces a trivial expected output.)
2. **Boundary cases**: Run stages 1→k on N=0, N=1, and one small canonical fixture. Confirm each intermediate output matches expectations at every boundary, not just the final one.
3. **Resource projection**: For each stage, measure worst-case resource use on a small input. Extrapolate to the full input. If projected use exceeds budget by >2×, redesign that stage before scaling.
4. **No-shortcut check**: If you find yourself writing code that "should work" without testing, STOP. Run the stage and verify the actual output matches expectation. A correct-looking implementation that has never been executed is not a working implementation.

## Stop Signal

**Threshold**: If you have written 2 versions of any single stage and both fail the same diagnostic check, STOP. Do not write a third version on the same architecture.

**Reset action**:
1. Re-read the stage's specification from the task description.
2. Inspect the actual intermediate outputs you persisted (not your mental model of them).
3. If still stuck, consider whether the stage should be decomposed further into smaller sub-stages.
4. As a last resort, abandon the current pipeline decomposition and try an alternative one. Do NOT keep iterating on a broken architecture — switching decomposition often reveals that the bug was structural, not local.

## Scope

**Use when**: task has ≥3 transformation stages, each stage feeds the next, resource constraints exist (time / accuracy / memory / gate-budget / token-budget), and failures are silent (a wrong intermediate yields a wrong final result without an obvious error).

**Skip when**: single transformation (one function, one output); pure analysis with no transformation; end-to-end test fixtures already pass on the first try.