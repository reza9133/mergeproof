interface HeroProps {
  openCount: number;
  escrowedGen: string;
  settledCount: number;
  onFund: () => void;
}

export function Hero({ openCount, escrowedGen, settledCount, onFund }: HeroProps) {
  return (
    <section className="hero wrap">
      <div className="hero-inner">
        <h1 className="hero-title">A ledger that pays out the moment the diff proves it.</h1>
        <p className="hero-sub">
          Fund a specification in GEN. A contributor merges the fix. GenLayer&rsquo;s validators check CI, judge
          the pull request against your spec, and settle the payout by consensus &mdash; no reviewer required,
          and nothing final until the appeal window closes.
        </p>
        <div className="hero-actions">
          <button className="btn btn-primary" onClick={onFund}>
            Fund a bounty
          </button>
          <a className="btn btn-text" href="#board">
            Browse the ledger
          </a>
        </div>
      </div>
      <div className="ledger-summary">
        <div className="stat">
          <span className="stat-value">{openCount}</span>
          <span className="stat-label">open bounties</span>
        </div>
        <div className="stat">
          <span className="stat-value">{escrowedGen}</span>
          <span className="stat-label">GEN escrowed</span>
        </div>
        <div className="stat">
          <span className="stat-value">{settledCount}</span>
          <span className="stat-label">settled to date</span>
        </div>
      </div>
    </section>
  );
}
