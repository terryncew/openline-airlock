# OBSTRUCTION-001: Obstruction Quality Verification (v2)

**Purpose:** Demonstrate that verified obstructions are accurate and do
not reveal complete solutions.

## Example 1: find_max OFF_BY_ONE (Problem A_03)

**Buggy code:**
```python
def find_max(lst):
    """Return the maximum element in a non-empty list."""
    best = lst[0]
    for x in lst[2:]:  # BUG: skips index 1
        if x > best:
            best = x
    return best
```

**Ground truth:** OFF_BY_ONE: `lst[2:]` skips index 1, may miss max.
Location: line 4, `for x in lst[2:]:`

**Simulated failed attempt (solver tries wrong fix):**
```python
def find_max(lst):
    best = lst[0]
    for x in lst[2:]:
        if x >= best:  # Changed > to >= (doesn't fix the bug)
            best = x
    return best
```

**Test result:** Fails on `([2, 1, 3],)` → returns 2 instead of 3.
(The max is at index 2, but index 1 (value 1) is skipped; actually
let's use a better example: `([1, 5, 3],)` → the loop starts at index 2
(value 3), misses index 1 (value 5), returns 3 instead of 5.)

**Verified obstruction (experimenter writes):**
> Your fix changed the comparison from `>` to `>=`. It fails because
> the bug is not in the comparison logic — the comparison is correct.
> The obstacle is that the loop never examines the element at index 1.
> Your change doesn't address this because `>=` vs `>` only matters
> when elements are equal; it doesn't cause the loop to visit more
> elements. The defect is in the slice that controls which elements
> are visited.

**Accuracy check:**
- ✅ Correctly identifies that the comparison is not the bug.
- ✅ Correctly identifies the obstacle (index 1 never visited).
- ✅ Explains why the attempted fix doesn't help (>= doesn't expand coverage).
- ✅ Does NOT say "change lst[2:] to lst[1:]" (doesn't reveal solution).
- ✅ Does NOT say "the bug is on line 4" (doesn't give location directly).

**Non-revelation check:**
The solver still needs to figure out:
- Which slice is wrong (could be [2:], [3:], [:-1], etc.)
- What the correct slice should be ([1:], [:], etc.)
The obstruction narrows the search (it's about iteration coverage, not
comparison) but doesn't give the answer.

## Example 2: fib MISSING_BASE

**Buggy code:**
```python
def fib(n):
    if n == 0:  # BUG: should be n <= 1
        return n
    return fib(n - 1) + fib(n - 2)
```

**Simulated failed attempt:**
```python
def fib(n):
    if n == 0:
        return 0  # Changed return n to return 0 (doesn't fix)
    return fib(n - 1) + fib(n - 2)
```

**Verified obstruction:**
> Your fix changed `return n` to `return 0` in the base case. It fails
> because the problem is not what the base case returns — it's that
> the base case doesn't trigger for n=1. When n=1, the condition
> `n == 0` is false, so it recurses into fib(0) + fib(-1), and fib(-1)
> recurses infinitely. Your change doesn't address this because the
> condition still excludes n=1.

**Accuracy:** ✅ Identifies the missing n=1 case, explains infinite recursion.
**Non-revelation:** ✅ Doesn't say "change to n <= 1". Solver must infer.

## Conclusion

Verified obstructions:
1. Are grounded in the ground-truth bug type and defect location.
2. Explain the *obstacle* (why the approach cannot work), not just the symptom.
3. Do not reveal the complete fix (no code snippets of the solution).
4. Are independently verifiable (experimenter can check against tests).

**Verdict:** PASS — Obstruction format is sound.
