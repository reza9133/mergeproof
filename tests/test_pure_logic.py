"""Plain unit tests for mergeproof_pure.py.

These need nothing beyond pytest itself -- no GenVM SDK, no
genlayer-test package, no network access -- because mergeproof_pure.py
never imports ``genlayer``. Run with:

    pytest tests/test_pure_logic.py -v
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from mergeproof_pure import combined_score, derive_ci_status, safe_confidence


class TestDeriveCiStatus:
    def test_no_runs_is_pending(self):
        assert derive_ci_status([]) == "pending"

    def test_all_successful_is_success(self):
        runs = [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "neutral"},
            {"status": "completed", "conclusion": "skipped"},
        ]
        assert derive_ci_status(runs) == "success"

    def test_any_incomplete_is_pending(self):
        runs = [
            {"status": "completed", "conclusion": "success"},
            {"status": "in_progress", "conclusion": None},
        ]
        assert derive_ci_status(runs) == "pending"

    def test_any_failure_is_failing(self):
        runs = [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "failure"},
        ]
        assert derive_ci_status(runs) == "failing"

    def test_timed_out_run_counts_as_failing(self):
        runs = [{"status": "completed", "conclusion": "timed_out"}]
        assert derive_ci_status(runs) == "failing"


class TestSafeConfidence:
    def test_plain_int(self):
        assert safe_confidence(83) == 83

    def test_numeric_string(self):
        assert safe_confidence("74") == 74

    def test_float_gets_rounded(self):
        assert safe_confidence(88.6) == 89

    def test_percent_sign_is_stripped(self):
        assert safe_confidence(" 91% ") == 91

    def test_clamped_above_100(self):
        assert safe_confidence(250) == 100

    def test_clamped_below_0(self):
        assert safe_confidence(-40) == 0

    def test_garbage_becomes_zero(self):
        assert safe_confidence("not a number") == 0
        assert safe_confidence(None) == 0


class TestCombinedScore:
    def test_success_and_perfect_confidence_is_100(self):
        assert combined_score("success", 100) == 100

    def test_failing_ci_caps_the_score(self):
        # (0 + 100) // 2 == 50, no matter how confident the model is
        assert combined_score("failing", 100) == 50

    def test_pending_ci_caps_below_full_marks(self):
        # (60 + 100) // 2 == 80: never reaches 100 before CI is green
        assert combined_score("pending", 100) == 80

    def test_zero_confidence_with_success_ci(self):
        assert combined_score("success", 0) == 50

    def test_unknown_status_uses_neutral_component(self):
        assert combined_score("something-unrecognized", 100) == 70
