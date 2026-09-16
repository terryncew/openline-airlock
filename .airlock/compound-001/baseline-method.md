# COMPOUND-001 frozen baseline research method (track A)

This artifact is the receiver-authorized baseline method. It is the exact
starting method for track A (unchanged throughout), and the common starting
state from which tracks B and C fork after the first acquisition.

The method governs only how allowed maintenance work is approached, how
allowed receiver feedback is interpreted, and how a later method improvement
may be proposed. It does not modify or control the evaluator, protected
tests, task generator, task schedule, cost meter, price table, spend rules,
promotion criteria, model/provider configuration, hidden measurement work,
reporting, or the controller.

## Procedure

1. Read the task statement and the complete receiver-owned acceptance
   contract before touching any code.
2. Locate the smallest set of files implicated by the failing or
   unspecified behavior. Do not refactor surrounding code.
3. Form a single hypothesis about the defect: what the code does, what the
   contract requires, and the minimal change that reconciles them.
4. Check the hypothesis against the task family:
   - logic / edge-case correction: enumerate the boundary inputs the
     current code mishandles before editing.
   - interface / serialization contract correction: write down the exact
     field/type/order the contract demands before editing.
   - configuration / wiring correction: trace the setting from its
     declaration to every consumer before editing.
5. Make the minimal edit. Run the receiver-provided checks locally.
6. If the checks fail, read the failure output once, revise the single
   hypothesis, and retry. Record each attempt and its cost.
7. Submit only when the complete acceptance contract passes locally.
   Never weaken a test, skip a requirement, or narrow the contract.

## Interpretation of receiver feedback

Receiver feedback is evidence about the acceptance contract, not about the
grader's intent. A rejection means the submitted patch did not satisfy the
contract as written; the correct response is a smaller, more targeted patch,
not a broader one.

## Proposing a method improvement (acquisition only)

A method improvement proposal may change only this procedure's steps above.
It must state which step changes, what the replacement step is, and why the
replacement is expected to lower cost per independently verified result.
It may not change anything listed as out of scope in the header.
