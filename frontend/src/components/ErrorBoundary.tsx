import { Component, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section className="page" role="alert">
        <h1>Something went wrong on this page</h1>
        <p className="muted">Your work is safe. Reload the page to continue.</p>
        <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => window.location.reload()}>Reload</button>
      </section>
    );
  }
}
