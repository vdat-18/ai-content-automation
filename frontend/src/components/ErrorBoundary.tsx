import { Component, type ReactNode } from "react";
import { I18nContext } from "../hooks/useI18n";
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <I18nContext.Consumer>{(i18n) => {
      const t = i18n?.t ?? ((source: string) => source);
      return <section className="error-panel" role="alert"><h1>{t("This view could not be displayed")}</h1><p>{t("Persisted backend data was not changed.")}</p><button className="primary-button" onClick={() => window.location.reload()}>{t("Reload dashboard")}</button></section>;
    }}</I18nContext.Consumer>;
    return this.props.children;
  }
}
