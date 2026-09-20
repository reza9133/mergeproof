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

from genlayer import *

import json

from mergeproof_pure import derive_ci_status, safe_confidence

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
