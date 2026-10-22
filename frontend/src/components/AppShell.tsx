import { Suspense, useEffect, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import {
  AlertTriangle,
  BarChart3,
  Bell,
  BrainCircuit,
  Bot,
  ChevronDown,
  CircleGauge,
  Database,
  GitBranch,
  Image,
  LibraryBig,
  Menu,
  MessageSquare,
  Clapperboard,
  Moon,
  Sun,
  Search,
  X,
  CircleDollarSign,
} from "lucide-react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useCreativeJobs, useNotifications, usePilotDashboard } from "../hooks/usePilotDashboard";
import { useWorkspace } from "../hooks/useWorkspace";
import { SkeletonPage } from "./ui";
import { useI18n, type Language } from "../hooks/useI18n";
import { dashboardStreamLabels } from "../marketing/labels";
import { useTheme } from "../hooks/useTheme";

type NavGroup = "marketing" | "creative" | "research" | "activity" | "system";
type NavItem = { to: string; label: string; icon: typeof CircleGauge; count?: boolean; exception?: boolean; group: NavGroup };

const SIDEBAR_WIDTH_KEY = "aic-sidebar-width";
const legacyLocalModelsEnabled = import.meta.env.VITE_ENABLE_LEGACY_LOCAL_MODELS === "true";
const clampSidebarWidth = (value: number) => Math.min(420, Math.max(208, value));
const readStoredSidebarWidth = () => {
  const stored = Number(window.localStorage.getItem(SIDEBAR_WIDTH_KEY));
  return Number.isFinite(stored) && stored >= 208 && stored <= 420 ? clampSidebarWidth(stored) : null;
};

const nav: NavItem[] = [
  { to: "/", label: "Today", icon: CircleGauge, group: "marketing" },
  { to: "/performance", label: "Performance", icon: BarChart3, group: "marketing" },
  { to: "/creative-production", label: "Creative Production", icon: Clapperboard, group: "creative" },
  { to: "/approvals", label: "Needs approval", icon: Bell, count: true, group: "creative" },
  { to: "/creatives", label: "Creative Library", icon: Image, group: "creative" },
  { to: "/research-crawler", label: "Research crawler", icon: Search, group: "research" },
  { to: "/research-library", label: "Research Library", icon: LibraryBig, group: "research" },
  { to: "/second-brain", label: "SecondBrain", icon: BrainCircuit, group: "research" },
  ...(legacyLocalModelsEnabled
    ? [{ to: "/media-lab", label: "Create content", icon: Clapperboard, group: "creative" as const }]
    : []),
  { to: "/workflows", label: "AI activity", icon: GitBranch, group: "activity" },
  { to: "/exceptions", label: "Exceptions", icon: AlertTriangle, exception: true, group: "system" },
  { to: "/data-sources", label: "Data sources", icon: Database, group: "system" },
  { to: "/ai-usage", label: "AI usage & cost", icon: CircleDollarSign, group: "system" },
  ...(legacyLocalModelsEnabled
    ? [{ to: "/model-lab", label: "Model Lab", icon: MessageSquare, group: "system" as const }]
    : []),
];

export function AppShell() {
  const { language, setLanguage, t } = useI18n();
  const { theme, setTheme } = useTheme();
  const { brand, setBrand, notify } = useWorkspace();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [mobileLayout, setMobileLayout] = useState(() => window.matchMedia("(max-width: 900px)").matches);
  const [sidebarWidth, setSidebarWidth] = useState<number | null>(readStoredSidebarWidth);
  const sidebarDrag = useRef<{ pointerId: number; startX: number; startWidth: number } | null>(null);
  const sidebarRef = useRef<HTMLElement>(null);
  const mainRef = useRef<HTMLElement>(null);
  const menuTriggerRef = useRef<HTMLButtonElement>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const location = useLocation();
  const navigate = useNavigate();
  const pilot = usePilotDashboard();
  const creatives = useCreativeJobs();
  const notifications = useNotifications();

  useEffect(() => {
    if (sidebarWidth !== null) window.localStorage.setItem(SIDEBAR_WIDTH_KEY, String(sidebarWidth));
  }, [sidebarWidth]);

  const startSidebarDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (mobileLayout || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    sidebarDrag.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: sidebarRef.current?.getBoundingClientRect().width ?? 264,
    };
    event.currentTarget.dataset.active = "true";
    document.body.classList.add("sidebar-resizing");
  };
  const moveSidebarDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = sidebarDrag.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    setSidebarWidth(clampSidebarWidth(drag.startWidth + event.clientX - drag.startX));
  };
  const endSidebarDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (sidebarDrag.current?.pointerId !== event.pointerId) return;
    sidebarDrag.current = null;
    delete event.currentTarget.dataset.active;
    document.body.classList.remove("sidebar-resizing");
  };
  const resetSidebarWidth = (event: ReactPointerEvent<HTMLDivElement> | React.MouseEvent<HTMLDivElement>) => {
    sidebarDrag.current = null;
    delete event.currentTarget.dataset.active;
    document.body.classList.remove("sidebar-resizing");
    window.localStorage.removeItem(SIDEBAR_WIDTH_KEY);
    setSidebarWidth(null);
  };
  const backendBrands = [
    ...(pilot.data?.approvals.map((item) => item.brand_id) ?? []),
    ...(pilot.data?.workflows.map((item) => item.brand_id) ?? []),
    ...(pilot.data?.exceptions.map((item) => item.brand_id) ?? []),
  ].filter((item): item is string => Boolean(item));
  const brands = [...new Set(backendBrands)];
  const pending = pilot.data?.summary.pending_approvals ?? 0;
  const issues = pilot.data?.summary.open_exceptions ?? 0;
  const currentNavItem = nav.find((item) => item.to === "/"
    ? location.pathname === "/"
    : location.pathname === item.to || location.pathname.startsWith(`${item.to}/`));

  const closeMobile = () => setMobileOpen(false);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const change = () => { setMobileLayout(media.matches); if (!media.matches) setMobileOpen(false); };
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    const sidebar = sidebarRef.current!;
    const main = mainRef.current!;
    sidebar.inert = mobileLayout && !mobileOpen;
    main.inert = mobileLayout && mobileOpen;
    if (!mobileLayout || !mobileOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    sidebar.querySelector<HTMLButtonElement>(".sidebar-close")?.focus();
    return () => {
      main.inert = false;
      if (previous?.isConnected && previous.getClientRects().length) previous.focus();
    };
  }, [mobileLayout, mobileOpen]);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (mainRef.current?.inert) { mainRef.current.inert = false; menuTriggerRef.current?.focus(); }
        setMobileOpen(false);
        setSearchOpen((value) => !value);
      }
      if (event.key === "Escape") setMobileOpen(false);
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, []);
  const searchable = [
    ...nav.map((item) => ({ to: item.to, label: t(item.label), detail: t("Page") })),
    ...(pilot.data?.approvals.map((item) => ({ to: item.action_path, label: item.title, detail: dashboardStreamLabels[item.workstream] + " · " + (item.brand_id ?? "shared") })) ?? []),
    ...(pilot.data?.workflows.map((item) => ({ to: item.action_path, label: item.title, detail: dashboardStreamLabels[item.workstream] + " · " + t(item.state.replaceAll("_", " ")) })) ?? []),
    ...(pilot.data?.exceptions.map((item) => ({ to: item.action_path, label: item.title, detail: t("Exception") + " · " + dashboardStreamLabels[item.workstream] })) ?? []),
    ...(creatives.data?.items.map((item) => ({ to: `/creatives/${item.job_id}`, label: item.display_title, detail: t("Creative") + " · " + item.status.replaceAll("_", " ") })) ?? []),
  ];
  const matches = query.trim() ? searchable.filter((item) => (item.label + " " + item.detail).toLowerCase().includes(query.trim().toLowerCase())).slice(0, 20) : searchable.slice(0, 10);

  return (
    <div
      className="app-shell"
      style={sidebarWidth !== null && !mobileLayout ? ({ "--sidebar-w": `${sidebarWidth}px` } as CSSProperties) : undefined}
    >
      {mobileOpen && <button className="mobile-backdrop" onClick={closeMobile} aria-label={t("Close menu")} tabIndex={-1} />}
      <aside ref={sidebarRef} id="workspace-navigation" className={`sidebar ${mobileOpen ? "sidebar--open" : ""}`} aria-hidden={mobileLayout && !mobileOpen ? true : undefined} role={mobileLayout && mobileOpen ? "dialog" : undefined} aria-modal={mobileLayout && mobileOpen ? true : undefined} aria-label={t("Workspace navigation")} onKeyDown={(event) => {
        if (!mobileLayout || !mobileOpen || event.key !== "Tab") return;
        const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('a[href], button:not(:disabled), select:not(:disabled), summary')).filter((item) => item.getClientRects().length);
        const first = controls[0];
        const last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }}>
        <div className="brand-lockup">
          <img
            className="brand-logo"
            src={import.meta.env.BASE_URL + "assets/aicontent-logo.svg"}
            alt="Aic Bros"
          />
          <span className="brand-product">{t("Marketing operations")}</span>
          <button className="icon-button sidebar-close" aria-label={t("Close menu")} onClick={closeMobile}><X size={20} /></button>
        </div>

        {location.pathname === "/ai-usage" && brands.length > 0 && (
          <label className="workspace-switcher"><span className="workspace-avatar">NX</span><div><small>{t("AI usage brand")}</small>
            <select aria-label={t("AI usage brand")} value={brand} onChange={(event) => setBrand(event.target.value)}>
              <option value="all">{t("All brands")}</option>{brands.map((item) => <option key={item}>{item}</option>)}
            </select></div></label>
        )}

        <nav>
          <p className="nav-label">{t("Marketing")}</p>
          {nav.filter((item) => item.group === "marketing").map(({ to, label, icon: Icon, count }) => (
            <NavLink key={to} to={to} end={to === "/"} onClick={closeMobile}>
              <Icon size={18} /><span>{t(label)}</span>{count && pending > 0 && <em>{pending}</em>}
            </NavLink>
          ))}
          <p className="nav-label nav-label--spaced">{t("Creative workflow")}</p>
          {nav.filter((item) => item.group === "creative").map(({ to, label, icon: Icon, count }) => (
            <NavLink key={to} to={to} onClick={closeMobile}>
              <Icon size={18} /><span>{t(label)}</span>{count && pending > 0 && <em>{pending}</em>}
            </NavLink>
          ))}
          <p className="nav-label nav-label--spaced">{t("Research & knowledge")}</p>
          {nav.filter((item) => item.group === "research").map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={closeMobile}>
              <Icon size={18} /><span>{t(label)}</span>
            </NavLink>
          ))}
          <p className="nav-label nav-label--spaced">{t("Automation")}</p>
          {nav.filter((item) => item.group === "activity").map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={closeMobile}><Icon size={18} /><span>{t(label)}</span></NavLink>
          ))}
          <details className="operator-nav" open={nav.some((item) => item.group === "system" && (location.pathname === item.to || location.pathname.startsWith(`${item.to}/`)))}>
            <summary><span>{t("Operations")}</span><ChevronDown size={15} /></summary>
            <div>
              {nav.filter((item) => item.group === "system").map(({ to, label, icon: Icon, exception }) => (
                <NavLink key={to} to={to} onClick={closeMobile}>
                  <Icon size={18} /><span>{t(label)}</span>{exception && issues > 0 && <em className="danger-count">{issues}</em>}
                </NavLink>
              ))}
            </div>
          </details>
        </nav>

        <div className="automation-card">
          <div><Bot size={19} /><span className="live-dot" /></div>
          <strong>{t("AI is working")}</strong>
          <p>{t("{count} active items", { count: pilot.data?.summary.active_commands ?? 0 })}</p>
        </div>
        <div className="user-card"><span>LP</span><div><strong>{t("Local pilot")}</strong><small>{t("No sign-in")}</small></div><ChevronDown size={15} /></div>
        <div
          className="sidebar-resizer"
          role="separator"
          aria-orientation="vertical"
          tabIndex={0}
          aria-label={t("Resize sidebar navigation")}
          title={t("Drag to resize · double-click to reset")}
          onPointerDown={startSidebarDrag}
          onPointerMove={moveSidebarDrag}
          onPointerUp={endSidebarDrag}
          onPointerCancel={endSidebarDrag}
          onDoubleClick={resetSidebarWidth}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            setSidebarWidth(clampSidebarWidth((sidebarWidth ?? 264) + (event.key === "ArrowRight" ? 16 : -16)));
          }}
        />
      </aside>

      <main ref={mainRef} className="main-area">
        <header className="topbar">
          <button ref={menuTriggerRef} className="icon-button mobile-menu" aria-label={t("Open menu")} aria-expanded={mobileOpen} aria-controls="workspace-navigation" onClick={() => setMobileOpen(true)}><Menu size={21} /></button>
          <div className="topbar-context">
            <span>{t("Marketing operations")}</span>
            <strong>{t(currentNavItem?.label ?? "Workspace")}</strong>
          </div>
          <button className="global-search" aria-label={t("Search workspace")} onClick={() => { setQuery(""); setSearchOpen(true); }}><Search size={17} /><span>{t("Search records across the dashboard")}</span><kbd>Ctrl / ⌘ K</kbd></button>
          <div className="topbar-actions">
            <button className="icon-button" onClick={() => { const newTheme = theme === "dark" ? "light" : "dark"; setTheme(newTheme); notify(`Switched to ${newTheme} mode`, "success"); }} aria-label={t("Toggle theme")}>
              {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
            </button>
            <label className="language-switcher"><span className="sr-only">{t("Interface language")}</span><select aria-label={t("Interface language")} value={language} onChange={(event) => { setLanguage(event.target.value as Language); notify(`Language changed`, 'success'); }}><option value="vi">VI</option><option value="en">EN</option></select></label>
            <span className="environment-pill"><i /> {t("Connected")}</span>
            <NavLink aria-label={t("Open notifications")} className="icon-button notification-button" to="/notifications"><Bell size={18} />{(notifications.data?.unread ?? 0) > 0 && <span />}</NavLink>
          </div>
        </header>
        <div className="page-content">
          <Suspense fallback={<SkeletonPage />}><Outlet /></Suspense>
        </div>
      </main>

      {searchOpen && (
        <div className="omnibar-backdrop" onClick={() => setSearchOpen(false)}>
          <div className="omnibar" role="dialog" aria-modal="true" aria-label={t("Search workspace")} onClick={(e) => e.stopPropagation()} onKeyDown={(event) => {
            if (event.key === "Escape") { event.preventDefault(); setSearchOpen(false); }
            if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
            const links = Array.from(event.currentTarget.querySelectorAll<HTMLAnchorElement>(".omnibar-results a"));
            if (!links.length) return;
            event.preventDefault();
            const index = links.indexOf(document.activeElement as HTMLAnchorElement);
            links[(index + (event.key === "ArrowDown" ? 1 : -1) + links.length) % links.length]?.focus();
          }}>
            <div className="omnibar-header">
              <Search size={22} className="omnibar-icon" />
              <input
                autoFocus
                aria-label={t("Search query")}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("Search approval, workflow, exception or creative")}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && matches[0]) { navigate(matches[0].to); setSearchOpen(false); setQuery(""); }
                  else if (event.key === "ArrowDown") {
                    event.preventDefault();
                    const links = Array.from(event.currentTarget.closest(".omnibar")!.querySelectorAll<HTMLAnchorElement>(".omnibar-results a"));
                    links[0]?.focus();
                  }
                }}
              />
              <span className="omnibar-shortcut">ESC</span>
            </div>
            <div className="omnibar-results">
              <p className="omnibar-label">{query ? t("{count} results in this workspace", { count: matches.length }) : t("QUICK NAVIGATION")}</p>
              {matches.map((item) => (
                <NavLink key={item.to} to={item.to} onClick={() => { setSearchOpen(false); setQuery(""); }}>
                  <strong>{item.label}</strong>
                  <small>{item.detail}</small>
                </NavLink>
              ))}
              {!matches.length && <p className="omnibar-empty">{t("No matching records. Try another workflow, exception, or creative title.")}</p>}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
