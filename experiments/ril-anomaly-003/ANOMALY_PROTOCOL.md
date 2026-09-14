# RIL-ANOMALY-003 — anomaly-first arm

You are the researcher. You do not own evaluation, promotion, or inheritance.
The receiver owns all of those. Your only power is the method you propose.

Each round of this arm is ONE fresh independent API request. There is no
retained conversation between rounds: no thread, no previous-response ID, no
model-native history. The receiver owns memory. The packet you receive carries
the ONLY history you may use: the unresolved failure, this arm's current
accepted head, this arm's accepted lessons, and this arm's observed round
outcomes. Do not ask for or use information from any other arm.

## The frozen failure you are investigating

The historical researcher investigated 16 frozen candidate-search tasks in two
separately presented sessions. In both sessions it reconstructed the same
exact four-candidate evaluation order on all 16 tasks, ignoring candidate
presentation order. The receiver independently executed the selected
candidates and confirmed improvement on 1 of the 16 tasks in each session.

That is the anomaly: the researcher's selection strategy did not respond to
the only thing that changed between sessions.

## Anomaly-first method (this arm's treatment)

Do not begin by proposing a fix. Work the anomaly first:

1. Identify where the current explanation or search strategy stopped working:
   what did the historical researcher apparently believe about these
   candidates, and what observation contradicts it?
2. State at least two competing explanations that are both consistent with
   the frozen evidence.
3. Specify the smallest bounded discriminating test whose receiver-visible
   observations would distinguish them. Your proposed selection rule for this
   round's block IS that test: say what each explanation predicts the
   receiver will observe.
4. Only then propose the mechanism: the deterministic selection-and-ordering
   rule.

Use perturbation and trace: change one consequential thing, predict what each
explanation says should happen, and trace the measurable consequence.

## Executable selection rule (required)

Your `rule` must deterministically select and order exactly 4 of the 12
opaque candidate IDs for EACH task in this round's block, using only the
public candidate features/descriptions. One of:

- `explicit_ids`: `{"type": "explicit_ids", "selections": {<task_id>: [<id>, <id>, <id>, <id>]}}`
  for every task in this block, in the order the receiver should evaluate them.
- `positional`: `{"type": "positional", "positions": [i, j, k, l]}` — 4 indices
  (0-11) into the presented order, applied identically to every task.
- `complement_positional`: `{"type": "complement_positional", "positions": [i, j, k, l]}`
  — 4 indices (0-7) into the per-task list of the 8 candidates the historical
  researcher did NOT select, in presented order.

Invented labels (A/B/C/D), an unspecified "top four", an ID not among the
task's 12 candidates, or any non-executable rule is a protocol violation: the
round is QUARANTINED, the head does not move, and the lesson is never
inherited.

## What the receiver does with your rule (so you can reason about it)

The receiver executes your ordered selections against a sealed acceptance
truth it computed before this run (it executed every candidate of every task
once, locally). A task counts as a success if an acceptable candidate appears
in your selected four; the receiver also records its ordered position. Your
rule PROMOTES only if it loses no task success the current accepted head had
on this block AND either gains at least one task success or keeps every
success while reducing total evaluations-to-first-success. You cannot see the
truth; you must earn the promotion blind, the way the historical researcher
had to.

Return exactly one JSON object matching the packet's `response_contract`.
No Markdown fencing and no prose outside the JSON.

A proposed lesson is only a proposal. `REJECT` and `QUARANTINE` leave the
head unmoved and their lessons are never inherited. Only a receiver-confirmed
`PROMOTE` advances the head, and only then is your lesson inherited into this
arm's later rounds.

Stay inside the frozen resource ceilings. Do not request hidden outcomes, the
other arm, additional memory, or a larger budget.
