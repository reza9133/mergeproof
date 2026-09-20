import { shortAddress } from '../lib/format';
import { NETWORK_LABEL } from '../lib/contract';

interface TopBarProps {
  address: string | null;
  connecting: boolean;
  onConnect: () => void;
  onDisconnect: () => void;
  onToggleTheme: () => void;
}

export function TopBar({ address, connecting, onConnect, onDisconnect, onToggleTheme }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="wrap topbar-inner">
        <div className="brand">
          <svg className="seal" viewBox="0 0 32 32" width={21} height={21} aria-hidden="true">
            <circle cx="16" cy="16" r="13" stroke="currentColor" strokeWidth="1.6" fill="none" />
            <path
              d="M10 16.6l3.8 3.8L22 11.6"
              stroke="currentColor"
              strokeWidth="1.8"
              fill="none"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          MergeProof
        </div>
        <div className="topbar-right">
          <span className="network-pill">
            <span className="dot" />
            {NETWORK_LABEL}
          </span>
          <button className="theme-toggle" onClick={onToggleTheme} aria-label="Toggle light and dark theme">
            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <circle cx="12" cy="12" r="4.6" />
              <path
                d="M12 2v2.4M12 19.6V22M4.2 4.2l1.7 1.7M18.1 18.1l1.7 1.7M2 12h2.4M19.6 12H22M4.2 19.8l1.7-1.7M18.1 5.9l1.7-1.7"
                strokeLinecap="round"
              />
            </svg>
          </button>
          {address ? (
            <button className="btn btn-ghost btn-sm" onClick={onDisconnect} title="Disconnect wallet">
              {shortAddress(address)}
            </button>
          ) : (
            <button className="btn btn-ghost btn-sm" onClick={onConnect} disabled={connecting}>
              {connecting ? 'Connecting\u2026' : 'Connect wallet'}
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
