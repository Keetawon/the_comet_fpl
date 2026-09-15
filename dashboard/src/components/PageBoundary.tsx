import { Component, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

/** A missing lazy chunk after publication must not take down the navigation shell. */
export class PageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="space-y-3 p-6">
        <p>This page could not load. Reload to try again.</p>
        <Button onClick={() => window.location.reload()}>Reload page</Button>
      </div>
    );
  }
}
