import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { WorkspaceProvider } from "./components/WorkspaceProvider";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { I18nProvider } from "./i18n";
import { ThemeProvider } from "./hooks/useTheme";
/* Self-hosted fonts keep the dashboard pixel-identical when deployed offline. */
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "./styles.css";
import "./marketing/marketing.css";
import "./marketing/shared.css";
import "./marketing/creative.css";
import "./marketing/workspace.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15_000, retry: false },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider><I18nProvider><ErrorBoundary><WorkspaceProvider><BrowserRouter basename="/dashboard">
        <App />
      </BrowserRouter></WorkspaceProvider></ErrorBoundary></I18nProvider></ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
);
