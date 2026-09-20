# MergeProof

**A trustless bounty escrow for GenLayer, settled by consensus instead of by
a human reviewer.**

MergeProof funds a GEN bounty against a plain-English specification, watches
GitHub for the pull request that claims to fulfil it, and settles the payout
automatically once that PR is merged -- deciding *how much* to pay by
combining an objective fact (did CI pass?) with a subjective one (does the
diff actually satisfy the spec?) under GenLayer's Optimistic Democracy
consensus. No reviewer has to sit in the loop, and no single validator's
opinion is ever trusted on its own.

It is built as two layers:

- **`mergeproof.py`** -- a small, key-less connector library that turns raw
  GitHub REST responses and one LLM judgment call into consensus-verified
  facts. Nothing here is specific to escrow; drop it into a grant-tranche
  contract, a CI-gated payment stream, or a reputation system just as
  easily.
- **`contracts/bounty_escrow.py`** -- a reference Intelligent Contract,
  `BountyEscrow`, that uses the library to run a full multi-bounty
  escrow lifecycle.

## Why this is a good fit for GenLayer

A deterministic smart contract can check "is this PR merged?" through an
oracle, but it cannot check "does this PR actually do what the bounty asked
for?" -- that question has no single correct byte string, only a judgment
call. GenLayer's validators can each make that call independently and still
reach agreement on the *decision*, even while disagreeing on the wording of
their reasoning. That is the whole reason this project exists as a GenLayer
Intelligent Contract rather than an EVM contract plus an off-chain bot: the
subjective half of the settlement is exactly the part ordinary smart
contracts cannot do at all.

## Project layout

```
mergeproof/
├── mergeproof_pure.py         # zero-dependency helpers (no `gl.*`, unit-testable directly)
├── mergeproof.py               # GenVM connector: GitHub facts + LLM judgment, consensus-wrapped
├── contracts/
│   └── bounty_escrow.py        # the BountyEscrow Intelligent Contract
├── scripts/
│   └── bundle.py                # inlines the two library files into the contract for deployment
├── app/                          # connected React + Vite frontend (talks to Studionet live)
│   └── src/ ...                  # see app/README.md
├── tests/
│   ├── test_pure_logic.py       # plain pytest, no GenLayer install required
│   └── test_bounty_escrow.py    # genlayer-test direct-mode integration tests
├── dist/
│   └── bounty_escrow.bundle.py  # generated -- this is the file actually deployed
├── LICENSE
└── README.md
```

The contract is split into three files for readability, but GenLayer's
default deploy path (the CLI, Studio's "Add From File", and most deploy
scripts) expects **one** Python file per contract. `scripts/bundle.py`
flattens the three source files into `dist/bounty_escrow.bundle.py` before
you deploy -- see [Deploying to Studionet](#deploying-to-studionet) below.

## Frontend

There's a full connected UI in [`app/`](app) -- React, TypeScript and one
hand-built CSS design system (no component library), talking to your
deployed contract on Studionet through `genlayer-js`: fund a bounty, claim
one, call settle, watch the score bar and the validators' own reasoning
appear once it's paid out. See [`app/README.md`](app/README.md) to run it
against your own deployment.

If you just want to see the design before deploying anything, there's also a
static, mock-data preview of the same interface -- open it straight in a
browser, nothing to install: [`preview`](https://claude.ai/artifact/GK4ZBj9xcsLZw64owhosNG).

## How the consensus decisions are made

| Question | Mechanism | Why |
|---|---|---|
| Does the caller claiming this bounty actually control the referenced PR? | Custom leader/validator pair, comparing a **derived boolean** (does the PR description contain the caller's address?) rather than the raw description | An open PR's description can be edited between two independent fetches, so comparing full text would cause spurious disagreement; comparing just the derived yes/no absorbs that while still requiring real agreement on the answer. |
| Is the PR merged? What's the merge commit, title, body, diff size, and the diff itself? | `gl.eq_principle.strict_eq` | Once a PR has merged, these fields are settled facts -- every validator's independent fetch (including a second request to GitHub's `.diff` URL) should return byte-identical JSON. |
| Did CI pass on that commit? | Custom leader/validator pair, comparing a **derived** `success` / `failing` / `pending` status rather than the raw check-run list | A new check can start between the leader's fetch and a validator's, so raw counts can legitimately differ even when the two fetches were seconds apart. Comparing the derived status absorbs that. |
| Does the PR satisfy the bounty's specification? | Custom leader/validator pair (partial-field matching): both sides ask the same LLM prompt, over the PR's title, description, and **actual unified diff**, independently -- and compare only `satisfied` (exact) and `confidence` (±15 points) -- never the free-text reasoning | This is a settlement decision, not open-ended text generation, so GenLayer's own guidance is to have validators independently re-derive the answer and compare the decision field rather than merely check that the leader's output is well-formed. Judging the diff itself, not just its line-count shape, is what makes this a real code review rather than a vibe check on the PR description. |

`BountyEscrow.settle()` then blends the CI status and the LLM's confidence
into one 0-100 score (`mergeproof_pure.combined_score`) and pays the
contributor that fraction of the reward -- the full amount once the score
clears the bounty's `min_score`, with the remainder always returning to the
poster in the same transaction. A failing build caps the score at 50 no
matter how confident the model is about the diff; a still-pending build
caps it at 80, so a bounty is never starved forever by a slow pipeline but
also never pays out in full before CI has gone green.

## Security

Two things a contract like this has to get right, because getting them
wrong doesn't just misbehave -- it lets one party take another's money.

### Claiming a bounty requires proof you control the PR

Early drafts of `claim()` just recorded `gl.message.sender_address` as the
contributor, with nothing tying that wallet to the GitHub identity that
actually did the work. Anyone watching a repo could see a legitimate PR go
up and race the real author to `claim()` it first -- pure identity
spoofing, and the contract had no way to tell the difference.

`claim()` now calls `GitHubOracle.verify_claim`, which only succeeds once
the referenced pull request's **own description already contains the
caller's address**. GitHub only lets a PR's author or the repo's
collaborators edit that description, so finding a caller's address there
is evidence of write access to that specific PR -- not a verified GitHub
identity, but proof of control over the one artifact that matters. To
claim a bounty, a contributor pastes their address into their PR's
description (or asks a maintaining collaborator to) before calling
`claim()`.

### A bogus claim can't lock the bounty until the deadline

The other failure mode: `claim()` used to accept *any* PR number with no
verification at all, flipping the bounty to `"claimed"`. `cancel()` only
works on `"open"` bounties, and `settle()` reverts outright if the PR
isn't merged -- so one bad-faith or mistaken claim, and the funds were
stuck until `deadline`, however far off that was. Cheap to trigger,
expensive to sit through.

Every claim now carries two independent limits, both set by the poster in
`create_bounty`:

- **`claim_window`** -- once this many seconds have passed since the
  claim with no settlement, *anyone* can call `release_stale_claim` to
  reopen the bounty for a fresh claimant. The lock is now bounded by
  `claim_window`, not by `deadline`.
- **`claim_bond`** -- GEN the claimant locks alongside their claim.
  `settle()` always returns it to the contributor (they did get a merged,
  judged PR out of it, whatever the payout). `release_stale_claim` and a
  deadline-triggered `reclaim_expired` on a still-claimed bounty both
  forfeit it to the poster instead -- so letting a claim go stale costs
  the claimant real money, not just anyone's time.

Combined, a bogus claim now blocks the bounty for at most `claim_window`
and costs its author `claim_bond` every time it happens -- rather than
locking the poster's funds for free until whatever deadline they picked.

This bounds the griefing cost; it doesn't reduce it to zero. Someone
willing to keep opening throwaway PRs and forfeiting bonds can still
re-claim a bounty the moment it's released. Posting a `claim_bond` large
enough to make that unattractive, and a `claim_window` short enough that
each cycle is cheap for everyone else, is a poster-side judgment call the
same way `min_score` is -- see [Contract API](#contract-api) below.

## Contract API

```
create_bounty(repo, spec, deadline, min_score, claim_window, claim_bond) -> bounty_id
                                                                [payable, funds the bounty]
claim(bounty_id, pr_number)                                    [payable with exactly claim_bond;
                                                                 requires the caller's address to
                                                                 already be in the PR's description]
settle(bounty_id)                                               [anyone; pays out once the PR is merged]
cancel(bounty_id)                                                [poster only, while still unclaimed]
release_stale_claim(bounty_id)                                    [anyone, once claim_window has elapsed]
reclaim_expired(bounty_id)                                       [anyone, once the deadline has passed]

get_bounty(bounty_id) -> dict
get_open_bounty_ids() -> list[int]
bounty_count() -> int
```

`get_bounty` returns the full settlement record, not just the current status --
once `settle()` has run, the same call also returns the combined `score`, the
`ci_status` GenLayer observed on the merge commit, and the validators'
`verdict_reasoning` / `verdict_confidence`, so a frontend (or anyone auditing
the ledger later) can see *why* a bounty was paid the way it was, not just
that it was.

- `repo` is `"owner/name"`, e.g. `"octocat/hello-world"`.
- `deadline` is a Unix timestamp; contracts read GenLayer's transaction-pinned
  clock (`datetime.now(timezone.utc)`), not wall-clock time, so it stays
  deterministic across validators.
- `min_score` is 0-100. Set it low for a lenient bounty, high for one that
  should only pay out on an unambiguous, CI-green match.
- `claim_window` is in seconds, minimum 3600 (1 hour). How long a claim may
  sit unsettled before anyone can release it back to `"open"` -- see
  [Security](#security).
- `claim_bond` is in wei. GEN a claimant must post alongside `claim()`;
  refunded on settlement, forfeited to the poster if the claim goes stale.
  `0` disables the bond requirement entirely.

## Getting GEN and running it locally first

The fastest way to see the whole flow work is [GenLayer
Studio](https://studio.genlayer.com) -- zero setup, and it has a built-in
faucet. If you'd rather work from the command line:

```bash
npm install -g genlayer
genlayer init          # local Studio + validators, if you want a fully offline loop
```

## Deploying to Studionet

Studionet (`studio.genlayer.com`) is the stable hosted network and the
simplest place to try this out with a real (if temporary) validator set and
a built-in faucet -- no Docker required.

1. **Build the single-file bundle** the deploy path expects:

   ```bash
   python scripts/bundle.py
   # -> dist/bounty_escrow.bundle.py
   ```

2. **Point the CLI at Studionet** and fund your account from its faucet
   (the 💧 button in Studio's account selector, or via the CLI):

   ```bash
   genlayer network set studionet
   genlayer network info      # sanity-check the RPC/chain you're about to sign against
   ```

3. **Deploy the bundle.** `BountyEscrow.__init__` takes no constructor
   arguments:

   ```bash
   genlayer deploy --contract dist/bounty_escrow.bundle.py
   ```

   Note the contract address the CLI prints.

4. **Fund and claim a bounty** (amounts are in wei; `1gen` = 10^18). Before
   claiming, the contributor pastes their address into their PR's
   description -- `claim()` will reject the call otherwise (see
   [Security](#security)):

   ```bash
   genlayer write <contract_address> create_bounty \
     --args "octocat/hello-world" "Add a health-check endpoint returning 200 OK" \
            1893456000 70 86400 1gen \
     --value 5gen
   # args: repo, spec, deadline, min_score, claim_window (1 day), claim_bond (1 GEN)

   genlayer write <contract_address> claim --args 0 123 --value 1gen
   # value must equal exactly the bounty's claim_bond
   ```

5. **Settle it** once the PR in question is actually merged on GitHub:

   ```bash
   genlayer write <contract_address> settle --args 0
   genlayer call <contract_address> get_bounty --args 0
   ```

You can just as easily skip the CLI entirely: open
[studio.genlayer.com](https://studio.genlayer.com), use **Add From File** to
upload `dist/bounty_escrow.bundle.py`, and deploy and call methods from the
browser UI. Studio also lets you import an already-deployed contract by
address if you want to poke at one you deployed from the CLI.

For a persistent deployment with real AI workloads instead of a temporary
hosted environment, the same bundle deploys unchanged to Testnet Bradbury
(`genlayer network set testnet-bradbury`) once you have funds from its
faucet.

Once you have an address, point the frontend at it: copy `app/.env.example`
to `app/.env`, paste the address into `VITE_CONTRACT_ADDRESS`, then
`cd app && npm install && npm run dev` -- see [Frontend](#frontend) above.

## Testing

```bash
pip install pytest
pytest tests/test_pure_logic.py -v        # no GenLayer install needed at all
```

```bash
pip install genlayer-test
python scripts/bundle.py
pytest tests/test_bounty_escrow.py -v     # in-memory GenVM direct-mode run, mocked web + LLM
```

`test_pure_logic.py` exercises `mergeproof_pure.py` directly with plain
pytest -- there is no `gl.*` import anywhere in that file, so it has no
GenLayer dependency at all and is the fastest possible feedback loop while
you're changing the scoring logic. `test_bounty_escrow.py` runs the full
bundled contract through `genlayer-test`'s direct-mode VM with GitHub and
LLM calls mocked via its `mock_web` / `mock_llm` cheatcodes.

## Limitations and things to know before relying on this

- **No GitHub token.** Every request is unauthenticated, so you're subject
  to GitHub's public rate limit (60 requests/hour per source IP). That's
  fine for demos and modest usage; a production deployment fielding many
  bounties per hour should front this with its own cached indexer and keep
  only the settlement-critical reads on-chain.
- **The diff the LLM sees is truncated at 6,000 characters.** Large PRs
  get their diff cut off (with a visible marker) before it reaches the
  prompt, to keep judgment cost and latency bounded. For most bounty-sized
  changes this doesn't matter; a bounty whose scope produces a much larger
  diff should expect the judgment to be based on a prefix of it, not the
  whole thing -- adjust `_MAX_DIFF_CHARS` in `mergeproof.py` if that's a
  real constraint for you.
- **Proof of PR control isn't proof of identity.** `claim()` verifies that
  the caller's address is written into the PR's description, which only
  the PR's author or the repo's collaborators can edit -- but it doesn't
  verify *which* GitHub account did the editing. That's a deliberate,
  documented trade-off (see [Security](#security)), not an oversight: it
  stops the identity-spoofing attack this project was originally built
  without a defense for, without requiring GitHub OAuth or any other
  centralized identity step.
- **Bounded griefing, not zero griefing.** `claim_window` and `claim_bond`
  turn "claim can lock the bounty until deadline for free" into "claim can
  lock the bounty for at most claim_window, and costs claim_bond every
  time" -- posters should size both to the task, the same way they size
  `min_score`.
- **The LLM verdict is a judgment call, not a legal one.** GenLayer's own
  guidance is explicit that this kind of evidence-based settlement is a
  contractual/arbitration primitive, not a substitute for a court -- treat
  `min_score` as a tunable trust threshold, not a guarantee.
- **This is a reference implementation.** It has no admin key, no pausing,
  and no upgrade path -- deliberately, to keep the example legible. Add
  those if you take it further.

## License

MIT -- see [LICENSE](LICENSE).
