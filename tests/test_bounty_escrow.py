"""Direct-mode tests for BountyEscrow.

These run the contract's Python source through genlayer-test's in-memory
VM (no Docker, no live network) and use its Foundry-style cheatcodes to
mock the two non-deterministic surfaces the contract touches: the
GitHub REST API and the LLM judgment call.

    pip install genlayer-test
    python scripts/bundle.py
    pytest tests/test_bounty_escrow.py -v

NOTE: genlayer-test's exact call signature for attaching GEN value to a
payable method in direct mode (``value=...`` below) can differ slightly
between package versions -- both ``create_bounty`` and ``claim`` are
payable now, the latter because claiming requires posting a bond. If a
call in this file doesn't match your installed version, check
`genlayer-test --help` or its README and adjust; the pure-logic tests in
test_pure_logic.py carry no such dependency and are the more stable
reference.
"""
import json
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "dist" / "bounty_escrow.bundle.py"

REPO = "octocat/example-repo"
PR_NUMBER = 42
ONE_GEN = 10**18
FAR_FUTURE_DEADLINE = 9_999_999_999
MIN_CLAIM_WINDOW = 3600  # matches _MIN_CLAIM_WINDOW_SECONDS in the contract


@pytest.fixture(scope="session", autouse=True)
def _ensure_bundle():
    """Regenerate dist/bounty_escrow.bundle.py before the suite runs, so
    these tests never drift from the three source files they exercise.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import bundle  # noqa: E402

    bundle.main()
    yield


def _pr_payload(*, claimant, merged=True, satisfied_body=True, additions=120, deletions=8, changed_files=5):
    """A PR body always contains the claimant's address (so `claim()`
    can verify it) unless a test explicitly wants that check to fail.
    """
    body = "This closes the bounty by adding the requested endpoint."
    if satisfied_body:
        body += f" Claiming address: {claimant}"
    return {
        "merged": merged,
        "state": "closed" if merged else "open",
        "merge_commit_sha": "a" * 40,
        "title": "Implement the requested feature",
        "body": body,
        "additions": additions,
        "deletions": deletions,
        "changed_files": changed_files,
    }


DEFAULT_DIFF = (
    "diff --git a/app.py b/app.py\n"
    "index 1111111..2222222 100644\n"
    "--- a/app.py\n"
    "+++ b/app.py\n"
    "@@ -10,6 +10,10 @@\n"
    "+@app.route('/health')\n"
    "+def health():\n"
    "+    return 'ok', 200\n"
)


def _mock_pr(direct_vm, payload, diff_text=DEFAULT_DIFF):
    direct_vm.mock_web(rf"repos/{REPO}/pulls/{PR_NUMBER}", {"status": 200, "body": json.dumps(payload)})
    direct_vm.mock_web(rf"github\.com/{REPO}/pull/{PR_NUMBER}\.diff", {"status": 200, "body": diff_text})


def _mock_ci(direct_vm, ci: str):
    if ci == "pending":
        checks_payload = {"check_runs": []}
    else:
        checks_payload = {
            "check_runs": [{"status": "completed", "conclusion": "success" if ci == "success" else "failure"}]
        }
    direct_vm.mock_web(rf"repos/{REPO}/commits/{'a' * 40}/check-runs", {"status": 200, "body": json.dumps(checks_payload)})


def _mock_verdict(direct_vm, *, satisfied: bool, confidence: int):
    verdict_payload = {"satisfied": satisfied, "confidence": confidence, "reasoning": "matches the specification"}
    direct_vm.mock_llm(r"reviewing a software bounty submission", json.dumps(verdict_payload))


def _create(contract, *, value, claim_window=MIN_CLAIM_WINDOW, claim_bond=0, min_score=70, spec="Add a health-check endpoint returning 200 OK"):
    return contract.create_bounty(
        REPO, spec, FAR_FUTURE_DEADLINE, min_score, claim_window, claim_bond, value=value
    )


# ---------------------------------------------------------------------
# Fix 1: identity spoofing -- claiming requires proof of PR control
# ---------------------------------------------------------------------

def test_claim_fails_without_address_in_pr_description(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.deal(direct_alice, 1_000 * ONE_GEN)
    direct_vm.deal(direct_bob, 1_000 * ONE_GEN)

    with direct_vm.prank(direct_alice):
        contract = direct_deploy(str(BUNDLE))
        bounty_id = _create(contract, value=100 * ONE_GEN)

    # Bob's address is nowhere in the PR body -- he doesn't control it.
    _mock_pr(direct_vm, _pr_payload(claimant=direct_bob, satisfied_body=False))

    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("could not verify control"):
            contract.claim(bounty_id, PR_NUMBER, value=0)

    assert contract.get_bounty(bounty_id)["status"] == "open"


def test_claim_succeeds_once_address_is_in_pr_description(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.deal(direct_alice, 1_000 * ONE_GEN)
    direct_vm.deal(direct_bob, 1_000 * ONE_GEN)

    with direct_vm.prank(direct_alice):
        contract = direct_deploy(str(BUNDLE))
        bounty_id = _create(contract, value=100 * ONE_GEN)

    _mock_pr(direct_vm, _pr_payload(claimant=direct_bob))

    with direct_vm.prank(direct_bob):
        contract.claim(bounty_id, PR_NUMBER, value=0)

    result = contract.get_bounty(bounty_id)
    assert result["status"] == "claimed"
    assert result["pr_number"] == PR_NUMBER


def test_claim_requires_the_exact_bond(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.deal(direct_alice, 1_000 * ONE_GEN)
    direct_vm.deal(direct_bob, 1_000 * ONE_GEN)

    with direct_vm.prank(direct_alice):
        contract = direct_deploy(str(BUNDLE))
        bounty_id = _create(contract, value=100 * ONE_GEN, claim_bond=5 * ONE_GEN)

    _mock_pr(direct_vm, _pr_payload(claimant=direct_bob))

    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("requires a bond"):
            contract.claim(bounty_id, PR_NUMBER, value=0)
        contract.claim(bounty_id, PR_NUMBER, value=5 * ONE_GEN)

    assert contract.get_bounty(bounty_id)["status"] == "claimed"


# ---------------------------------------------------------------------
# Fix 2: griefing -- a stale claim no longer locks funds until deadline
# ---------------------------------------------------------------------

def test_bogus_claim_can_be_released_after_the_claim_window_and_forfeits_its_bond(
    direct_vm, direct_deploy, direct_alice, direct_bob, direct_charlie
):
    direct_vm.deal(direct_alice, 1_000 * ONE_GEN)
    direct_vm.deal(direct_bob, 1_000 * ONE_GEN)
    direct_vm.deal(direct_charlie, 1_000 * ONE_GEN)

    with direct_vm.prank(direct_alice):
        contract = direct_deploy(str(BUNDLE))
        bounty_id = _create(contract, value=100 * ONE_GEN, claim_bond=5 * ONE_GEN)

    # Bob claims with a PR he genuinely controls, then simply never merges it.
    _mock_pr(direct_vm, _pr_payload(claimant=direct_bob))
    with direct_vm.prank(direct_bob):
        contract.claim(bounty_id, PR_NUMBER, value=5 * ONE_GEN)

    claimed_at = int(contract.get_bounty(bounty_id)["claimed_at"])

    # Cancel is blocked while claimed -- this is expected, not a bug.
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("unclaimed bounty"):
            contract.cancel(bounty_id)

    # Before the window elapses, nobody can release the claim.
    still_within_window = datetime.fromtimestamp(claimed_at + 10, tz=timezone.utc).isoformat()
    direct_vm.warp(still_within_window)
    with direct_vm.expect_revert("claim window has not elapsed"):
        contract.release_stale_claim(bounty_id)

    # Once it has, anyone can -- the bounty reopens instead of staying
    # locked until the (far-future) deadline.
    after_window = datetime.fromtimestamp(claimed_at + MIN_CLAIM_WINDOW + 10, tz=timezone.utc).isoformat()
    direct_vm.warp(after_window)
    contract.release_stale_claim(bounty_id)

    reopened = contract.get_bounty(bounty_id)
    assert reopened["status"] == "open"
    assert reopened["contributor"] == "0x0000000000000000000000000000000000000000"
    assert reopened["claimed_at"] == "0"

    # A fresh, legitimate claimant can now take it.
    _mock_pr(direct_vm, _pr_payload(claimant=direct_charlie))
    with direct_vm.prank(direct_charlie):
        contract.claim(bounty_id, PR_NUMBER, value=5 * ONE_GEN)
    assert contract.get_bounty(bounty_id)["status"] == "claimed"


# ---------------------------------------------------------------------
# Settlement (bond refund + payout blending), unaffected by the fixes
# ---------------------------------------------------------------------

def test_settle_prompt_includes_the_actual_diff_not_just_its_shape(direct_vm, direct_deploy, direct_alice, direct_bob):
    """Regression test: judge_deliverable must see the real code change,
    not just title/body/line-counts -- otherwise a correct PR with a
    terse description can be wrongly rejected, and a well-worded PR that
    does nothing can be wrongly accepted.
    """
    direct_vm.deal(direct_alice, 1_000 * ONE_GEN)
    direct_vm.deal(direct_bob, 1_000 * ONE_GEN)

    with direct_vm.prank(direct_alice):
        contract = direct_deploy(str(BUNDLE))
        bounty_id = _create(contract, value=100 * ONE_GEN)

    marker = "GENLAYER_DIFF_MARKER_7f3a"
    distinctive_diff = DEFAULT_DIFF + f"+    # {marker}\n"
    _mock_pr(direct_vm, _pr_payload(claimant=direct_bob, merged=True), diff_text=distinctive_diff)
    with direct_vm.prank(direct_bob):
        contract.claim(bounty_id, PR_NUMBER, value=0)

    _mock_ci(direct_vm, "success")
    # This mock only matches an LLM prompt that actually contains the
    # diff's marker string -- if judge_deliverable stopped passing the
    # diff through, no mock would match and settle() would fail.
    direct_vm.mock_llm(marker, json.dumps({"satisfied": True, "confidence": 88, "reasoning": "diff matches spec"}))
    contract.settle(bounty_id)

    assert contract.get_bounty(bounty_id)["status"] == "settled"


def test_full_payout_on_satisfied_merge(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.deal(direct_alice, 1_000 * ONE_GEN)
    direct_vm.deal(direct_bob, 1_000 * ONE_GEN)

    with direct_vm.prank(direct_alice):
        contract = direct_deploy(str(BUNDLE))
        bounty_id = _create(contract, value=100 * ONE_GEN, claim_bond=5 * ONE_GEN)

    _mock_pr(direct_vm, _pr_payload(claimant=direct_bob, merged=True))
    with direct_vm.prank(direct_bob):
        contract.claim(bounty_id, PR_NUMBER, value=5 * ONE_GEN)

    _mock_ci(direct_vm, "success")
    _mock_verdict(direct_vm, satisfied=True, confidence=90)
    contract.settle(bounty_id)

    result = contract.get_bounty(bounty_id)
    assert result["status"] == "settled"
    assert int(result["payout"]) == 100 * ONE_GEN
    assert result["score"] == 95  # (ci success=100 + confidence 90) // 2
    assert result["ci_status"] == "success"
    assert result["verdict_confidence"] == 90


def test_full_refund_when_the_verdict_is_not_satisfied(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.deal(direct_alice, 1_000 * ONE_GEN)
    direct_vm.deal(direct_bob, 1_000 * ONE_GEN)

    with direct_vm.prank(direct_alice):
        contract = direct_deploy(str(BUNDLE))
        bounty_id = _create(contract, value=50 * ONE_GEN, claim_bond=2 * ONE_GEN)

    _mock_pr(direct_vm, _pr_payload(claimant=direct_bob, merged=True))
    with direct_vm.prank(direct_bob):
        contract.claim(bounty_id, PR_NUMBER, value=2 * ONE_GEN)

    _mock_ci(direct_vm, "success")
    _mock_verdict(direct_vm, satisfied=False, confidence=20)
    contract.settle(bounty_id)

    result = contract.get_bounty(bounty_id)
    assert result["status"] == "settled"
    assert int(result["payout"]) == 0
    assert result["verdict_reasoning"] == "matches the specification"


def test_settle_rejects_an_unmerged_pull_request(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.deal(direct_alice, 1_000 * ONE_GEN)
    direct_vm.deal(direct_bob, 1_000 * ONE_GEN)

    with direct_vm.prank(direct_alice):
        contract = direct_deploy(str(BUNDLE))
        bounty_id = _create(contract, value=10 * ONE_GEN, spec="Fix the bug")

    _mock_pr(direct_vm, _pr_payload(claimant=direct_bob, merged=False))
    with direct_vm.prank(direct_bob):
        contract.claim(bounty_id, PR_NUMBER, value=0)

    with direct_vm.expect_revert("has not been merged yet"):
        contract.settle(bounty_id)


def test_only_the_poster_can_cancel(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.deal(direct_alice, 1_000 * ONE_GEN)

    with direct_vm.prank(direct_alice):
        contract = direct_deploy(str(BUNDLE))
        bounty_id = _create(contract, value=10 * ONE_GEN, spec="Fix the bug")

    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("only the poster"):
            contract.cancel(bounty_id)

    with direct_vm.prank(direct_alice):
        contract.cancel(bounty_id)
        assert contract.get_bounty(bounty_id)["status"] == "cancelled"
