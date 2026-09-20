import { shortAddress } from '../lib/format';
import { NETWORK_LABEL } from '../lib/contract';

interface TopBarProps {
  address: string | null;
  connecting: boolean;
  wrongNetwork: boolean;
  onSwitchNetwork: () => void;
  onConnect: () => void;
  onDisconnect: () => void;
  onToggleTheme: () => void;
}

export function TopBar({
  address,
  connecting,
  wrongNetwork,
  onSwitchNetwork,
  onConnect,
  onDisconnect,
  onToggleTheme,
}: TopBarProps) {
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
            <>
              {wrongNetwork && (
                <button
                  className="btn btn-ghost btn-sm"
                  style={{ borderColor: 'var(--bad)', color: 'var(--bad)' }}
                  onClick={onSwitchNetwork}
                >
                  Wrong network &mdash; switch to {NETWORK_LABEL}
                </button>
              )}
              <button
                className="btn btn-ghost btn-sm"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}
                onClick={onDisconnect}
                title={`Connected as ${address} \u2014 click to disconnect`}
              >
                <span
                  aria-hidden="true"
                  style={{
                    width: 7,
                    height: 7,
                    borderRadius: '50%',
                    background: wrongNetwork ? 'var(--bad)' : 'var(--good)',
                    boxShadow: `0 0 0 3px ${wrongNetwork ? 'var(--bad-soft)' : 'var(--good-soft)'}`,
                  }}
                />
                {shortAddress(address)}
              </button>
            </>
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
