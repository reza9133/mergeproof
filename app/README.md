# MergeProof — app

The connected frontend for `BountyEscrow`: React + TypeScript + Vite, talking to
Studionet live through [`genlayer-js`](https://www.npmjs.com/package/genlayer-js).
No UI framework beyond React itself — the whole design system is one plain CSS
file (`src/index.css`) sharing tokens with the published design preview, so
what you see in the preview is exactly what you get here, minus the mock data.

This was built and type-checked against `genlayer-js@1.2.0`, the current
stable release. If you're targeting the Consensus v0.6 / Studio-dev preview
instead of stable Studionet, its fee-estimation API differs — see
[Targeting Studio-dev instead](#targeting-studio-dev-instead) below.

## Setup

1. **Deploy the contract first**, from the project root (not this folder):

   ```bash
   python scripts/bundle.py
   genlayer network set studionet
   genlayer deploy --contract dist/bounty_escrow.bundle.py
   ```

   Copy the address the CLI prints.

2. **Configure the app (optional):** the app ships pre-pointed at the
   Studionet deployment `0xFF9461802642D8D065D4e685a97653D35701Cfe1`. To use
   your own deployment instead:

   ```bash
   cd app
   cp .env.example .env
   # paste your deployed address into VITE_CONTRACT_ADDRESS
   ```

3. **Install and run:**

   ```bash
   npm install
   npm run dev
   ```

   Open the printed local URL. Click **Connect wallet** (MetaMask or any
   EIP-1193-compatible extension) to fund, claim, settle, cancel, or reclaim
   bounties for real.

`npm run build` produces a static `dist/` you can deploy anywhere (Vercel,
Netlify, Cloudflare Pages, a plain static host) — it's a client-only app with
no server component; the chain is the backend.

## How it talks to the chain

- **Reads** (`bounty_count`, `get_bounty`) go through one shared read-only
  client created with no account — see `src/lib/genlayerClient.ts`.
- **Writes** (`create_bounty`, `claim`, `settle`, `cancel`, `release_stale_claim`, `reclaim_expired`)
  require a connected wallet. Connecting requests `eth_requestAccounts` from
  `window.ethereum`, then binds a GenLayer client to that address and calls
  `client.connect('studionet')`, matching the pattern in the GenLayerJS docs.
- Every write in `src/lib/contract.ts` waits for `ACCEPTED` (contract state is
  readable from that point; `FINALIZED` only arrives after the finality
  window) and checks **both** the transaction status *and*
  `txExecutionResultName === 'FINISHED_WITH_RETURN'` before treating it as
  successful — a decided status alone doesn't mean the call didn't revert
  inside the contract. GEN payouts and refunds are released on finalization.

## Targeting Studio-dev instead

The Consensus v0.6 / Studio-dev preview environment uses a different,
fee-aware `genlayer-js@2.0.0-rc.x` API (`estimateTransactionFeesForWrite`,
explicit `fees: { distribution, feeValue }` on every write). If you're
pointing this app at Studio-dev rather than stable Studionet:

1. Install the matching release candidate: `npm install genlayer-js@2.0.0-rc.1`
   (check the GenLayer release notes for the exact current tag).
2. Swap the `studionet` import for `studioDevnet` in `src/lib/genlayerClient.ts`.
3. In `src/lib/contract.ts`, wrap each write with an
   `estimateTransactionFeesForWrite` call and pass the returned `fees` into
   `writeContract`, and swap `waitForTransactionReceipt` for
   `waitForFinalization` — see the project's main README and the GenLayerJS
   API reference for the exact shapes.

## Project layout

```
app/
├── src/
│   ├── lib/
│   │   ├── genlayerClient.ts   # read client + browser wallet connect
│   │   ├── contract.ts          # typed BountyEscrow reads/writes
│   │   └── format.ts             # GEN/address/deadline formatting
│   ├── hooks/
│   │   ├── useWallet.ts          # connect/disconnect state
│   │   └── useBounties.ts        # fetch + refresh the full bounty list
│   ├── components/               # TopBar, Hero, HowItWorks, BountyGrid,
│   │                              # CreateBountyModal, BountyDetailModal, Toast
│   ├── App.tsx
│   └── index.css                 # the entire design system, token-driven
├── .env.example
└── package.json
```
