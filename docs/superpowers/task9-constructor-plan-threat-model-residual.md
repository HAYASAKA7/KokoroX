# Task 9 — Guarded-target constructor-plan trust boundary: threat model & residual

_Status: convergence record for the Campaign 6 Task 9 "constructor plan"
composite-verifier hardening (review repairs A–G). Companion to
`2026-08-21-kokoroarc-complete-suite-campaign-6.md`._

## What this boundary is

`tests/skills/complete_suite_shell_preflight.py` embeds a dormant, source-only
"constructor plan" composite verifier (outer fragment ->
inner fragment). It authenticates the pinned prefix / precreation / fragment
bytes and canonical native vector before any launch authority could ever be
derived. It performs **no** process, socket, native, provider, or control-plane
activity; activation remains gated elsewhere.

## Threat model (in scope)

The verifier defends against **forged or drifted data** reaching the trust
decision: wrong prefix/precreation/fragment version, size, or SHA; non-canonical
native vectors; forged lifecycle/handle/topology fields; and unauthenticated
dependency substitution that would change the *result bytes* it returns. Every
such path fails closed with the canonical guarded `RuntimeError`, with tests
proving zero hostile dispatch.

## Out of scope — documented residual (same-interpreter object mutation)

Consistent with the plan's stable, non-hostile-host TCB assumption (see the
"trusted host TCB" section of the campaign plan) and with the previously
recorded R21.1 "coordinated multi-cell replacement" residual, the following is
**explicitly out of scope**: an attacker already executing arbitrary code inside
the *same Python interpreter* who coordinately rebinds interpreter-internal
object state — `__code__`, `__defaults__`, `__kwdefaults__`, `__globals__`,
`__builtins__`, closure cells, class descriptors, or builtin table entries — and
restores it around the verifier's own checks (e.g. via a line-trace callback).

This is not closable in pure Python: the verifier's own guards are built from the
same mutable objects, so an in-interpreter adversary who owns object rebinding
has already escaped any pure-Python gate. Such an adversary is inside the trusted
computing base by definition; the boundary assumes a non-instrumented
interpreter exactly as the host threat model assumes a non-instrumented shell.

## Review repairs A–G disposition

- **A — active-frame globals/builtins authentication** — DONE. A same-globals
  clone that retained a distinct captured builtins mapping is rejected; exact
  `str`/`bytes` are fast-bound rather than resolved through live builtins.
  Regression retained in the constructor-plan family.
- **B — composite verifier `__defaults__`/`__code__` on the invocation line** —
  COVERED / OUT OF SCOPE. The boundary already performs the full
  `__code__/__defaults__/__kwdefaults__/__globals__/__builtins__/__closure__`
  identity check immediately before the call, and re-checks `__code__` on the
  dispatch line; the guarded helper call additionally passes both arguments
  explicitly, so a trace-driven `__defaults__` swap at that line is inert. Any
  deeper trace-restore variant is the same-interpreter residual above.
- **C — bounded traversal / cycle rejection** — COVERED BY CONSTRUCTION for
  authenticated input; deeper variant OUT OF SCOPE. The outer fragment's
  `ast.walk` (bound as `trusted_ast_walk`) runs only over the tree of the
  SHA-authenticated, freshly-parsed pinned source, which is a finite acyclic
  parse tree, so traversal always terminates. Index-bounded
  `while index < len(...)` / fixed-`range` iteration is used elsewhere over
  authenticated tuples. Forcing a cyclic or unbounded node graph would require
  same-interpreter mutation of the parsed tree or the walker (residual above);
  no authenticated input can drive it.
- **D — inner `json.dumps.__globals__["JSONEncoder"]` rebind** — OUT OF SCOPE.
  Same-interpreter global-table mutation; see residual above.
- **E — inner use-line helper dispatch** — OUT OF SCOPE. Same-interpreter
  closure/helper rebinding.
- **F — inner recursive verifier `__code__` replacement** — OUT OF SCOPE.
  Same-interpreter code-object rebinding.
- **G — emptied closure cell -> canonical error** — OUT OF SCOPE (observed nit
  documented). Today `capture_function_state` reads
  `getattr(cell, "cell_contents")` directly (inner fragment ~line 1415); an
  emptied cell would leak a raw `ValueError` instead of the canonical guarded
  `RuntimeError`. Converting that to a fail-closed canonical error is a benign
  hygiene improvement, but the trigger — emptying a *live* closure cell — is not
  reachable from normal Python and requires the same same-interpreter object
  manipulation as the residual. It is left documented rather than applied, to
  avoid modifying the green, hash-frozen embedded fragment for a residual-class
  case. If Task 9 later re-opens the fragment for an in-scope reason, wrap that
  one access in the existing guarded-`RuntimeError` path.

## Convergence decision

Per owner direction, Task 9 converges here: the in-scope data-forgery and
fail-closed properties are enforced and gate-green; the same-interpreter
object-mutation vector (B/D/E/F, and deeper variants of A/C/G) is recorded as an
accepted, documented residual rather than chased indefinitely. Gate evidence is
recorded in the Task 9 commit message.
