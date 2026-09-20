"""Pure, GenVM-independent helpers for MergeProof.

Nothing in this file touches ``gl.*``, so it can be imported and unit
tested with plain pytest -- no GenVM SDK, no genlayer-test package, no
mocked web/LLM calls required. ``mergeproof.py`` and the bounty contract
import these functions instead of duplicating the logic inline.

This file intentionally carries no runner header and is never deployed
on its own: ``scripts/bundle.py`` inlines it into the final contract.
"""


def derive_ci_status(check_runs: list) -> str:
    """Collapse a list of GitHub check-runs into one of "success",
    "failing" or "pending".

    Deliberately ignores *how many* runs fired or in what order --
    only whether every run that has actually completed also passed.
    A brand new check starting between one validator's fetch and
    another's therefore doesn't flip the derived status back and
    forth; it just keeps things at "pending" until everything settles.
    """
    if not check_runs:
        return "pending"
    for run in check_runs:
        if run.get("status") != "completed":
            return "pending"
        if run.get("conclusion") not in ("success", "neutral", "skipped"):
            return "failing"
    return "success"


def safe_confidence(value) -> int:
    """Coerce an LLM-supplied confidence value into an int on [0, 100].

    Tolerates strings, floats, surrounding whitespace and the odd
    stray percent sign; anything genuinely unparsable becomes 0
    rather than raising and aborting the whole judgment call.
    """
    text = str(value).strip().rstrip("%").strip()
    try:
        parsed = int(round(float(text)))
    except (TypeError, ValueError):
        parsed = 0
    return max(0, min(100, parsed))


def combined_score(ci_status: str, confidence: int) -> int:
    """Blend the deterministic CI signal with the LLM's confidence into
    one 0-100 settlement score.

    A failing CI run caps its half of the score at 0 -- no amount of
    LLM enthusiasm buys back a broken build. A still-pending run caps
    its half at 60, so a bounty can clear a modest ``min_score``
    threshold without being starved forever by a slow pipeline, but
    can never reach full marks before CI has actually gone green.
    """
    ci_component = {"success": 100, "pending": 60, "failing": 0}.get(ci_status, 40)
    llm_component = max(0, min(100, int(confidence)))
    return (ci_component + llm_component) // 2
