import { act, renderHook } from "@testing-library/react";
import { useCallback } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAsync } from "./useAsync";
import { usePolling } from "./usePolling";

describe("usePolling", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("ticks while active and stops when deactivated or unmounted", async () => {
    const tick = vi.fn().mockResolvedValue(undefined);
    const { rerender, unmount } = renderHook(({ on }) => usePolling(tick, on, 1000), { initialProps: { on: true } });
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(tick).toHaveBeenCalledTimes(3);
    rerender({ on: false });
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(tick).toHaveBeenCalledTimes(3);
    rerender({ on: true });
    unmount();
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(tick).toHaveBeenCalledTimes(3);
  });

  it("never overlaps slow ticks", async () => {
    let running = 0, max = 0;
    const tick = vi.fn(async () => { running++; max = Math.max(max, running); await new Promise((r) => setTimeout(r, 2500)); running--; });
    renderHook(() => usePolling(tick, true, 1000));
    await act(async () => { await vi.advanceTimersByTimeAsync(7000); });
    expect(max).toBe(1);
  });
});

describe("useAsync", () => {
  it("ignores a stale response that resolves after a newer one", async () => {
    let resolveSlow: (v: string) => void = () => undefined;
    const slow = new Promise<string>((r) => { resolveSlow = r; });
    const { result, rerender } = renderHook(({ p }) => useAsync(useCallback(() => p, [p])), { initialProps: { p: slow } });
    rerender({ p: Promise.resolve("fresh") });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { resolveSlow("stale"); await Promise.resolve(); });
    expect(result.current.data).toBe("fresh");
  });
  it("surfaces errors as readable messages", async () => {
    const failing = () => Promise.reject(new Error("boom"));
    const { result } = renderHook(() => useAsync(failing));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.error).toBe("boom");
    expect(result.current.loading).toBe(false);
  });
});
