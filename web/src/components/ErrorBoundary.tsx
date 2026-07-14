// A render-error boundary. React has no hook equivalent (error boundaries must be
// class components), so this is the one class in the app. A caught error swaps the
// subtree for `fallback` instead of unmounting the whole tree to a blank page.
//
// `resetKey` lets a caught error clear itself when the surrounding context changes
// (e.g. the route or the open entry) — without it, a boundary stays "failed" until
// a full reload even after the user has navigated away from whatever threw.

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback: ReactNode;
  /** When this value changes after a failure, the boundary resets and retries. */
  resetKey?: unknown;
}

interface State {
  failed: boolean;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // No error-reporting backend yet; surface it in the console for local debugging.
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  componentDidUpdate(prev: Props): void {
    if (this.state.failed && prev.resetKey !== this.props.resetKey) {
      this.setState({ failed: false });
    }
  }

  render(): ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
