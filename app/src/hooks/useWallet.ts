import { useCallback, useState } from 'react';
import type { GenLayerClient } from 'genlayer-js/types';
import { connectBrowserWallet } from '../lib/genlayerClient';

export interface WalletState {
  address: `0x${string}` | null;
  client: GenLayerClient<any> | null;
  connecting: boolean;
  error: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
}

export function useWallet(): WalletState {
  const [address, setAddress] = useState<`0x${string}` | null>(null);
  const [client, setClient] = useState<GenLayerClient<any> | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = useCallback(async () => {
    setConnecting(true);
    setError(null);
    try {
      const result = await connectBrowserWallet();
      setAddress(result.address);
      setClient(result.client);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not connect a wallet.');
    } finally {
      setConnecting(false);
    }
  }, []);

  const disconnect = useCallback(() => {
    setAddress(null);
    setClient(null);
  }, []);

  return { address, client, connecting, error, connect, disconnect };
}
