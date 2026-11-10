import { lazy, Suspense } from "react";
import { Link, Navigate, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { Skeleton } from "./components/ui";

const HomePage = lazy(() => import("./pages/Home").then((module) => ({ default: module.HomePage })));
const ProductsPage = lazy(() => import("./pages/Products").then((module) => ({ default: module.ProductsPage })));
const VideosPage = lazy(() => import("./pages/Videos").then((module) => ({ default: module.VideosPage })));
const StudioPage = lazy(() => import("./pages/Studio").then((module) => ({ default: module.StudioPage })));
const MemoryPage = lazy(() => import("./pages/Memory").then((module) => ({ default: module.MemoryPage })));
const NotificationsPage = lazy(() => import("./pages/Notifications").then((module) => ({ default: module.NotificationsPage })));

export default function App() {
  return (
    <Suspense fallback={<div className="page"><Skeleton /></div>}>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<HomePage />} />
          <Route path="products" element={<ProductsPage />} />
          <Route path="videos" element={<VideosPage />} />
          <Route path="studio/:productId" element={<StudioPage />} />
          <Route path="memory" element={<MemoryPage />} />
          <Route path="notifications" element={<NotificationsPage />} />
          {/* links from the old dashboard keep working */}
          <Route path="briefs" element={<Navigate replace to="/videos" />} />
          <Route path="outputs" element={<Navigate replace to="/videos" />} />
          <Route path="second-brain" element={<Navigate replace to="/memory" />} />
          <Route path="references" element={<Navigate replace to="/memory?tab=scenes" />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

function NotFound() {
  return (
    <section className="page" role="alert">
      <h1>Page not found</h1>
      <p className="muted">The page you asked for does not exist.</p>
      <Link className="btn btn-primary" style={{ alignSelf: "flex-start" }} to="/">Back to home</Link>
    </section>
  );
}
