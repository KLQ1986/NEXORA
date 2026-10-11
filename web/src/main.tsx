import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { listenForChanges, usePoll, type Run } from "./api";
import Costs from "./Costs";
import Home from "./Home";
import Library from "./Library";
import Notices from "./Notices";
import Projects from "./Projects";
import Runs from "./Runs";
import System from "./System";

const PAGES = [
  { path: "/", label: "Tổng quan", view: null },
  { path: "/thu-vien", label: "Thư viện", view: Library },
  { path: "/du-an", label: "Dự án", view: null },
  { path: "/tien-trinh", label: "Tiến trình", view: Runs },
  { path: "/chi-phi", label: "Chi phí", view: Costs },
  { path: "/thong-bao", label: "Thông báo", view: Notices },
  { path: "/he-thong", label: "Hệ thống", view: System },
];

function App() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => { const on = () => setPath(window.location.pathname); window.addEventListener("popstate", on); return () => window.removeEventListener("popstate", on); }, []);
  const go = (to: string) => { window.history.pushState({}, "", to); setPath(to); };
  const { data: runs } = usePoll<Run[]>("/api/v1/runs", 4000);
  const working = (runs ?? []).filter((r) => r.status === "running" && !r.held).length;
  const { data: home } = usePoll<{ attention: unknown[]; gaps: unknown[]; offline_volumes: unknown[]; problems: unknown[] }>("/api/v1/home", 4000);
  const waiting = home ? home.attention.length + home.gaps.length + home.offline_volumes.length + home.problems.length : 0;
  const { data: notices } = usePoll<{ unread: number }>("/api/v1/notifications", 5000);
  const page = PAGES.find((p) => p.path !== "/" && path.startsWith(p.path)) ?? PAGES[0];
  const View = page.view;
  const sub = path.startsWith("/du-an/") ? path.slice("/du-an/".length) : null;
  return (
    <div className="flex h-full flex-col md:flex-row">
      <nav className="flex shrink-0 items-center gap-1 border-b border-line bg-surface px-3 py-2 md:w-48 md:flex-col md:items-stretch md:border-b-0 md:border-r md:px-3 md:py-5" aria-label="Điều hướng chính">
        <p className="mr-4 px-2 text-lg font-semibold tracking-[0.18em] md:mb-6 md:mr-0">NEXORA</p>
        {PAGES.map((p) => (
          <a key={p.path} href={p.path} onClick={(e) => { e.preventDefault(); go(p.path); }} aria-current={p === page ? "page" : undefined}
             className={`flex items-center justify-between rounded px-2 py-1.5 transition-colors ${p === page ? "bg-raised font-medium" : "text-mute hover:text-ink"}`}>
            {p.label}
            {p.path === "/" && waiting > 0 && <span className="tc ml-2 rounded-full bg-cue px-1.5 text-xs font-semibold text-canvas" title="Số việc đang chờ bạn">{waiting}</span>}

            {p.path === "/thong-bao" && (notices?.unread ?? 0) > 0 && p !== page && <span className="tc ml-2 rounded-full bg-raised px-1.5 text-xs font-semibold" title="Thông báo chưa đọc">{notices?.unread}</span>}
          </a>
        ))}
        <p className="mt-auto hidden px-2 text-xs leading-relaxed text-mute md:block">{working > 0 ? `Đang chạy ${working} việc` : "Máy đang rảnh"}<br />Chỉ chạy trên máy này</p>
      </nav>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">{View ? <View /> : page.path === "/" ? <Home go={go} /> : <Projects sub={sub} go={go} />}</main>
    </div>
  );
}

listenForChanges();
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
