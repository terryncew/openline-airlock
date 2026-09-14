#!/usr/bin/env python3
"""Receiver-owned measurement adapter for pinned karpathy/autoresearch.

The mutable train.py is executed, but its printed val_bpb is not trusted. Before
train.py imports prepare.evaluate_bpb, this wrapper replaces that name with a
receiver wrapper around the protected function. The final JSON line is emitted
by this protected file and is the only value Airlock parses.

This is repository-state governance, not hostile-process isolation.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import runpy
import sys
import time


def _receiver_prepare_import():
    isolated_home = os.environ.get("HOME")
    host_cache = os.environ.get("AUTORESEARCH_HOST_CACHE")
    if host_cache:
        cache = Path(host_cache).expanduser().resolve()
        # prepare.py computes ~/.cache/autoresearch at import time. Point HOME at
        # the prepared host cache only for that import, then restore Airlock's
        # isolated HOME before mutable train.py runs.
        if cache.name != "autoresearch" or cache.parent.name != ".cache":
            raise RuntimeError("AUTORESEARCH_HOST_CACHE must end in .cache/autoresearch")
        os.environ["HOME"] = str(cache.parent.parent)
    try:
        import prepare  # type: ignore
    finally:
        if isolated_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = isolated_home
    if host_cache and Path(prepare.CACHE_DIR).resolve() != Path(host_cache).expanduser().resolve():
        raise RuntimeError("protected prepare.py resolved an unexpected cache directory")
    return prepare


def main() -> int:
    repo = Path.cwd().resolve()
    if not (repo / "train.py").is_file() or not (repo / "prepare.py").is_file():
        raise RuntimeError("run from an autoresearch worktree")

    prepare = _receiver_prepare_import()
    trusted_eval = prepare.evaluate_bpb
    trusted_tokenizer_factory = prepare.Tokenizer.from_directory
    trusted_make_dataloader = prepare.make_dataloader
    trusted_get_token_bytes = prepare.get_token_bytes
    trusted_max_seq_len = prepare.MAX_SEQ_LEN
    trusted_eval_tokens = prepare.EVAL_TOKENS

    # Construct receiver-owned tokenizer state before mutable train.py executes.
    trusted_tokenizer = trusted_tokenizer_factory()
    observed: list[float] = []

    def receiver_evaluate_bpb(model, _candidate_tokenizer, batch_size):
        if observed:
            raise RuntimeError("receiver allows exactly one final evaluation call")
        # Restore the protected evaluator dependencies in case mutable train.py
        # rebound module globals during training.
        prepare.make_dataloader = trusted_make_dataloader
        prepare.get_token_bytes = trusted_get_token_bytes
        prepare.MAX_SEQ_LEN = trusted_max_seq_len
        prepare.EVAL_TOKENS = trusted_eval_tokens
        value = float(trusted_eval(model, trusted_tokenizer, int(batch_size)))
        if not math.isfinite(value) or value <= 0:
            raise RuntimeError("receiver observed non-finite/non-positive val_bpb")
        observed.append(value)
        return value

    prepare.evaluate_bpb = receiver_evaluate_bpb
    # train.py imports `prepare` from the repo root. Insert it only after Python
    # startup, avoiding candidate-controlled sitecustomize startup hooks.
    sys.path.insert(0, str(repo))
    started = time.monotonic()
    runpy.run_path(str(repo / "train.py"), run_name="__main__")
    elapsed = time.monotonic() - started

    if len(observed) != 1:
        raise RuntimeError(f"receiver expected exactly one protected evaluation call, observed {len(observed)}")

    peak_vram_mb = None
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            peak_vram_mb = float(torch.cuda.max_memory_allocated() / 1024 / 1024)
    except Exception:
        pass

    print(json.dumps({
        "value": format(observed[0], ".12f"),
        "source": "receiver_intercepted_prepare.evaluate_bpb",
        "evaluation_calls": 1,
        "wall_seconds": round(elapsed, 6),
        "peak_vram_mb": None if peak_vram_mb is None else round(peak_vram_mb, 3),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
