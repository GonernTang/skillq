---
name: scheme-metacircular-eval
description: Build a metacircular evaluator for a Scheme-like language hosted in another interpreter. Covers evaluator dispatch, environments as association lists, compound vs primitive procedures, self-hosting STDIN handling, and triple-eval testing.
---

# Scheme Metacircular Evaluator

## When to use
Building an interpreter for a Scheme-like Lisp in another host language (typically Python), particularly when the host provides its own primitives (read/eval/apply, car/cdr/cons, arithmetic, I/O).

## Procedure

### 1. Study the host interpreter
- Identify how primitives are exposed: as callable functions wrapped in host-side objects, or as plain callables.
- Understand pair/list representation: host may use tagged pairs (`cons(x, y)` returns a pair object whose `car` is x, `cdr` is y).
- Understand environment representation: the host likely passes an environment object you must thread through eval/apply. Unwrap nested primitive wrappers with `car` if primitives are wrapped pairs.
- Inventory primitives you'll need: arithmetic (`+`, `-`, `*`, `/`, `=`), pair ops (`cons`, `car`, `cdr`, `list`), predicates (`eq?`, `pair?`, `null?`, `number?`, `symbol?`, `boolean?`), I/O (`display`, `newline`, `read`, `open-input-file`, `open-output-file`, `close-input-port`, `close-output-port`), control (`and`, `or`, `not`).

### 2. Implement `my-eval` (dispatch on expression type)
- Self-evaluating: numbers, strings, booleans, `#f` → return as-is.
- Symbol → lookup in environment.
- Quoted expression `(quote expr)` → return `expr` unevaluated.
- Assignment `(set! var expr)` → evaluate expr, then `set-variable-value!`.
- Definition `(define var expr)` → `define-variable!`. For function shorthand `(define (f args...) body)`, expand to `(define f (lambda (args...) body))`.
- `if` → evaluate test; if true (and not `#f`), eval consequent else alternate. Allow zero or more alternative expressions (treat as `begin`).
- `lambda` → return a compound procedure: `(params, body, env)`.
- `begin` → evaluate sequentially, return last.
- `cond` → expand into nested `if` (with `else` clause).
- Application → eval operator, eval each operand, then `my-apply`.
- `and`/`or` → short-circuit sequentially.

### 3. Implement `my-apply` (dispatch on procedure type)
- Compound procedure: build extended environment by binding params to args (frame-by-frame), then eval body sequentially.
- Primitive procedure: call underlying host function via `car` of the primitive object (unwrapping any wrappers), passing evaluated args.

### 4. Manage environments as association lists
- An environment is a list of frames; each frame is a list of `(name . value)` pairs.
- Helpers:
  - `make-environment` → list of empty frames
  - `extend-environment params args env` → cons a new frame
  - `lookup-variable-value name env` → search frames top-down
  - `set-variable-value! name value env` → mutate first match in place
  - `define-variable! name value env` → add to top frame (allows redefinition in same scope)
- Treat `#f` as the only false value; everything else (including 0, empty list, `'()`) is true.

### 5. Handle variable-arity primitives
- `+`, `*`, `and`, `or` accept 1+ args. Reduce with the host's binary primitive: `(op a (reduce op rest))` over the args list.

### 6. Self-hosting I/O convention
For a self-hosting evaluator (evaluator interpreting the evaluator):
- On startup, read **exactly one line** from STDIN → that line is a file path.
- Open that file, read all S-expressions, evaluate them.
- Any remaining STDIN (after the first newline) becomes the STDIN of the interpreted program.
- Top-level loop: `(read)` → `my-eval` → repeat until EOF. Print each result if desired.

### 7. Test incrementally
1. **Direct**: run the host on a simple program (e.g., a calculator) — sanity check the test harness.
2. **Single eval**: run the host on your evaluator interpreting the calculator — exercises `my-eval`/`my-apply`.
3. **Triple eval**: run the host on the evaluator interpreting the evaluator interpreting the calculator — exercises self-hosting (this is the real test).
- Add a `--port` or dummy primitive early if you can't yet wire `read` to a port — your evaluator needs to call `read` itself for true self-hosting.
- Use `set-variable-value!` (mutating) rather than always defining, to mirror Scheme semantics.

## Pitfalls
- Forgetting that `cond` clauses are `(test body...)`, not just `(test body)`.
- Boolean handling: `if` test must check `#f` explicitly; don't use Python truthiness on the test result.
- Primitive unwrapping: if the host wraps primitives (e.g., `(lambda (x) (car x))`), you must `car` before calling.
- Empty arg list: `(+)` should return 0 (or identity); handle base case.
- Mutation vs definition: `define` in a lambda body should add to that frame (Scheme behavior), not just shadow the outer binding.

## Output format
When done, print a single JSON line: `{"status": "ok", "skill_name": "<name>", "body_tokens": <N>}` or `{"status": "skip", "reason": "<why>"}`.