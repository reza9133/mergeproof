import type { Bounty, BountyStatus, BoardFilter } from '../types';
import { formatGen, relativeDeadline } from '../lib/format';

const STATUS_LABEL: Record<BountyStatus, string> = {
  open: 'Open',
  claimed: 'Claimed',
  settled: 'Settled',
  expired: 'Expired',
  cancelled: 'Cancelled',
};

export function StatusBadge({ status }: { status: BountyStatus }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABEL[status]}</span>;
}

const TABS: { id: BoardFilter; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'open', label: 'Open' },
  { id: 'claimed', label: 'Claimed' },
  { id: 'settled', label: 'Settled' },
  { id: 'closed', label: 'Closed' },
];

export function FilterTabs({ value, onChange }: { value: BoardFilter; onChange: (f: BoardFilter) => void }) {
  return (
    <div className="filter-tabs" role="tablist" aria-label="Filter bounties by status">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          className={`tab ${value === tab.id ? 'active' : ''}`}
          role="tab"
          aria-selected={value === tab.id}
          onClick={() => onChange(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function ScoreRow({ score, minScore }: { score: number; minScore: number }) {
  return (
    <div className="score-row">
      <div className="score-track">
        <div className="score-fill" style={{ width: `${score}%` }} />
        <div className="score-mark" style={{ left: `${minScore}%` }} />
      </div>
      <span className="score-num">{score}</span>
    </div>
  );
}

function titleFromSpec(spec: string): string {
  return spec.length > 90 ? `${spec.slice(0, 87)}\u2026` : spec;
}

export function BountyCard({ bounty, onOpen }: { bounty: Bounty; onOpen: (id: number) => void }) {
  const footRight =
    bounty.status === 'settled'
      ? `${formatGen(bounty.payout)} GEN paid`
      : bounty.status === 'expired' || bounty.status === 'cancelled'
        ? 'refunded'
        : relativeDeadline(bounty.deadline);

  return (
    <button className="entry" onClick={() => onOpen(bounty.id)}>
      <div className={`entry-accent s-${bounty.status}`} />
      <div className="entry-body">
        <div className="entry-top">
          <span className="entry-id">#{String(bounty.id).padStart(3, '0')}</span>
          <StatusBadge status={bounty.status} />
        </div>
        <h3 className="entry-title">{titleFromSpec(bounty.spec)}</h3>
        <p className="entry-repo">{bounty.repo}</p>
        {bounty.status === 'settled' && <ScoreRow score={bounty.score} minScore={bounty.minScore} />}
        <div className="entry-foot">
          <div className="entry-reward">
            <span className="reward-amount">{formatGen(bounty.reward)}</span>
            <span className="reward-unit">GEN</span>
          </div>
          <div className="entry-meta">{footRight}</div>
        </div>
      </div>
    </button>
  );
}

interface BountyGridProps {
  bounties: Bounty[];
  filter: BoardFilter;
  loading: boolean;
  onOpen: (id: number) => void;
}

function matchesFilter(bounty: Bounty, filter: BoardFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'closed') return bounty.status === 'expired' || bounty.status === 'cancelled';
  return bounty.status === filter;
}

export function BountyGrid({ bounties, filter, loading, onOpen }: BountyGridProps) {
  if (loading) {
    return (
      <div className="grid">
        {[0, 1, 2].map((i) => (
          <div className="entry skeleton" key={i} aria-hidden="true">
            <div className="entry-accent" />
            <div className="entry-body">
              <div className="skeleton-line" style={{ width: '40%' }} />
              <div className="skeleton-line" style={{ width: '85%', height: 18, marginTop: 14 }} />
              <div className="skeleton-line" style={{ width: '55%' }} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  const list = bounties.filter((b) => matchesFilter(b, filter)).sort((a, b) => b.id - a.id);

  if (!list.length) {
    return (
      <div className="grid">
        <div className="empty-state">
          <strong>Nothing here yet</strong>
          No bounty in this ledger currently has that status.
        </div>
      </div>
    );
  }

  return (
    <div className="grid">
      {list.map((bounty) => (
        <BountyCard bounty={bounty} onOpen={onOpen} key={bounty.id} />
      ))}
    </div>
  );
}
