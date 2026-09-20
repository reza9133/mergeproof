const STEPS = [
  {
    num: '01',
    title: 'Fund',
    body: 'Post your specification and lock GEN in escrow. Set a deadline and the score a submission needs to clear for full payout.',
  },
  {
    num: '02',
    title: 'Claim & ship',
    body: 'A contributor claims the bounty against their pull request number, then gets it merged like any other contribution.',
  },
  {
    num: '03',
    title: 'Settle',
    body: 'Anyone calls settle once the PR is merged. Validators check CI and judge the diff against your spec, then split the payout without a human referee.',
  },
];

export function HowItWorks() {
  return (
    <section className="how wrap" id="how">
      <div className="how-head">
        <h2>How settlement works</h2>
        <p>
          Three write calls on <code className="mono">BountyEscrow</code>. No off-chain reviewer at any step.
        </p>
      </div>
      <div className="how-steps">
        {STEPS.map((step) => (
          <div className="how-step" key={step.num}>
            <div className="how-step-num">{step.num}</div>
            <h3>{step.title}</h3>
            <p>{step.body}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
