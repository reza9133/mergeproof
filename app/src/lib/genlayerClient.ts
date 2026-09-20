import { createClient } from 'genlayer-js';
import { studionet } from 'genlayer-js/chains';
import type { GenLayerClient } from 'genlayer-js/types';

export const chain = studionet;

/** A single shared read-only client. No account is needed for `readContract`. */
let readClient: GenLayerClient<typeof studionet> | null = null;

export function getReadClient(): GenLayerClient<typeof studionet> {
  if (!readClient) {
    readClient = createClient({ chain });
  }
  return readClient;
}

export interface WalletConnection {
  address: `0x${string}`;
  client: GenLayerClient<typeof studionet>;
}

/**
 * Connects to an injected EIP-1193 wallet (MetaMask or compatible),
 * requests the active account, and binds a GenLayer client to it and
 * to the Studionet chain definition.
 */
export async function connectBrowserWallet(): Promise<WalletConnection> {
  const eth = window.ethereum;
  if (!eth) {
    throw new Error('No browser wallet found \u2014 install MetaMask or a compatible extension.');
  }

  const accounts = (await eth.request({ method: 'eth_requestAccounts' })) as string[];
  const address = accounts[0] as `0x${string}` | undefined;
  if (!address) {
    throw new Error('The wallet did not return an account.');
  }

  const client = createClient({ chain, account: address, provider: eth });
  await client.connect('studionet');

  return { address, client };
}
