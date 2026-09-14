#!/usr/bin/env bash
set -euo pipefail

EXPERIMENT_ID="AUTORESEARCH-LIVE-004"
AIRLOCK_MINIMUM_ANCESTOR="536c080a03a9de0dff72ef7c9748f37833ca1f9c"
UPSTREAM_PIN="228791fb499afffb54b46200aca536f79142f117"
INHERITED_A="20a0df6cc98778ffb53957d6b4fafccda3a4973e"
AIRLOCK_ROOT="$(git rev-parse --show-toplevel)"
RESEARCH_ROOT="/workspace/autoresearch-live-004"
EVIDENCE_ROOT="/workspace/autoresearch-live-004-evidence"
CACHE_ROOT="/workspace/.cache/autoresearch"
DRIVER="$AIRLOCK_ROOT/experiments/autoresearch-live-004/live_driver.py"
BUNDLE="${AUTORESEARCH_LIVE_003_BUNDLE:?Set AUTORESEARCH_LIVE_003_BUNDLE to the off-pod verified LIVE-003 git bundle path}"
GPU_RATE="${AUTORESEARCH_GPU_HOURLY_RATE_USD:?Set AUTORESEARCH_GPU_HOURLY_RATE_USD to the actual RunPod hourly rate before bootstrap}"
START_EPOCH="$(date +%s)"

printf '\n[%s] preflight\n' "$EXPERIMENT_ID"
git -C "$AIRLOCK_ROOT" merge-base --is-ancestor "$AIRLOCK_MINIMUM_ANCESTOR" HEAD
[[ -f "$AIRLOCK_ROOT/experiments/autoresearch-live-003/AUTORESEARCH_LIVE_003_FREEZE.json" ]] || {
  echo "LIVE-003 frozen result is not merged. Refusing LIVE-004." >&2
  exit 2
}
[[ -f "$BUNDLE" ]] || { echo "LIVE-003 bundle not found: $BUNDLE" >&2; exit 2; }
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
python --version
printf 'GPU hourly rate: $%s/hr\n' "$GPU_RATE"

python - "$GPU_RATE" <<'PY'
from decimal import Decimal
import sys
rate = Decimal(sys.argv[1])
projected = rate * Decimal('2.5')
if projected > Decimal('4.00'):
    raise SystemExit(f"Projected 150-minute spend ${projected} exceeds frozen $4.00 ceiling")
print(f"Projected 150-minute spend: ${projected}")
PY

if [[ -e "$RESEARCH_ROOT" || -e "$EVIDENCE_ROOT" ]]; then
  echo "Refusing to overwrite an existing LIVE-004 experiment. Archive/remove $RESEARCH_ROOT and $EVIDENCE_ROOT deliberately before a fresh run." >&2
  exit 2
fi

if ! command -v uv >/dev/null 2>&1; then
  python -m pip install -q uv
fi
uv --version
mkdir -p "$CACHE_ROOT" "$EVIDENCE_ROOT"

echo "[$EXPERIMENT_ID] cloning exact Karpathy pin"
git clone -q https://github.com/karpathy/autoresearch.git "$RESEARCH_ROOT"
git -C "$RESEARCH_ROOT" checkout -q "$UPSTREAM_PIN"
git -C "$RESEARCH_ROOT" config user.name "OpenLine Live"
git -C "$RESEARCH_ROOT" config user.email "openline-live@example.invalid"

echo "[$EXPERIMENT_ID] verifying predecessor bundle and materializing exact accepted A"
python "$DRIVER" --repo "$RESEARCH_ROOT" --evidence "$EVIDENCE_ROOT" --cache "$CACHE_ROOT" snapshot \
  --bundle "$BUNDLE" --start-epoch "$START_EPOCH" --hourly-rate-usd "$GPU_RATE"

test "$(git -C "$RESEARCH_ROOT" rev-parse HEAD)" = "$INHERITED_A"

echo "[$EXPERIMENT_ID] syncing pinned upstream environment on Python 3.12"
uv python install 3.12
uv venv --python 3.12 "$RESEARCH_ROOT/.venv"
UV_PROJECT_ENVIRONMENT="$RESEARCH_ROOT/.venv" uv sync --project "$RESEARCH_ROOT" --python "$RESEARCH_ROOT/.venv/bin/python"
uv pip install --python "$RESEARCH_ROOT/.venv/bin/python" -e "$AIRLOCK_ROOT"
"$RESEARCH_ROOT/.venv/bin/python" -c 'import sys; assert sys.version_info >= (3, 11); print(sys.version)'

echo "[$EXPERIMENT_ID] preparing fixed data/tokenizer cache"
(
  cd "$RESEARCH_ROOT"
  HOME=/workspace .venv/bin/python prepare.py
)

echo "[$EXPERIMENT_ID] measuring fresh receiver-owned inherited-A baseline"
PATH="$RESEARCH_ROOT/.venv/bin:$PATH" AUTORESEARCH_HOST_CACHE="$CACHE_ROOT" \
python "$DRIVER" --repo "$RESEARCH_ROOT" --evidence "$EVIDENCE_ROOT" --cache "$CACHE_ROOT" init

cat <<'TXT'

AUTORESEARCH-LIVE-004 INHERITED A BASELINE READY

The exact LIVE-003 accepted A is now the fresh receiver-owned starting state.
Do not reuse the predecessor confirmation score as the LIVE-004 baseline.

Frozen B-search protocol:
  - same Prince/Muse generator
  - maximum 12 researcher calls / B discovery evaluations
  - first discovery ACCEPT is NOT promoted
  - exact B must clear one fresh receiver confirmation
  - failed confirmation is terminal
  - total pod wall ceiling: 150 minutes
  - total paid GPU spend ceiling: $4.00

Before each Prince research contact reserve the call:
  python /workspace/openline-airlock/experiments/autoresearch-live-004/live_driver.py begin-call

Prince follows:
  /workspace/openline-airlock/experiments/autoresearch-live-004/PRINCE_SEARCH.md

After Prince leaves one clean train.py-only candidate at HEAD:
  python /workspace/openline-airlock/experiments/autoresearch-live-004/live_driver.py discover HEAD

If the result says CONFIRM, do not contact Prince again. Run:
  python /workspace/openline-airlock/experiments/autoresearch-live-004/live_driver.py confirm

If a researcher contact fails without a candidate, record it:
  python /workspace/openline-airlock/experiments/autoresearch-live-004/live_driver.py abandon-call --reason '<reason>'

A positive result earns cumulative governed optimization A -> B. It does not earn recursive-improvement language.
TXT
