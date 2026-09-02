from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airlock.gitops import head
from airlock.harness import fingerprint_harness_set, fingerprint_hermes_harness
from airlock.nightshift import run_nightshift
from airlock.providers import resolve_provider

PYTHON = sys.executable


def sh(*args: str, cwd: Path | None = None) -> str:
    cp = subprocess.run(
        list(args), cwd=cwd, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return cp.stdout.strip()


def make_fake_hermes(path: Path, body: str = "print('ok')\n") -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class HarnessFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_deterministic_and_excludes_secret_or_transient_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="airlock-harness-fp-") as tmp:
            root = Path(tmp)
            home = root / "hermes-home"
            (home / "skills" / "coding").mkdir(parents=True)
            (home / "tools").mkdir()
            (home / "memories").mkdir()
            (home / "sessions").mkdir()
            (home / "logs").mkdir()
            (home / "cache").mkdir()
            (home / "config.yaml").write_text(
                "# local comment\n"
                "model: fake/model\n"
                "max_turns: 12\n"
                "api_key: secret-one\n"
            )
            (home / "SOUL.md").write_text("Be careful and verify work.\n")
            (home / "skills" / "coding" / "SKILL.md").write_text("Run tests before finishing.\n")
            (home / "tools" / "helper.py").write_text("VALUE = 1\n")
            (home / "memories" / "lesson.md").write_text("Prefer small patches.\n")
            (home / ".env").write_text("OPENROUTER_API_KEY=secret-env-one\n")
            (home / "auth.json").write_text('{"token":"secret-auth-one"}\n')
            (home / "state.db").write_bytes(b"database-secret")
            (home / "sessions" / "session.json").write_text('{"prompt":"private"}\n')
            (home / "logs" / "run.log").write_text("private log\n")
            (home / "cache" / "blob.bin").write_bytes(b"cache")

            bindir = root / "bin"
            bindir.mkdir()
            make_fake_hermes(bindir / "hermes")
            env = {
                "HERMES_HOME": str(home),
                "HERMES_COMMIT": "a" * 40,
                "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
            }
            provider = {"command": ["hermes", "-z", "{prompt}"], "pass_env": ["HERMES_HOME"]}

            first = fingerprint_hermes_harness("hermes", provider, env=env)
            second = fingerprint_hermes_harness("hermes", provider, env=env)
            self.assertEqual(first["fingerprint_sha256"], second["fingerprint_sha256"])
            self.assertEqual(first["runtime"]["source_commit"], "a" * 40)
            self.assertEqual(len(first["runtime"]["executable_sha256"]), 64)
            self.assertEqual(first["routing"]["requested_model"], "fake/model")
            self.assertEqual(first["routing"]["requested_model_source"], "config.yaml:model")
            self.assertEqual(first["routing"]["tool_registry"]["tracked_tool_files"], 1)
            self.assertEqual(len(first["routing"]["tool_registry"]["fingerprint_sha256"]), 64)

            serialized = json.dumps(first, sort_keys=True)
            for secret in ("secret-one", "secret-env-one", "secret-auth-one", "database-secret"):
                self.assertNotIn(secret, serialized)
            tracked = {row["path"] for row in first["tracked_files"]}
            self.assertIn("config.yaml", tracked)
            self.assertIn("SOUL.md", tracked)
            self.assertIn("skills/coding/SKILL.md", tracked)
            self.assertIn("tools/helper.py", tracked)
            self.assertIn("memories/lesson.md", tracked)
            self.assertNotIn(".env", tracked)
            self.assertNotIn("auth.json", tracked)
            self.assertNotIn("state.db", tracked)
            self.assertFalse(any(path.startswith("sessions/") for path in tracked))
            self.assertFalse(any(path.startswith("logs/") for path in tracked))

            # Secret rotation, session/log/cache churn, and DB changes do not alter identity.
            (home / ".env").write_text("OPENROUTER_API_KEY=secret-env-two\n")
            (home / "auth.json").write_text('{"token":"secret-auth-two"}\n')
            (home / "state.db").write_bytes(b"new database bytes")
            (home / "sessions" / "session.json").write_text('{"prompt":"different"}\n')
            (home / "logs" / "run.log").write_text("different log\n")
            (home / "cache" / "blob.bin").write_bytes(b"different cache")
            (home / "config.yaml").write_text(
                "model: fake/model\n"
                "max_turns: 12\n"
                "api_key: secret-two\n"
            )
            rotated = fingerprint_hermes_harness("hermes", provider, env=env)
            self.assertEqual(first["fingerprint_sha256"], rotated["fingerprint_sha256"])

            # Tool routing is a first-class part of harness identity.
            old_tool_registry = rotated["routing"]["tool_registry"]["fingerprint_sha256"]
            (home / "tools" / "helper.py").write_text("VALUE = 2\n")
            tool_changed = fingerprint_hermes_harness("hermes", provider, env=env)
            self.assertNotEqual(old_tool_registry, tool_changed["routing"]["tool_registry"]["fingerprint_sha256"])
            self.assertNotEqual(rotated["fingerprint_sha256"], tool_changed["fingerprint_sha256"])

            # A behavior-bearing skill mutation also creates a new harness identity.
            (home / "skills" / "coding" / "SKILL.md").write_text("Run tests, then inspect the diff.\n")
            changed = fingerprint_hermes_harness("hermes", provider, env=env)
            self.assertNotEqual(tool_changed["fingerprint_sha256"], changed["fingerprint_sha256"])

    def test_profile_fingerprints_are_isolated_and_ordered(self) -> None:
        with tempfile.TemporaryDirectory(prefix="airlock-harness-profiles-") as tmp:
            root = Path(tmp)
            base = root / "hermes-home"
            for name, soul in (("worker_a", "favor tests\n"), ("worker_b", "favor benchmarks\n")):
                profile = base / "profiles" / name
                profile.mkdir(parents=True)
                (profile / "SOUL.md").write_text(soul)
            bindir = root / "bin"
            bindir.mkdir()
            make_fake_hermes(bindir / "hermes")
            env = {
                "HERMES_HOME": str(base),
                "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
            }
            config = {
                "providers": {
                    "hermes": {"command": ["hermes", "-z", "{prompt}"], "pass_env": ["HERMES_HOME"]}
                }
            }
            models = ["hermes@worker_a", "hermes@worker_b"]
            providers = [resolve_provider(config, model) for model in models]
            observed = fingerprint_harness_set(models, providers, env=env)
            self.assertEqual([row["hermes_profile"] for row in observed["workers"]], ["worker_a", "worker_b"])
            self.assertNotEqual(
                observed["workers"][0]["fingerprint_sha256"],
                observed["workers"][1]["fingerprint_sha256"],
            )
            repeated = fingerprint_harness_set(models, providers, env=env)
            self.assertEqual(observed["fingerprint_sha256"], repeated["fingerprint_sha256"])

    def test_unobserved_harness_change_fails_before_next_tournament(self) -> None:
        with tempfile.TemporaryDirectory(prefix="airlock-harness-lineage-") as tmp:
            root = Path(tmp)
            (root / ".airlock").mkdir()
            (root / ".airlock" / "config.json").write_text(json.dumps({
                "schema": "airlock.config.v1",
                "providers": {
                    "hermes": {"command": ["hermes", "-z", "{prompt}"], "pass_env": ["HERMES_HOME"]}
                }
            }))
            home = root / "hermes-home"
            home.mkdir()
            (home / "SOUL.md").write_text("state A\n")
            bindir = root / "bin"
            bindir.mkdir()
            make_fake_hermes(bindir / "hermes")
            env = {
                "HERMES_HOME": str(home),
                "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
            }
            calls = []

            def fake_tournament(*args, **kwargs):
                calls.append("spent")
                return {"run_id": f"run-{len(calls)}", "candidates": []}

            def fake_loop(*args, tournament_runner, run_context, **kwargs):
                tournament_runner(root, "first")
                # This mutation happened outside the observed tournament boundary.
                (home / "SOUL.md").write_text("state changed elsewhere\n")
                tournament_runner(root, "second")
                return {"generations": [], "run_context": run_context}

            with mock.patch.dict(os.environ, env, clear=False), mock.patch(
                "airlock.nightshift.run_improvement_loop", side_effect=fake_loop
            ):
                with self.assertRaisesRegex(RuntimeError, "outside an observed Nightshift transition"):
                    run_nightshift(root, tournament_runner=fake_tournament)
            self.assertEqual(calls, ["spent"])


class HarnessLineageReceiptTests(unittest.TestCase):
    def test_signed_generation_receipts_bind_observed_harness_descent(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="airlock-harness-receipt-"))
        try:
            repo = tmp / "repo"
            repo.mkdir()
            sh("git", "init", "-q", str(repo))
            sh("git", "-C", str(repo), "config", "user.name", "Airlock Test")
            sh("git", "-C", str(repo), "config", "user.email", "test@example.invalid")
            (repo / "src").mkdir()
            (repo / "tests").mkdir()
            (repo / ".airlock" / "objectives").mkdir(parents=True)
            (repo / "src" / "value.py").write_text("VALUE = 0\n")
            (repo / "tests" / "check.py").write_text(
                "from src.value import VALUE\nraise SystemExit(0 if isinstance(VALUE, int) and VALUE >= 0 else 1)\n"
            )
            (repo / ".airlock" / "objectives" / "measure.py").write_text(
                "import json\nfrom src.value import VALUE\nprint(json.dumps({'value': VALUE}))\n"
            )
            objective = {
                "schema": "airlock.objective.v1",
                "name": "fixture value",
                "goal": "Increase fixture value by one.",
                "measure": {
                    "command": [PYTHON, ".airlock/objectives/measure.py"],
                    "direction": "maximize", "unit": "points", "repeats": 1,
                    "timeout_seconds": 30, "pass_env": [],
                    "protected_evaluator_paths": [".airlock/objectives/measure.py"],
                },
                "bounds": {"max_generations": 2, "max_changed_files": 2, "max_changed_lines": 20},
                "selection": {
                    "minimum_gain": "1", "complexity_penalty_per_changed_line": "0", "minimum_score_gap": "0"
                },
            }
            (repo / ".airlock" / "objective.json").write_text(json.dumps(objective, indent=2) + "\n")
            config = {
                "schema": "airlock.config.v1", "parallelism": 1,
                "protected_paths": ["tests/**", ".github/**", ".airlock/**", "pyproject.toml"],
                "verification": {
                    "static_commands": [[PYTHON, "-m", "py_compile", "src/value.py"]],
                    "test_commands": [[PYTHON, "tests/check.py"]],
                    "target_commands": [[PYTHON, "tests/check.py"]],
                    "timeout_seconds": 30, "coverage_mode": "changed-module-reference",
                },
                "providers": {
                    "hermes": {"command": ["hermes", "-z", "{prompt}"], "pass_env": ["HERMES_HOME"], "timeout_seconds": 30}
                },
                "init_baseline": {"green": True},
            }
            (repo / ".airlock" / "config.json").write_text(json.dumps(config, indent=2) + "\n")
            (repo / ".gitignore").write_text(
                ".airlock/runs/\n.airlock/records/\n.airlock/improvements/\n.airlock/verification.key\n.airlock/index.json\n"
            )
            sh("git", "add", ".", cwd=repo)
            sh("git", "commit", "-qm", "base", cwd=repo)
            base = head(repo)

            home = tmp / "hermes-home"
            (home / "skills").mkdir(parents=True)
            (home / "config.yaml").write_text("model: fake/model\nmax_turns: 10\n")
            (home / "SOUL.md").write_text("state A\n")
            bindir = tmp / "bin"
            bindir.mkdir()
            hermes = make_fake_hermes(
                bindir / "hermes",
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "home = Path(os.environ['HERMES_HOME'])\n"
                "report = Path(os.environ['AIRLOCK_AGENT_REPORT'])\n"
                "report.write_text(json.dumps({'provider': 'hermes', 'model': 'fake/model'}) + '\\n')\n"
                "skill = home / 'skills' / 'learned' / 'SKILL.md'\n"
                "if not skill.exists():\n"
                "    skill.parent.mkdir(parents=True, exist_ok=True)\n"
                "    skill.write_text('learned harness state B\\n')\n"
                "    Path('src/value.py').write_text('VALUE = 1\\n')\n"
                "print('done')\n",
            )
            self.assertTrue(hermes.exists())
            env = {
                "HERMES_HOME": str(home),
                "HERMES_COMMIT": "b" * 40,
                "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", ""),
            }
            with mock.patch.dict(os.environ, env, clear=False):
                report = run_nightshift(repo, generations=2, agents=1, budget=0.20)

            self.assertEqual(head(repo), base)
            context = report["run_context"]
            self.assertEqual(context["harness_fingerprint_schema"], "airlock.hermes-harness-fingerprint.v1")
            self.assertTrue(context["harness_lineage_complete"])
            self.assertEqual(len(context["harness_lineage"]), 2)
            start = context["starting_harness"]["fingerprint_sha256"]
            first = context["harness_lineage"][0]
            second = context["harness_lineage"][1]
            self.assertEqual(first["parent_harness_fingerprint_sha256"], start)
            self.assertEqual(first["before_fingerprint_sha256"], start)
            self.assertTrue(first["changed"])
            self.assertEqual(
                first["worker_fingerprints_before"]["hermes"],
                context["starting_harness"]["workers"][0]["fingerprint_sha256"],
            )
            self.assertEqual(len(first["attempts"]), 1)
            attempt = first["attempts"][0]
            self.assertEqual(attempt["harness_fingerprint_sha256"], first["worker_fingerprints_before"]["hermes"])
            self.assertEqual(attempt["model_route"]["requested_model"], "fake/model")
            self.assertEqual(attempt["model_route"]["effective_model_observed"], "fake/model")
            self.assertEqual(attempt["model_route"]["effective_model_observation"], "agent_report.model")
            self.assertTrue(attempt["model_route"]["matches_requested"])
            self.assertTrue(first["effective_model_observation_complete"])
            state_b = first["after_fingerprint_sha256"]
            self.assertNotEqual(state_b, start)
            self.assertEqual(second["parent_harness_fingerprint_sha256"], state_b)
            self.assertEqual(second["before_fingerprint_sha256"], state_b)
            self.assertFalse(second["changed"])
            self.assertEqual(second["after_fingerprint_sha256"], state_b)

            report_path = repo / report["report_file"]
            generation1 = json.loads((report_path.parent / "generation-01.json").read_text())["payload"]
            generation2 = json.loads((report_path.parent / "generation-02.json").read_text())["payload"]
            self.assertEqual(generation1["base_commit"], base)
            self.assertEqual(len(generation1["run_context"]["harness_lineage"]), 1)
            self.assertEqual(generation1["run_context"]["harness_lineage"][0]["after_fingerprint_sha256"], state_b)
            self.assertEqual(len(generation2["run_context"]["harness_lineage"]), 2)
            self.assertEqual(generation2["run_context"]["harness_lineage"][1]["before_fingerprint_sha256"], state_b)
            self.assertEqual(generation2["tournament"]["models"], ["hermes"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
