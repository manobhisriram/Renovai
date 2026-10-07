import { useEffect, useRef } from "react";

/** Calls `tick` every `ms` while `active` is true. Cleans up on unmount; never overlaps ticks. */
export function usePolling(tick: () => Promise<void> | void, active: boolean, ms = 1500): void {
  const saved = useRef(tick);
  useEffect(() => { saved.current = tick; });
  useEffect(() => {
    if (!active) return;
    let stopped = false;
    let busy = false;
    const id = setInterval(async () => {
      if (busy || stopped) return;
      busy = true;
      try { await saved.current(); } finally { busy = false; }
    }, ms);
    return () => { stopped = true; clearInterval(id); };
  }, [active, ms]);
}
