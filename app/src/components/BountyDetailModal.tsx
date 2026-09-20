import { useState } from 'react';
import type { GenLayerClient } from 'genlayer-js/types';
import type { Bounty } from '../types';
import { StatusBadge } from './BountyGrid';
import { claimBounty, settleBounty, cancelBounty, reclaimExpired, releaseStaleClaim } from '../lib/contract';
import { formatDuration, formatGen, isPast, relativeDeadline, shortAddress } from '../lib/format';
import { useToast } from './Toast';

interface BountyDetailModalProps {
  bounty: Bounty | null;
  onClose: () => void;
  client: GenLayerClient<any> | null;
  address: string | null;
  onConnectWallet: () => void;
  onChanged: () => void;
}

type Busy = null | 'claim' | 'settle' | 'cancel' | 'reclaim' | 'release';

function stepState(bounty: Bounty) {
  interface Step {
    done: boolean;
    label: string;
    bad: boolean;
  }
  const claimed: Step = { done: false, label: 'Claimed', bad: false };
  const resolved: Step = { done: false, label: 'Settled', bad: false };
  if (bounty.prNumber > 0 || bounty.status !== 'open') claimed.done = true;
  if (bounty.status === 'settled') {
    resolved.done = true;
    resolved.label = 'Settled';
  } else if (bounty.status === 'expired') {
    resolved.done = true;
    resolved.label = 'Expired';
    resolved.bad = true;
  } else if (bounty.status === 'cancelled') {
    resolved.done = true;
    resolved.label = 'Cancelled';
    resolved.bad = true;
  }
  const steps: Step[] = [{ done: true, label: 'Funded', bad: false }, claimed, resolved];
  return steps;
}

export function BountyDetailModal({ bounty, onClose, client, address, onConnectWallet, onChanged }: BountyDetailModalProps) {
  const toast = useToast();
  const [prInput, setPrInput] = useState('');
  const [busy, setBusy] = useState<Busy>(null);

  if (!bounty) return null;

  const isPoster = !!address && !!bounty.poster && address.toLowerCase() === bounty.poster.toLowerCase();
  const deadlinePassed = isPast(bounty.deadline);
  const claimReleasable = bounty.status === 'claimed' && Date.now() / 1000 >= bounty.claimedAt + bounty.claimWindow;

  async function run(kind: Exclude<Busy, null>, action: () => Promise<unknown>, successMsg: string) {
    if (!client || !address) {
      toast.push('Connect a wallet first.', 'error');
      onConnectWallet();
      return;
    }
    setBusy(kind);
    try {
      await action();
      toast.push(successMsg);
      onChanged();
      onClose();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : 'Transaction failed.', 'error');
    } finally {
      setBusy(null);
    }
  }

  function handleClaim() {
    const pr = Number(prInput);
    if (!pr || pr <= 0) {
      toast.push('Enter a valid pull request number.', 'error');
      return;
    }
    void run(
      'claim',
      () => claimBounty({ client: client! }, bounty!.id, pr, bounty!.claimBond),
      `Claimed #${String(bounty!.id).padStart(3, '0')} against PR #${pr}`,
    );
  }

  function handleSettle() {
    void run('settle', () => settleBounty({ client: client! }, bounty!.id), 'Settlement complete.');
  }

  function handleCancel() {
    void run('cancel', () => cancelBounty({ client: client! }, bounty!.id), 'Bounty cancelled and refunded.');
  }

  function handleReclaim() {
    void run('reclaim', () => reclaimExpired({ client: client! }, bounty!.id), 'Expired bounty refunded.');
  }

  function handleRelease() {
    void run(
      'release',
      () => releaseStaleClaim({ client: client! }, bounty!.id),
      'Stale claim released \u2014 bond forfeited to the poster, bounty reopened.',
    );
  }

  const steps = stepState(bounty);

  return (
    <div
      className="backdrop open"
      role="dialog"
      aria-modal="true"
      aria-labelledby="detailTitle"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" style={{ maxWidth: 600 }}>
        <div className="modal-head">
          <h3 id="detailTitle">
            #{String(bounty.id).padStart(3, '0')} &middot; {bounty.repo}
          </h3>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="modal-body">
          <div className="panel-heading">Specification</div>
          <div className="spec-block">{bounty.spec}</div>

          <div className="stepper">
            {steps.map((step, i) => (
              <div className={`step ${step.done ? 'done' : ''} ${step.bad ? 'bad' : ''}`} key={i}>
                <div className="step-line" />
                <div className="step-dot" />
                <div className="step-label">{step.label}</div>
              </div>
            ))}
          </div>

          <div className="kv-row">
            <span className="k">Status</span>
            <span className="v">
              <StatusBadge status={bounty.status} />
            </span>
          </div>
          <div className="kv-row">
            <span className="k">Reward locked</span>
            <span className="v">{formatGen(bounty.reward)} GEN</span>
          </div>
          <div className="kv-row">
            <span className="k">Minimum score</span>
            <span className="v">{bounty.minScore} / 100</span>
          </div>
          <div className="kv-row">
            <span className="k">Claim window / bond</span>
            <span className="v">
              {formatDuration(bounty.claimWindow)} / {formatGen(bounty.claimBond)} GEN
            </span>
          </div>
          <div className="kv-row">
            <span className="k">Deadline</span>
            <span className="v">{relativeDeadline(bounty.deadline)}</span>
          </div>
          <div className="kv-row">
            <span className="k">Poster</span>
            <span className="v">{shortAddress(bounty.poster)}</span>
          </div>
          {bounty.prNumber > 0 && (
            <div className="kv-row">
              <span className="k">Pull request</span>
              <span className="v">
                {bounty.repo.split('/')[1]} #{bounty.prNumber}
              </span>
            </div>
          )}
          {bounty.contributor && bounty.contributor !== '0x0000000000000000000000000000000000000000' && (
            <div className="kv-row">
              <span className="k">Contributor</span>
              <span className="v">{shortAddress(bounty.contributor)}</span>
            </div>
          )}
          {bounty.status === 'claimed' && (
            <div className="kv-row">
              <span className="k">Claim releasable</span>
              <span className="v">{claimReleasable ? 'now' : relativeDeadline(bounty.claimedAt + bounty.claimWindow)}</span>
            </div>
          )}

          {bounty.status === 'settled' && (
            <>
              <div className="panel-heading">Settlement</div>
              <div className="kv-row">
                <span className="k">CI on merge commit</span>
                <span className="v">{bounty.ciStatus || '\u2014'}</span>
              </div>
              <div className="kv-row">
                <span className="k">Combined score</span>
                <span className="v">{bounty.score} / 100</span>
              </div>
              <div className="kv-row">
                <span className="k">Paid to contributor</span>
                <span className="v">{formatGen(bounty.payout)} GEN</span>
              </div>
              {bounty.reward - bounty.payout > 0n && (
                <div className="kv-row">
                  <span className="k">Refunded to poster</span>
                  <span className="v">{formatGen(bounty.reward - bounty.payout)} GEN</span>
                </div>
              )}
              {bounty.verdictReasoning && (
                <div className="verdict-block">
                  <p>&ldquo;{bounty.verdictReasoning}&rdquo;</p>
                  <cite>validator consensus &middot; confidence {bounty.verdictConfidence}</cite>
                </div>
              )}
            </>
          )}

          {bounty.status === 'open' && !deadlinePassed && (
            <>
              <div className="panel-heading">Claim this bounty</div>
              <p className="modal-note" style={{ marginTop: 0, marginBottom: 12 }}>
                Add your address to the pull request&rsquo;s description before claiming &mdash; <code className="mono">claim()</code>{' '}
                verifies it&rsquo;s there. Requires a bond of {formatGen(bounty.claimBond)} GEN, refunded on settlement.
              </p>
              <div className="field-row" style={{ alignItems: 'end' }}>
                <div className="field" style={{ marginBottom: 0 }}>
                  <label htmlFor="pr-number">Pull request number</label>
                  <input
                    id="pr-number"
                    type="number"
                    min="1"
                    placeholder="482"
                    value={prInput}
                    onChange={(e) => setPrInput(e.target.value)}
                  />
                </div>
                <button className="btn btn-ghost" onClick={handleClaim} disabled={busy !== null}>
                  {busy === 'claim' ? 'Claiming\u2026' : 'Claim'}
                </button>
              </div>
              {isPoster && (
                <button className="btn btn-text" style={{ marginTop: 14 }} onClick={handleCancel} disabled={busy !== null}>
                  {busy === 'cancel' ? 'Cancelling\u2026' : 'Cancel bounty & refund me'}
                </button>
              )}
            </>
          )}

          {bounty.status === 'claimed' && (
            <div style={{ marginTop: 18, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <button className="btn btn-primary" onClick={handleSettle} disabled={busy !== null}>
                {busy === 'settle' ? 'Settling\u2026' : 'Call settle()'}
              </button>
              {claimReleasable && (
                <button className="btn btn-ghost" onClick={handleRelease} disabled={busy !== null}>
                  {busy === 'release' ? 'Releasing\u2026' : 'Release stale claim'}
                </button>
              )}
              {deadlinePassed && (
                <button className="btn btn-ghost" onClick={handleReclaim} disabled={busy !== null}>
                  {busy === 'reclaim' ? 'Reclaiming\u2026' : 'Reclaim expired instead'}
                </button>
              )}
            </div>
          )}

          {bounty.status === 'open' && deadlinePassed && (
            <div style={{ marginTop: 18 }}>
              <button className="btn btn-ghost" onClick={handleReclaim} disabled={busy !== null}>
                {busy === 'reclaim' ? 'Reclaiming\u2026' : 'Reclaim expired funds'}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
