# v0.1 public-run checklist

- Pick a public issue before inspecting swarm outcomes.
- Pin the base commit and Airlock config before dispatch.
- Use the repository's existing independently maintained test/static suite.
- Add target-specific evidence before the run when the repo's general suite does not establish the requested behavior.
- Preserve every candidate commit and disposition, including zero-patch and insufficient-evidence outcomes.
- Preserve agent-reported economics exactly; never convert unknown cost into zero or an estimate presented as measured.
- Keep release/GitHub credentials outside the agent subprocess.
- Publish the admitted receipt and SHA-256.
- If multiple candidates survive, do not choose retrospectively and call it automatic admission.
- If no candidate survives, publish that result.
- Do not edit the evaluator after seeing candidates and present the rerun as the same primary.
