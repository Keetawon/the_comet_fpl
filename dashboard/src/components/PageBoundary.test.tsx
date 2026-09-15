import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PageBoundary } from "./PageBoundary";

afterEach(() => vi.restoreAllMocks());

it("keeps a load failure recoverable and resets when navigating to another page", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  function FailedChunk(): never { throw new Error("Failed to fetch dynamically imported module"); }
  const { rerender } = render(<PageBoundary key="old"><FailedChunk /></PageBoundary>);
  expect(screen.getByRole("alert")).toHaveTextContent("This page could not load");
  expect(screen.getByRole("button", { name: "Reload page" })).toBeInTheDocument();
  rerender(<PageBoundary key="new"><h1>Another page</h1></PageBoundary>);
  expect(screen.getByRole("heading", { name: "Another page" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
