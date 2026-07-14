// ErrorBoundary is the app's one crash safety net (H1), so verify it actually
// catches a throwing child, shows the fallback, and recovers when resetKey changes.

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "../src/components/ErrorBoundary";

function Boom(): never {
  throw new Error("kaboom");
}

// React logs caught errors to console.error; silence it for these expected throws.
afterEach(() => vi.restoreAllMocks());

describe("ErrorBoundary", () => {
  it("renders children when nothing throws", () => {
    render(
      <ErrorBoundary fallback={<p>fallback</p>}>
        <p>ok</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("ok")).toBeTruthy();
    expect(screen.queryByText("fallback")).toBeNull();
  });

  it("shows the fallback when a child throws", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <ErrorBoundary fallback={<p>fallback</p>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("fallback")).toBeTruthy();
  });

  it("recovers when resetKey changes after a failure", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { rerender } = render(
      <ErrorBoundary resetKey="a" fallback={<p>fallback</p>}>
        <Boom />
      </ErrorBoundary>,
    );
    expect(screen.getByText("fallback")).toBeTruthy();

    // New resetKey (e.g. navigation) clears the caught error and retries children.
    rerender(
      <ErrorBoundary resetKey="b" fallback={<p>fallback</p>}>
        <p>recovered</p>
      </ErrorBoundary>,
    );
    expect(screen.getByText("recovered")).toBeTruthy();
    expect(screen.queryByText("fallback")).toBeNull();
  });
});
