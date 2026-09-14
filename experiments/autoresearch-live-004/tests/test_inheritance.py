import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import inheritance


def run(*args, cwd):
    p = subprocess.run(list(args), cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout.strip()


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class InheritanceTests(unittest.TestCase):
    def test_exact_bundle_materializes_only_frozen_a(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "src"
            src.mkdir()
            run("git", "init", "-q", cwd=src)
            run("git", "config", "user.name", "Test", cwd=src)
            run("git", "config", "user.email", "test@example.invalid", cwd=src)
            (src / "README.md").write_text("immutable\n")
            (src / "train.py").write_text("batch = 1\n")
            run("git", "add", ".", cwd=src)
            run("git", "commit", "-q", "-m", "upstream", cwd=src)
            upstream = run("git", "rev-parse", "HEAD", cwd=src)
            readme_blob = run("git", "rev-parse", "HEAD:README.md", cwd=src)

            (src / ".airlock").mkdir()
            (src / ".airlock" / "marker").write_text("receiver overlay\n")
            run("git", "add", ".", cwd=src)
            run("git", "commit", "-q", "-m", "baseline overlay", cwd=src)
            baseline = run("git", "rev-parse", "HEAD", cwd=src)

            (src / "train.py").write_text("batch = 2\n")
            run("git", "add", "train.py", cwd=src)
            run("git", "commit", "-q", "-m", "accepted A", cwd=src)
            accepted_a = run("git", "rev-parse", "HEAD", cwd=src)
            run("git", "branch", "openline/accepted", accepted_a, cwd=src)

            bundle = root / "live003.bundle"
            run("git", "bundle", "create", str(bundle), "--all", cwd=src)

            carrier = root / "carrier"
            run("git", "clone", "-q", str(src), str(carrier), cwd=root)
            run("git", "checkout", "-q", upstream, cwd=carrier)

            airlock = root / "airlock"
            freeze_dir = airlock / "experiments" / "autoresearch-live-003"
            gate_dir = airlock / "experiments" / "autoresearch-gate-001"
            freeze_dir.mkdir(parents=True)
            gate_dir.mkdir(parents=True)
            freeze = {
                "schema": inheritance.FREEZE_SCHEMA,
                "experiment_id": "AUTORESEARCH-LIVE-003",
                "terminal_verdict": "CONFIRMED_LIVE_IMPROVEMENT_PROMOTED",
                "final_accepted_commit": accepted_a,
                "baseline": {"accepted_commit": baseline},
                "confirmation": {"candidate_commit": accepted_a, "decision": "ACCEPT"},
                "protected_integrity": {"status": "MATCH"},
                "artifacts": {"git_bundle": {"sha256": sha256(bundle)}},
            }
            (freeze_dir / "AUTORESEARCH_LIVE_003_FREEZE.json").write_text(json.dumps(freeze))
            manifest = {
                "commit": upstream,
                "blobs": {"README.md": readme_blob},
                "immutable_during_run": ["README.md"],
            }
            (gate_dir / "upstream_manifest.json").write_text(json.dumps(manifest))

            with mock.patch.object(inheritance, "UPSTREAM_PIN", upstream), \
                 mock.patch.object(inheritance, "PREDECESSOR_BASELINE", baseline), \
                 mock.patch.object(inheritance, "INHERITED_A", accepted_a):
                record = inheritance.verify_and_materialize_a(carrier, bundle, airlock)

            self.assertEqual(record["inherited_a_commit"], accepted_a)
            self.assertEqual(record["predecessor_delta_paths"], ["train.py"])
            self.assertEqual(run("git", "rev-parse", "HEAD", cwd=carrier), accepted_a)
            self.assertEqual(run("git", "status", "--porcelain", cwd=carrier), "")
            self.assertTrue(run("git", "remote", "get-url", "--push", "origin", cwd=carrier).startswith("no_push://"))

    def test_freeze_rejects_wrong_terminal_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / inheritance.FREEZE_REL
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "schema": inheritance.FREEZE_SCHEMA,
                "experiment_id": "AUTORESEARCH-LIVE-003",
                "terminal_verdict": "GOVERNANCE_PASS_NO_PROMOTION",
            }))
            with self.assertRaises(RuntimeError):
                inheritance.verify_live003_freeze(root)


if __name__ == "__main__":
    unittest.main()
