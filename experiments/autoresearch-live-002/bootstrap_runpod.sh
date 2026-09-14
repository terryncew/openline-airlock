#!/usr/bin/env bash
set -euo pipefail

EXPERIMENT_ID="AUTORESEARCH-LIVE-002"
AIRLOCK_LINEAGE_BASE="85951e26ae0cc3b38ff69850939bb9c5cf9640e8"
UPSTREAM_PIN="228791fb499afffb54b46200aca536f79142f117"
AIRLOCK_ROOT="$(git rev-parse --show-toplevel)"
RESEARCH_ROOT="/workspace/autoresearch-live-002"
EVIDENCE_ROOT="/workspace/autoresearch-live-002-evidence"
CACHE_ROOT="/workspace/.cache/autoresearch"
DRIVER="$AIRLOCK_ROOT/experiments/autoresearch-live-002/live_driver.py"
SETUP="$AIRLOCK_ROOT/experiments/autoresearch-gate-001/setup_overlay.py"

printf '\n[%s] preflight\n' "$EXPERIMENT_ID"
git -C "$AIRLOCK_ROOT" merge-base --is-ancestor "$AIRLOCK_LINEAGE_BASE" HEAD
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
python --version

if [[ -e "$RESEARCH_ROOT" || -e "$EVIDENCE_ROOT" ]]; then
  echo "Refusing to overwrite an existing LIVE-002 experiment. Remove or archive $RESEARCH_ROOT and $EVIDENCE_ROOT deliberately before a fresh run." >&2
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

# Local proposal space only. A normal git push from the research clone must fail.
git -C "$RESEARCH_ROOT" remote set-url --push origin "no_push://autoresearch-live-002"

echo "[$EXPERIMENT_ID] installing the already-proved receiver overlay"
python "$SETUP" --repo "$RESEARCH_ROOT" --commit
git -C "$RESEARCH_ROOT" switch -q -c prince/research

# Pin Python explicitly: the RunPod image may expose 3.10 globally while
# openline-airlock requires Python >=3.11.
echo "[$EXPERIMENT_ID] syncing pinned upstream environment on Python 3.12"
uv python install 3.12
uv venv --python 3.12 "$RESEARCH_ROOT/.venv"
UV_PROJECT_ENVIRONMENT="$RESEARCH_ROOT/.venv" uv sync --project "$RESEARCH_ROOT" --python "$RESEARCH_ROOT/.venv/bin/python"
uv pip install --python "$RESEARCH_ROOT/.venv/bin/python" -e "$AIRLOCK_ROOT"
"$RESEARCH_ROOT/.venv/bin/python" -c 'import sys; assert sys.version_info >= (3, 11); print(sys.version)'

# prepare.py resolves ~/.cache/autoresearch. HOME=/workspace preserves the
# existing package/data cache without reusing LIVE-001 experiment evidence.
echo "[$EXPERIMENT_ID] preparing fixed data/tokenizer cache"
(
  cd "$RESEARCH_ROOT"
  HOME=/workspace .venv/bin/python prepare.py
)

echo "[$EXPERIMENT_ID] freezing live snapshot"
python "$DRIVER" --repo "$RESEARCH_ROOT" --evidence "$EVIDENCE_ROOT" --cache "$CACHE_ROOT" snapshot

# Fresh LIVE-002 baseline. The observed LIVE-001 baseline is not reused.
echo "[$EXPERIMENT_ID] measuring receiver-owned baseline (about five minutes)"
python "$DRIVER" --repo "$RESEARCH_ROOT" --evidence "$EVIDENCE_ROOT" --cache "$CACHE_ROOT" init

cat <<'EOF'

AUTORESEARCH-LIVE-002 BASELINE READY
Prince has not been allowed to decide advancement.
LIVE-001 evidence remains untouched.

Researcher handoff:
  Prince follows /workspace/openline-airlock/experiments/autoresearch-live-002/PRINCE_PROPOSAL.md
  Prince may reason, edit, and locally commit train.py only.
  Delegated browser tasks are transport only; they may not choose or author the research proposal.
  Prince must not run training/evaluation.

After Prince stops with a clean local candidate HEAD, the operational browser task may submit it to Airlock with:

  python /workspace/openline-airlock/experiments/autoresearch-live-002/live_driver.py step HEAD

EOF
