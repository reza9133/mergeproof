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

from mergeproof import GitHubOracle, ERROR_EXPECTED, ERROR_EXTERNAL, ERROR_TRANSIENT
from mergeproof_pure import combined_score

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
