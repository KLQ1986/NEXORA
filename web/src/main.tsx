import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { listenForChanges, post, usePoll, type Run } from "./api";
import Costs from "./Costs";
import Home from "./Home";
import Library from "./Library";
import Notices from "./Notices";
import Projects from "./Projects";
import Runs from "./Runs";
import System from "./System";
import { Icon } from "./parts";

const PAGES = [
  { path: "/", label: "Tổng quan", icon: "home", view: null, group: 0 },
  { path: "/du-an", label: "Dự án", icon: "clapper", view: null, group: 0 },
  { path: "/thu-vien", label: "Thư viện", icon: "film", view: Library, group: 0 },
  { path: "/tien-trinh", label: "Tiến trình", icon: "pulse", view: Runs, group: 1 },
  { path: "/chi-phi", label: "Chi phí", icon: "gauge", view: Costs, group: 1 },
  { path: "/thong-bao", label: "Thông báo", icon: "bell", view: Notices, group: 1 },
  { path: "/he-thong", label: "Hệ thống", icon: "sliders", view: System, group: 1 },
];
const GROUPS = ["Sản xuất", "Vận hành"];

/** The mark: three takes of different lengths on a timeline. */
function Mark() {
  return <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true"><rect x="1" y="3" width="20" height="4" rx="1" fill="var(--color-ink)" /><rect x="1" y="9" width="13" height="4" rx="1" fill="var(--color-cue)" /><rect x="1" y="15" width="17" height="4" rx="1" fill="var(--color-ink)" opacity=".45" /></svg>;
}

function App() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => { const on = () => setPath(window.location.pathname); window.addEventListener("popstate", on); return () => window.removeEventListener("popstate", on); }, []);
  const go = (to: string) => { window.history.pushState({}, "", to); setPath(to); };
  const { data: runs } = usePoll<Run[]>("/api/v1/runs", 4000);
  const working = (runs ?? []).filter((r) => r.status === "running" && !r.held).length;
  const { data: home } = usePoll<{ attention: unknown[]; gaps: unknown[]; offline_volumes: unknown[]; problems: unknown[]; kill_switch: boolean }>("/api/v1/home", 4000);
  const waiting = home ? home.attention.length + home.gaps.length + home.offline_volumes.length + home.problems.length : 0;
  const { data: notices } = usePoll<{ unread: number }>("/api/v1/notifications", 5000);
  const page = PAGES.find((p) => p.path !== "/" && path.startsWith(p.path)) ?? PAGES[0];
  const View = page.view;
  const sub = path.startsWith("/du-an/") ? path.slice("/du-an/".length) : null;
  const count = (p: (typeof PAGES)[number]) => (p.path === "/" ? waiting : p.path === "/thong-bao" && p !== page ? notices?.unread ?? 0 : 0);
  return (
    <div className="flex h-full flex-col md:flex-row">
      <nav className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-line bg-surface px-3 py-2 md:w-[216px] md:flex-col md:items-stretch md:gap-0 md:overflow-visible md:border-b-0 md:border-r md:px-3 md:py-4" aria-label="Điều hướng chính">
        <a href="/" onClick={(e) => { e.preventDefault(); go("/"); }} className="mr-3 flex items-center gap-2.5 px-2 md:mb-6 md:mr-0 md:h-9">
          <Mark /><span className="text-[15px] font-semibold tracking-[0.2em]">NEXORA</span>
        </a>
        {GROUPS.map((group, g) => (
          <div key={group} className="flex gap-1 md:mb-5 md:flex-col md:gap-0.5">
            <p className="hidden px-2 pb-1.5 text-[12px] text-faint md:block">{group}</p>
            {PAGES.filter((p) => p.group === g).map((p) => (
              <a key={p.path} href={p.path} onClick={(e) => { e.preventDefault(); go(p.path); }} aria-current={p === page ? "page" : undefined}
                 className={`flex h-9 items-center gap-2.5 whitespace-nowrap rounded-md px-2 transition-colors ${p === page ? "bg-raised font-medium text-ink" : "text-mute hover:bg-raised/50 hover:text-ink"}`}>
                <Icon name={p.icon} size={17} /><span className="flex-1">{p.label}</span>
                {count(p) > 0 && <span className={`tc rounded-full px-1.5 text-[11px] font-semibold leading-[18px] ${p.path === "/" ? "bg-cue text-canvas" : "bg-line text-ink"}`} title={p.path === "/" ? "Số việc đang chờ bạn" : "Thông báo chưa đọc"}>{count(p)}</span>}
              </a>
            ))}
          </div>
        ))}
        <div className="mt-auto hidden items-start gap-2.5 rounded-md border border-line px-3 py-2.5 text-[12px] leading-snug md:flex">
          <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${home?.kill_switch ? "bg-tally" : working > 0 ? "animate-pulse bg-proof" : "bg-faint"}`} />
          <span className="min-w-0 flex-1"><span className="block text-ink">{home?.kill_switch ? "Đang dừng khẩn cấp" : working > 0 ? `Đang chạy ${working} việc` : "Máy đang rảnh"}</span>
            <button type="button" onClick={async () => { await post("/api/v1/control/kill-switch", { on: !home?.kill_switch }).catch(() => {}); }}
                    className={`mt-1 underline underline-offset-2 ${home?.kill_switch ? "text-ink" : "text-faint hover:text-tally"}`}>{home?.kill_switch ? "Cho chạy lại" : "Dừng khẩn cấp"}</button></span>
        </div>
      </nav>
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">{View ? <View /> : page.path === "/" ? <Home go={go} /> : <Projects sub={sub} go={go} />}</main>
    </div>
  );
}

listenForChanges();
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
