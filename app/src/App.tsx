import { useEffect, useMemo, useState } from 'react';
import { TopBar } from './components/TopBar';
import { Hero } from './components/Hero';
import { HowItWorks } from './components/HowItWorks';
import { FilterTabs, BountyGrid } from './components/BountyGrid';
import { CreateBountyModal } from './components/CreateBountyModal';
import { BountyDetailModal } from './components/BountyDetailModal';
import { useWallet } from './hooks/useWallet';
import { useBounties } from './hooks/useBounties';
import { isConfigured, CONTRACT_ADDRESS } from './lib/contract';
import { formatGen } from './lib/format';
import { useToast } from './components/Toast';
import type { BoardFilter } from './types';

type Theme = 'light' | 'dark' | null;

function useTheme() {
  const [theme, setTheme] = useState<Theme>(null);
  useEffect(() => {
    if (theme) document.documentElement.setAttribute('data-theme', theme);
    else document.documentElement.removeAttribute('data-theme');
  }, [theme]);
  const toggle = () => {
    const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
    setTheme((cur) => {
      if (!cur) return prefersDark ? 'light' : 'dark';
      return cur === 'dark' ? 'light' : 'dark';
    });
  };
  return toggle;
}

export default function App() {
  const wallet = useWallet();
  const { bounties, loading, error, refresh } = useBounties();
  const toggleTheme = useTheme();
  const { push: pushToast } = useToast();

  // Wallet errors used to be stored but never shown, so a failed or rejected
  // connect looked like nothing had happened.
  useEffect(() => {
    if (wallet.error) pushToast(wallet.error, 'error');
  }, [wallet.error, pushToast]);

  const [createOpen, setCreateOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filter, setFilter] = useState<BoardFilter>('all');

  const selectedBounty = useMemo(() => bounties.find((b) => b.id === selectedId) ?? null, [bounties, selectedId]);

  const stats = useMemo(() => {
    const open = bounties.filter((b) => b.status === 'open').length;
    const escrowed = bounties
      .filter((b) => b.status === 'open' || b.status === 'claimed')
      .reduce((sum, b) => sum + b.reward, 0n);
    const settled = bounties.filter((b) => b.status === 'settled').length;
    return { open, escrowed: formatGen(escrowed), settled };
  }, [bounties]);

  return (
    <>
      <TopBar
        address={wallet.address}
        connecting={wallet.connecting}
        wrongNetwork={wallet.wrongNetwork}
        onSwitchNetwork={() => void wallet.switchNetwork()}
        onConnect={wallet.connect}
        onDisconnect={wallet.disconnect}
        onToggleTheme={toggleTheme}
      />

      <main>
        <Hero openCount={stats.open} escrowedGen={stats.escrowed} settledCount={stats.settled} onFund={() => setCreateOpen(true)} />
        <HowItWorks />

        <section className="board wrap" id="board">
          <div className="board-head">
            <h2>The ledger</h2>
            <FilterTabs value={filter} onChange={setFilter} />
          </div>

          {!isConfigured ? (
            <div className="config-panel">
              <strong>No contract configured yet</strong>
              <p>
                Deploy <code className="mono">BountyEscrow</code> to Studionet, then set{' '}
                <code className="mono">VITE_CONTRACT_ADDRESS</code> in <code className="mono">app/.env</code> and
                restart the dev server. See the project README for the exact commands.
              </p>
            </div>
          ) : error ? (
            <div className="config-panel config-panel-error">
              <strong>Could not reach the chain</strong>
              <p>{error}</p>
              <button className="btn btn-ghost btn-sm" style={{ marginTop: 12 }} onClick={() => void refresh()}>
                Try again
              </button>
            </div>
          ) : (
            <BountyGrid bounties={bounties} filter={filter} loading={loading} onOpen={setSelectedId} />
          )}
        </section>
      </main>

      <footer className="footer wrap">
        <div className="footer-inner">
          <p>
            {isConfigured
              ? `Reading and writing BountyEscrow at ${CONTRACT_ADDRESS.slice(0, 10)}\u2026${CONTRACT_ADDRESS.slice(-6)} on Studionet.`
              : 'Not yet connected to a deployed contract.'}
          </p>
          <div className="footer-links">
            <a href="#how">How it works</a>
            <a href="#board">Ledger</a>
          </div>
        </div>
      </footer>

      <CreateBountyModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        client={wallet.client}
        address={wallet.address}
        onConnectWallet={wallet.connect}
        onCreated={() => void refresh()}
      />
      <BountyDetailModal
        bounty={selectedBounty}
        onClose={() => setSelectedId(null)}
        client={wallet.client}
        address={wallet.address}
        onConnectWallet={wallet.connect}
        onChanged={() => void refresh()}
      />
    </>
  );
}
