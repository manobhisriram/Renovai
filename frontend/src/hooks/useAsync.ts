import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage } from "../services/api";

export interface AsyncState<T> { data: T | null; error: string | null; loading: boolean; reload: () => Promise<void> }

/** Loads data on mount and whenever `fn` changes (memoise it with useCallback). Ignores stale responses. */
export function useAsync<T>(fn: () => Promise<T>): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);

  const reload = useCallback(async () => {
    const id = ++seq.current;
    setLoading(true);
    try {
      const d = await fn();
      if (id === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (id === seq.current) setError(errorMessage(e));
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, [fn]);

  useEffect(() => { void reload(); }, [reload]);
  return { data, error, loading, reload };
}
