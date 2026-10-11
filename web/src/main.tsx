import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { usePoll, type Run } from "./api";
import Library from "./Library";
import Runs from "./Runs";
import System from "./System";

const PAGES = [
  { path: "/", label: "Thư viện", view: Library },
  { path: "/tien-trinh", label: "Tiến trình", view: Runs },
  { path: "/he-thong", label: "Hệ thống", view: System },
];

function App() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => { const on = () => setPath(window.location.pathname); window.addEventListener("popstate", on); return () => window.removeEventListener("popstate", on); }, []);
  const go = (to: string) => { window.history.pushState({}, "", to); setPath(to); };
  const { data: runs } = usePoll<Run[]>("/api/v1/runs", 4000);
  const waiting = (runs ?? []).filter((r) => r.status === "blocked" || r.status === "waiting_review").length;
  const page = PAGES.find((p) => p.path === path) ?? PAGES[0];
  const View = page.view;
  return (
    <div className="flex h-full flex-col md:flex-row">
      <nav className="flex shrink-0 items-center gap-1 border-b border-line bg-surface px-3 py-2 md:w-48 md:flex-col md:items-stretch md:border-b-0 md:border-r md:px-3 md:py-5" aria-label="Điều hướng chính">
        <p className="mr-4 px-2 text-lg font-semibold tracking-[0.18em] md:mb-6 md:mr-0">NEXORA</p>
        {PAGES.map((p) => (
          <a key={p.path} href={p.path} onClick={(e) => { e.preventDefault(); go(p.path); }} aria-current={p === page ? "page" : undefined}
             className={`flex items-center justify-between rounded px-2 py-1.5 transition-colors ${p === page ? "bg-raised font-medium" : "text-mute hover:text-ink"}`}>
            {p.label}
            {p.path === "/tien-trinh" && waiting > 0 && <span className="tc ml-2 rounded-full bg-cue px-1.5 text-xs font-semibold text-canvas" title="Số việc đang cần bạn">{waiting}</span>}
          </a>
        ))}
      </nav>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col"><View /></main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
