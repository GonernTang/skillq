---
name: metacircular-evaluator
description: Build a metacircular evaluator for a Scheme-like Lisp in another language (typically Python). Implements eval/apply, environments, primitives, S-expression reader, and supports self-hosting (the evaluator interpreting its own source).
---

# Metacircular Evaluator (Scheme-like)

A reusable procedure for building a Scheme-like metacircular evaluator embedded in a host language (typically Python). The evaluator should be able to interpret its own source code.

## 1. Core Data Structures

- **Pair**: cons cell with `car` and `cdr`. Use a tagged pair (e.g., a tuple `(tag, payload)`) so primitives can be distinguished from user data.
- **Environment**: represented as a pair of `(frame-alist, parent-env)` where `parent-env` is another environment or a sentinel (e.g., `'()`) for the global scope. The frame-alist is a list of `(symbol . value)` pairs.

## 2. Environment Operations

Implement four primitives over environments:

- **make-env(parent)**: create a new empty environment whose parent is `parent`.
- **env-lookup(env, symbol)**: search the current frame; if not found, recurse to parent; error if unbound.
- **env-define!(env, symbol, value)**: cons the new binding onto the current frame (defines in the *current* scope, does not walk).
- **env-set!(env, symbol, value)**: mutate the existing binding in whichever frame holds it; walk the parent chain; error if unbound.

## 3. Eval Dispatch

`eval(expr, env)` returns the value of `expr` in `env`:

1. **Self-evaluating atoms**: numbers, booleans (`#t`/`#f`), strings — return as-is.
2. **Symbol lookup**: a bare symbol resolves via `env-lookup`.
3. **Special forms** — check the `car` and dispatch:
   - `quote` → return `cadr` unevaluated.
   - `if` → evaluate the test; evaluate and return the consequent branch (only as needed).
   - `define` → either `(define var expr)` (define a variable) or `(define (name params…) body)` (lambda shorthand).
   - `set!` → evaluate value, then `env-set!` into the variable.
   - `lambda` → create a procedure value `(params, body, env)`.
   - `let` → desugar to an immediately-applied lambda: `((lambda (bindings…) body) arg-values…)`.
   - `begin` / `progn` → evaluate each sub-expression in sequence; return the last.
   - `cond` → evaluate each `(test . consequent)` clause; return the consequent of the first non-false test; support `else`.
4. **Function application**: recursively `eval` the operator, recursively `eval` each argument left-to-right, then `apply`.

## 4. Apply

`apply(proc, args)`:

- **User-defined (lambda)**: build a new environment extending the closure's captured env with `params` bound to `args`; evaluate the body in it.
- **Primitive**: tagged as `(primitive . fn)`; call `fn(args)` where `fn` is a host-language closure receiving an already-evaluated list and returning the result.

## 5. Primitives

Wrap each host function as a `(primitive . fn)` tagged value. Cover at minimum:

- Arithmetic: `+`, `-`, `*`, `/`, `=`, `<`, `>`.
- Type predicates: `number?`, `symbol?`, `pair?`, `null?`, `boolean?`, `string?`, `procedure?`.
- Pairs: `cons`, `car`, `cdr`, `set-car!`, `set-cdr!`.
- Equality: `eq?`, `equal?`.
- I/O: `display`, `newline`, `read`.
- Files: `open-input-file`, `open-output-file`, `close-input-port`, `close-output-port`, `read-char`, `write-char`, `read-line`, `write-line`.
- List helpers: `list`, `length`, `append`, `reverse`, `map`, `filter`, `fold-left`, `fold-right`.
- Assoc helpers: `assq`, `assoc`.
- Control: `not`, `and`, `or`.

Bind all of these in the **global environment** at startup.

## 6. S-Expression Reader

Implement `read(port)` consuming characters from an input port:

- Skip whitespace and `;`-to-end-of-line comments.
- Parse atoms: numbers, booleans (`#t`, `#f`), strings (with escapes), symbols.
- Parse `'x` as `(quote x)`.
- Parse lists: balanced `(...)`; a `.` separates car and cdr of a single pair (dotted pairs); `()` is the empty list.
- EOF is signalled by a distinct marker the loop can detect.

## 7. Loading Files

`load(path)`:

1. Open the file as an input port.
2. Repeatedly call `read` collecting each top-level form into a list.
3. Close the port.
4. `eval` the list as a single `(begin form1 form2 …)` so the evaluator only recurses through one begin frame instead of N independent evals (avoids host-stack blowup when the evaluator runs on itself).

## 8. Self-Hosting Requirements

For the evaluator to interpret *its own* source:

- Support every special form the implementation uses (`quote`, `if`, `define`, `set!`, `lambda`, `let`, `begin`, `cond`, `and`, `or`).
- Provide every primitive the implementation calls (full I/O, list, and assoc set above).
- Implement `load` so the file can re-read itself.
- **Increase the host interpreter's recursion limit** (e.g. `sys.setrecursionlimit(10_000_000)` for Python) — metacircular evaluation on its own source nests roughly twice as deep per source-level call as a direct call, and the default limit will be exceeded.

## 9. Build & Verify Checklist

1. Define Pair + tagged primitive + Environment.
2. Implement env-lookup/define!/set! — test with a nested scope.
3. Implement eval dispatch + apply — test with arithmetic and conditionals.
4. Bind primitives into the global env.
5. Implement the reader — test round-trip on simple programs.
6. Add `load` as a primitive that reads all forms then evals one big begin.
7. Smoke test on a small `.scm` script.
8. Bootstrap: have `load` read the evaluator's own source file; verify it produces identical output on a non-trivial program.