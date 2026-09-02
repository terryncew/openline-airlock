# SEARCH-004 — Unattended Yield — frozen result

This directory freezes the completed AIRLOCK-SEARCH-004 evidence artifact without rerunning or modifying the experiment.

## Result

- Verdict: `GUIDANCE_YIELD_ADVANTAGE`
- Airlock unattended: 4 distinct verified improvements / $0.6928628 metered experimental spend / 0 maintainer task assignments
- Maintainer-guided Hermes: 4 distinct verified improvements / $0.5813860 metered experimental spend / 4 maintainer task assignments
- Unattended yield: 5.7731 improvements/$
- Guided yield: 6.8801 improvements/$
- Unattended/guided yield ratio: 83.91%
- Frozen parity boundary: unattended must reach at least 85% of guided yield
- Telemetry preflight: $0.049822, recorded separately and excluded from both arm denominators

Interpretation: Airlock removed the developer from task-picking and found the same four distinct verified improvements, but used about 19% more experimental spend than guided Hermes. Autonomous allocation therefore did not earn an economic-superiority claim in SEARCH-004.

## Frozen evidence

- Full Actions artifact: `AIRLOCK-SEARCH-004-result.zip`
- Artifact SHA-256: `1beb2efbd8a82c031b8e453c6873928e32980319627620b107ebaf9d222a212e`
- Canonical result: `SEARCH-004-result.json`
- Canonical result SHA-256: `635d4c9b8887cf1e29815d0ea972e5281a92886a6d40cb691de054e5b812d6cc`
- Terminal receipt: `SEARCH-004-result.receipt.json`
- Included verification key: `SEARCH-004-verification.key`
- Terminal receipt HMAC verification: PASS

The included key reproduces the local Airlock HMAC integrity check for the frozen artifact. It proves the receipt matches the payload sealed by that Airlock installation; it is not a GitHub signature and does not create external authority.

## Claim boundary

SEARCH-004 supports: unattended Airlock removed maintainer task assignment while producing four distinct independently verified improvements under the frozen experiment.

SEARCH-004 does **not** support: unattended allocation was as cheap as or cheaper than maintainer-guided Hermes. The preregistered verdict was `GUIDANCE_YIELD_ADVANTAGE`.

Do not rerun SEARCH-004 to revise this result. Any later allocation experiment requires a new experiment ID.
