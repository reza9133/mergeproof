import type { CalldataEncodable, GenLayerClient } from 'genlayer-js/types';
import { ExecutionResult, TransactionStatus } from 'genlayer-js/types';
import { getReadClient } from './genlayerClient';
import type { Bounty, BountyStatus } from '../types';

export const CONTRACT_ADDRESS = (import.meta.env.VITE_CONTRACT_ADDRESS || '') as `0x${string}` | '';
export const NETWORK_LABEL = import.meta.env.VITE_NETWORK_LABEL || 'Studionet';
export const isConfigured = CONTRACT_ADDRESS.length > 0;

function requireAddress(): `0x${string}` {
  if (!isConfigured) {
    throw new Error(
      'VITE_CONTRACT_ADDRESS is not set. Deploy BountyEscrow and add its address to app/.env \u2014 see the README.',
    );
  }
  return CONTRACT_ADDRESS as `0x${string}`;
}

function toBounty(id: number, raw: Record<string, unknown>): Bounty {
  return {
    id,
    poster: String(raw.poster),
    repo: String(raw.repo),
    spec: String(raw.spec),
    reward: BigInt(String(raw.reward)),
    deadline: Number(raw.deadline),
    minScore: Number(raw.min_score),
    claimWindow: Number(raw.claim_window ?? 0),
    claimBond: BigInt(String(raw.claim_bond ?? '0')),
    status: String(raw.status) as BountyStatus,
    contributor: String(raw.contributor),
    prNumber: Number(raw.pr_number),
    claimedAt: Number(raw.claimed_at ?? 0),
    payout: BigInt(String(raw.payout)),
    score: Number(raw.score ?? 0),
    ciStatus: String(raw.ci_status ?? ''),
    verdictConfidence: Number(raw.verdict_confidence ?? 0),
    verdictReasoning: String(raw.verdict_reasoning ?? ''),
  };
}

export async function fetchBountyCount(): Promise<number> {
  const address = requireAddress();
  const client = getReadClient();
  const count = await client.readContract({ address, functionName: 'bounty_count', args: [] });
  return Number(count);
}

export async function fetchBounty(id: number): Promise<Bounty> {
  const address = requireAddress();
  const client = getReadClient();
  const raw = (await client.readContract({
    address,
    functionName: 'get_bounty',
    args: [BigInt(id)],
  })) as Record<string, unknown>;
  return toBounty(id, raw);
}

/** Reads every bounty from id 0 up to (but excluding) the current counter. */
export async function fetchAllBounties(): Promise<Bounty[]> {
  const count = await fetchBountyCount();
  const ids = Array.from({ length: count }, (_, i) => i);
  const results = await Promise.all(ids.map((id) => fetchBounty(id).catch(() => null)));
  return results.filter((b): b is Bounty => b !== null);
}

interface WriteDeps {
  client: GenLayerClient<any>;
}

/**
 * Submits a write, waits for it to finalize, and throws unless the
 * transaction both finalized *and* actually returned rather than
 * erroring \u2014 a finalized status alone does not mean the call succeeded.
 */
async function submitWrite(
  { client }: WriteDeps,
  functionName: string,
  args: CalldataEncodable[],
  value: bigint = 0n,
) {
  const address = requireAddress();

  const txId = await client.writeContract({ address, functionName, args, value });
  const receipt = await client.waitForTransactionReceipt({
    hash: txId,
    status: TransactionStatus.FINALIZED,
    interval: 3000,
    retries: 100,
  });

  const statusName = receipt.statusName;
  const executionResultName = receipt.txExecutionResultName;
  const succeeded =
    (statusName === TransactionStatus.FINALIZED || statusName === TransactionStatus.ACCEPTED) &&
    executionResultName === ExecutionResult.FINISHED_WITH_RETURN;

  if (!succeeded) {
    throw new Error(`Transaction did not succeed: ${statusName ?? '?'} / ${executionResultName ?? '?'}`);
  }
  return { txId, receipt };
}

export function createBounty(
  deps: WriteDeps,
  params: {
    repo: string;
    spec: string;
    deadline: number;
    minScore: number;
    claimWindow: number;
    claimBond: bigint;
    rewardWei: bigint;
  },
) {
  return submitWrite(
    deps,
    'create_bounty',
    [params.repo, params.spec, BigInt(params.deadline), params.minScore, BigInt(params.claimWindow), params.claimBond],
    params.rewardWei,
  );
}

export function claimBounty(deps: WriteDeps, bountyId: number, prNumber: number, claimBondWei: bigint) {
  return submitWrite(deps, 'claim', [BigInt(bountyId), prNumber], claimBondWei);
}

export function settleBounty(deps: WriteDeps, bountyId: number) {
  return submitWrite(deps, 'settle', [BigInt(bountyId)]);
}

export function cancelBounty(deps: WriteDeps, bountyId: number) {
  return submitWrite(deps, 'cancel', [BigInt(bountyId)]);
}

export function releaseStaleClaim(deps: WriteDeps, bountyId: number) {
  return submitWrite(deps, 'release_stale_claim', [BigInt(bountyId)]);
}

export function reclaimExpired(deps: WriteDeps, bountyId: number) {
  return submitWrite(deps, 'reclaim_expired', [BigInt(bountyId)]);
}
