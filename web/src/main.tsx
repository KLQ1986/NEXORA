import { t as tr, tv } from "./i18n";
import { StrictMode, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { listenForChanges, megabytes, post, projectState, useConnection, usePoll, type Project, type Run } from "./api";
import Costs from "./Costs";
import Home from "./Home";
import Library from "./Library";
import Notices from "./Notices";
import Plan from "./Plan";
import Projects from "./Projects";
import Runs from "./Runs";
import System from "./System";
import { Dialogs, Icon, LangSwitch, Toaster, toast } from "./parts";

const PAGES = [
  { path: "/", label: tr("Tổng quan"), icon: "home", view: null, group: 0 },
  { path: "/du-an", label: tr("Dự án"), icon: "clapper", view: null, group: 0 },
  { path: "/thu-vien", label: tr("Thư viện"), icon: "film", view: Library, group: 0 },
  { path: "/ke-hoach", label: tr("Kế hoạch"), icon: "calendar", view: Plan, group: 0 },
  { path: "/tien-trinh", label: tr("Tiến trình"), icon: "pulse", view: Runs, group: 1 },
  { path: "/chi-phi", label: tr("Chi phí"), icon: "coins", view: Costs, group: 1 },
  { path: "/thong-bao", label: tr("Thông báo"), icon: "bell", view: Notices, group: 1 },
  { path: "/he-thong", label: tr("Hệ thống"), icon: "sliders", view: System, group: 1 },
];
const GROUPS = [tr("Sản xuất"), tr("Vận hành")];
const ENGINES: [string, string][] = [["library.understand", tr("Thị giác")], ["sourcing.match", tr("Chọn clip")], ["edit.render", tr("Dựng")], ["sourcing.generate", tr("Sinh hình")]];

type HomeLite = { attention: unknown[]; gaps: unknown[]; offline_volumes: unknown[]; problems: unknown[]; kill_switch: boolean;
  counts?: { videos: number; photos: number; music: number; projects: number; moments: number }; disk?: { free_bytes: number; total_bytes: number }; spent_today?: number };

const read = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private window */ } };

/** The mark: three takes of different lengths on a timeline, in the brand light. */
function Mark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
      <rect width="28" height="28" rx="8" fill="#14161d" stroke="#8a7cf5" strokeOpacity=".5" />
      <rect x="6" y="7.5" width="16" height="3" rx="1.5" fill="#8a7cf5" /><rect x="6" y="12.5" width="10" height="3" rx="1.5" fill="#eef0f5" /><rect x="6" y="17.5" width="13" height="3" rx="1.5" fill="#8a7cf5" opacity=".55" />
    </svg>
  );
}

/** ⌘K: jump to a screen or a project, or search footage by words. */
function Palette({ close, go, projects, kill }: { close: () => void; go: (to: string) => void; projects: Project[]; kill: boolean }) {
  const [q, setQ] = useState("");
  const [at, setAt] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => { input.current?.focus(); }, []);
  const term = q.trim().toLowerCase();
  const items = useMemo(() => {
    const out: { key: string; icon: string; label: string; hint: string; to: string; run?: () => void }[] = [];
    if (term) out.push({ key: "search", icon: "sparkles", label: tv`Tìm cảnh “${q.trim()}” trong footage`, hint: tr("Tìm bằng lời"), to: `/thu-vien?q=${encodeURIComponent(q.trim())}` });
    const actions = [
      { key: "add", icon: "plus", label: tr("Thêm footage"), hint: tr("Thư viện"), to: "/thu-vien?them=1" },
      { key: "kill", icon: "power", label: kill ? tr("Cho hệ thống chạy lại") : tr("Dừng khẩn cấp"), hint: tr("Điều khiển"), to: "", run: () => post("/api/v1/control/kill-switch", { on: !kill }).then(() => toast(kill ? tr("Hệ thống chạy lại.") : tr("Đã bật dừng khẩn cấp."), { tone: kill ? "proof" : "tally" })).catch((e) => toast((e as Error).message, { tone: "tally" })) },
      { key: "settings", icon: "sliders", label: tr("Giọng đọc và mô hình"), hint: tr("Hệ thống"), to: "/he-thong?muc=ai" },
      { key: "autonomy", icon: "bolt", label: tr("Mức tự chủ"), hint: tr("Hệ thống"), to: "/he-thong?muc=autonomy" },
    ];
    for (const a of actions) if (term && a.label.toLowerCase().includes(term)) out.push(a);
    for (const p of PAGES) if (!term || p.label.toLowerCase().includes(term)) out.push({ key: p.path, icon: p.icon, label: p.label, hint: tr("Màn hình"), to: p.path });
    for (const p of projects) if (!term || p.title.toLowerCase().includes(term)) out.push({ key: p.project_id, icon: "clapper", label: p.title, hint: projectState(p).label, to: `/du-an/${p.project_id}` });
    out.push({ key: "new", icon: "plus", label: tr("Làm video mới"), hint: tr("Dự án"), to: "/du-an?moi=1" });
    if (!term) out.push(...actions);
    return out.slice(0, 12);
  }, [term, q, projects, kill]);
  const pick = (i: number) => { const it = items[i]; if (it) { if (it.run) it.run(); else go(it.to); close(); } };
  return (
    <div className="scrim fixed inset-0 z-50 grid place-items-start justify-center px-4 pt-[12vh]" onMouseDown={close}>
      <div className="dialog w-full max-w-xl overflow-hidden" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={tr("Tìm nhanh")}>
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Icon name="search" size={18} className="text-faint" />
          <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setAt(0); }} placeholder={tr("Tìm màn hình, dự án, hoặc mô tả một cảnh…")} aria-label={tr("Tìm nhanh")}
                 onKeyDown={(e) => { if (e.key === "Escape") close(); if (e.key === "ArrowDown") { e.preventDefault(); setAt(Math.min(items.length - 1, at + 1)); } if (e.key === "ArrowUp") { e.preventDefault(); setAt(Math.max(0, at - 1)); } if (e.key === "Enter") pick(at); }}
                 className="bare h-14 min-w-0 flex-1 px-0 text-[15px]" />
          <kbd className="mono rounded border border-line px-1.5 text-[11px] text-faint">esc</kbd>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto p-1.5">
          {items.map((it, i) => (
            <li key={it.key}><button type="button" onMouseEnter={() => setAt(i)} onClick={() => pick(i)}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left ${i === at ? "bg-overlay" : ""}`}>
              <span className={`grid h-7 w-7 place-items-center rounded-md ${it.key === "search" ? "bg-ai/12 text-ai" : "bg-raised text-mute"}`}><Icon name={it.icon} size={15} /></span>
              <span className="min-w-0 flex-1 truncate">{it.label}</span><span className="shrink-0 text-[12px] text-faint">{it.hint}</span>
            </button></li>
          ))}
        </ul>
        <div className="mono flex items-center gap-4 border-t border-line px-4 py-2 text-[11px] text-faint">
          <span><kbd className="rounded border border-line px-1">↑</kbd> <kbd className="rounded border border-line px-1">↓</kbd> {tr("chọn")}</span>
          <span><kbd className="rounded border border-line px-1">↵</kbd> {tr("mở")}</span>
          <span className="ml-auto"><kbd className="rounded border border-line px-1">?</kbd> {tr("phím tắt")}</span>
        </div>
      </div>
    </div>
  );
}

const SHORTCUTS: [string, string][] = [["⌘ K", tr("Tìm nhanh: màn hình, dự án, cảnh, lệnh")], ["?", tr("Bảng phím tắt này")], ["Esc", tr("Đóng hộp thoại, bảng, hoặc menu")], ["← →", tr("Chọn cảnh trước hoặc sau trên dòng thời gian")],
  ["Space", tr("Phát hoặc dừng video đang mở")], ["⌘ Enter", tr("Lưu kịch bản đang sửa")]];
function Shortcuts({ close }: { close: () => void }) {
  useEffect(() => { const key = (e: KeyboardEvent) => { if (e.key === "Escape") close(); }; window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key); }, [close]);
  return (
    <div className="scrim fixed inset-0 z-50 grid place-items-center px-4" onMouseDown={close}>
      <div className="dialog w-full max-w-sm p-5" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="keys-title">
        <h2 id="keys-title" className="text-[15px] font-semibold">{tr("Phím tắt")}</h2>
        <dl className="mt-3 grid gap-2 text-[13px]">{SHORTCUTS.map(([k, what]) => <div key={k} className="flex items-center gap-3"><dt className="mono w-20 shrink-0 rounded-md border border-line bg-raised px-2 py-1 text-center text-[11.5px]">{k}</dt><dd className="text-mute">{what}</dd></div>)}</dl>
      </div>
    </div>
  );
}

function App() {
  const [href, setHref] = useState(window.location.pathname + window.location.search);
  const path = href.split("?")[0];
  const [collapsed, setCollapsed] = useState(read("nx.sidebar") === "1");
  const [drawer, setDrawer] = useState(false);
  const [palette, setPalette] = useState(false);
  const [keys, setKeys] = useState(false);
  const online = useConnection();
  useEffect(() => { const on = () => setHref(window.location.pathname + window.location.search); window.addEventListener("popstate", on); return () => window.removeEventListener("popstate", on); }, []);
  useEffect(() => {
    const typing = (e: KeyboardEvent) => { const t = e.target as HTMLElement | null; return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable); };
    const on = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((v) => !v); return; }
      if (e.key === "Escape") { setDrawer(false); return; }
      if (e.key === "?" && !typing(e) && !e.metaKey && !e.ctrlKey) { e.preventDefault(); setKeys((v) => !v); }
    };
    window.addEventListener("keydown", on); return () => window.removeEventListener("keydown", on);
  }, []);
  const go = (to: string) => { window.history.pushState({}, "", to); setHref(window.location.pathname + window.location.search); setDrawer(false); };
  const { data: runs } = usePoll<Run[]>("/api/v1/runs", 4000);
  const working = (runs ?? []).filter((r) => r.status === "running" && !r.held).length;
  const queued = (runs ?? []).filter((r) => r.status === "queued").length;
  const { data: home } = usePoll<HomeLite>("/api/v1/home", 4000);
  const waiting = home ? home.attention.length + home.gaps.length + home.offline_volumes.length + home.problems.length : 0;
  const { data: notices } = usePoll<{ unread: number }>("/api/v1/notifications", 5000);
  const { data: caps } = usePoll<{ pipelines: { pipeline: string; available: boolean; missing: string[] }[] }>("/api/v1/capabilities", 30000);
  const { data: projects } = usePoll<Project[]>("/api/v1/projects", 15000);
  const page = PAGES.find((p) => p.path !== "/" && path.startsWith(p.path)) ?? PAGES[0];
  const View = page.view;
  const sub = path.startsWith("/du-an/") ? path.slice("/du-an/".length) : null;
  const count = (p: (typeof PAGES)[number]) => (p.path === "/" ? waiting : p.path === "/thong-bao" && p !== page ? notices?.unread ?? 0 : p.path === "/tien-trinh" ? working : 0);
  const fold = () => { write("nx.sidebar", collapsed ? "0" : "1"); setCollapsed(!collapsed); };
  const mini = collapsed && !drawer;
  const kill = !!home?.kill_switch;
  const used = home?.disk ? 1 - home.disk.free_bytes / home.disk.total_bytes : 0;
  const crumb = sub ? (projects ?? []).find((p) => p.project_id === sub)?.title : null;

  const nav = (
    <nav aria-label={tr("Điều hướng chính")} className={`flex h-full flex-col border-r border-line bg-surface/80 backdrop-blur ${mini ? "w-[68px] px-2.5" : "w-[244px] px-3"} py-4 transition-[width] duration-200`}>
      <div className={`mb-5 flex items-center ${mini ? "justify-center" : "justify-between px-1.5"}`}>
        <a href="/" onClick={(e) => { e.preventDefault(); go("/"); }} className="flex items-center gap-2.5" title="NEXORA">
          <Mark /> {!mini && <span className="leading-tight"><span className="block text-[14px] font-bold tracking-[0.22em]">NEXORA</span><span className="block text-[10.5px] tracking-wide text-faint">Video Studio</span></span>}
        </a>
        {!mini && <button type="button" onClick={fold} className="hidden h-7 w-7 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink md:grid" title={tr("Thu gọn thanh bên")} aria-label={tr("Thu gọn thanh bên")}><Icon name="collapse" size={16} /></button>}
      </div>
      <button type="button" onClick={() => go("/du-an?moi=1")} title={tr("Làm video mới")}
              className={`brand-button mb-6 flex h-9 items-center justify-center gap-2 rounded-lg text-[13.5px] font-medium ${mini ? "w-11 self-center" : "w-full"}`}>
        <Icon name="plus" size={16} />{!mini && tr("Làm video mới")}
      </button>
      {GROUPS.map((group, g) => (
        <div key={group} className="mb-5 flex flex-col gap-0.5">
          {!mini ? <p className="eyebrow px-2.5 pb-1.5">{group}</p> : g > 0 && <div className="mx-2 mb-2 border-t border-line" />}
          {PAGES.filter((p) => p.group === g).map((p) => {
            const on = p === page, n = count(p);
            return (
              <a key={p.path} href={p.path} onClick={(e) => { e.preventDefault(); go(p.path); }} aria-current={on ? "page" : undefined} title={mini ? p.label : undefined}
                 className={`group relative flex h-9 items-center gap-3 whitespace-nowrap rounded-lg transition-colors ${mini ? "justify-center" : "px-2.5"} ${on ? "bg-raised text-ink" : "text-mute hover:bg-raised/60 hover:text-ink"}`}>
                {on && <span className="absolute -left-3 top-2 bottom-2 w-[3px] rounded-r bg-accent shadow-[0_0_10px_var(--color-accent)]" />}
                <Icon name={p.icon} size={18} className={on ? "text-accent" : ""} />{!mini && <span className="flex-1 text-[13.5px]">{p.label}</span>}
                {n > 0 && (mini
                  ? <span className={`absolute right-1.5 top-1.5 h-2 w-2 rounded-full ${p.path === "/" ? "bg-cue" : p.path === "/tien-trinh" ? "bg-ai" : "bg-accent"}`} />
                  : <span className={`mono rounded-md px-1.5 text-[11px] font-semibold leading-[18px] ${p.path === "/" ? "bg-cue text-canvas" : p.path === "/tien-trinh" ? "bg-ai/15 text-ai" : "bg-overlay text-ink"}`}
                          title={p.path === "/" ? tr("Số việc đang chờ bạn") : p.path === "/tien-trinh" ? tr("Đang chạy") : tr("Thông báo chưa đọc")}>{n}</span>)}
              </a>
            );
          })}
        </div>
      ))}
      <div className="mt-auto">
        {mini ? (
          <div className="flex flex-col items-center gap-3">
            <button type="button" onClick={fold} className="grid h-8 w-8 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink" title={tr("Mở rộng thanh bên")} aria-label={tr("Mở rộng thanh bên")}><Icon name="collapse" size={16} className="rotate-180" /></button>
            <span className={`relative h-2.5 w-2.5 rounded-full ${kill ? "bg-tally" : working ? "ping bg-ai" : "bg-proof"}`} title={kill ? tr("Đang dừng khẩn cấp") : working ? tv`Đang chạy ${working} việc` : tr("Máy đang rảnh")} />
          </div>
        ) : (
          <div className="panel-raised p-3">
            <div className="mb-2.5 flex items-center justify-between"><span className="flex items-center gap-1.5 text-[12.5px] font-medium"><Icon name="shield" size={14} className="text-proof" />{tr("Máy trạm")}</span>
              <span className={`flex items-center gap-1.5 text-[11.5px] ${kill ? "text-tally" : working ? "text-ai" : "text-proof"}`}><span className={`relative h-1.5 w-1.5 rounded-full ${kill ? "bg-tally" : working ? "ping bg-ai" : "bg-proof"}`} />{kill ? tr("Dừng khẩn cấp") : working ? tv`${working} việc đang chạy` : tr("Sẵn sàng")}</span></div>
            <div className="grid gap-2 text-[11.5px]">
              {queued > 0 && <div className="flex justify-between text-mute"><span>{tr("Hàng đợi")}</span><span className="mono text-ink">{queued}</span></div>}
              {home?.disk && <div><div className="mb-1 flex justify-between text-mute"><span>{tr("Ổ đĩa")}</span><span className={`mono ${used > 0.9 ? "text-cue" : "text-ink"}`}>{tv`còn ${megabytes(home.disk.free_bytes)}`}</span></div>
                <div className="h-1 overflow-hidden rounded-full bg-overlay"><div className={`h-full rounded-full ${used > 0.9 ? "bg-cue" : "bg-gradient-to-r from-accent to-ai"}`} style={{ width: `${used * 100}%` }} /></div></div>}
            </div>
            <button type="button" onClick={async () => { await post("/api/v1/control/kill-switch", { on: !kill }).then(() => toast(kill ? tr("Hệ thống chạy lại.") : tr("Đã bật dừng khẩn cấp: không bắt đầu thêm việc tốn tiền."), { tone: kill ? "proof" : "tally" })).catch((e) => toast((e as Error).message, { tone: "tally" })); }}
                    className={`mt-3 flex h-7 w-full items-center justify-center gap-1.5 rounded-md text-[12px] font-medium transition-colors ${kill ? "bg-proof/15 text-proof hover:bg-proof/25" : "border border-line text-mute hover:border-tally/60 hover:text-tally"}`}>
              <Icon name="power" size={13} />{kill ? tr("Cho chạy lại") : tr("Dừng khẩn cấp")}</button>
          </div>
        )}
      </div>
    </nav>
  );

  return (
    <div className="backdrop flex h-full flex-col">
      <a href="#main" className="skip" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>{tr("Tới nội dung chính")}</a>
      <div className="flex min-h-0 flex-1">
        <div className="hidden shrink-0 md:block">{nav}</div>
        {drawer && <div className="fixed inset-0 z-40 md:hidden" onClick={() => setDrawer(false)}><div className="absolute inset-0 bg-black/60" /><div className="relative h-full w-fit" onClick={(e) => e.stopPropagation()}>{nav}</div></div>}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-4 md:px-8">
            <button type="button" className="grid h-8 w-8 place-items-center rounded-md text-mute hover:bg-raised md:hidden" onClick={() => setDrawer(true)} aria-label={tr("Mở điều hướng")}><Icon name="list" size={18} /></button>
            <nav aria-label={tr("Vị trí")} className="hidden min-w-0 items-center gap-2 text-[13px] sm:flex">
              <span className="hidden text-faint sm:inline">NEXORA</span><Icon name="next" size={12} className="hidden text-faint sm:block" />
              <a href={page.path} onClick={(e) => { e.preventDefault(); go(page.path); }} className={crumb ? "text-mute hover:text-ink" : "font-medium"}>{page.label}</a>
              {crumb && <><Icon name="next" size={12} className="text-faint" /><span className="truncate font-medium">{crumb}</span></>}
            </nav>
            <button type="button" onClick={() => setPalette(true)} className="ml-auto flex h-9 w-full min-w-0 max-w-[360px] items-center gap-2.5 rounded-lg border border-line bg-surface px-3 text-[13px] text-faint transition-colors hover:border-edge hover:text-mute">
              <Icon name="search" size={15} /><span className="flex-1 truncate text-left">{tr("Tìm dự án, màn hình, cảnh…")}</span><kbd className="mono hidden rounded border border-line px-1.5 text-[11px] sm:inline">⌘K</kbd>
            </button>
            <a href="/thong-bao" onClick={(e) => { e.preventDefault(); go("/thong-bao"); }} className="relative grid h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-surface text-mute hover:text-ink" aria-label={tr("Thông báo")}>
              <Icon name="bell" size={17} />{(notices?.unread ?? 0) > 0 && <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-accent ring-2 ring-surface" />}
            </a>
            <LangSwitch />
            <span className="hidden h-9 w-9 shrink-0 place-items-center rounded-lg border border-line bg-raised text-[13px] font-semibold text-mute sm:grid" title={tr("Người vận hành")} aria-hidden="true">K</span>
          </header>
          {!online && <div role="alert" className="flex shrink-0 items-center gap-3 border-b border-tally/30 bg-tally/10 px-4 py-2 text-[13px] text-tally md:px-8"><Icon name="alert" size={15} />{tr("Không kết nối được với máy chủ NEXORA. Màn hình giữ số liệu cũ cho tới khi nối lại; kiểm tra xem")} <span className="mono">nexora serve</span> {tr("còn chạy không.")}</div>}
          {kill && <div className="flex shrink-0 items-center gap-3 border-b border-tally/30 bg-tally/10 px-4 py-2 text-[13px] text-tally md:px-8"><Icon name="power" size={15} />{tr("Đang bật dừng khẩn cấp: hệ thống không bắt đầu việc tốn tiền hay tác động ra ngoài.")}
            <button type="button" className="ml-auto font-medium underline underline-offset-2" onClick={() => post("/api/v1/control/kill-switch", { on: false }).catch(() => {})}>{tr("Cho chạy lại")}</button></div>}
          <main id="main" tabIndex={-1} className="flex min-h-0 min-w-0 flex-1 flex-col outline-none">{View ? <View /> : page.path === "/" ? <Home go={go} /> : <Projects sub={sub} go={go} />}</main>
          <nav aria-label={tr("Điều hướng nhanh")} className="grid shrink-0 grid-cols-5 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden">
            {[...PAGES.slice(0, 4), { path: "", label: tr("Thêm"), icon: "list", view: null, group: 2 }].map((p) => {
              const on = p.path ? p === page : false, n = p.path ? count(p) : 0;
              return <button key={p.label} type="button" onClick={() => (p.path ? go(p.path) : setDrawer(true))} aria-current={on ? "page" : undefined}
                             className={`relative flex h-14 flex-col items-center justify-center gap-1 text-[10.5px] ${on ? "text-accent" : "text-mute"}`}>
                <Icon name={p.icon} size={20} />{p.label}{n > 0 && <span className="absolute right-[18%] top-2 h-2 w-2 rounded-full bg-cue" />}</button>;
            })}
          </nav>
        </div>
      </div>
      <footer className="mono hidden h-7 shrink-0 items-center gap-5 border-t border-line bg-surface/70 px-4 text-[10.5px] uppercase tracking-wider text-faint md:flex">
        <span>{tr("Nguồn")} <span className="text-mute">{(home?.counts?.videos ?? 0) + (home?.counts?.photos ?? 0) + (home?.counts?.music ?? 0)}</span></span>
        <span>{tr("Dự án")} <span className="text-mute">{home?.counts?.projects ?? projects?.length ?? 0}</span></span>
        <span>{tr("Cảnh đã hiểu")} <span className="text-mute">{home?.counts?.moments ?? 0}</span></span>
        <span className="ml-auto flex items-center gap-4">
          {ENGINES.map(([key, name]) => { const c = caps?.pipelines.find((p) => p.pipeline === key); return (
            <span key={key} className="flex items-center gap-1.5" title={c ? (c.available ? tr("Sẵn sàng") : tv`Thiếu ${c.missing.join(", ")}`) : ""}><span className={`h-1.5 w-1.5 rounded-full ${!c ? "bg-faint" : c.available ? "bg-proof" : "bg-cue"}`} />{name}</span>); })}
          <span className="flex items-center gap-1.5"><span className={`h-1.5 w-1.5 rounded-full ${kill ? "bg-tally" : working ? "bg-ai" : "bg-faint"}`} />Worker {working}</span>
          {home?.spent_today != null && <span>{tr("Hôm nay")} <span className="text-mute">{home.spent_today.toFixed(2)} USD</span></span>}
        </span>
      </footer>
      {palette && <Palette close={() => setPalette(false)} go={go} projects={projects ?? []} kill={kill} />}
      {keys && <Shortcuts close={() => setKeys(false)} />}
      <Toaster />
      <Dialogs />
    </div>
  );
}

listenForChanges();
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
