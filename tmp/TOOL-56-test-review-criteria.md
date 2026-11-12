# TOOL-56 — per-test review criteria (draft for approval)

A reviewer subagent takes one test class, reads it and the production code it calls, runs it once
alone (`mvn test -Dtest=<Class>`), and gives every test method one verdict with the criteria that
decided it. The suite-wide goal is **all of `mvn test` under 5 seconds**: 796 tests today, so the
average test gets about 6 ms and a whole class about 50 ms.

## Verdicts

| Verdict | Meaning |
|---|---|
| KEEP | Worth its time as it is. |
| SHRINK | The idea is right, but the input is too big or slow: swap a scan for a primitive, cut the iterations, share one setup across the class. |
| REWRITE | Something real is being checked, but the wrong way: change it to an invariant, use the public API instead of internals, or move it into a DSL fixture. |
| MERGE | Another test already covers it. Name that test. |
| MOVE | Valuable, but it does not belong on the default path (a benchmark, or a real-scan check). Tag it `heavy` or move it out of the test source root. |
| DELETE | Not worth keeping. |

Each verdict comes with the measured time, the criteria numbers it rests on, and for REWRITE or
SHRINK a sketch of the replacement in one or two sentences.

## A. What a test should check (keep signals)

1. **States an invariant of the operation, not a value from one run.** The assertion would still
   hold if the algorithm changed but stayed correct. Examples: spherize a cube, and its volume is
   within a tolerance of the sphere's (4/3·π·r³); a remesh keeps the mesh closed and its Euler
   characteristic the same; a smoothing pass doesn't shrink a sphere by more than ε; a boolean
   union's volume is ≤ the sum of the two inputs. Good invariants: conservation (volume, area,
   genus, χ, boundary loop count), idempotence (running it twice gives the same result as running
   it once), symmetry (a mirrored input gives a mirrored output), bounds (the output stays inside
   the hull or the input's bounding box), round trips (export then import, or apply then
   invert), and monotonicity (a bigger parameter gives a bigger or smaller result).
2. **The tolerance is justified.** Each epsilon is written in terms of the input: mesh resolution,
   the tessellation's known error, or the order of a numerical method. If a tolerance was tuned
   until the test passed (`0.0137`) and nothing explains it, the test only pins one run's result
   (→ REWRITE).
3. **Uses the simplest mesh that shows the behaviour, and builds it in DSL.** A single triangle,
   a quad, a cube, a tetrahedron, a low-res UV sphere, a torus for genus 1, a plane with a hole for
   a boundary. Inputs are a few hundred faces at most unless the size is the point of the test.
   Geometry is never built in Java: no hand-filled vertex or face arrays, no builder calls, no
   mesh-construction helpers in the test. It always comes from DSL. A separate `.dsl` fixture file
   is preferred; DSL inlined in the test as a string is acceptable. If the feature under test
   can't be reached from DSL, that is a red flag about the feature, not a reason to build the
   geometry in code. Report it, and say which node or parameter the DSL is missing.
4. **Covers an error case or edge case on purpose.** Degenerate faces, zero-area triangles,
   coincident vertices, non-manifold edges, open boundaries, flipped normals, empty input, a single
   element, views that share no volume. When the operation is meant to refuse an input, the test
   checks for the refusal and its message. Tests like these are worth more than another happy
   path.
5. **Fails for one reason, and its name says which.** A reader can tell what broke from the
   method name and the assertion message alone, without stepping through the code.
6. **Geometry tests reference DSL.** Any test of a geometry or mesh function loads its input from
   DSL: preferably a `.dsl` fixture (`NodeGraphRuntime.executeResource("dsl/fixtures/…")`), so the
   user can open the same case in the app and look at it, or else DSL inlined in the test. A
   geometry test with no DSL → REWRITE: write the fixture and point the test at it.

## B. What disqualifies or demotes a test

7. **It duplicates the code.** The expected value comes from the same formula, loop or helper as
   the production code, so the test can't disagree with it. This includes copying the algorithm
   into a test helper, and computing "expected" by calling the function under test or its sibling
   (→ DELETE, or REWRITE as an invariant from A1).
8. **It reaches into internal state that only the test uses.** It reads or writes package-private
   or `@VisibleForTesting` fields and methods, uses reflection (`setAccessible`), or calls
   accessors that exist only for tests. Check: grep for callers of each member it touches. If the
   class itself and this test are the only callers, the test is pinning an implementation
   (→ REWRITE through the public API, or DELETE, and remove the accessor with it).
9. **It builds geometry in Java, or has no DSL** (the reverse of A3 and A6; flag it every time).
   If the operation it tests has no DSL node or parameter that reaches it, the verdict also
   carries a **DSL GAP** flag naming what is missing. The DSL gaps are collected into their own
   list for the user, since each one means a feature the app can't drive.
10. **It runs on a real scan or production asset** (the crawfish IMG_*, skull, hand, fertility,
    anything under `test/resources/quadlayout` or outside the repo) when a primitive would show
    the same behaviour (→ SHRINK). If what it checks only shows up on a real scan, it's a
    benchmark or a regression probe (→ MOVE, tagged `heavy`).
11. **It takes too long.** Over 50 ms for one method, or over 100 ms for a class, needs a reason
    the reviewer accepts. Check whether the time goes to setup (one `@BeforeAll` shared by every
    test would fix it), input size (→ SHRINK), solver iterations, or I/O.
12. **Its assertions are weak.** It asserts only non-null, only "no exception", only
    `size() > 0`, or nothing at all. It passes for almost any output (→ REWRITE or DELETE).
13. **It's redundant.** Another test already exercises the same path with an equal or stronger
    assertion (→ MERGE).
14. **It depends on order or on the environment.** It relies on statics that other tests leave
    behind (the Platform/GL stand-in, see ENG-39), on wall-clock time, `Thread.sleep`, random
    numbers without a fixed seed, the file system outside `target/`, network access, or
    surefire's run order.
15. **It tests dead or test-only code.** The production code under test has no caller outside the
    tests (→ DELETE both, or flag it for the user).
16. **It's disabled or never runs.** `@Disabled`, excluded by every profile, or misnamed so
    surefire skips it (→ DELETE, or fix it and justify the fix).

## C. Golden / fingerprint tests

17. **Classify every golden.** Is it (a) a fingerprint of a whole pipeline's output, (b) a
    hand-checked reference result, or (c) a regression lock-in for a bug that was fixed? Only (b)
    is worth keeping as is. For (a) and (c), find the invariant from A1 that the golden stands in
    for, and recommend it as the replacement.
18. **Would a correct change break it?** If any change to a float's last bits, the face order or
    the iteration order fails the golden, then the golden blocks valid work (the "not bit
    identical" trap). Record which kind of change would break it. Phase 2 uses that to choose
    between dropping goldens and building an endpoint that hands an agent master's golden for its
    ticket.

## D. Benchmarks (`test/benchmark/`)

19. **Name the performance problem it guards.** Find the ticket or commit that introduced it. If
    that problem is fixed and nothing would regress silently without the benchmark, → DELETE.
20. **Real-mesh benchmarks need a reason** that a primitive can't stand in for (e.g. the scan's
    vertex count is what triggers the slow path). Otherwise → SHRINK to a generated mesh of
    the same size.
21. **Benchmarks still cost compile time.** All 24 classes (4.6k lines) are under the test source
    root, so every build compiles them. Note whether a benchmark could live in its own source set
    or module (overlaps TOOL-14).

## E. Report format per test class

```
<Class> — <class time> ms, <n> tests
  <method>  <time> ms  VERDICT  [criteria #s]  one-line reason
     replacement: <sketch, for REWRITE/SHRINK>   merge-into: <test, for MERGE>
  static-check candidates: <patterns seen here that a lint could catch>
```
