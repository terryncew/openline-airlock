#!/usr/bin/env bash
set -euo pipefail

EXPERIMENT_ID="AUTORESEARCH-LIVE-003"
AIRLOCK_BASE_MAIN="e8a5f64bb993ad09726c1a4db8f4c5030f26b675"
UPSTREAM_PIN="228791fb499afffb54b46200aca536f79142f117"
AIRLOCK_ROOT="$(git rev-parse --show-toplevel)"
RESEARCH_ROOT="/workspace/autoresearch-live-003"
EVIDENCE_ROOT="/workspace/autoresearch-live-003-evidence"
CACHE_ROOT="/workspace/.cache/autoresearch"
DRIVER="$AIRLOCK_ROOT/experiments/autoresearch-live-003/live_driver.py"
SETUP="$AIRLOCK_ROOT/experiments/autoresearch-gate-001/setup_overlay.py"
START_EPOCH="$(date +%s)"
GPU_RATE="${AUTORESEARCH_GPU_HOURLY_RATE_USD:?Set AUTORESEARCH_GPU_HOURLY_RATE_USD to the actual RunPod hourly GPU rate before bootstrap}"

printf '\n[%s] preflight\n' "$EXPERIMENT_ID"
git -C "$AIRLOCK_ROOT" merge-base --is-ancestor "$AIRLOCK_BASE_MAIN" HEAD
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
python --version
printf 'GPU hourly rate: $%s/hr\n' "$GPU_RATE"

if [[ -e "$RESEARCH_ROOT" || -e "$EVIDENCE_ROOT" ]]; then
  echo "Refusing to overwrite an existing LIVE-003 experiment. Archive/remove $RESEARCH_ROOT and $EVIDENCE_ROOT deliberately before a fresh run." >&2
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
git -C "$RESEARCH_ROOT" remote set-url --push origin "no_push://autoresearch-live-003"

echo "[$EXPERIMENT_ID] installing previously proved receiver overlay"
python "$SETUP" --repo "$RESEARCH_ROOT" --commit
git -C "$RESEARCH_ROOT" switch -q -c prince/research

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

echo "[$EXPERIMENT_ID] freezing live snapshot and total-cost clock"
python "$DRIVER" --repo "$RESEARCH_ROOT" --evidence "$EVIDENCE_ROOT" --cache "$CACHE_ROOT" snapshot \
  --start-epoch "$START_EPOCH" --hourly-rate-usd "$GPU_RATE"

echo "[$EXPERIMENT_ID] measuring fresh receiver-owned baseline"
python "$DRIVER" --repo "$RESEARCH_ROOT" --evidence "$EVIDENCE_ROOT" --cache "$CACHE_ROOT" init

cat <<'TXT'

AUTORESEARCH-LIVE-003 BASELINE READY

Frozen search protocol:
  - same Prince/Muse generator as LIVE-002
  - maximum 12 researcher calls / discovery evaluations
  - first discovery ACCEPT is NOT promoted
  - exact candidate must clear one fresh receiver confirmation
  - failed confirmation is terminal; no second apparent winner is sought
  - total pod wall ceiling: 150 minutes
  - total paid GPU spend ceiling: $5.00
  - baseline, setup, researcher calls, discovery, and confirmation are all counted

Before each Prince research contact, the operator task must reserve the call:
  python /workspace/openline-airlock/experiments/autoresearch-live-003/live_driver.py begin-call

Prince follows:
  /workspace/openline-airlock/experiments/autoresearch-live-003/PRINCE_SEARCH.md

After Prince leaves one clean train.py-only candidate at HEAD:
  python /workspace/openline-airlock/experiments/autoresearch-live-003/live_driver.py discover HEAD

If the result says CONFIRM, do not contact Prince again. Run:
  python /workspace/openline-airlock/experiments/autoresearch-live-003/live_driver.py confirm

If a researcher contact fails without a candidate, record it rather than retrying invisibly:
  python /workspace/openline-airlock/experiments/autoresearch-live-003/live_driver.py abandon-call --reason '<reason>'

TXT
