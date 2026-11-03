import { lazy, Suspense } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { SkeletonPage } from "./components/ui";
import { useI18n } from "./hooks/useI18n";
const NotificationsPage = lazy(() => import("./pages/Notifications").then((module) => ({ default: module.NotificationsPage })));
const ReferencesPage = lazy(() => import("./pages/References").then((module) => ({ default: module.ReferencesPage })));
const ProductsPage = lazy(() => import("./pages/Products").then((module) => ({ default: module.ProductsPage })));
const CreativeKnowledgePage = lazy(() => import("./pages/CreativeKnowledge").then((module) => ({ default: module.CreativeKnowledgePage })));

export default function App() {
  return (
    <Suspense fallback={<SkeletonPage />}><Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate replace to="/products" />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="products" element={<ProductsPage />} />
        <Route path="references" element={<ReferencesPage />} />
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
