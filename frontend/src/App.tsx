import { lazy, Suspense } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { SkeletonPage } from "./components/ui";
import { useI18n } from "./hooks/useI18n";
const NotificationsPage = lazy(() => import("./pages/Notifications").then((module) => ({ default: module.NotificationsPage })));
const ApprovalsPage = lazy(() => import("./pages/Approvals").then((module) => ({ default: module.ApprovalsPage })));
const CreativeLibraryPage = lazy(() => import("./pages/CreativeLibrary").then((module) => ({ default: module.CreativeLibraryPage })));
const CreativeDetailPage = lazy(() => import("./pages/CreativeJobs").then((module) => ({ default: module.CreativeDetailPage })));
const OverviewPage = lazy(() => import("./pages/Overview").then((module) => ({ default: module.OverviewPage })));
const DataSourcesPage = lazy(() => import("./pages/Operations").then((module) => ({ default: module.DataSourcesPage })));
const ExceptionsPage = lazy(() => import("./pages/Operations").then((module) => ({ default: module.ExceptionsPage })));
const PerformancePage = lazy(() => import("./pages/Operations").then((module) => ({ default: module.PerformancePage })));
const WorkflowsPage = lazy(() => import("./pages/Operations").then((module) => ({ default: module.WorkflowsPage })));
const CreativeProductionPage = lazy(() => import("./pages/Operations").then((module) => ({ default: module.CreativeProductionPage })));
const CreativeAutomationDetailPage = lazy(() => import("./pages/Operations").then((module) => ({ default: module.CreativeAutomationDetailPage })));
const AIUsagePage = lazy(() => import("./pages/AIUsage").then((module) => ({ default: module.AIUsagePage })));
const ModelLabPage = lazy(() => import("./pages/ModelLab").then((module) => ({ default: module.ModelLabPage })));
const MediaLabPage = lazy(() => import("./pages/MediaLab").then((module) => ({ default: module.MediaLabPage })));
const ResearchCrawlerPage = lazy(() => import("./pages/ResearchCrawler").then((module) => ({ default: module.ResearchCrawlerPage })));
const ResearchLibraryPage = lazy(() => import("./pages/ResearchLibrary").then((module) => ({ default: module.ResearchLibraryPage })));
const CreativeKnowledgePage = lazy(() => import("./pages/CreativeKnowledge").then((module) => ({ default: module.CreativeKnowledgePage })));
const legacyLocalModelsEnabled = import.meta.env.VITE_ENABLE_LEGACY_LOCAL_MODELS === "true";

export default function App() {
  return (
    <Suspense fallback={<SkeletonPage />}><Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="creatives" element={<CreativeLibraryPage />} />
        <Route path="creatives/:creativeId" element={<CreativeDetailPage />} />
        <Route path="performance" element={<PerformancePage />} />
        <Route path="workflows" element={<WorkflowsPage />} />
        <Route path="creative-production" element={<CreativeProductionPage />} />
        <Route path="creative-production/:requestId" element={<CreativeAutomationDetailPage />} />
        <Route path="exceptions" element={<ExceptionsPage />} />
        <Route path="data-sources" element={<DataSourcesPage />} />
        <Route path="ai-usage" element={<AIUsagePage />} />
        {legacyLocalModelsEnabled && <Route path="model-lab" element={<ModelLabPage />} />}
        {legacyLocalModelsEnabled && <Route path="media-lab" element={<MediaLabPage />} />}
        <Route path="media-library" element={<Navigate replace to="/creatives?view=media" />} />
        <Route path="research-crawler" element={<ResearchCrawlerPage />} />
        <Route path="research-library" element={<ResearchLibraryPage />} />
        <Route path="second-brain" element={<CreativeKnowledgePage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes></Suspense>
  );
}

function NotFoundPage() {
  const { t } = useI18n();
  return (
    <section className="empty-state" role="alert">
      <h1>{t("Page not found")}</h1>
      <p>{t("The page or record you requested does not exist.")}</p>
      <Link className="primary-button" to="/">{t("Back to overview")}</Link>
    </section>
  );
}
