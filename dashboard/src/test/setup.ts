import "@testing-library/jest-dom/vitest";

// Radix Popover measures its trigger in a layout effect. jsdom intentionally has no
// ResizeObserver, so provide the inert observer needed by interaction tests.
if (!("ResizeObserver" in globalThis)) {
  Object.defineProperty(globalThis, "ResizeObserver", {
    configurable: true,
    value: class MockResizeObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  });
}
