const ZERO_ADDRESS = '0x0000000000000000000000000000000000000000';
const DAY_MS = 86_400_000;

export function weiToGen(wei: bigint): number {
  return Number(wei) / 1e18;
}

/**
 * Exact GEN -> wei conversion. Parses the decimal text instead of
 * multiplying floats, so 1.1 GEN is exactly 1100000000000000000 wei
 * (`Math.round(1.1 * 1e18)` would give ...128).
 */
export function genToWei(gen: number | string): bigint {
  let text = typeof gen === 'number' ? String(gen) : gen.trim();
  if (/e/i.test(text)) text = Number(text).toFixed(18); // very small/large numbers print in exponent form
  if (!/^\d*\.?\d*$/.test(text) || text === '' || text === '.') {
    throw new Error('Invalid GEN amount.');
  }
  const [whole = '0', frac = ''] = text.split('.');
  const fracWei = (frac + '0'.repeat(18)).slice(0, 18);
  return BigInt(whole || '0') * 10n ** 18n + BigInt(fracWei);
}

export function formatGen(wei: bigint): string {
  return weiToGen(wei).toLocaleString('en-US', { maximumFractionDigits: 2 });
}

export function shortAddress(addr: string | null | undefined): string {
  if (!addr || addr.toLowerCase() === ZERO_ADDRESS) return '\u2014';
  return `${addr.slice(0, 6)}\u2026${addr.slice(-4)}`;
}

export function relativeDeadline(unixSeconds: number): string {
  const diffMs = unixSeconds * 1000 - Date.now();
  const abs = Math.abs(diffMs);
  const mins = Math.round(abs / 60_000);
  const hrs = Math.round(abs / 3_600_000);
  const days = Math.round(abs / DAY_MS);
  const label = days >= 1 ? `${days}d` : hrs >= 1 ? `${hrs}h` : `${Math.max(mins, 1)}m`;
  return diffMs >= 0 ? `closes in ${label}` : `closed ${label} ago`;
}

export function isPast(unixSeconds: number): boolean {
  return unixSeconds * 1000 <= Date.now();
}

export function dateInputToUnixSeconds(dateInput: string): number {
  return Math.floor(new Date(`${dateInput}T23:59:59`).getTime() / 1000);
}

export function isZeroAddress(addr: string | null | undefined): boolean {
  return !addr || addr.toLowerCase() === ZERO_ADDRESS;
}

export function formatDuration(seconds: number): string {
  if (seconds >= DAY_MS / 1000 && seconds % (DAY_MS / 1000) === 0) {
    return `${seconds / (DAY_MS / 1000)}d`;
  }
  const hrs = seconds / 3600;
  if (hrs >= 1) return Number.isInteger(hrs) ? `${hrs}h` : `${hrs.toFixed(1)}h`;
  return `${Math.round(seconds / 60)}m`;
}

export function secondsUntil(unixSeconds: number): number {
  return Math.max(0, Math.round(unixSeconds - Date.now() / 1000));
}
