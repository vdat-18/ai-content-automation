import { useQuery } from "@tanstack/react-query";
import { Bell, Film, Home, Menu, Moon, Package, Sparkles, Sun } from "lucide-react";
import { Suspense, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useNotifications } from "../hooks/useNotifications";
import { useTheme } from "../hooks/useTheme";
import { pilotApi } from "../services/pilotApi";
import { Skeleton } from "./ui";

const NAV = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/products", label: "Products", icon: Package, end: false },
  { to: "/videos", label: "My videos", icon: Film, end: false },
  { to: "/memory", label: "AI memory", icon: Sparkles, end: false },
];

export function Shell() {
  const { theme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const notifications = useNotifications();
  const rules = useQuery({ queryKey: ["creative-knowledge"], queryFn: ({ signal }) => pilotApi.creativeKnowledge(undefined, signal) });
  const learned = (rules.data?.items ?? []).filter((item) => item.status === "approved").length;
  return (
    <div className="app">
      <aside className={`sidebar${open ? " open" : ""}`} aria-label="Main menu">
        <div className="brand"><span className="brand-mark">AI</span>AI Content</div>
        <nav className="nav">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}>
              <Icon size={20} aria-hidden="true" />{label}
            </NavLink>
          ))}
        </nav>
        <div className="side-note">
          <strong>{learned === 1 ? "AI follows 1 rule" : `AI follows ${learned} rules`}</strong>
          Every time you point out a mistake, the AI avoids it next time.
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="icon-button menu-button" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(!open)}><Menu size={22} /></button>
          <button className="icon-button" aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>
          <NavLink to="/notifications" className="icon-button" aria-label="Notifications">
            <Bell size={20} />{(notifications.data?.unread ?? 0) > 0 && <span className="dot" />}
          </NavLink>
        </header>
        <Suspense fallback={<div className="page"><Skeleton /></div>}><Outlet /></Suspense>
      </div>
    </div>
  );
}
