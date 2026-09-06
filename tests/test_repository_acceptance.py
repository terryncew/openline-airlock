from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from airlock.acceptance import discover_acceptance_evidence
from airlock.discovery import protected_patterns
from airlock.sieve import _candidate_base, run_checks, sufficiency_check


def sh(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        list(args),
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


class RepoFixture:
    def __init__(self, files: dict[str, str]):
        self.tmp = Path(tempfile.mkdtemp(prefix="airlock-repo-acceptance-"))
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        sh("git", "init", "-q", cwd=self.repo)
        sh("git", "config", "user.name", "Airlock Test", cwd=self.repo)
        sh("git", "config", "user.email", "test@example.invalid", cwd=self.repo)
        for name, content in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        sh("git", "add", ".", cwd=self.repo)
        sh("git", "commit", "-qm", "base", cwd=self.repo)
        self.base = sh("git", "rev-parse", "HEAD", cwd=self.repo)

    def candidate(self, changes: dict[str, str], message: str) -> str:
        sh("git", "checkout", "-q", self.base, cwd=self.repo)
        for name, content in changes.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        sh("git", "add", "-A", cwd=self.repo)
        sh("git", "commit", "-qm", message, cwd=self.repo)
        return sh("git", "rev-parse", "HEAD", cwd=self.repo)

    def close(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


BASE_SOURCE = '''VALUE = 1
MODE = "strict"
'''

FUNCTIONAL_TEST = '''import unittest
from src.value import VALUE

class ValueTests(unittest.TestCase):
    def test_value_is_integer(self):
        self.assertIsInstance(VALUE, int)

if __name__ == "__main__":
    unittest.main()
'''

JUDGE = '''from pathlib import Path
text = Path("src/value.py").read_text()
raise SystemExit(0 if 'MODE = "strict"' in text else 7)
'''


class RepositoryAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixtures: list[RepoFixture] = []

    def tearDown(self) -> None:
        for fixture in self.fixtures:
            fixture.close()

    def make_repo(self, files: dict[str, str]) -> RepoFixture:
        fixture = RepoFixture(files)
        self.fixtures.append(fixture)
        return fixture

    def test_candidate_base_is_branch_creation_even_after_worker_commits(self):
        fixture = self.make_repo(
            {
                "src/__init__.py": "",
                "src/value.py": BASE_SOURCE,
                "tests/test_value.py": FUNCTIONAL_TEST,
            }
        )
        sh("git", "checkout", "-qb", "airlock/demo/candidate-01", cwd=fixture.repo)
        (fixture.repo / "src/value.py").write_text('VALUE = 2\nMODE = "strict"\n')
        sh("git", "add", "-A", cwd=fixture.repo)
        sh("git", "commit", "-qm", "worker commit one", cwd=fixture.repo)
        (fixture.repo / "notes.txt").write_text("worker commit two\n")
        sh("git", "add", "-A", cwd=fixture.repo)
        sh("git", "commit", "-qm", "worker commit two", cwd=fixture.repo)
        self.assertEqual(_candidate_base(fixture.repo), fixture.base)

    def test_github_actions_constraint_distinguishes_two_functional_passes(self):
        fixture = self.make_repo(
            {
                "src/__init__.py": "",
                "src/value.py": BASE_SOURCE,
                "tests/test_value.py": FUNCTIONAL_TEST,
                "tools/verify_contract.py": JUDGE,
                ".github/workflows/quality.yml": (
                    "name: quality\non:\n  pull_request:\n\njobs:\n  check:\n    steps:\n"
                    "      - run: python -S tools/verify_contract.py\n"
                ),
            }
        )
        noncompliant = fixture.candidate(
            {"src/value.py": 'VALUE = 2\nMODE = "loose"\n'},
            "noncompliant",
        )
        result = run_checks(
            fixture.repo,
            [["python", "-S", "-m", "unittest", "discover", "-s", "tests", "-q"]],
            timeout=30,
            kind="regression",
        )
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=fixture.repo), noncompliant)
        self.assertEqual(result["rule"], "repository_acceptance")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["basis"], "acceptance_command_failed")

        fixture.candidate(
            {"src/value.py": 'VALUE = 2\nMODE = "strict"\n'},
            "compliant",
        )
        result = run_checks(
            fixture.repo,
            [["python", "-S", "-m", "unittest", "discover", "-s", "tests", "-q"]],
            timeout=30,
            kind="regression",
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["repository_acceptance"]["status"], "PASS")
        self.assertTrue(
            any(row.get("kind") == "acceptance" for row in result["commands"])
        )

    @unittest.skipUnless(shutil.which("make"), "make is required for this fixture")
    def test_make_verify_is_repo_owned_acceptance_evidence(self):
        fixture = self.make_repo(
            {
                "src/__init__.py": "",
                "src/value.py": BASE_SOURCE,
                "tests/test_value.py": FUNCTIONAL_TEST,
                "tools/verify_contract.py": JUDGE,
                "Makefile": "verify:\n\tpython -S tools/verify_contract.py\n",
            }
        )
        evidence = discover_acceptance_evidence(fixture.repo, fixture.base)
        self.assertIn(["make", "verify"], evidence["commands"])

        fixture.candidate(
            {"src/value.py": 'VALUE = 3\nMODE = "loose"\n'},
            "bad",
        )
        result = run_checks(
            fixture.repo,
            [["python", "-S", "-m", "unittest", "discover", "-s", "tests", "-q"]],
            timeout=30,
            kind="regression",
        )
        self.assertEqual(result["rule"], "repository_acceptance")
        self.assertEqual(result["status"], "FAIL")

    def test_candidate_cannot_rewrite_the_repo_owned_judge(self):
        fixture = self.make_repo(
            {
                "src/__init__.py": "",
                "src/value.py": BASE_SOURCE,
                "tests/test_value.py": FUNCTIONAL_TEST,
                "tools/verify_contract.py": JUDGE,
                ".github/workflows/quality.yml": (
                    "name: quality\non:\n  pull_request:\n\njobs:\n  check:\n    steps:\n"
                    "      - run: python -S tools/verify_contract.py\n"
                ),
            }
        )
        fixture.candidate(
            {
                "src/value.py": 'VALUE = 4\nMODE = "loose"\n',
                "tools/verify_contract.py": "raise SystemExit(0)\n",
            },
            "rewrite judge",
        )
        result = run_checks(
            fixture.repo,
            [["python", "-S", "-m", "unittest", "discover", "-s", "tests", "-q"]],
            timeout=30,
            kind="regression",
        )
        self.assertEqual(result["rule"], "repository_acceptance")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "tools/verify_contract.py",
            result.get("restored_judge_paths", []),
        )

    def test_unreplayable_repo_evidence_is_needs_evidence_not_survival(self):
        fixture = self.make_repo(
            {
                "src/__init__.py": "",
                "src/value.py": BASE_SOURCE,
                "tests/test_value.py": "from src.value import VALUE\n",
                ".github/workflows/quality-types.yml": (
                    "name: Quality types\non:\n  pull_request:\n\njobs:\n  check:\n    steps:\n"
                    "      - run: pyright --verifytypes demo --ignoreexternal\n"
                ),
            }
        )
        real_which = shutil.which
        with mock.patch(
            "airlock.acceptance.shutil.which",
            side_effect=lambda name: None if name == "pyright" else real_which(name),
        ):
            check = sufficiency_check(
                fixture.repo,
                fixture.base,
                ["src/value.py"],
                ["tests/test_value.py"],
                [],
            )
        self.assertEqual(check["status"], "INSUFFICIENT")
        self.assertEqual(
            check["basis"],
            "unresolved_repository_acceptance_evidence",
        )


    def test_new_project_control_file_cannot_redefine_candidate_acceptance(self):
        fixture = self.make_repo(
            {
                "src/__init__.py": "",
                "src/value.py": BASE_SOURCE,
                "tests/test_value.py": FUNCTIONAL_TEST,
            }
        )
        fixture.candidate(
            {
                "src/value.py": 'VALUE = 5\nMODE = "strict"\n',
                "pyproject.toml": (
                    "[tool.example]\n"
                    "check = \"candidate-defined\"\n"
                ),
            },
            "candidate adds control",
        )
        result = run_checks(
            fixture.repo,
            [["python", "-S", "-m", "unittest", "discover", "-s", "tests", "-q"]],
            timeout=30,
            kind="regression",
        )
        self.assertEqual(result["rule"], "repository_acceptance")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["basis"], "project_control_file_changed")

    def test_new_project_control_file_is_protected_even_if_missing_at_base(self):
        fixture = self.make_repo(
            {
                "src/__init__.py": "",
                "src/value.py": BASE_SOURCE,
                "tests/test_value.py": FUNCTIONAL_TEST,
            }
        )
        patterns = protected_patterns(fixture.repo)
        self.assertIn("pyproject.toml", patterns)
        self.assertIn(".pre-commit-config.yaml", patterns)


if __name__ == "__main__":
    unittest.main()
