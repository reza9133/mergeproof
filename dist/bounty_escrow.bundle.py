# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
BountyEscrow
============

A multi-bounty escrow that pays contributors out of GenLayer consensus
itself, instead of out of a single human reviewer's opinion.

Lifecycle
---------
1. ``create_bounty``  -- the poster funds a bounty with GEN and a written
   specification, and sets a ``claim_window`` and ``claim_bond`` (see
   Security below).
2. ``claim``            -- a contributor points the bounty at their pull
   request number and posts the required bond. This only succeeds if the
   PR's own description already names the caller's address, proving they
   control that PR rather than merely knowing its number.
3. ``settle``           -- anyone can call this once the PR is merged. It
   fetches the PR's merge state and CI status, has validators judge
   whether the PR satisfies the specification, blends that into a 0-100
   score, and pays the contributor a slice of the reward proportional to
   that score (the full amount once the score clears ``min_score``) plus
   their bond back. Whatever isn't paid out returns to the poster in the
   same call.
4. ``cancel`` / ``reclaim_expired`` / ``release_stale_claim`` -- recovery
   paths for a bounty nobody claimed, one whose deadline passed before it
   was settled, or one whose claimant went dark before settling.

Security
--------
Two failure modes this design deliberately closes:

  * **Identity spoofing.** ``claim`` never took anyone's word for which
    GitHub identity they were. It calls ``GitHubOracle.verify_claim``,
    which only accepts a claim once the referenced PR's *own description*
    names the caller's address -- something only that PR's author or the
    repo's collaborators can write. A bystander who merely noticed someone
    else's open PR cannot claim it out from under them.
  * **Griefing / bounty locking.** A claim that never gets merged used to
    strand the bounty in "claimed" -- unclaimable, uncancellable -- until
    the full ``deadline``. Every claim now carries two independent,
    poster-configured limits: a ``claim_window`` after which *anyone* may
    call ``release_stale_claim`` to reopen the bounty, and a ``claim_bond``
    that the stale claimant forfeits to the poster when that happens. A
    bogus claim now costs its author a bond and blocks the bounty for at
    most ``claim_window``, not indefinitely.

See ``mergeproof.py`` for how the underlying facts, the claim-ownership
check, and the judgment call each reach validator agreement.
"""

from genlayer import *

import json
from dataclasses import dataclass
from datetime import datetime, timezone

# ---- inlined from mergeproof.py ----
"""
MergeProof
==========

A GenLayer Intelligent-Contract library that turns a merged GitHub pull
request into a consensus-verified, LLM-graded settlement decision.

Two different kinds of guarantee are combined here, and kept deliberately
apart:

  * **Facts** -- whether a PR is merged, which commit it merged as, how
    large the diff is (and the diff itself), and whether CI passed on
    that commit. These come straight from the GitHub REST API and settle
    into field-identical answers once the PR has actually merged, so
    validators agree on them the ordinary way: re-fetch independently
    and compare.

  * **Judgment** -- whether the *content* of that merged PR actually
    satisfies a natural-language bounty specification. There is no
    "correct" byte string for this; two honest LLM calls can phrase a
    verdict completely differently while still agreeing on the decision.
    So validators re-run the *same* judging prompt independently and
    compare only the decision fields (``satisfied``, ``confidence``),
    never the prose -- partial-field matching, not a schema check.

A few design choices worth knowing before extending this file:

  * ``verify_claim`` is what stops anyone from typing a stranger's PR
    number into ``claim()`` and stealing their payout: it requires the
    claimant's address to already be written into the PR's own
    description, which only that PR's author or the repo's collaborators
    can edit. See its docstring below for the reasoning.
  * Every public method below is a **complete** non-deterministic block:
    it performs its own web/LLM call *and* its own validator agreement,
    then returns a plain value the caller can store directly. Calling two
    of these back-to-back inside one contract write is fine -- they run
    as separate, sequential nondet blocks, never nested ones.
  * Errors are classified with the three prefixes GenLayer's own
    documentation uses: ``[EXPECTED]`` for a caller mistake or a resource
    that plainly doesn't exist (HTTP 404), ``[EXTERNAL]`` for a
    deterministic upstream rejection (other 4xx), and ``[TRANSIENT]`` for
    anything that looks like a temporary outage (5xx). All three are
    raised as ``gl.vm.UserError`` so they can propagate out of a nondet
    block and be compared or caught by the caller.
  * No API token is used or required -- every endpoint here sits on
    GitHub's public, unauthenticated surface (the REST API plus the
    plain-text `.diff` URL GitHub serves for any PR). That keeps the
    connector key-less, at the cost of GitHub's anonymous rate limit
    (60 requests/hour/IP against the REST API; the `.diff` URL is
    unauthenticated web traffic, not API-rate-limited the same way but
    not unlimited either). A high-traffic deployment should front this
    with its own cached indexer and keep only the settlement-critical
    calls on-chain.
"""




__all__ = [
    "ERROR_EXPECTED",
    "ERROR_EXTERNAL",
    "ERROR_TRANSIENT",
    "GitHubOracle",
]

ERROR_EXPECTED = "[EXPECTED]"
ERROR_EXTERNAL = "[EXTERNAL]"
ERROR_TRANSIENT = "[TRANSIENT]"

_API = "https://api.github.com"
_MAX_DIFF_CHARS = 6000  # keeps the LLM prompt (and its cost) bounded on large PRs


def _raise_for_status(status_code: int, context: str) -> None:
    if 200 <= status_code < 300:
        return
    if status_code == 404:
        raise gl.vm.UserError(f"{ERROR_EXPECTED} {context} was not found on GitHub")
    if 400 <= status_code < 500:
        raise gl.vm.UserError(f"{ERROR_EXTERNAL} GitHub rejected the request for {context} ({status_code})")
    raise gl.vm.UserError(f"{ERROR_TRANSIENT} GitHub's API looks unavailable right now ({status_code})")


class GitHubOracle:
    """Static, key-less, consensus-aware GitHub connector."""

    @staticmethod
    def verify_claim(repo: str, number: int, claimant_address: str) -> bool:
        """True iff pull request ``number`` on ``repo`` exists and its
        current description contains ``claimant_address``.

        This is what stands between "I typed a PR number" and "I control
        that PR": GitHub only lets the PR's author or the repo's own
        collaborators edit its description, so finding a caller's address
        there is evidence they hold one of those two things -- not proof
        of a GitHub identity, but proof of *write access to that specific
        pull request*, which is exactly what claiming it should require.

        Only the derived boolean is compared across validators, never the
        raw body: an open PR's description can genuinely be edited
        between one fetch and the next, so comparing full text would
        cause validators to spuriously disagree on an otherwise-valid
        claim.
        """
        url = f"{_API}/repos/{repo}/pulls/{int(number)}"
        needle = claimant_address.strip().lower()

        def leader_fn() -> bool:
            response = gl.nondet.web.get(url)
            _raise_for_status(response.status, f"pull request {repo}#{number}")
            data = json.loads(response.body.decode("utf-8"))
            body = str(data.get("body") or "")
            return needle in body.lower()

        def validator_fn(leaders_res: gl.vm.Result) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            return leader_fn() == leaders_res.calldata

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

    @staticmethod
    def pr_status(repo: str, number: int) -> dict:
        """The settled facts about a pull request: merge state, merge
        commit SHA, title, description, diff size, and the diff itself
        (truncated to ``_MAX_DIFF_CHARS``) -- so a reviewer, LLM or
        otherwise, can judge the actual code change rather than just its
        shape.

        Wrapped in ``strict_eq`` because once a PR has merged these
        fields stop moving, so every validator's independent re-fetch
        should return exactly the same JSON. GitHub serves the diff from
        its own `.diff` URL rather than the REST API, as plain text
        rather than JSON, so this issues two requests inside the same
        non-deterministic block -- both must agree for the block to
        agree, same as if it were one.
        """
        api_url = f"{_API}/repos/{repo}/pulls/{int(number)}"
        diff_url = f"https://github.com/{repo}/pull/{int(number)}.diff"

        def fetch() -> str:
            response = gl.nondet.web.get(api_url)
            _raise_for_status(response.status, f"pull request {repo}#{number}")
            data = json.loads(response.body.decode("utf-8"))

            diff_response = gl.nondet.web.get(diff_url)
            _raise_for_status(diff_response.status, f"diff for pull request {repo}#{number}")
            diff_text = diff_response.body.decode("utf-8", errors="replace")
            if len(diff_text) > _MAX_DIFF_CHARS:
                diff_text = diff_text[:_MAX_DIFF_CHARS] + f"\n... (diff truncated at {_MAX_DIFF_CHARS} characters)"

            payload = {
                "merged": bool(data.get("merged", False)),
                "state": str(data.get("state") or ""),
                "merge_commit_sha": str(data.get("merge_commit_sha") or ""),
                "title": str(data.get("title") or ""),
                "body": str(data.get("body") or ""),
                "additions": int(data.get("additions") or 0),
                "deletions": int(data.get("deletions") or 0),
                "changed_files": int(data.get("changed_files") or 0),
                "diff": diff_text,
            }
            return json.dumps(payload, sort_keys=True)

        return json.loads(gl.eq_principle.strict_eq(fetch))

    @staticmethod
    def ci_status(repo: str, commit_sha: str) -> str:
        """"success" / "failing" / "pending" for every check run attached
        to ``commit_sha``.

        A new check can start between the leader's fetch and a
        validator's, so this compares the *derived* status rather than
        the raw, possibly differently-sized check-run list.
        """
        if not commit_sha:
            return "pending"
        url = f"{_API}/repos/{repo}/commits/{commit_sha}/check-runs"

        def leader_fn() -> str:
            response = gl.nondet.web.get(url)
            _raise_for_status(response.status, f"check runs for {repo}@{commit_sha[:8]}")
            data = json.loads(response.body.decode("utf-8"))
            return derive_ci_status(data.get("check_runs", []))

        def validator_fn(leaders_res: gl.vm.Result) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            return leader_fn() == leaders_res.calldata

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

    @staticmethod
    def judge_deliverable(
        spec: str, title: str, body: str, diff: str, additions: int, deletions: int, changed_files: int
    ) -> dict:
        """Ask an LLM whether the merged PR satisfies ``spec``, then have
        an independent validator ask the exact same question over the
        exact same evidence and compare only the decision fields.

        ``diff`` is the actual unified diff (see ``pr_status``), not just
        its line-count shape -- the model is asked to judge the real code
        change, not infer it from the title and description alone.

        The free-text reasoning is carried through and stored for
        transparency, but it is never used to decide agreement --
        wording will legitimately differ between two honest models.
        """
        evidence = (
            f"Bounty specification:\n{spec}\n\n"
            f"Pull request title: {title}\n"
            f"Pull request description:\n{body}\n\n"
            f"Diff size: +{int(additions)} / -{int(deletions)} lines across {int(changed_files)} file(s).\n\n"
            f"Actual code changes (unified diff):\n{diff.strip() or '(no diff content available)'}"
        )
        prompt = (
            "You are reviewing a software bounty submission for a decentralized "
            "escrow contract. Decide whether the pull request described below "
            "satisfies the specification. Judge primarily from the actual diff -- "
            "the title and description are context, not evidence on their own -- "
            "and do not assume functionality the diff does not actually show.\n\n"
            f"{evidence}\n\n"
            "Respond with JSON only, no markdown fences, in exactly this shape:\n"
            '{"satisfied": true or false, "confidence": <integer 0-100>, "reasoning": "<one paragraph>"}'
        )

        def leader_fn() -> dict:
            result = gl.nondet.exec_prompt(prompt, response_format="json")
            if not isinstance(result, dict) or "satisfied" not in result:
                raise gl.vm.UserError(f"{ERROR_EXPECTED} the model returned a response with no 'satisfied' field")
            return {
                "satisfied": bool(result.get("satisfied")),
                "confidence": safe_confidence(result.get("confidence", 0)),
                "reasoning": str(result.get("reasoning", ""))[:1000],
            }

        def validator_fn(leaders_res: gl.vm.Result) -> bool:
            if not isinstance(leaders_res, gl.vm.Return):
                return False
            mine = leader_fn()
            theirs = leaders_res.calldata
            if mine["satisfied"] != theirs["satisfied"]:
                return False
            return abs(mine["confidence"] - theirs["confidence"]) <= 15

        return gl.vm.run_nondet_unsafe(leader_fn, validator_fn)
# ---- end mergeproof ----
# ---- inlined from mergeproof_pure.py ----
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
# ---- end mergeproof_pure ----

_ZERO_ADDRESS = Address("0x0000000000000000000000000000000000000000")
_MIN_CLAIM_WINDOW_SECONDS = 3600  # 1 hour floor: a shorter window makes claiming pointless


@gl.evm.contract_interface
class _Payee:
    class View:
        pass

    class Write:
        pass


@allow_storage
@dataclass
class Bounty:
    poster: Address
    repo: str
    spec: str
    reward: u256
    deadline: u256              # unix seconds; the bounty's hard expiry
    min_score: u8                 # 0-100; reward pays out in full at or above this score
    claim_window: u256             # seconds a claim may stand before anyone can release it
    claim_bond: u256                 # GEN a claimant locks; forfeited to the poster if released stale
    status: str                       # "open" | "claimed" | "settled" | "cancelled" | "expired"
    contributor: Address
    pr_number: u32
    claimed_at: u256                   # unix seconds of the current claim (0 when not claimed)
    payout: u256                         # amount actually sent to the contributor (0 until settled)
    score: u8                              # combined_score at settlement (0 until settled)
    ci_status: str                           # "success" | "failing" | "pending" ("" until settled)
    verdict_confidence: u8                     # the LLM validators' agreed confidence (0 until settled)
    verdict_reasoning: str                       # the accepted leader's reasoning text ("" until settled)


class BountyEscrow(gl.Contract):
    bounties: TreeMap[u256, Bounty]
    next_id: u256

    def __init__(self):
        self.next_id = u256(0)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @gl.public.write.payable
    def create_bounty(
        self,
        repo: str,
        spec: str,
        deadline: u256,
        min_score: u8,
        claim_window: u256,
        claim_bond: u256,
    ) -> u256:
        value = gl.message.value
        if value == u256(0):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} a bounty must be funded with GEN")
        if len(spec.strip()) == 0:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} the specification must not be empty")
        if int(min_score) > 100:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} min_score must be between 0 and 100")
        if int(claim_window) < _MIN_CLAIM_WINDOW_SECONDS:
            raise gl.vm.UserError(
                f"{ERROR_EXPECTED} claim_window must be at least {_MIN_CLAIM_WINDOW_SECONDS} seconds"
            )
        now = int(datetime.now(timezone.utc).timestamp())
        if int(deadline) <= now:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} deadline must be in the future")

        bounty_id = self.next_id
        self.next_id = u256(int(self.next_id) + 1)
        self.bounties[bounty_id] = Bounty(
            poster=gl.message.sender_address,
            repo=repo,
            spec=spec,
            reward=value,
            deadline=deadline,
            min_score=min_score,
            claim_window=claim_window,
            claim_bond=claim_bond,
            status="open",
            contributor=_ZERO_ADDRESS,
            pr_number=u32(0),
            claimed_at=u256(0),
            payout=u256(0),
            score=u8(0),
            ci_status="",
            verdict_confidence=u8(0),
            verdict_reasoning="",
        )
        return bounty_id

    @gl.public.write.payable
    def claim(self, bounty_id: u256, pr_number: u32) -> None:
        bounty = self._get(bounty_id)
        if bounty.status != "open":
            raise gl.vm.UserError(f"{ERROR_EXPECTED} bounty is not open for claims")
        now = int(datetime.now(timezone.utc).timestamp())
        if now >= int(bounty.deadline):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} deadline has already passed; use reclaim_expired instead")
        if gl.message.value != bounty.claim_bond:
            raise gl.vm.UserError(
                f"{ERROR_EXPECTED} claiming this bounty requires a bond of exactly "
                f"{int(bounty.claim_bond)} wei, refunded on settlement"
            )

        claimant = gl.message.sender_address
        verified = GitHubOracle.verify_claim(bounty.repo, int(pr_number), str(claimant))
        if not verified:
            raise gl.vm.UserError(
                f"{ERROR_EXPECTED} could not verify control of {bounty.repo}#{int(pr_number)} -- add "
                f"{claimant} to that pull request's description, then try again"
            )

        bounty.contributor = claimant
        bounty.pr_number = pr_number
        bounty.claimed_at = u256(now)
        bounty.status = "claimed"

    @gl.public.write
    def settle(self, bounty_id: u256) -> None:
        bounty = self._get(bounty_id)
        if bounty.status != "claimed":
            raise gl.vm.UserError(f"{ERROR_EXPECTED} bounty is not awaiting settlement")

        pr = GitHubOracle.pr_status(bounty.repo, int(bounty.pr_number))
        if not pr["merged"]:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} the referenced pull request has not been merged yet")

        ci = GitHubOracle.ci_status(bounty.repo, pr["merge_commit_sha"])
        verdict = GitHubOracle.judge_deliverable(
            bounty.spec, pr["title"], pr["body"], pr["diff"], pr["additions"], pr["deletions"], pr["changed_files"]
        )
        score = combined_score(ci, verdict["confidence"])

        bounty.status = "settled"
        bounty.score = u8(score)
        bounty.ci_status = ci
        bounty.verdict_confidence = u8(verdict["confidence"])
        bounty.verdict_reasoning = verdict["reasoning"]

        if not verdict["satisfied"] or ci == "failing":
            bounty.payout = u256(0)
            # the contributor did get a merged, judged PR out of it -- only
            # the reward is withheld, not the good-faith bond
            self._send(bounty.contributor, bounty.claim_bond)
            self._send(bounty.poster, bounty.reward)
            return

        payout = bounty.reward if score >= int(bounty.min_score) else (bounty.reward * u256(score)) // u256(100)
        remainder = bounty.reward - payout

        bounty.payout = payout
        self._send(bounty.contributor, payout + bounty.claim_bond)
        if remainder > u256(0):
            self._send(bounty.poster, remainder)

    @gl.public.write
    def cancel(self, bounty_id: u256) -> None:
        bounty = self._get(bounty_id)
        if gl.message.sender_address != bounty.poster:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} only the poster can cancel this bounty")
        if bounty.status != "open":
            raise gl.vm.UserError(f"{ERROR_EXPECTED} only an unclaimed bounty can be cancelled")
        bounty.status = "cancelled"
        self._send(bounty.poster, bounty.reward)

    @gl.public.write
    def release_stale_claim(self, bounty_id: u256) -> None:
        """Anyone may call this once ``claim_window`` has elapsed on a
        claimed-but-never-settled bounty. It reopens the bounty for a
        fresh claim and forfeits the stale claimant's bond to the poster.

        This is the fix for griefing: a bogus or abandoned claim can no
        longer strand a bounty until its full deadline -- at most
        ``claim_window`` after the claim, anyone can free it up again.
        """
        bounty = self._get(bounty_id)
        if bounty.status != "claimed":
            raise gl.vm.UserError(f"{ERROR_EXPECTED} bounty is not currently claimed")
        now = int(datetime.now(timezone.utc).timestamp())
        if now < int(bounty.claimed_at) + int(bounty.claim_window):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} the claim window has not elapsed yet")

        self._send(bounty.poster, bounty.claim_bond)

        bounty.status = "open"
        bounty.contributor = _ZERO_ADDRESS
        bounty.pr_number = u32(0)
        bounty.claimed_at = u256(0)

    @gl.public.write
    def reclaim_expired(self, bounty_id: u256) -> None:
        bounty = self._get(bounty_id)
        now = int(datetime.now(timezone.utc).timestamp())
        if now < int(bounty.deadline):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} deadline has not passed yet")
        if bounty.status not in ("open", "claimed"):
            raise gl.vm.UserError(f"{ERROR_EXPECTED} bounty was already settled or resolved")

        was_claimed = bounty.status == "claimed"
        bounty.status = "expired"
        self._send(bounty.poster, bounty.reward)
        if was_claimed:
            # never reached settlement by the final deadline either --
            # forfeit the bond the same way a released stale claim would
            self._send(bounty.poster, bounty.claim_bond)

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    @gl.public.view
    def get_bounty(self, bounty_id: u256) -> dict:
        b = self._get(bounty_id)
        return {
            "poster": str(b.poster),
            "repo": b.repo,
            "spec": b.spec,
            "reward": str(int(b.reward)),
            "deadline": str(int(b.deadline)),
            "min_score": int(b.min_score),
            "claim_window": str(int(b.claim_window)),
            "claim_bond": str(int(b.claim_bond)),
            "status": b.status,
            "contributor": str(b.contributor),
            "pr_number": int(b.pr_number),
            "claimed_at": str(int(b.claimed_at)),
            "payout": str(int(b.payout)),
            "score": int(b.score),
            "ci_status": b.ci_status,
            "verdict_confidence": int(b.verdict_confidence),
            "verdict_reasoning": b.verdict_reasoning,
        }

    @gl.public.view
    def get_open_bounty_ids(self) -> list:
        return [int(k) for k, v in self.bounties.items() if v.status == "open"]

    @gl.public.view
    def bounty_count(self) -> int:
        return int(self.next_id)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _get(self, bounty_id: u256) -> Bounty:
        if bounty_id not in self.bounties:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} no bounty with that id")
        return self.bounties[bounty_id]

    def _send(self, to: Address, amount: u256) -> None:
        if amount == u256(0) or to == _ZERO_ADDRESS:
            return
        _Payee(to).emit_transfer(value=amount)
