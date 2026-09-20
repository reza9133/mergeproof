export type BountyStatus = 'open' | 'claimed' | 'settled' | 'cancelled' | 'expired';

export interface Bounty {
  id: number;
  poster: string;
  repo: string;
  spec: string;
  reward: bigint;
  deadline: number; // unix seconds
  minScore: number;
  claimWindow: number; // seconds a claim may stand before release_stale_claim can reopen it
  claimBond: bigint; // GEN a claimant must post; refunded on settle, forfeited if released stale
  status: BountyStatus;
  contributor: string;
  prNumber: number;
  claimedAt: number; // unix seconds of the current claim (0 when not claimed)
  payout: bigint;
  score: number;
  ciStatus: string;
  verdictConfidence: number;
  verdictReasoning: string;
}

export type BoardFilter = 'all' | 'open' | 'claimed' | 'settled' | 'closed';
