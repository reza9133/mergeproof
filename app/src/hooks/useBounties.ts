import { useCallback, useEffect, useState } from 'react';
import { fetchAllBounties, isConfigured } from '../lib/contract';
import type { Bounty } from '../types';

export interface BountiesState {
  bounties: Bounty[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useBounties(): BountiesState {
  const [bounties, setBounties] = useState<Bounty[]>([]);
  const [loading, setLoading] = useState(isConfigured);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!isConfigured) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const list = await fetchAllBounties();
      list.sort((a, b) => b.id - a.id);
      setBounties(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load bounties from the chain.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { bounties, loading, error, refresh };
}
