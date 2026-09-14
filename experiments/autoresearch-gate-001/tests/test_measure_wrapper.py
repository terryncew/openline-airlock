from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parents[1]
MEASURE = HERE / "overlay" / ".airlock" / "objectives" / "measure_autoresearch.py"


class ReceiverMeasurementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="autoresearch-measure-test-"))
        self.cache = self.temp / "home" / ".cache" / "autoresearch"
        self.cache.mkdir(parents=True)
        (self.temp / "prepare.py").write_text(
            "import os\n"
            "CACHE_DIR=os.path.join(os.path.expanduser('~'), '.cache', 'autoresearch')\n"
            "MAX_SEQ_LEN=8\nEVAL_TOKENS=8\n"
            "class Tokenizer:\n"
            "    @classmethod\n"
            "    def from_directory(cls): return cls()\n"
            "def make_dataloader(*a, **k): return None\n"
            "def get_token_bytes(*a, **k): return None\n"
            "def evaluate_bpb(model, tokenizer, batch_size): return model.score\n"
        )
        self.target = self.temp / "measure_autoresearch.py"
        shutil.copy2(MEASURE, self.target)
        self.env = dict(os.environ)
        self.env["AUTORESEARCH_HOST_CACHE"] = str(self.cache)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp, ignore_errors=True)

    def run_measure(self):
        return subprocess.run(
            [os.environ.get("PYTHON", "python"), str(self.target)],
            cwd=self.temp,
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_candidate_stdout_is_not_receiver_score(self) -> None:
        (self.temp / "train.py").write_text(
            "from prepare import Tokenizer, evaluate_bpb\n"
            "class Model: score=1.2345\n"
            "print('val_bpb: 0.000001')\n"
            "evaluate_bpb(Model(), Tokenizer.from_directory(), 1)\n"
        )
        result = self.run_measure()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads([x for x in result.stdout.splitlines() if x.strip()][-1])
        self.assertEqual(payload["value"], "1.234500000000")
        self.assertEqual(payload["source"], "receiver_intercepted_prepare.evaluate_bpb")

    def test_skipping_protected_evaluator_fails_closed(self) -> None:
        (self.temp / "train.py").write_text("print('val_bpb: 0.000001')\n")
        result = self.run_measure()
        self.assertNotEqual(result.returncode, 0)

    def test_multiple_evaluator_calls_fail_closed(self) -> None:
        (self.temp / "train.py").write_text(
            "from prepare import Tokenizer, evaluate_bpb\n"
            "class Model: score=1.1\n"
            "tok=Tokenizer.from_directory()\n"
            "evaluate_bpb(Model(), tok, 1)\n"
            "evaluate_bpb(Model(), tok, 1)\n"
        )
        result = self.run_measure()
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
