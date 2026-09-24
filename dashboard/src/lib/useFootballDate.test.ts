import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useFootballDate } from "./useFootballDate";

afterEach(() => vi.useRealTimers());

it("rolls an open tab over at UK midnight and clears its timer on unmount", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-23T22:59:30Z"));
  const { result, unmount } = renderHook(() => useFootballDate());
  expect(result.current).toBe("2026-09-23");
  act(() => vi.advanceTimersByTime(60_000));
  expect(result.current).toBe("2026-09-24");
  unmount();
  expect(vi.getTimerCount()).toBe(0);
});
