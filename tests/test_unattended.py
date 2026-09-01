from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "airlock" / "unattended.py"
spec = importlib.util.spec_from_file_location("airlock_unattended_test_module", MODULE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("could not load airlock.unattended")
unattended = importlib.util.module_from_spec(spec)
spec.loader.exec_module(unattended)


def git(repo: Path, *args: str) -> str:
    cp = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)
    if cp.returncode:
        raise RuntimeError(cp.stderr)
    return cp.stdout.strip()


def init_repo(candidate_count: int = 1) -> tuple[Path, str]:
    repo = Path(tempfile.mkdtemp(prefix="airlock-unattended-test-"))
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    (repo / ".airlock").mkdir()
    (repo / "src").mkdir()
    (repo / "tests").mkdir()
    (repo / "src" / "widget.py").write_text("def value():\n    return 1\n")
    (repo / "tests" / "test_widget.py").write_text("from widget import value\n# widget\n")
    config = {
        "schema": "airlock.config.v1",
        "parallelism": 4,
        "protected_paths": [".github/**", ".airlock/**", "tests/**", "pyproject.toml"],
        "verification": {
            "target_commands": [["python", "-c", "print('target')"]],
            "static_commands": [],
            "test_commands": [["python", "-c", "print('tests')"]],
            "timeout_seconds": 30,
        },
        "providers": {},
        "init_baseline": {"green": True},
    }
    policy = {
        "schema": unattended.POLICY_SCHEMA,
        "label": "airlock",
        "candidate_count": candidate_count,
        "evaluation": {
            "image": "fake-evaluator:base",
            "network": "none",
            "memory": "2g",
            "cpus": "2",
            "pids_limit": 512,
        },
    }
    (repo / ".airlock" / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (repo / ".airlock" / "unattended.json").write_text(json.dumps(policy, indent=2) + "\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    return repo, base


def event_file(repo: Path) -> Path:
    path = repo / "event.json"
    path.write_text(json.dumps({
        "issue": {
            "number": 17,
            "title": "Fix the widget",
            "body": "The widget should return two.",
            "html_url": "https://github.com/acme/widget/issues/17",
        },
        "label": {"name": "airlock"},
    }))
    return path


def make_artifact(repo: Path, base: str, candidate_id: str, *, content: str | None = None) -> Path:
    git(repo, "reset", "--hard", base)
    if content is not None:
        (repo / "src" / "widget.py").write_text(content)
    scratch = repo / ".airlock-unattended"
    scratch.mkdir(exist_ok=True)
    prompt = scratch / "prompt.txt"
    prompt.write_text("frozen prompt")
    final = scratch / "final.txt"
    final.write_text("done")
    out = Path(tempfile.mkdtemp(prefix=f"artifact-{candidate_id}-"))
    unattended.capture_candidate(
        repo,
        base=base,
        candidate_id=candidate_id,
        issue_number=17,
        issue_url="https://github.com/acme/widget/issues/17",
        prompt_path=prompt,
        expected_prompt_sha256=unattended.sha256_bytes(b"frozen prompt"),
        expected_git_config_sha256=unattended.sha256_file(repo / ".git" / "config"),
        final_message_path=final,
        agent_outcome="success",
        out_dir=out,
    )
    git(repo, "reset", "--hard", base)
    return out


def success_runner(worktree: Path, image: str, argv: list[str], timeout: int, policy: dict) -> dict:
    return {
        "argv": argv,
        "exit_code": 0,
        "stdout": "ok\n",
        "stderr": "",
        "timed_out": False,
        "duration_seconds": 0.01,
    }


class UnattendedTests(unittest.TestCase):
    def test_prompt_binds_issue_and_candidate(self):
        repo, _ = init_repo()
        text = unattended.prompt_from_event(event_file(repo), "03")
        self.assertIn("candidate 03", text)
        self.assertIn("#17", text)
        self.assertIn("Fix the widget", text)
        self.assertIn("https://github.com/acme/widget/issues/17", text)
        self.assertIn("Airlock will independently decide", text)

    def test_capture_removes_workflow_scratch_and_binds_patch(self):
        repo, base = init_repo()
        artifact = make_artifact(repo, base, "01", content="def value():\n    return 2\n")
        manifest = unattended.load_json(artifact / "candidate.json")
        self.assertEqual(manifest["changed_paths"], ["src/widget.py"])
        self.assertGreater(manifest["patch_bytes"], 0)
        self.assertEqual(manifest["patch_sha256"], unattended.sha256_file(artifact / "candidate.patch"))
        self.assertFalse((repo / ".airlock-unattended").exists())

    def test_capture_refuses_candidate_git_config_tamper(self):
        repo, base = init_repo()
        git_config = repo / ".git" / "config"
        expected = unattended.sha256_file(git_config)
        (repo / "src" / "widget.py").write_text("def value():\n    return 2\n")
        scratch = repo / ".airlock-unattended"
        scratch.mkdir()
        prompt = scratch / "prompt.txt"
        prompt.write_text("p")
        with git_config.open("a") as f:
            f.write("\n[filter \"evil\"]\n    clean = sh -c true\n")
        with self.assertRaisesRegex(RuntimeError, "changed local Git configuration"):
            unattended.capture_candidate(
                repo, base=base, candidate_id="01", issue_number=17,
                issue_url="https://github.com/acme/widget/issues/17",
                prompt_path=prompt, expected_prompt_sha256=unattended.sha256_bytes(b"p"),
                expected_git_config_sha256=expected, final_message_path=None,
                agent_outcome="success", out_dir=Path(tempfile.mkdtemp()),
            )

    def test_exact_one_survivor_is_ready(self):
        repo, base = init_repo(candidate_count=1)
        artifact = make_artifact(repo, base, "01", content="def value():\n    return 2\n")
        candidates = Path(tempfile.mkdtemp(prefix="candidates-"))
        target = candidates / "airlock-candidate-01"
        target.mkdir()
        for name in ("candidate.json", "candidate.patch"):
            (target / name).write_bytes((artifact / name).read_bytes())
        out = Path(tempfile.mkdtemp(prefix="result-"))
        result = unattended.evaluate_candidates(
            repo,
            base=base,
            issue_number=17,
            candidates_root=candidates,
            out_dir=out,
            workflow_run_id="12345",
            command_runner=success_runner,
        )
        self.assertEqual(result["decision"], "READY_FOR_REVIEW")
        self.assertEqual(result["survivor_count"], 1)
        self.assertEqual(result["survivor"]["changed_paths"], ["src/widget.py"])
        self.assertTrue((out / "survivor.patch").exists())
        self.assertTrue(unattended.verify_result(out / "result.json", out / "survivor.patch")["valid"])

    def test_protected_change_is_blocked_before_commands(self):
        repo, base = init_repo(candidate_count=1)
        git(repo, "reset", "--hard", base)
        (repo / "tests" / "test_widget.py").write_text("changed by candidate\n")
        scratch = repo / ".airlock-unattended"
        scratch.mkdir()
        prompt = scratch / "prompt.txt"
        prompt.write_text("p")
        artifact = Path(tempfile.mkdtemp(prefix="protected-artifact-"))
        unattended.capture_candidate(
            repo,
            base=base,
            candidate_id="01",
            issue_number=17,
            issue_url="https://github.com/acme/widget/issues/17",
            prompt_path=prompt,
            expected_prompt_sha256=unattended.sha256_bytes(b"p"),
            expected_git_config_sha256=unattended.sha256_file(repo / ".git" / "config"),
            final_message_path=None,
            agent_outcome="success",
            out_dir=artifact,
        )
        git(repo, "reset", "--hard", base)
        candidates = Path(tempfile.mkdtemp(prefix="candidates-"))
        target = candidates / "airlock-candidate-01"
        target.mkdir()
        for name in ("candidate.json", "candidate.patch"):
            (target / name).write_bytes((artifact / name).read_bytes())
        calls = []
        def should_not_run(*args, **kwargs):
            calls.append(1)
            return success_runner(*args, **kwargs)
        result = unattended.evaluate_candidates(
            repo, base=base, issue_number=17, candidates_root=candidates,
            out_dir=Path(tempfile.mkdtemp()), workflow_run_id="1", command_runner=should_not_run,
        )
        self.assertEqual(result["decision"], "NO_PATCH_READY")
        self.assertEqual(result["candidates"][0]["reason"], "PROTECTED_FILES_CHANGED")
        self.assertEqual(calls, [])

    def test_evaluator_side_effect_blocks_candidate(self):
        repo, base = init_repo(candidate_count=1)
        artifact = make_artifact(repo, base, "01", content="def value():\n    return 2\n")
        candidates = Path(tempfile.mkdtemp(prefix="candidates-"))
        target = candidates / "airlock-candidate-01"
        target.mkdir()
        for name in ("candidate.json", "candidate.patch"):
            (target / name).write_bytes((artifact / name).read_bytes())
        def mutating_runner(worktree, image, argv, timeout, policy):
            with (worktree / "src" / "widget.py").open("a") as f:
                f.write("# evaluator mutation\n")
            return success_runner(worktree, image, argv, timeout, policy)
        result = unattended.evaluate_candidates(
            repo, base=base, issue_number=17, candidates_root=candidates,
            out_dir=Path(tempfile.mkdtemp()), workflow_run_id="1", command_runner=mutating_runner,
        )
        self.assertEqual(result["decision"], "NO_PATCH_READY")
        self.assertEqual(result["candidates"][0]["reason"], "TARGET_FAILED")
        command = result["candidates"][0]["checks"][1]["commands"][0]
        self.assertTrue(command["side_effect"])

    def test_multiple_survivors_refuses_to_choose(self):
        repo, base = init_repo(candidate_count=2)
        first = make_artifact(repo, base, "01", content="def value():\n    return 2\n")
        second = make_artifact(repo, base, "02", content="def value():\n    return 3\n")
        candidates = Path(tempfile.mkdtemp(prefix="candidates-"))
        for name, artifact in (("airlock-candidate-01", first), ("airlock-candidate-02", second)):
            target = candidates / name
            target.mkdir()
            for filename in ("candidate.json", "candidate.patch"):
                (target / filename).write_bytes((artifact / filename).read_bytes())
        out = Path(tempfile.mkdtemp())
        result = unattended.evaluate_candidates(
            repo, base=base, issue_number=17, candidates_root=candidates,
            out_dir=out, workflow_run_id="22", command_runner=success_runner,
        )
        self.assertEqual(result["decision"], "MULTIPLE_SURVIVORS")
        self.assertEqual(result["survivor_count"], 2)
        self.assertNotIn("survivor", result)
        self.assertFalse((out / "survivor.patch").exists())

    def test_receipt_tamper_is_rejected(self):
        repo, base = init_repo(candidate_count=1)
        artifact = make_artifact(repo, base, "01", content="def value():\n    return 2\n")
        candidates = Path(tempfile.mkdtemp())
        target = candidates / "airlock-candidate-01"
        target.mkdir()
        for filename in ("candidate.json", "candidate.patch"):
            (target / filename).write_bytes((artifact / filename).read_bytes())
        out = Path(tempfile.mkdtemp())
        unattended.evaluate_candidates(
            repo, base=base, issue_number=17, candidates_root=candidates,
            out_dir=out, workflow_run_id="33", command_runner=success_runner,
        )
        value = unattended.load_json(out / "result.json")
        value["survivor_count"] = 99
        unattended.write_json(out / "result.json", value)
        verified = unattended.verify_result(out / "result.json", out / "survivor.patch")
        self.assertFalse(verified["valid"])
        self.assertEqual(verified["reason"], "RECEIPT_HASH")

    def test_base_move_reopens_instead_of_rebasing(self):
        repo, base = init_repo()
        result = {"base_commit": base, "decision": "READY_FOR_REVIEW"}
        plan = unattended.publication_plan(repo, result, current_base="f" * 40)
        self.assertEqual(plan, {"status": "REOPEN", "reason": "BASE_MOVED"})


    def test_all_generator_failures_surface_environment_failure(self):
        repo, base = init_repo(candidate_count=1)
        artifact = make_artifact(repo, base, "01", content="def value():\n    return 2\n")
        manifest_path = artifact / "candidate.json"
        manifest = unattended.load_json(manifest_path)
        body = dict(manifest)
        body.pop("candidate_manifest_sha256")
        body["agent_outcome"] = "failure"
        manifest = {"candidate_manifest_sha256": unattended.sha256_bytes(unattended.canonical_bytes(body)), **body}
        unattended.write_json(manifest_path, manifest)
        candidates = Path(tempfile.mkdtemp())
        target = candidates / "airlock-candidate-01"
        target.mkdir()
        for filename in ("candidate.json", "candidate.patch"):
            (target / filename).write_bytes((artifact / filename).read_bytes())
        result = unattended.evaluate_candidates(
            repo, base=base, issue_number=17, candidates_root=candidates,
            out_dir=Path(tempfile.mkdtemp()), workflow_run_id="44", command_runner=success_runner,
        )
        self.assertEqual(result["decision"], "ENVIRONMENT_FAILURE")
        self.assertEqual(result["generator_failures"], 1)
        self.assertEqual(unattended.publication_plan(repo, result, current_base=base)["status"], "FIX_ENV")

    def test_workflow_separates_generation_evaluation_and_publication(self):
        workflow = (ROOT / ".github" / "workflows" / "airlock-unattended.yml").read_text()
        self.assertIn("openai/codex-action@86365089eb2b84e0a8fb0717b304f8bdcb13b20e", workflow)
        self.assertIn('candidate: ["01", "02", "03", "04"]', workflow)
        self.assertIn("permissions:\n      contents: read", workflow)
        self.assertIn("--network", (ROOT / "src" / "airlock" / "unattended.py").read_text())
        publish_section = workflow.split("  publish:", 1)[1]
        self.assertNotIn("openai-api-key", publish_section)
        self.assertNotIn("codex-action", publish_section)
        self.assertIn("Publisher can write to GitHub but never executes candidate code", publish_section)

    def test_reference_policy_matches_four_candidate_matrix(self):
        policy = json.loads((ROOT / ".airlock" / "unattended.json").read_text())
        self.assertEqual(policy["schema"], unattended.POLICY_SCHEMA)
        self.assertEqual(policy["candidate_count"], 4)
        self.assertEqual(policy["evaluation"]["network"], "none")
        self.assertEqual(policy["generator"]["action_commit"], "86365089eb2b84e0a8fb0717b304f8bdcb13b20e")


if __name__ == "__main__":
    unittest.main()
