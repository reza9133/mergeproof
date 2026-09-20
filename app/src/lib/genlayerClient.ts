import { createClient } from 'genlayer-js';
import { studionet } from 'genlayer-js/chains';
import type { GenLayerClient } from 'genlayer-js/types';

export const chain = studionet;

const CHAIN_ID_HEX = `0x${chain.id.toString(16)}`;

/** A single shared read-only client. No account is needed for `readContract`. */
let readClient: GenLayerClient<typeof studionet> | null = null;

export function getReadClient(): GenLayerClient<typeof studionet> {
  if (!readClient) {
    readClient = createClient({ chain });
  }
  return readClient;
}

function getProvider() {
  const eth = window.ethereum;
  if (!eth) {
    throw new Error('No browser wallet found \u2014 install MetaMask or a compatible extension.');
  }
  return eth;
}

/** Binds a GenLayer client to an injected-wallet account on Studionet. */
export function createWalletClient(address: `0x${string}`): GenLayerClient<typeof studionet> {
  return createClient({ chain, account: address, provider: getProvider() });
}

/** True when a wallet-reported chain id (hex string or number) is Studionet. */
export function isStudionetChainId(chainId: unknown): boolean {
  if (typeof chainId === 'string') return chainId.toLowerCase() === CHAIN_ID_HEX;
  if (typeof chainId === 'number') return chainId === chain.id;
  return false;
}

export async function readWalletChainId(): Promise<string | null> {
  const eth = window.ethereum;
  if (!eth) return null;
  try {
    const id = await eth.request({ method: 'eth_chainId' });
    return typeof id === 'string' ? id : null;
  } catch {
    return null;
  }
}

/** Asks the wallet for permission to see an account (opens the wallet's connect popup). */
export async function requestBrowserAccount(): Promise<`0x${string}`> {
  const accounts = (await getProvider().request({ method: 'eth_requestAccounts' })) as string[];
  const address = accounts[0] as `0x${string}` | undefined;
  if (!address) {
    throw new Error('The wallet did not return an account.');
  }
  return address;
}

/** Already-authorised account, if any. Never opens a popup. */
export async function getAuthorisedAccount(): Promise<`0x${string}` | null> {
  const eth = window.ethereum;
  if (!eth) return null;
  const accounts = (await eth.request({ method: 'eth_accounts' })) as string[];
  return (accounts[0] as `0x${string}` | undefined) ?? null;
}

/**
 * Switches the wallet to Studionet, adding the network first if the wallet
 * has never seen it. Deliberately does not install the GenLayer MetaMask
 * snap (which `client.connect()` does): writes go through a plain
 * `eth_sendTransaction`, so the snap is optional, and requiring it made
 * connecting fail on non-MetaMask wallets.
 */
export async function switchToStudionet(): Promise<void> {
  const eth = getProvider();
  try {
    await eth.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: CHAIN_ID_HEX }] });
    return;
  } catch (err) {
    if ((err as { code?: number }).code === 4001) throw err; // user rejected: don't chain another popup
  }

  await eth.request({
    method: 'wallet_addEthereumChain',
    params: [
      {
        chainId: CHAIN_ID_HEX,
        chainName: chain.name,
        rpcUrls: chain.rpcUrls.default.http,
        nativeCurrency: chain.nativeCurrency,
        ...(chain.blockExplorers ? { blockExplorerUrls: [chain.blockExplorers.default.url] } : {}),
      },
    ],
  });

  // Most wallets switch as part of adding; a few don't.
  if (!isStudionetChainId(await readWalletChainId())) {
    await eth.request({ method: 'wallet_switchEthereumChain', params: [{ chainId: CHAIN_ID_HEX }] });
  }
}

/** Turns raw wallet/RPC errors into something a person can act on. */
export function describeWalletError(err: unknown): string {
  const code = (err as { code?: number })?.code;
  if (code === 4001) return 'You rejected the request in your wallet.';
  if (code === -32002) return 'A request is already pending in your wallet \u2014 open the extension and answer it.';
  if (err instanceof Error && err.message) return err.message;
  const message = (err as { message?: unknown })?.message;
  return typeof message === 'string' && message ? message : 'Could not connect a wallet.';
}
