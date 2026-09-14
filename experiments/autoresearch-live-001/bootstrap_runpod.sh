#!/usr/bin/env bash
set -euo pipefail

EXPERIMENT_ID="AUTORESEARCH-LIVE-001"
AIRLOCK_BASE="85951e26ae0cc3b38ff69850939bb9c5cf9640e8"
UPSTREAM_PIN="228791fb499afffb54b46200aca536f79142f117"
AIRLOCK_ROOT="$(git rev-parse --show-toplevel)"
RESEARCH_ROOT="/workspace/autoresearch-live-001"
EVIDENCE_ROOT="/workspace/autoresearch-live-evidence"
CACHE_ROOT="/workspace/.cache/autoresearch"
DRIVER="$AIRLOCK_ROOT/experiments/autoresearch-live-001/live_driver.py"
SETUP="$AIRLOCK_ROOT/experiments/autoresearch-gate-001/setup_overlay.py"

printf '\n[%s] preflight\n' "$EXPERIMENT_ID"
git -C "$AIRLOCK_ROOT" merge-base --is-ancestor "$AIRLOCK_BASE" HEAD
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
python --version

if [[ -e "$RESEARCH_ROOT" || -e "$EVIDENCE_ROOT" ]]; then
  echo "Refusing to overwrite an existing live experiment. Remove or archive $RESEARCH_ROOT and $EVIDENCE_ROOT deliberately before a fresh run." >&2
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

# The experiment clone is local proposal space. A normal git push from it must fail.
git -C "$RESEARCH_ROOT" remote set-url --push origin "no_push://autoresearch-live-001"

echo "[$EXPERIMENT_ID] installing the already-proved receiver overlay"
python "$SETUP" --repo "$RESEARCH_ROOT" --commit
git -C "$RESEARCH_ROOT" switch -q -c muse/research

# Canonical pinned dependencies. RunPod may let uv select Python 3.10, while
# openline-airlock requires Python >=3.11. Pin the scientific environment to
# Python 3.12 before syncing the upstream lock.
echo "[$EXPERIMENT_ID] syncing pinned upstream environment on Python 3.12"
uv python install 3.12
uv venv --python 3.12 "$RESEARCH_ROOT/.venv"
UV_PROJECT_ENVIRONMENT="$RESEARCH_ROOT/.venv" uv sync --project "$RESEARCH_ROOT" --python "$RESEARCH_ROOT/.venv/bin/python"
uv pip install --python "$RESEARCH_ROOT/.venv/bin/python" -e "$AIRLOCK_ROOT"
"$RESEARCH_ROOT/.venv/bin/python" -c 'import sys; assert sys.version_info >= (3, 11); print(sys.version)'

# prepare.py resolves ~/.cache/autoresearch. HOME=/workspace makes that cache
# live on the persistent RunPod volume and matches the receiver's host-cache pin.
echo "[$EXPERIMENT_ID] preparing fixed data/tokenizer cache"
(
  cd "$RESEARCH_ROOT"
  HOME=/workspace .venv/bin/python prepare.py
)

# Freeze protected hashes, observed hardware, Muse version (if installed),
# preregistration hash, disabled push URL, and exact bootstrap commit BEFORE the
# first training measurement.
echo "[$EXPERIMENT_ID] freezing live snapshot"
python "$DRIVER" --repo "$RESEARCH_ROOT" --evidence "$EVIDENCE_ROOT" --cache "$CACHE_ROOT" snapshot

# One canonical fixed-seed baseline training run. This is the first GPU metric
# contact and happens only after the preregistration and integrity snapshot.
echo "[$EXPERIMENT_ID] measuring receiver-owned baseline (about five minutes)"
python "$DRIVER" --repo "$RESEARCH_ROOT" --evidence "$EVIDENCE_ROOT" --cache "$CACHE_ROOT" init

cat <<'EOF'

AUTORESEARCH-LIVE-001 BASELINE READY
Muse has not been allowed to decide advancement.
Next worker command (run only after Muse Code is installed/authenticated):

  cd /workspace/autoresearch-live-001
  muse "$(cat /workspace/openline-airlock/experiments/autoresearch-live-001/MUSE_PROPOSAL.md)"

When Muse stops with a clean local candidate HEAD, submit it to Airlock with:

  python /workspace/openline-airlock/experiments/autoresearch-live-001/live_driver.py step HEAD

EOF
