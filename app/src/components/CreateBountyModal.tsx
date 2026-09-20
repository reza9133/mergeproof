import { useState, type FormEvent } from 'react';
import type { GenLayerClient } from 'genlayer-js/types';
import { createBounty } from '../lib/contract';
import { dateInputToUnixSeconds, genToWei } from '../lib/format';
import { useToast } from './Toast';

interface CreateBountyModalProps {
  open: boolean;
  onClose: () => void;
  client: GenLayerClient<any> | null;
  address: string | null;
  onConnectWallet: () => void;
  onCreated: () => void;
}

const DEFAULT_MIN_SCORE = 70;
const DEFAULT_CLAIM_WINDOW_DAYS = 3;
const MIN_CLAIM_WINDOW_SECONDS = 3600; // matches _MIN_CLAIM_WINDOW_SECONDS in the contract

export function CreateBountyModal({
  open,
  onClose,
  client,
  address,
  onConnectWallet,
  onCreated,
}: CreateBountyModalProps) {
  const toast = useToast();
  const [repo, setRepo] = useState('');
  const [spec, setSpec] = useState('');
  const [reward, setReward] = useState('');
  const [deadline, setDeadline] = useState('');
  const [minScore, setMinScore] = useState(DEFAULT_MIN_SCORE);
  const [claimWindowDays, setClaimWindowDays] = useState(DEFAULT_CLAIM_WINDOW_DAYS);
  const [claimBond, setClaimBond] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  function resetForm() {
    setRepo('');
    setSpec('');
    setReward('');
    setDeadline('');
    setMinScore(DEFAULT_MIN_SCORE);
    setClaimWindowDays(DEFAULT_CLAIM_WINDOW_DAYS);
    setClaimBond('');
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();

    if (!address || !client) {
      toast.push('Connect a wallet before funding a bounty.', 'error');
      onConnectWallet();
      return;
    }
    if (!repo.includes('/')) {
      toast.push('Repository should look like owner/name.', 'error');
      return;
    }
    if (!spec.trim()) {
      toast.push('Add a specification before funding.', 'error');
      return;
    }
    const rewardNum = Number(reward);
    if (!rewardNum || rewardNum <= 0) {
      toast.push('Reward must be greater than zero.', 'error');
      return;
    }
    if (!deadline) {
      toast.push('Pick a deadline.', 'error');
      return;
    }
    const deadlineUnix = dateInputToUnixSeconds(deadline);
    if (deadlineUnix * 1000 <= Date.now()) {
      toast.push('Deadline must be in the future.', 'error');
      return;
    }
    const claimWindowSeconds = Math.round(claimWindowDays * 86400);
    if (claimWindowSeconds < MIN_CLAIM_WINDOW_SECONDS) {
      toast.push('Claim window must be at least 1 hour.', 'error');
      return;
    }
    const claimBondNum = claimBond === '' ? 0 : Number(claimBond);
    if (Number.isNaN(claimBondNum) || claimBondNum < 0) {
      toast.push('Claim bond must be zero or a positive amount.', 'error');
      return;
    }

    setSubmitting(true);
    try {
      await createBounty(
        { client },
        {
          repo: repo.trim(),
          spec: spec.trim(),
          deadline: deadlineUnix,
          minScore,
          claimWindow: claimWindowSeconds,
          claimBond: genToWei(claimBondNum),
          rewardWei: genToWei(rewardNum),
        },
      );
      toast.push('Bounty funded and added to the ledger.');
      resetForm();
      onClose();
      onCreated();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : 'Could not fund the bounty.', 'error');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="backdrop open" role="dialog" aria-modal="true" aria-labelledby="createTitle" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal">
        <div className="modal-head">
          <h3 id="createTitle">Fund a bounty</h3>
          <button className="modal-close" onClick={onClose} aria-label="Close">
            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="modal-body">
          <form onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="f-repo">Repository</label>
              <input id="f-repo" type="text" placeholder="owner/name" value={repo} onChange={(e) => setRepo(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="f-spec">
                Specification<span className="hint">what &ldquo;done&rdquo; means</span>
              </label>
              <textarea
                id="f-spec"
                placeholder="Describe the change precisely enough for a validator to judge a diff against it."
                value={spec}
                onChange={(e) => setSpec(e.target.value)}
                required
              />
            </div>
            <div className="field-row">
              <div className="field">
                <label htmlFor="f-reward">Reward</label>
                <div className="amount-input">
                  <input id="f-reward" type="number" min="1" step="1" placeholder="150" value={reward} onChange={(e) => setReward(e.target.value)} required />
                  <span>GEN</span>
                </div>
              </div>
              <div className="field">
                <label htmlFor="f-deadline">Deadline</label>
                <input id="f-deadline" type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)} required />
              </div>
            </div>
            <div className="field">
              <label htmlFor="f-score">Minimum score for full payout</label>
              <div className="slider-row">
                <input
                  id="f-score"
                  type="range"
                  min={0}
                  max={100}
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value))}
                />
                <span className="slider-val">{minScore}</span>
              </div>
            </div>
            <div className="field-row">
              <div className="field">
                <label htmlFor="f-window">
                  Claim window<span className="hint">days before a stale claim can be released</span>
                </label>
                <input
                  id="f-window"
                  type="number"
                  min="0.05"
                  step="0.5"
                  value={claimWindowDays}
                  onChange={(e) => setClaimWindowDays(Number(e.target.value))}
                  required
                />
              </div>
              <div className="field">
                <label htmlFor="f-bond">
                  Claim bond<span className="hint">0 to disable</span>
                </label>
                <div className="amount-input">
                  <input id="f-bond" type="number" min="0" step="0.1" placeholder="0" value={claimBond} onChange={(e) => setClaimBond(e.target.value)} />
                  <span>GEN</span>
                </div>
              </div>
            </div>
            <button className="btn btn-primary btn-full" type="submit" disabled={submitting}>
              {submitting ? 'Locking GEN\u2026' : 'Lock GEN & fund bounty'}
            </button>
            <p className="modal-note">
              A claimant must post the bond and prove control of their PR before this bounty leaves &ldquo;open&rdquo;
              &mdash; see the README&rsquo;s Security section.
              {!address && ' You\u2019ll be asked to connect a wallet when you submit.'}
            </p>
          </form>
        </div>
      </div>
    </div>
  );
}
