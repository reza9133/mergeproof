import { useCallback, useEffect, useState } from 'react';
import type { GenLayerClient } from 'genlayer-js/types';
import {
  createWalletClient,
  describeWalletError,
  getAuthorisedAccount,
  isStudionetChainId,
  readWalletChainId,
  requestBrowserAccount,
  switchToStudionet,
} from '../lib/genlayerClient';

export interface WalletState {
  address: `0x${string}` | null;
  client: GenLayerClient<any> | null;
  connecting: boolean;
  /** Connected, but the wallet is on a different chain than Studionet. */
  wrongNetwork: boolean;
  error: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
  switchNetwork: () => Promise<void>;
}

// An injected wallet can't be "disconnected" by a page, so remember that the
// user asked to be, and don't silently reconnect on the next page load.
const DISCONNECTED_KEY = 'mergeproof:wallet-disconnected';

function wasDisconnectedByUser(): boolean {
  try {
    return window.localStorage.getItem(DISCONNECTED_KEY) === '1';
  } catch {
    return false;
  }
}

function rememberDisconnect(disconnected: boolean) {
  try {
    if (disconnected) window.localStorage.setItem(DISCONNECTED_KEY, '1');
    else window.localStorage.removeItem(DISCONNECTED_KEY);
  } catch {
    /* storage unavailable: the worst case is we auto-reconnect */
  }
}

export function useWallet(): WalletState {
  const [address, setAddress] = useState<`0x${string}` | null>(null);
  const [client, setClient] = useState<GenLayerClient<any> | null>(null);
  const [chainId, setChainId] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const adopt = useCallback((account: `0x${string}`) => {
    setAddress(account);
    setClient(createWalletClient(account));
  }, []);

  const refreshChain = useCallback(async () => {
    const id = await readWalletChainId();
    setChainId(id);
    return id;
  }, []);

  const connect = useCallback(async () => {
    setConnecting(true);
    setError(null);
    try {
      const account = await requestBrowserAccount();
      rememberDisconnect(false);
      // Show "connected" straight away; the network step below can still fail.
      adopt(account);
      if (!isStudionetChainId(await refreshChain())) {
        await switchToStudionet();
        await refreshChain();
      }
    } catch (err) {
      setError(describeWalletError(err));
    } finally {
      setConnecting(false);
    }
  }, [adopt, refreshChain]);

  const switchNetwork = useCallback(async () => {
    setError(null);
    try {
      await switchToStudionet();
      await refreshChain();
    } catch (err) {
      setError(describeWalletError(err));
    }
  }, [refreshChain]);

  const disconnect = useCallback(() => {
    rememberDisconnect(true);
    setAddress(null);
    setClient(null);
    setError(null);
  }, []);

  // Restore an already-authorised wallet on page load (no popup).
  useEffect(() => {
    if (wasDisconnectedByUser()) return;
    let cancelled = false;
    (async () => {
      try {
        const account = await getAuthorisedAccount();
        if (cancelled || !account) return;
        adopt(account);
        const id = await readWalletChainId();
        if (!cancelled) setChainId(id);
      } catch {
        /* no wallet, or it refused a silent lookup: stay disconnected */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [adopt]);

  // Follow the wallet when the user switches account or network in it.
  useEffect(() => {
    const eth = window.ethereum;
    if (!eth?.on) return;

    const onAccountsChanged = (accounts: unknown) => {
      const list = Array.isArray(accounts) ? (accounts as string[]) : [];
      if (!list[0]) {
        setAddress(null);
        setClient(null);
        return;
      }
      if (wasDisconnectedByUser()) return;
      adopt(list[0] as `0x${string}`);
    };
    const onChainChanged = (id: unknown) => setChainId(typeof id === 'string' ? id : null);

    eth.on('accountsChanged', onAccountsChanged);
    eth.on('chainChanged', onChainChanged);
    return () => {
      eth.removeListener?.('accountsChanged', onAccountsChanged);
      eth.removeListener?.('chainChanged', onChainChanged);
    };
  }, [adopt]);

  const wrongNetwork = !!address && chainId !== null && !isStudionetChainId(chainId);

  return { address, client, connecting, wrongNetwork, error, connect, disconnect, switchNetwork };
}
