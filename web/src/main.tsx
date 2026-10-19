import { t as tr, tv, locale } from "./i18n";
import { StrictMode, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import "./styles.css";
import { listenForChanges, megabytes, post, projectState, useConnection, usePoll, type Notice, type Project, type Run } from "./api";
import Costs from "./Costs";
import Home from "./Home";
import Library from "./Library";
import MissionControl from "./Mission";
import Quality from "./Quality";
import Notices, { ICON as NOTICE_ICON, KIND as NOTICE_KIND, PIPE as NOTICE_PIPE, noticeTone } from "./Notices";
import Plan from "./Plan";
import Projects from "./Projects";
import Review from "./Review";
import Runs from "./Runs";
import System from "./System";
import Trash from "./Trash";
import { ask, Dialogs, Icon, LangSwitch, setNavigator, Spinner, Toaster, toast, toggleSide } from "./parts";

const PAGES = [
  { path: "/", label: tr("Tổng quan"), icon: "home", view: null, group: 0 },
  { path: "/du-an", label: tr("Dự án"), icon: "clapper", view: null, group: 0 },
  { path: "/phong-chieu", label: tr("Phòng chiếu"), icon: "screen", view: Review, group: 0 },
  { path: "/thu-vien", label: tr("Thư viện"), icon: "film", view: Library, group: 0 },
  { path: "/chat-luong-hinh", label: tr("VQ"), icon: "eye", view: Quality, group: 0, hidden: true },     // now a tab of the Library; the address forwards there
  { path: "/ke-hoach", label: tr("Kế hoạch"), icon: "calendar", view: Plan, group: 0 },
  { path: "/phong-may", label: tr("Mission Control"), icon: "gauge", view: MissionControl, group: 1 },
  { path: "/tien-trinh", label: tr("Tiến trình"), icon: "pulse", view: Runs, group: 1 },
  { path: "/chi-phi", label: tr("Chi phí"), icon: "coins", view: Costs, group: 1 },
  { path: "/thong-bao", label: tr("Thông báo"), icon: "bell", view: Notices, group: 1 },
  { path: "/thung-rac", label: tr("Thùng rác"), icon: "trash", view: Trash, group: 1 },
  { path: "/he-thong", label: tr("Hệ thống"), icon: "sliders", view: System, group: 1 },
];
const ENGINES: [string, string][] = [["library.understand", tr("Thị giác")], ["sourcing.match", tr("Chọn clip")], ["edit.render", tr("Dựng")], ["sourcing.generate", tr("Sinh hình")]];

type HomeLite = { attention: unknown[]; gaps: unknown[]; offline_volumes: unknown[]; problems: unknown[]; kill_switch: boolean;
  counts?: { videos: number; photos: number; music: number; projects: number; moments: number }; disk?: { free_bytes: number; total_bytes: number }; spent_today?: number };


/** The mark: three takes of different lengths on a timeline, in the brand light. */
function Mark({ size = 26 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
      <rect x=".5" y=".5" width="27" height="27" rx="7.5" fill="#111318" stroke="#46c8e0" strokeOpacity=".55" />
      <rect x="6" y="7.5" width="16" height="3" rx="1.5" fill="#46c8e0" /><rect x="6" y="12.5" width="10" height="3" rx="1.5" fill="#eceef2" /><rect x="6" y="17.5" width="13" height="3" rx="1.5" fill="#46c8e0" opacity=".55" />
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
    for (const p of PAGES) if (!p.hidden && (!term || p.label.toLowerCase().includes(term))) out.push({ key: p.path, icon: p.icon, label: p.label, hint: tr("Màn hình"), to: p.path });
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
                 className="bare h-14 min-w-0 flex-1 px-0 text-title" />
          <kbd className="mono rounded border border-line px-1.5 text-mini text-faint">esc</kbd>
        </div>
        <ul className="max-h-[50vh] overflow-y-auto p-1.5">
          {items.map((it, i) => (
            <li key={it.key}><button type="button" onMouseEnter={() => setAt(i)} onClick={() => pick(i)}
                className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left ${i === at ? "bg-overlay" : ""}`}>
              <span className={`grid h-7 w-7 place-items-center rounded-md ${it.key === "search" ? "bg-ai/12 text-ai" : "bg-raised text-mute"}`}><Icon name={it.icon} size={15} /></span>
              <span className="min-w-0 flex-1 truncate">{it.label}</span><span className="shrink-0 text-mini text-faint">{it.hint}</span>
            </button></li>
          ))}
        </ul>
        <div className="mono flex items-center gap-4 border-t border-line px-4 py-2 text-mini text-faint">
          <span><kbd className="rounded border border-line px-1">↑</kbd> <kbd className="rounded border border-line px-1">↓</kbd> {tr("chọn")}</span>
          <span><kbd className="rounded border border-line px-1">↵</kbd> {tr("mở")}</span>
          <span className="ml-auto"><kbd className="rounded border border-line px-1">?</kbd> {tr("phím tắt")}</span>
        </div>
      </div>
    </div>
  );
}

const SHORTCUTS: [string, string][] = [["⌘ K", tr("Tìm nhanh: màn hình, dự án, cảnh, lệnh")], ["?", tr("Bảng phím tắt này")], ["[", tr("Ẩn hoặc hiện menu bên của mục")], ["Esc", tr("Đóng hộp thoại, bảng, hoặc menu")], ["← →", tr("Chọn cảnh trước hoặc sau trên dòng thời gian")],
  ["Space", tr("Phát hoặc dừng video đang mở")], ["⌘ Enter", tr("Lưu kịch bản đang sửa")], ["J  L", tr("Phòng chiếu: lùi / tới 5 giây")], ["↑ ↓", tr("Phòng chiếu: cảnh trước / sau")], ["N", tr("Phòng chiếu: ghi mốc nhận xét")]];
function Shortcuts({ close }: { close: () => void }) {
  useEffect(() => { const key = (e: KeyboardEvent) => { if (e.key === "Escape") close(); }; window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key); }, [close]);
  return (
    <div className="scrim fixed inset-0 z-50 grid place-items-center px-4" onMouseDown={close}>
      <div className="dialog w-full max-w-sm p-5" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="keys-title">
        <h2 id="keys-title" className="text-title font-semibold">{tr("Phím tắt")}</h2>
        <dl className="mt-3 grid gap-2 text-ui">{SHORTCUTS.map(([k, what]) => <div key={k} className="flex items-center gap-3"><dt className="mono w-20 shrink-0 rounded-md border border-line bg-raised px-2 py-1 text-center text-mini">{k}</dt><dd className="text-mute">{what}</dd></div>)}</dl>
      </div>
    </div>
  );
}

/** The bell: the latest notices in a panel under it, read where they are, with the full record one click away. */
function Bell({ go, unread }: { go: (to: string) => void; unread: number }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const { data } = usePoll<{ unread: number; items: Notice[] }>("/api/v1/notifications", 8000);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    const read = window.setTimeout(() => { post("/api/v1/notifications/read").catch(() => {}); }, 1200);
    document.addEventListener("mousedown", away); window.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", away); window.removeEventListener("keydown", key); window.clearTimeout(read); };
  }, [open]);
  const tile = { cue: "bg-cue/12 text-cue", tally: "bg-tally/12 text-tally", proof: "bg-proof/12 text-proof", mute: "bg-raised text-mute" };
  const items = (data?.items ?? []).slice(0, 8);
  const visit = (to: string) => { setOpen(false); go(to); };
  return (
    <div ref={box} className="relative shrink-0">
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="dialog" aria-label={tr("Thông báo")} title={tr("Thông báo")}
              className={`relative grid h-9 w-9 place-items-center rounded-lg border transition-colors ${open ? "border-accent/50 bg-accent/10 text-accent" : "border-line bg-surface text-mute hover:text-ink"}`}>
        <Icon name="bell" size={17} />{unread > 0 && <span className="mono absolute -right-1.5 -top-1.5 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-accent px-1 text-mini font-semibold text-[#04161b] ring-2 ring-canvas">{unread > 9 ? "9+" : unread}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label={tr("Thông báo")} className="dialog absolute right-0 top-11 z-40 w-[380px] max-w-[calc(100vw-2rem)] overflow-hidden p-0">
          <div className="flex items-center justify-between border-b border-line px-4 py-3"><p className="text-body font-semibold">{tr("Thông báo")}</p>
            {unread > 0 && <span className="text-mini text-accent">{tv`${unread} chưa đọc`}</span>}</div>
          {items.length === 0 && <p className="px-4 py-8 text-center text-ui text-mute">{tr("Chưa có thông báo")}</p>}
          <ul className="max-h-[420px] overflow-y-auto">
            {items.map((n) => { const tone = noticeTone(n.kind), fresh = n.read_at === null; return (
              <li key={n.notification_id}>
                <button type="button" disabled={!n.link} onClick={() => n.link && visit(n.link)} className={`flex w-full items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-white/[0.04] disabled:cursor-default ${fresh ? "bg-accent/[0.04]" : ""}`}>
                  <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg ${tile[tone]}`}><Icon name={NOTICE_ICON[n.kind] ?? "bell"} size={14} /></span>
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate text-ui ${fresh ? "font-medium" : ""}`}>{n.subject_name ?? NOTICE_PIPE[n.pipeline ?? ""] ?? n.pipeline ?? tr("Máy này")}</span>
                    <span className={`block truncate text-mini ${tone === "cue" ? "text-cue" : tone === "tally" ? "text-tally" : "text-faint"}`}>{NOTICE_KIND[n.kind] ?? n.kind}</span>
                  </span>
                  <span className="mono shrink-0 pt-0.5 text-mini text-faint">{new Date(n.created_at * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })}</span>
                </button>
              </li>); })}
          </ul>
          <button type="button" onClick={() => visit("/thong-bao")} className="flex w-full items-center justify-center gap-1.5 border-t border-line px-4 py-2.5 text-meta text-mute transition-colors hover:bg-white/[0.03] hover:text-ink">{tr("Xem tất cả thông báo")}<Icon name="next" size={13} /></button>
        </div>
      )}
    </div>
  );
}

/* The sections of the studio, left to right in the top bar. Operations gathers the screens that look after the machine. */
const SECTIONS = [
  { key: "home", label: tr("Tổng quan"), icon: "home", to: "/", paths: ["/"] },
  // Mission Control holds the projects too (design 2026-10-19): one side menu for missions, approvals, the machine and the videos.
  { key: "ops", label: tr("Mission Control"), icon: "gauge", to: "/phong-may", paths: ["/phong-may", "/du-an", "/tien-trinh", "/chi-phi", "/thong-bao", "/thung-rac", "/he-thong"] },
  { key: "review", label: tr("Phòng chiếu"), icon: "screen", to: "/phong-chieu", paths: ["/phong-chieu"] },
  { key: "library", label: tr("Thư viện"), icon: "film", to: "/thu-vien", paths: ["/thu-vien", "/chat-luong-hinh"] },
  { key: "plan", label: tr("Kế hoạch"), icon: "calendar", to: "/ke-hoach", paths: ["/ke-hoach"] },
];

function App() {
  const [href, setHref] = useState(window.location.pathname + window.location.search);
  const path = href.split("?")[0];
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
      if (e.key === "[" && !typing(e) && !e.metaKey && !e.ctrlKey) { e.preventDefault(); toggleSide(); }
    };
    window.addEventListener("keydown", on); return () => window.removeEventListener("keydown", on);
  }, []);
  // Moving between screens cross-fades the content while the bars stay put (where the browser can).
  const go = (to: string) => {
    const apply = () => { window.history.pushState({}, "", to); setHref(window.location.pathname + window.location.search); setDrawer(false); };
    const doc = document as Document & { startViewTransition?: (update: () => void) => unknown };
    if (doc.startViewTransition && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) doc.startViewTransition(() => flushSync(apply)); else apply();
  };
  useEffect(() => { setNavigator(go); });
  const { data: runs } = usePoll<Run[]>("/api/v1/runs", 4000);
  // A run "running" has started and is not done; most are only waiting their turn for a worker. Only stages a worker holds are running.
  const started = (runs ?? []).filter((r) => r.status === "running" && !r.held);
  const working = started.reduce((n, r) => n + r.stages.filter((s) => s.status === "running").length, 0);
  const waitingTurn = started.filter((r) => !r.stages.some((s) => s.status === "running")).length;
  const busyText = waitingTurn ? tv`${working} đang chạy · ${waitingTurn} đang chờ` : tv`${working} việc đang chạy`;
  const queued = (runs ?? []).filter((r) => r.status === "queued").length;
  const { data: home } = usePoll<HomeLite>("/api/v1/home", 4000);
  const waiting = home ? home.attention.length + home.gaps.length + home.offline_volumes.length + home.problems.length : 0;
  const { data: notices } = usePoll<{ unread: number }>("/api/v1/notifications", 5000);
  const { data: caps } = usePoll<{ pipelines: { pipeline: string; available: boolean; missing: string[] }[] }>("/api/v1/capabilities", 30000);
  const { data: projects } = usePoll<Project[]>("/api/v1/projects", 15000);
  const page = PAGES.find((p) => p.path !== "/" && path.startsWith(p.path)) ?? PAGES[0];
  const View = page.view;
  const sub = path.startsWith("/du-an/") ? path.slice("/du-an/".length) : null;
  const section = SECTIONS.find((x) => x.key !== "home" && x.paths.some((q) => path.startsWith(q))) ?? SECTIONS[0];
  const toReview = (projects ?? []).filter((x) => x.render?.status === "waiting_review").length;
  const count = (key: string) => (key === "home" ? waiting : key === "review" ? toReview : key === "ops" ? working : 0);
  const kill = !!home?.kill_switch;
  const used = home?.disk ? 1 - home.disk.free_bytes / home.disk.total_bytes : 0;

  // One lamp that says how the machine is: stopped, busy, missing an engine, or ready. The engines are named in its tooltip.
  const engines = ENGINES.map(([key, name]) => ({ name, c: caps?.pipelines.find((x) => x.pipeline === key) }));
  const missing = engines.filter((e) => e.c && !e.c.available);
  const status = kill ? { tone: "tally", text: tr("Dừng khẩn cấp") } : working || waitingTurn ? { tone: "ai", text: busyText }
    : missing.length ? { tone: "cue", text: tv`Thiếu ${missing.length} bộ máy` } : { tone: "proof", text: tr("Sẵn sàng") };
  const lamp = ({ tally: "bg-tally", ai: "bg-ai", cue: "bg-cue", proof: "bg-proof" } as Record<string, string>)[status.tone];
  const engineNote = engines.map((e) => `${e.name}: ${!e.c ? "…" : e.c.available ? tr("sẵn sàng") : tv`thiếu ${e.c.missing.join(", ")}`}`).join("\n");
  const machineNote = `${status.text}${queued ? tv` · ${queued} việc trong hàng đợi` : ""}${home?.disk ? `\n${tr("Ổ đĩa")}: ${megabytes(home.disk.free_bytes)} ${tr("trống")}` : ""}\n${engineNote}`;
  const toggleKill = async () => {
    if (!kill && !(await ask(tr("Bật dừng khẩn cấp?"), { body: tr("Hệ thống sẽ không bắt đầu thêm việc tốn tiền hay tác động ra ngoài. Việc đang chạy vẫn chạy nốt."), confirm: tr("Dừng khẩn cấp") }))) return;
    await post("/api/v1/control/kill-switch", { on: !kill }).then(() => toast(kill ? tr("Hệ thống chạy lại.") : tr("Đã bật dừng khẩn cấp: không bắt đầu thêm việc tốn tiền."), { tone: kill ? "proof" : "tally" })).catch((e) => toast((e as Error).message, { tone: "tally" }));
  };
  const badge = (key: string) => {
    const n = count(key);
    if (!n) return null;
    const look = key === "home" ? "bg-cue text-[#1a1203]" : key === "ops" ? "bg-ai/20 text-ai" : "bg-accent/20 text-accent";
    const what = key === "home" ? tr("Số việc đang chờ bạn") : key === "ops" ? tr("Đang chạy") : tr("Bản dựng chờ duyệt");
    return <span className={`mono rounded-md px-1.5 text-mini font-semibold leading-[18px] ${look}`} title={what}>{n}</span>;
  };

  // On a phone the sections and the operations screens open from the menu button, as one list.
  const phoneMenu = (
    <nav aria-label={tr("Điều hướng chính")} className="drawer flex h-full w-[280px] max-w-[85vw] flex-col border-r border-line bg-surface px-3 py-4">
      <div className="mb-4 flex items-center gap-2.5 px-1"><Mark /><span className="display text-title">NEXORA</span></div>
      <button type="button" onClick={() => go("/du-an?moi=1")} className="brand-button mb-4 flex h-10 items-center justify-center gap-2 rounded-lg text-body font-medium"><Icon name="plus" size={16} />{tr("Làm video mới")}</button>
      <div className="grid gap-0.5 overflow-y-auto">
        {PAGES.filter((p) => !p.hidden).map((p) => { const on = p === page; return (
          <button key={p.path} type="button" onClick={() => go(p.path)} aria-current={on ? "page" : undefined}
                  className={`flex h-10 items-center gap-3 rounded-lg px-3 text-body ${on ? "bg-accent/10 text-accent" : "text-mute hover:bg-raised hover:text-ink"}`}><Icon name={p.icon} size={18} />{p.label}</button>); })}
      </div>
      <button type="button" onClick={() => go("/he-thong")} className="mt-auto flex items-center gap-2.5 rounded-lg px-3 py-2 text-ui text-mute"><span className={`h-2 w-2 rounded-full ${lamp}`} />{status.text}</button>
    </nav>
  );

  return (
    <div className="backdrop flex h-full flex-col">
      <a href="#main" className="skip" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>{tr("Tới nội dung chính")}</a>
      <header style={{ viewTransitionName: "sidebar" }} className="flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface/70 px-3 backdrop-blur md:px-5">
        <button type="button" className="grid h-9 w-9 place-items-center rounded-md text-mute hover:bg-raised md:hidden" onClick={() => setDrawer(true)} aria-label={tr("Mở điều hướng")}><Icon name="list" size={18} /></button>
        <a href="/" onClick={(e) => { e.preventDefault(); go("/"); }} className="mr-2 flex shrink-0 items-center gap-2.5 lg:mr-5" title="NEXORA">
          <Mark /><span className="display hidden text-title leading-none xl:inline">NEXORA</span>
        </a>
        <span className="display truncate text-page md:hidden">{section.label}</span>
        <nav aria-label={tr("Điều hướng chính")} className="hidden min-w-0 items-center gap-0.5 md:flex">
          {SECTIONS.map((x) => { const on = x === section; return (
            <a key={x.key} href={x.to} onClick={(e) => { e.preventDefault(); go(x.to); }} aria-current={on ? "page" : undefined} title={x.label}
               className={`relative flex h-9 shrink-0 items-center gap-2 rounded-lg px-2.5 text-ui transition-colors lg:px-3 ${on ? "bg-accent/10 font-medium text-accent shadow-[inset_0_0_0_1px_rgba(70,200,224,0.18)]" : "text-mute hover:bg-raised/60 hover:text-ink"}`}>
              <Icon name={x.icon} size={16} /><span className="hidden lg:inline">{x.label}</span>{badge(x.key)}
              {on && <span className="absolute inset-x-3 -bottom-[11px] h-[2px] rounded-full bg-accent" />}
            </a>); })}
        </nav>
        <span className="flex-1" />
        {(working > 0 || waitingTurn > 0) && <button type="button" onClick={() => go("/tien-trinh")} title={tr("Xem tiến trình")} className="hidden h-9 shrink-0 items-center gap-2 rounded-lg border border-ai/30 bg-ai/10 px-3 text-meta font-medium text-ai transition-colors hover:bg-ai/15 2xl:flex"><Spinner size={13} />{busyText}</button>}
        <button type="button" onClick={() => setPalette(true)} title={tr("Tìm dự án, màn hình, cảnh…")} aria-label={tr("Tìm dự án, màn hình, cảnh…")}
                className="flex h-9 w-9 shrink-0 items-center justify-center gap-2.5 rounded-lg border border-line bg-surface text-ui text-faint transition-colors hover:border-edge hover:text-mute 2xl:w-52 2xl:justify-start 2xl:px-3">
          <Icon name="search" size={15} /><span className="hidden flex-1 truncate text-left 2xl:inline">{tr("Tìm…")}</span><kbd className="mono hidden rounded border border-line px-1.5 text-mini 2xl:inline">⌘K</kbd>
        </button>
        <Bell go={go} unread={notices?.unread ?? 0} />
        <div className="hidden h-9 shrink-0 items-center rounded-lg border border-line bg-surface sm:flex">
          <button type="button" onClick={() => go("/he-thong")} title={machineNote} aria-label={status.text} className="flex h-full items-center gap-2 rounded-l-lg px-2.5 text-meta text-mute hover:text-ink">
            <span className={`relative h-2 w-2 rounded-full ${lamp} ${working ? "ping" : ""}`} /><span className="hidden xl:inline">{status.text}</span>
            {home?.disk && <span className={`mono hidden text-mini 2xl:inline ${used > 0.9 ? "text-cue" : "text-faint"}`}>{megabytes(home.disk.free_bytes)}</span>}</button>
          <button type="button" onClick={toggleKill} title={kill ? tr("Cho chạy lại") : tr("Dừng khẩn cấp")} aria-label={kill ? tr("Cho chạy lại") : tr("Dừng khẩn cấp")}
                  className={`grid h-full w-8 place-items-center rounded-r-lg border-l border-line transition-colors ${kill ? "bg-proof/15 text-proof" : "text-faint hover:bg-tally/10 hover:text-tally"}`}><Icon name="power" size={14} /></button>
        </div>
        <span className="hidden lg:block"><LangSwitch /></span>
        <button type="button" onClick={() => go("/du-an?moi=1")} title={tr("Làm video mới")} className="brand-button hidden h-9 shrink-0 items-center gap-2 rounded-lg px-3 text-ui font-medium sm:flex"><Icon name="plus" size={16} /><span className="hidden lg:inline">{tr("Làm video mới")}</span></button>
      </header>
      {drawer && <div className="fixed inset-0 z-50 md:hidden" onClick={() => setDrawer(false)}><div className="scrim absolute inset-0" /><div className="relative h-full w-fit" onClick={(e) => e.stopPropagation()}>{phoneMenu}</div></div>}
      {!online && <div role="alert" className="flex shrink-0 items-center gap-3 border-b border-tally/30 bg-tally/10 px-4 py-2 text-ui text-tally md:px-8"><Icon name="alert" size={15} />{tr("Không kết nối được với máy chủ NEXORA. Màn hình giữ số liệu cũ cho tới khi nối lại; kiểm tra xem")} <span className="mono">nexora serve</span> {tr("còn chạy không.")}</div>}
      {kill && <div className="flex shrink-0 items-center gap-3 border-b border-tally/30 bg-tally/10 px-4 py-2 text-ui text-tally md:px-8"><Icon name="power" size={15} />{tr("Đang bật dừng khẩn cấp: hệ thống không bắt đầu việc tốn tiền hay tác động ra ngoài.")}
        <button type="button" className="ml-auto font-medium underline underline-offset-2" onClick={() => post("/api/v1/control/kill-switch", { on: false }).catch(() => {})}>{tr("Cho chạy lại")}</button></div>}
      <main id="main" tabIndex={-1} className="flex min-h-0 min-w-0 flex-1 flex-col outline-none">{View ? <View /> : page.path === "/" ? <Home go={go} /> : <Projects sub={sub} go={go} />}</main>
      <nav aria-label={tr("Điều hướng nhanh")} className="grid shrink-0 grid-cols-5 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden">
        {[...SECTIONS.slice(0, 4), { key: "more", label: tr("Thêm"), icon: "list", to: "", paths: [] as string[] }].map((x) => {
          const on = x.to ? x === section : false, n = x.to ? count(x.key) : 0;
          return <button key={x.key} type="button" onClick={() => (x.to ? go(x.to) : setDrawer(true))} aria-current={on ? "page" : undefined}
                         className={`relative flex h-14 flex-col items-center justify-center gap-1 text-mini ${on ? "text-accent" : "text-mute"}`}>
            <Icon name={x.icon} size={20} />{x.label}{n > 0 && <span className="absolute right-[18%] top-2 h-2 w-2 rounded-full bg-cue" />}</button>;
        })}
      </nav>
      {palette && <Palette close={() => setPalette(false)} go={go} projects={projects ?? []} kill={kill} />}
      {keys && <Shortcuts close={() => setKeys(false)} />}
      <Toaster />
      <Dialogs />
    </div>
  );
}

listenForChanges();
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
