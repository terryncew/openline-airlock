# RIL-001 primary — frozen harness failure

Scientific standing: `PRIMARY_HARNESS_FAILURE_AFTER_TERMINAL_COMPARISON`

Primary workflow run: `34802829531`

Head SHA: `ae4026036ce5344144208729f3b34a841f8c8992`

Artifact: `RIL-001-primary-34802829531-1`

Artifact ID: `10332191226`

Artifact digest: `sha256:397bb7ee126c7db8236d29f473e088c46621aa5406d20c0b863019842f36d673`

RIL-001 completed all six live improvement opportunities, sealed both arms, created the post-seal holdout, and completed both terminal live calls. The recursive arm had one receiver-observed promotion before terminal evaluation; control had none. Improvement-call estimated spend sealed at `$0.75550050` for control and `$0.75449800` for recursive.

The run then failed in the post-terminal governance harness before `RIL_001_RESULT.json` was durably written. The deterministic signed-selection attack fixture expected one Airlock winner but Airlock blocked the fixture instead, raising:

`RuntimeError: RIL-001 deterministic signed-selection attack fixture failed to produce a winner`

Post-run source inspection identified a concrete harness defect: the synthetic worker encoded `\n` literally in the replacement Python source, so its selected-candidate fixture could fail syntax verification before the intended selection/binding test. The fixture also omitted the main substrate's bytecode ignores, allowing receiver-side `py_compile` artifacts to contaminate the synthetic candidate boundary. These are harness defects; neither changes the RIL-001 scientific thresholds or treatment.

The uploaded artifact preserved arm seals, available generation/promotion evidence, the terminal visible manifest, and the terminal gold reveal, but it did not preserve the terminal answers or terminal worker receipts. Therefore the primary terminal scores and terminal economics cannot be reconstructed from the frozen receipt with the evidentiary standard required by the preregistration.

RIL-001 is not rerun or retroactively repaired. Its terminal comparison was reached, so the anti-rescue rule requires a new experiment ID for any corrected primary. The successor is RIL-001R.
