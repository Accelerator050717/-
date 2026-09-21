"""Small fictional archives test identity checks without retraining anything."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "frozen_verifier", Path(__file__).resolve().parents[1] / "52_verify_frozen_research.py")
VERIFIER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFIER)
EXPERIMENT = VERIFIER.EXPERIMENT


class FrozenResearchVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

        def write(path, value):
            destination = self.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(value, encoding="utf-8", newline="\n")

        def save(path, value):
            write(path, json.dumps(value, sort_keys=True))

        def record(path):
            full = self.root / path
            return {"path": Path(path).as_posix(), "size_bytes": full.stat().st_size,
                    "sha256": VERIFIER.sha256(full)}

        def manifest(path, paths):
            destination = self.root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=["path", "size_bytes", "sha256"])
                writer.writeheader()
                writer.writerows(record(item) for item in paths)

        self.save = save
        self.write = write
        self.source = Path("training.py")
        write(self.source, "# Fictional source, never executed.\n")
        write("evaluate.py", "# Fictional evaluator, never executed.\n")
        write("data/prices.csv", "date,close\n2020-01-02,100\n")
        write("models/old.joblib", "fictional old model bytes, not a pickle")
        write(EXPERIMENT / "models/new.joblib", "fictional new model bytes, not a pickle")
        write(EXPERIMENT / "scores.csv", "date,score\n2020-01-02,0.1\n")
        write(EXPERIMENT / "labels.csv", "date,label\n2020-01-02,0.2\n")
        write(EXPERIMENT / "training_summary.csv", "year,rows\n2020,5\n")
        write(EXPERIMENT / "PLAN.md", "Fictional fixed plan.\n")
        write("old_results.csv", "return\n0.1\n")
        manifest("old/ARTIFACTS.csv", ["old_results.csv"])

        inputs = {"input_files": {"data/prices.csv": record("data/prices.csv")},
                  "models": [record("models/old.joblib")]}
        save(EXPERIMENT / "INPUT_IDENTITY.json", inputs)
        save(EXPERIMENT / "plan.json", {"input_identity": inputs,
                                         "design_sha256": record(EXPERIMENT / "PLAN.md")["sha256"]})
        training_identity = {"git_head": "fictional-generation-head",
                             "packages": {"not_imported": "0"},
                             "plan_sha256": record(EXPERIMENT / "plan.json")["sha256"],
                             "source_sha256": {"training.py": record("training.py")["sha256"]}}
        save(EXPERIMENT / "TRAINING_IDENTITY.json", training_identity)
        outputs = ["models/new.joblib", "scores.csv", "labels.csv", "training_summary.csv"]
        save(EXPERIMENT / "TRAINING_COMPLETE.json", {
            "new_fits": 1, "reused_models": 1,
            "outputs_sha256": {name: record(EXPERIMENT / name)["sha256"] for name in outputs}})
        evaluation = {
            "plan_sha256": record(EXPERIMENT / "plan.json")["sha256"],
            "source_files": [record("evaluate.py")], "input_identity": inputs,
            "old_artifacts": {"manifest": record("old/ARTIFACTS.csv"), "verified_files": 1},
            "new_signals": ["fictional"], "scenarios": ["cost10"],
        }
        for key, name in [("score_file", "scores.csv"), ("label_file", "labels.csv"),
                          ("training_file", "training_summary.csv"),
                          ("training_complete", "TRAINING_COMPLETE.json"),
                          ("training_identity", "TRAINING_IDENTITY.json")]:
            evaluation[key] = record(EXPERIMENT / name)
        save(EXPERIMENT / "EVALUATION_IDENTITY.json", evaluation)
        evaluation_hash = record(EXPERIMENT / "EVALUATION_IDENTITY.json")["sha256"]
        self.backtest = EXPERIMENT / "backtests/fictional_cost10"
        write(self.backtest / "daily.csv", "date,equity\n2020-01-02,1.0\n")
        save(self.backtest / "complete.json", {"evaluation_identity_sha256": evaluation_hash,
                                                "files": [record(self.backtest / "daily.csv")]})
        save(EXPERIMENT / "evaluation_complete.json", {"evaluation_identity_sha256": evaluation_hash,
                                                        "new_strategy_runs": 1})
        write(EXPERIMENT / "source_snapshot/training.py", (self.root / self.source).read_text())
        save(EXPERIMENT / "SOURCE_SNAPSHOT.json", {"files": training_identity["source_sha256"]})
        manifest(EXPERIMENT / "ARTIFACTS.csv", [self.backtest / "complete.json", self.backtest / "daily.csv"])
        self.git("init", "--quiet")
        self.git("config", "user.email", "fictional-test@example.invalid")
        self.git("config", "user.name", "Fictional test")
        self.git("config", "core.autocrlf", "false")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Fictional archived experiment")
        self.archive = self.git("rev-parse", "HEAD").strip()

    def git(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.root), *arguments], text=True)

    def verify(self):
        return VERIFIER.verify_v11(self.root, self.archive)

    def test_later_commit_is_allowed_and_preserves_generation_identity(self):
        original_identity = (self.root / EXPERIMENT / "TRAINING_IDENTITY.json").read_bytes()
        self.write("README.md", "New documentation; original experiment unchanged.\n")
        self.git("add", "README.md")
        self.git("commit", "--quiet", "-m", "Later documentation")
        report = self.verify()
        self.assertTrue(report["passed"])
        self.assertNotEqual(report["verification"]["git_head"], self.archive)
        self.assertEqual(report["generation"]["git_head"], "fictional-generation-head")
        self.assertEqual(report["generation"]["archived_at_git_commit"], self.archive)
        self.assertFalse(report["verification"]["verifier_matches_current_commit"])
        self.assertIsNone(report["verification"]["verifier_at_current_commit_sha256"])
        self.assertEqual((self.root / EXPERIMENT / "TRAINING_IDENTITY.json").read_bytes(), original_identity)

    def test_changed_current_generation_source_fails_even_when_commit_is_ignored(self):
        self.write(self.source, "# changed source after original generation\n")
        report = self.verify()
        self.assertFalse(report["passed"])
        self.assertTrue(any(row["category"] == "generation_training_source" for row in report["failures"]))

    def test_changed_frozen_input_model_prediction_or_result_fails(self):
        paths = [Path("data/prices.csv"), Path("models/old.joblib"),
                 EXPERIMENT / "models/new.joblib", EXPERIMENT / "scores.csv",
                 self.backtest / "daily.csv"]
        for relative in paths:
            with self.subTest(path=relative):
                path = self.root / relative
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                report = self.verify()
                self.assertFalse(report["passed"])
                self.assertTrue(any(row["path"] == relative.as_posix() for row in report["failures"]))
                path.write_bytes(original)

    def test_missing_local_large_model_does_not_silently_pass(self):
        (self.root / EXPERIMENT / "models/new.joblib").unlink()
        report = self.verify()
        self.assertFalse(report["passed"])
        self.assertTrue(any(row["actual_sha256"] is None for row in report["failures"]))

    def test_rewriting_old_identity_to_current_head_is_rejected(self):
        path = EXPERIMENT / "TRAINING_IDENTITY.json"
        identity = json.loads((self.root / path).read_text())
        identity["git_head"] = self.git("rev-parse", "HEAD").strip()
        self.save(path, identity)
        with self.assertRaisesRegex(ValueError, "differs from the uploaded archive"):
            self.verify()

    def test_verification_does_not_modify_or_create_experiment_files(self):
        def snapshot():
            return {path.relative_to(self.root).as_posix():
                    (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                    for path in self.root.rglob("*")
                    if path.is_file() and ".git" not in path.relative_to(self.root).parts}

        before = snapshot()
        self.assertTrue(self.verify()["passed"])
        self.assertEqual(before, snapshot())


if __name__ == "__main__":
    unittest.main()
