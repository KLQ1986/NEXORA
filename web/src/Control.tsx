import { t as tr, tv, locale } from "./i18n";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { megabytes, post, projectState, stageName, usePoll, type AgentTask, type Campaign, type Project, type Publishing, type Radar, type Run } from "./api";
import { Button, Icon, Page, Spinner, ask, goTo, toast } from "./parts";

/* ───────────────────────── vocabulary ───────────────────────── */

const PIPE: Record<string, string> = {
  "library.ingest": tr("Nhập footage"), "library.ingest_image": tr("Nhập ảnh"), "library.ingest_audio": tr("Nhập nhạc"), "library.understand": tr("Xem và mô tả"),
  "library.transcribe": tr("Nghe lời thoại"), "library.cuts": tr("Tìm điểm cắt"), "library.enhance": tr("Làm nét"), "sourcing.match": tr("Chọn clip"),
  "sourcing.generate": tr("Sinh hình bằng AI"), "sourcing.train": tr("Huấn luyện nhân vật"), "edit.render": tr("Dựng video"), "edit.preview": tr("Bản xem nhanh"),
};
/* What the server declares about each step but does not send: where it waits for the operator, where it spends money, and which lane runs it. */
const GATE = new Set(["sourcing.match/match", "sourcing.generate/keyframes", "sourcing.generate/clips", "edit.render/assemble"]);
const COSTLY = new Set(["sourcing.generate/keyframes", "sourcing.generate/clips", "sourcing.train/train"]);
const NIGHT = new Set(["library.enhance/enhance", "library.cuts/cuts", "library.understand/describe", "library.understand/summarise", "library.understand/index", "library.transcribe/listen", "sourcing.train/train"]);
const ENGINE: Record<string, [string, "local" | "cloud"]> = {
  model: [tr("Ollama (mô hình)"), "local"], ffmpeg: ["FFmpeg", "local"], ffprobe: ["FFprobe", "local"], voice: [tr("Giọng đọc"), "local"], speech: [tr("Whisper (nghe)"), "local"],
  graphics: [tr("Vẽ phụ đề"), "local"], motion: [tr("Chuyển động ảnh"), "local"], image_gen: [tr("Sinh ảnh"), "cloud"], video_gen: [tr("Sinh video"), "cloud"], train: [tr("Huấn luyện"), "cloud"],
  stock: [tr("Kho stock"), "cloud"], web: [tr("Đọc web"), "cloud"], text: [tr("Claude (viết)"), "cloud"], publish: [tr("Xuất bản"), "local"], notify: [tr("Thông báo desktop"), "local"], desktop: [tr("Thông báo desktop"), "local"], ollama: [tr("Ollama (mô hình)"), "local"],
};
const STEPS: [string, string][] = [["research", tr("Tìm nguồn")], ["write", tr("Viết")], ["critique", tr("Tự phản biện")], ["facts", tr("Kiểm dữ kiện")], ["source", tr("Tìm hình")],
  ["matching", tr("Chọn clip")], ["gaps", tr("Lấp chỗ thiếu")], ["review", tr("Chờ duyệt")], ["cut", tr("Dựng")], ["cutting", tr("Đang dựng")], ["done", tr("Xong")]];

/* Step names the shared vocabulary does not carry yet. */
const STEP_NAME: Record<string, string> = { measure: tr("Đo ảnh"), listen: tr("Nghe"), enhance: tr("Làm nét"), cuts: tr("Tìm điểm cắt"), train: tr("Huấn luyện"), keyframes: tr("Khung hình chính"), clips: tr("Sinh clip"), match: tr("Chọn clip") };
const sn = (key: string, pipeline?: string) => { const n = stageName(key, pipeline); return n === key ? STEP_NAME[key] ?? key : n; };

type Tone = "ai" | "cue" | "tally" | "proof" | "accent" | "mute";
const TXT: Record<Tone, string> = { ai: "text-ai", cue: "text-cue", tally: "text-tally", proof: "text-proof", accent: "text-accent", mute: "text-faint" };
const BG: Record<Tone, string> = { ai: "bg-ai", cue: "bg-cue", tally: "bg-tally", proof: "bg-proof", accent: "bg-accent", mute: "bg-faint" };
const live = (s: string) => s === "running" || s === "queued";
const waits = (s: string) => s === "blocked" || s === "waiting_review";
/** A failure that still stands: not set aside by the operator, and not put right by a later run of the same work. */
const failing = (r: Run) => r.status === "failed" && !r.cleared;
const toneOf = (s: string): Tone => (s === "running" ? "ai" : waits(s) ? "cue" : s === "failed" ? "tally" : s === "succeeded" ? "proof" : s === "queued" ? "accent" : "mute");
const clock = (t: number) => new Date(t * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const ago = (t: number) => { const s = Date.now() / 1000 - t; return s < 60 ? tv`${Math.max(1, Math.round(s))} giây trước` : s < 3600 ? tv`${Math.round(s / 60)} phút trước` : s < 86400 ? tv`${Math.round(s / 3600)} giờ trước` : new Date(t * 1000).toLocaleDateString(locale); };
const secs = (s: number | null | undefined) => (s == null ? "–" : s < 60 ? `${s.toFixed(s < 10 ? 1 : 0)}s` : s < 3600 ? `${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, "0")}` : `${(s / 3600).toFixed(1)}h`);
const pct = (xs: number[], q: number) => { if (!xs.length) return null; const a = [...xs].sort((x, y) => x - y); return a[Math.min(a.length - 1, Math.floor(q * (a.length - 1)))]; };
const perHour = (stamps: number[], hours = 24) => { const now = Date.now() / 1000; const out = Array(hours).fill(0) as number[]; for (const t of stamps) { const k = Math.floor((now - t) / 3600); if (k >= 0 && k < hours) out[hours - 1 - k]++; } return out; };

type Attempt = { stage_key: string; number: number; outcome: string | null; worker: string; started_at: number; seconds: number | null; error_code: string | null; error_message: string | null };
type Detail = Run & { attempts: Attempt[]; events?: { at: number; kind: string; stage_key?: string | null }[] };
type Caps = { pipelines: { pipeline: string; available: boolean; missing: string[]; stages: { key: string; requires: string[]; available: boolean }[] }[] };
type Control = { kill_switch: boolean; background_window: string; background_running_now: boolean };
type Usage = { spent_today: number; tools_all: { adapter: string; operation: string; runs: string; calls: number; seconds: number; failures: number; cost: number }[]; tools_today: { adapter: string; calls: number; cost: number }[] };
type Autonomy = { level: number; levels: { level: number; name: string; does: string; earned: boolean }[] };
type Audit = { entries: { audit_id: number; at: number; method: string; path: string; status: number }[] };
type HomeLite = { disk: { free_bytes: number; total_bytes: number }; counts: { moments: number; videos: number }; offline_volumes: unknown[] };
type Event = { key: string; at: number; tone: Tone; who: string; text: string; run?: string };

/* Finished runs never change, so their details are fetched once per session; live ones are refreshed with every poll. */
const details = new Map<string, Detail>();
async function detailOf(id: string, fresh = false): Promise<Detail | null> {
  if (!fresh && details.has(id)) return details.get(id)!;
  try { const r = await fetch(`/api/v1/runs/${id}/detail`); if (!r.ok) return null; const d = (await r.json()) as Detail; details.set(id, d); return d; } catch { return null; }
}
const took = (d: Detail | undefined) => (d ? d.attempts.reduce((s, a) => s + (a.seconds ?? 0), 0) : null);

/* ───────────────────────── small marks ───────────────────────── */

function Lamp({ tone, pulse }: { tone: Tone; pulse?: boolean }) { return <span className={`relative inline-block h-1.5 w-1.5 shrink-0 rounded-full ${BG[tone]} ${pulse ? "ping" : ""}`} />; }

function Spark({ values, tone = "accent" }: { values: number[]; tone?: Tone }) {
  const top = Math.max(1, ...values);
  return (
    <span className="flex h-6 items-end gap-[2px]" aria-hidden="true">
      {values.map((v, k) => <span key={k} className={`w-full rounded-t-[2px] ${v ? BG[tone] : "bg-white/[0.06]"}`} style={{ height: `${Math.max(12, (v / top) * 100)}%`, opacity: v ? 0.45 + 0.55 * (v / top) : 1 }} />)}
    </span>
  );
}

function Frame({ title, icon, tone = "accent", end, children, className = "" }: { title: string; icon?: string; tone?: Tone; end?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`panel flex min-h-0 min-w-0 flex-col p-3.5 ${className}`} aria-label={title}>
      <h2 className="mb-2.5 flex shrink-0 items-center gap-2 text-[14px] font-semibold">{icon && <Icon name={icon} size={14} className={TXT[tone]} />}{title}<span className="mono ml-auto flex items-center gap-2 text-[12.5px] font-normal text-faint">{end}</span></h2>
      {children}
    </section>
  );
}

/* ───────────────────────── the screen ───────────────────────── */

type Lens = "factory" | "pipelines" | "runtime";
type Look = "mint" | "studio" | "amber";
const LOOK: Record<Look, string> = { mint: "lab", studio: "studio", amber: "lab lab-amber" };

export default function Control() {
  const { data: runs } = usePoll<Run[]>("/api/v1/runs", 3000);
  const { data: caps } = usePoll<Caps>("/api/v1/capabilities", 30000);
  const { data: ctl, reload: reloadCtl } = usePoll<Control>("/api/v1/control", 5000);
  const { data: auto, reload: reloadAuto } = usePoll<Autonomy>("/api/v1/autonomy", 15000);
  const { data: agent } = usePoll<{ tasks: AgentTask[] }>("/api/v1/agent/tasks", 4000);
  const { data: projects, reload: reloadProjects } = usePoll<Project[]>("/api/v1/projects", 8000);
  const { data: radar, reload: reloadRadar } = usePoll<Radar>("/api/v1/radar", 60000);
  const { data: camps, reload: reloadCamps } = usePoll<{ campaigns: Campaign[] }>("/api/v1/campaigns", 60000);
  const { data: pub, reload: reloadPub } = usePoll<Publishing>("/api/v1/publishing", 30000);
  const { data: usage } = usePoll<Usage>("/api/v1/usage", 30000);
  const { data: audit } = usePoll<Audit>("/api/v1/audit", 10000);
  const { data: home } = usePoll<HomeLite>("/api/v1/home", 6000);
  const [lens, setLens] = useState<Lens>(() => { try { return (localStorage.getItem("nx.control.lens") as Lens) || "factory"; } catch { return "factory"; } });
  const choose = (l: Lens) => { setLens(l); try { localStorage.setItem("nx.control.lens", l); } catch { /* fine */ } };
  const [open, setOpen] = useState<string | null>(null);
  const [panel, setPanel] = useState<string | null>(null);
  // The look of this one screen: mint instrument (default), the studio's own navy, or amber terminal.
  const [look, setLook] = useState<Look>(() => { try { return (localStorage.getItem("nx.control.look") as Look) || "mint"; } catch { return "mint"; } });
  const pickLook = (l: Look) => { setLook(l); try { localStorage.setItem("nx.control.look", l); } catch { /* fine */ } };
  const [, bump] = useState(0);
  useEffect(() => {
    const typing = (e: KeyboardEvent) => { const t = e.target as HTMLElement | null; return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT"); };
    const key = (e: KeyboardEvent) => { if (typing(e) || e.metaKey || e.ctrlKey || e.altKey) return; const l = ({ "1": "factory", "2": "pipelines", "3": "runtime" } as Record<string, Lens>)[e.key]; if (l) choose(l); };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, []);

  const all = useMemo(() => runs ?? [], [runs]);
  // Details: the recent finished runs once (for timings), every live run on each poll (for workers and steps).
  useEffect(() => {
    let stop = false;
    (async () => {
      const recent = [...all].sort((a, b) => b.created_at - a.created_at).slice(0, 40);
      for (const r of recent) { if (stop) return; const fresh = live(r.status) || waits(r.status); if (fresh || !details.has(r.run_id)) await detailOf(r.run_id, fresh); }
      if (!stop) bump((n) => n + 1);
    })();
    return () => { stop = true; };
  }, [all]);

  // The event stream: what the server tells us happened, plus the changes we see between two looks at the runs.
  const seen = useRef(new Map<string, string>());
  const [moves, setMoves] = useState<Event[]>([]);
  useEffect(() => {
    if (!runs) return;
    const fresh: Event[] = [];
    const now = Date.now() / 1000;
    for (const r of runs) {
      const was = seen.current.get(r.run_id);
      if (was && was !== r.status) fresh.push({ key: `${r.run_id}-${r.status}-${now}`, at: now, tone: toneOf(r.status), who: PIPE[r.pipeline] ?? r.pipeline, text: tv`chuyển sang ${statusName(r.status)}`, run: r.run_id });
      seen.current.set(r.run_id, r.status);
    }
    if (fresh.length) setMoves((m) => [...fresh, ...m].slice(0, 40));
  }, [runs]);
  const events: Event[] = useMemo(() => {
    const out: Event[] = [...moves];
    for (const r of all) out.push({ key: `new-${r.run_id}`, at: r.created_at, tone: toneOf(r.status), who: PIPE[r.pipeline] ?? r.pipeline, text: tv`bắt đầu một việc, giờ ${statusName(r.status)}`, run: r.run_id });
    for (const t of agent?.tasks ?? []) for (const l of t.log.slice(-6)) out.push({ key: `ag-${t.task_id}-${l.at}`, at: l.at, tone: "ai", who: l.role, text: l.text });
    for (const a of audit?.entries ?? []) out.push({ key: `au-${a.audit_id}`, at: a.at, tone: a.status >= 400 ? "tally" : "mute", who: tr("Bạn"), text: auditText(a.method, a.path) });
    return out.sort((a, b) => b.at - a.at).slice(0, 80);
  }, [moves, all, agent, audit]);

  const kill = !!ctl?.kill_switch;
  const toggleKill = async () => {
    if (!kill && !(await ask(tr("Bật dừng khẩn cấp?"), { body: tr("Hệ thống sẽ không bắt đầu thêm việc tốn tiền hay tác động ra ngoài. Việc đang chạy vẫn chạy nốt."), confirm: tr("Dừng khẩn cấp") }))) return;
    await post("/api/v1/control/kill-switch", { on: !kill }).catch((e) => toast((e as Error).message, { tone: "tally" })); reloadCtl();
  };
  const queued = all.filter((r) => r.status === "queued").length;

  const now = Date.now() / 1000;
  const fails = all.filter((r) => failing(r) && r.created_at > now - 2 * 86400).sort((a, b) => b.created_at - a.created_at);
  const toReview = (projects ?? []).filter((p) => p.render?.status === "waiting_review");
  const held = all.filter((r) => waits(r.status) && r.pipeline !== "edit.render").sort((a, b) => b.created_at - a.created_at);
  const asking = (agent?.tasks ?? []).filter((t) => t.status === "waiting_operator");
  const diskFull = home ? 1 - home.disk.free_bytes / home.disk.total_bytes > 0.9 : false;
  const needs: { key: string; tone: Tone; icon: string; count: number; label: string; cta: string; act: () => void }[] = [
    ...(kill ? [{ key: "kill", tone: "tally" as Tone, icon: "power", count: 1, label: tr("Dừng khẩn cấp đang bật"), cta: tr("Cho chạy lại"), act: toggleKill }] : []),
    ...(fails.length ? [{ key: "fail", tone: "tally" as Tone, icon: "alert", count: fails.length, label: tr("việc lỗi trong 2 ngày"), cta: tr("Xem"), act: () => setOpen(fails[0].run_id) }] : []),
    ...(toReview.length ? [{ key: "review", tone: "cue" as Tone, icon: "screen", count: toReview.length, label: tr("bản dựng chờ duyệt"), cta: tr("Duyệt"), act: () => setPanel("qc") }] : []),
    ...(held.length ? [{ key: "held", tone: "cue" as Tone, icon: "pause", count: held.length, label: tr("việc đang chờ bạn"), cta: tr("Mở"), act: () => setOpen(held[0].run_id) }] : []),
    ...(asking.length ? [{ key: "ask", tone: "cue" as Tone, icon: "comment", count: asking.length, label: tr("câu hỏi của trợ lý"), cta: tr("Trả lời"), act: () => setPanel("writer") }] : []),
    ...(pub?.due.length ? [{ key: "due", tone: "cue" as Tone, icon: "calendar", count: pub.due.length, label: tr("bài tới hạn nhập số liệu"), cta: tr("Nhập"), act: () => setPanel("publish") }] : []),
    ...(diskFull ? [{ key: "disk", tone: "cue" as Tone, icon: "disk", count: 1, label: tr("ổ đĩa sắp đầy"), cta: tr("Dọn"), act: () => goTo("/he-thong") }] : []),
  ];

  const lensBar = (
    <div className="lab-seg" role="radiogroup" aria-label={tr("Lớp nhìn")}>
      {([["factory", tr("Xưởng"), "1"], ["pipelines", tr("Quy trình"), "2"], ["runtime", tr("Máy chạy"), "3"]] as const).map(([k, label, n]) => (
        <button key={k} type="button" role="radio" aria-checked={lens === k} onClick={() => choose(k)} title={tv`Phím tắt: ${n}`}>{label}<kbd className="mono ml-1.5 hidden rounded border border-line px-1 text-[10.5px] leading-4 opacity-70 xl:inline">{n}</kbd></button>))}
    </div>
  );
  const perMin = perHour(events.map((e) => e.at));
  const active = all.filter((r) => r.status === "running" || waits(r.status)).sort((a, b) => b.created_at - a.created_at);
  return (
    <Page full flush title={tr("Phòng máy")}>
      <div className={`${LOOK[look]} flex h-full min-h-0 flex-col overflow-y-auto lg:overflow-hidden`}>
        {/* one row of switches: which view, the other operations screens, how busy, stop, look */}
        <header className="lab-rule flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
          {lensBar}
          <OpsLinks />
          <span className="lab-cap ml-auto hidden items-center gap-2 md:flex">{tr("Sự kiện / giờ")}<span className="w-24"><Spark values={perMin} tone="accent" /></span></span>
          <button type="button" onClick={toggleKill} className={`lab-btn ${kill ? "!border-proof/60 !text-proof" : "!border-tally/50 !text-tally hover:!bg-tally/10"}`}><Icon name="power" size={12} />{kill ? tr("Cho chạy lại") : tr("Dừng khẩn cấp")}</button>
          <LookMenu look={look} pick={pickLook} />
        </header>
        {/* what needs you, first; then what is running */}
        <div className="lab-rule flex flex-wrap items-center gap-2 px-4 py-1.5">
          {needs.length === 0
            ? <span className="flex items-center gap-2 text-[13px] text-proof"><Icon name="check" size={14} />{tr("Không có gì cần bạn xử lý")}</span>
            : <><span className="lab-cap mr-1 text-ink">{tr("Cần bạn")}</span>{needs.map((n) => (
              <button key={n.key} type="button" onClick={n.act} className="need flex h-7 items-center gap-2 border px-2.5 text-[13px] transition-colors"
                      style={{ borderColor: `color-mix(in srgb, var(--color-${n.tone}) 55%, transparent)`, background: `color-mix(in srgb, var(--color-${n.tone}) 9%, transparent)`, color: `var(--color-${n.tone})` }}>
                <Icon name={n.icon} size={13} /><span className="mono font-semibold">{n.count}</span><span className="text-ink">{n.label}</span><span className="underline decoration-dotted underline-offset-2">{n.cta}</span>
              </button>))}</>}
          <span className="lab-cap scroll-x ml-auto flex items-center gap-4 whitespace-nowrap">
            {active.length === 0 ? <><span className="text-ink">{tr("Máy rảnh")}</span><span className="hidden xl:inline">{tv`Bộ nhớ ${home?.counts.moments ?? 0} cảnh`}</span><span>{tv`${queued} chờ trong hàng`}</span><span className="hidden xl:inline">{tv`Tự chủ mức ${auto?.level ?? 0}`}</span></>
              : active.slice(0, 3).map((r, k) => { const st = r.stages.find((x) => x.status === "running" || waits(x.status)); const done = r.stages.filter((x) => x.status === "succeeded").length; return (
                <button key={r.run_id} type="button" onClick={() => setOpen(r.run_id)} className={`flex items-center gap-2 hover:underline ${k ? "border-l border-line pl-4" : ""} ${waits(r.status) ? "text-cue" : "text-ai"}`}>
                  <span className="text-ink">{rid(r.run_id)}</span><span>{PIPE[r.pipeline] ?? r.pipeline}</span>{st && <span className="hidden xl:inline">{sn(st.stage_key, r.pipeline)}</span>}<span>{Math.round((done / Math.max(1, r.stages.length)) * 100)} %</span></button>); })}
          </span>
        </div>
        {/* the command band: the loop, the work in hand, and what just happened, side by side */}
        <div className="grid gap-3 px-3 pt-3 lg:h-[184px] lg:shrink-0 lg:grid-cols-[minmax(0,1.65fr)_minmax(0,1fr)_minmax(0,0.95fr)] short:lg:h-[160px]">
          <Loop all={all} projects={projects ?? []} radar={radar} camps={camps?.campaigns ?? []} pub={pub} agent={agent?.tasks ?? []} onPanel={setPanel} />
          <TaskBoard all={all} open={setOpen} />
          <div className="h-[300px] lg:h-auto lg:min-h-0"><Feed events={events} open={setOpen} /></div>
        </div>
        <div className="grid gap-3 p-3 lg:min-h-0 lg:flex-1">
          <div className="min-w-0 lg:min-h-0 lg:overflow-hidden">
            {lens === "factory" && <Factory all={all} projects={projects ?? []} radar={radar} camps={camps?.campaigns ?? []} pub={pub} agent={agent?.tasks ?? []} home={home} open={setOpen} onPanel={setPanel} />}
            {lens === "pipelines" && <Pipelines all={all} caps={caps} agent={agent?.tasks ?? []} open={setOpen} />}
            {lens === "runtime" && <Runtime all={all} caps={caps} ctl={ctl} auto={auto} usage={usage} home={home} reloadAuto={reloadAuto} open={setOpen} />}
          </div>
        </div>
        <footer className="lab-rule lab-cap flex flex-wrap justify-between gap-2 border-t px-4 py-1.5"><span>{tr("Nguồn")} · NEXORA API · {tv`${all.length} lần chạy`}</span><span>{tr("Số liệu thật, cập nhật mỗi 3 giây")}</span></footer>
      </div>
      {panel && <QuickPanel dept={panel} look={look} close={() => setPanel(null)}
        ctx={{ all, projects: projects ?? [], radar, camps: camps?.campaigns ?? [], pub, agent: agent?.tasks ?? [], ctl, home, openRun: setOpen, reload: () => { reloadProjects(); reloadRadar(); reloadCamps(); reloadPub(); reloadCtl(); } }} />}
      {open && <RunDrawer id={open} close={() => setOpen(null)} />}
    </Page>
  );
}

/** A run's short name, the way the board and the ticker write it. */
const rid = (id: string) => `R-${id.slice(-4).toUpperCase()}`;

/** The other operations screens, one click away; named in words where there is room. */
function OpsLinks() {
  return (
    <span className="hidden items-center gap-0.5 border-l border-line pl-2 lg:flex">
      {([["/tien-trinh", tr("Tiến trình"), "pulse"], ["/chi-phi", tr("Chi phí"), "coins"], ["/thong-bao", tr("Thông báo"), "bell"], ["/he-thong", tr("Hệ thống"), "sliders"]] as const).map(([to, label, icon]) => (
        <button key={to} type="button" onClick={() => goTo(to)} title={label} aria-label={label} className="flex h-8 items-center gap-1.5 rounded-md px-2 text-[12.5px] text-mute transition-colors hover:bg-raised hover:text-ink"><Icon name={icon} size={14} /><span className="hidden 2xl:inline">{label}</span></button>))}
    </span>
  );
}

/** The look of this screen is set once, so it lives in a small menu rather than on the bar. */
function LookMenu({ look, pick }: { look: Look; pick: (l: Look) => void }) {
  const [on, setOn] = useState(false);
  const dot = (k: Look) => (k === "mint" ? "#8fe3c0" : k === "studio" ? "#30afff" : "#ffb347");
  return (
    <span className="relative">
      <button type="button" onClick={() => setOn((v) => !v)} aria-expanded={on} aria-haspopup="menu" title={tr("Phong cách của màn này")} className="lab-btn"><span className="inline-block h-2 w-2 rounded-full" style={{ background: dot(look) }} />{tr("Giao diện")}</button>
      {on && <>
        <span className="fixed inset-0 z-30" onClick={() => setOn(false)} />
        <span role="menu" className="lab-card absolute right-0 top-[calc(100%+6px)] z-40 grid w-40 gap-0.5 !bg-[var(--color-canvas)] p-1.5 shadow-xl">
          {([["mint", tr("Bạc hà")], ["studio", tr("Studio")], ["amber", tr("Hổ phách")]] as const).map(([k, label]) => (
            <button key={k} type="button" role="menuitemradio" aria-checked={look === k} onClick={() => { pick(k); setOn(false); }} className={`flex h-8 items-center gap-2 rounded px-2 text-left text-[13px] hover:bg-white/[0.05] ${look === k ? "text-ink" : "text-mute"}`}>
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: dot(k) }} />{label}{look === k && <Icon name="check" size={13} className="ml-auto" />}</button>))}
        </span>
      </>}
    </span>
  );
}

const statusName = (s: string) => ({ queued: tr("chờ"), running: tr("đang chạy"), blocked: tr("đang dừng"), waiting_review: tr("chờ duyệt"), failed: tr("lỗi"), succeeded: tr("xong"), cancelled: tr("đã huỷ") } as Record<string, string>)[s] ?? s;

function auditText(method: string, path: string) {
  const p = path.replace("/api/v1/", "");
  if (/render\/decision/.test(p)) return tr("duyệt hoặc từ chối một bản dựng");
  if (/match\/approve/.test(p)) return tr("duyệt clip của một dự án");
  if (/\/script$/.test(p)) return tr("lưu kịch bản");
  if (/\/render$/.test(p)) return tr("yêu cầu dựng video");
  if (/\/match$/.test(p)) return tr("yêu cầu tìm clip");
  if (/kill-switch/.test(p)) return tr("bật hoặc tắt dừng khẩn cấp");
  if (/autonomy/.test(p)) return tr("đổi mức tự chủ");
  if (/agent\/tasks/.test(p)) return tr("giao việc cho trợ lý");
  if (/retry|resume/.test(p)) return tr("chạy lại một bước");
  if (/cancel/.test(p)) return tr("huỷ một việc");
  if (/^evaluation/.test(p)) return method === "DELETE" ? tr("bỏ một mẫu chấm điểm") : tr("chạy hoặc sửa bộ chấm điểm");
  if (/^control|^settings/.test(p)) return tr("đổi cài đặt hệ thống");
  if (/^storage/.test(p)) return tr("sao lưu hoặc dọn ổ đĩa");
  if (/^assets|^library|^volumes/.test(p)) return tr("thay đổi footage trong thư viện");
  if (/^shots/.test(p)) return tr("sửa clip của một câu");
  if (/^projects/.test(p)) return method === "POST" && /^projects$/.test(p) ? tr("tạo dự án") : tr("sửa một dự án");
  if (/^campaigns|^experiments|^publications|^publishing/.test(p)) return tr("cập nhật kế hoạch hoặc số liệu đăng");
  return tr("một thao tác khác");
}

/* ───────────────────────── the production loop, drawn as a Petri net ───────────────────────── */

function Loop({ all, projects, radar, camps, pub, agent, onPanel }: { all: Run[]; projects: Project[]; radar: Radar | null; camps: Campaign[]; pub: Publishing | null; agent: AgentTask[]; onPanel: (d: string) => void }) {
  const step = (n: number) => projects.filter((p) => projectState(p).step === n).length;
  const libLive = all.filter((r) => r.pipeline.startsWith("library.") && live(r.status)).length;
  const writing = agent.filter((t) => t.status === "working" && ["research", "write", "critique", "facts"].includes(t.step)).length;
  const posts = (pub?.publications ?? []).filter((x) => x.status !== "published").length;
  const cutting = all.some((r) => r.pipeline === "edit.render" && r.status === "running");
  // Places hold work; transitions (the bars between) are what moves it on.
  const places: [string, number, Tone][] = [
    [tr("Cơ hội"), radar?.subjects.length ?? 0, "accent"], [tr("Chiến dịch"), camps.length, "accent"], [tr("Kịch bản"), step(0) + writing, writing ? "ai" : "accent"],
    [tr("Hiểu footage"), libLive, libLive ? "ai" : "accent"], [tr("Chọn clip"), step(1) + step(2), step(2) ? "cue" : "accent"], [tr("Dựng"), step(3), cutting ? "ai" : "accent"],
    [tr("Duyệt"), step(4), step(4) ? "cue" : "accent"], [tr("Đăng"), posts, "accent"], [tr("Số liệu"), pub?.due.length ?? 0, pub?.due.length ? "cue" : "accent"],
  ];
  const moves = [tr("lên kế hoạch"), tr("viết"), tr("phân tích"), tr("ghép"), tr("dựng"), tr("chấm"), tr("đăng"), tr("đo")];
  const fired = all.filter((r) => r.status === "succeeded").length, enabled = places.filter(([, n]) => n > 0).length;
  const peak = Math.max(1, ...places.map(([, n]) => n));
  const jam = places.reduce((b, pl, k) => (pl[1] > places[b][1] ? k : b), 0);
  const col = (n: number, tone: Tone) => (n ? `var(--color-${tone === "ai" ? "ai" : tone === "cue" ? "cue" : "accent"})` : "var(--color-edge)");
  return (
    <section className="lab-card flex min-h-0 flex-col px-3.5 py-2.5" aria-label={tr("Vòng sản xuất")}>
      <div className="lab-cap flex items-center gap-3">
        <span className="text-ink">{tr("Vòng sản xuất")}</span>
        <span className="flex items-center gap-1.5"><span className="relative inline-flex h-1.5 w-1.5"><span className="absolute inset-0 animate-ping rounded-full bg-proof opacity-60" /><span className="relative h-1.5 w-1.5 rounded-full bg-proof" /></span>{tr("Trực tiếp")}</span>
        <span className="ml-auto flex items-center gap-3">
          <span className="hidden xl:inline">{tv`Đã chạy ${fired}`}</span><span>{tv`Đang bật ${enabled}/${places.length}`}</span>
          {places[jam][1] > 0 && <span className="lab-tag !border-cue/50 !text-cue">{tv`Dồn ở ${places[jam][0]}`}</span>}
        </span>
      </div>
      <div className="scroll-x mt-auto">
      <ol className="grid min-w-[560px] grid-cols-9 pb-0.5 pt-4">
        {places.map(([label, n, tone], k) => { const c = col(n, tone), next = places[k + 1]; return (
          <li key={label} className="relative flex min-w-0 flex-col items-center">
            {next && <>
              <span aria-hidden="true" className="absolute top-[17px] h-px" style={{ left: "calc(50% + 21px)", right: "calc(-50% + 21px)", background: `linear-gradient(90deg, ${c}, ${col(next[1], next[2])})`, opacity: n || next[1] ? 0.75 : 0.5 }} />
              <span aria-hidden="true" className="absolute top-[14.5px] h-[6px] w-[6px] rotate-45 border-r border-t" style={{ left: "calc(150% - 28px)", borderColor: col(next[1], next[2]) }} />
              <span className="absolute -top-3.5 hidden -translate-x-1/2 whitespace-nowrap text-[11.5px] text-mute xl:block" style={{ left: "100%" }}>{moves[k]}</span>
            </>}
            <button type="button" onClick={() => onPanel(STATION[k])} title={tv`Mở ${label}`} className="group/st flex flex-col items-center">
            <span className="mono relative grid h-[34px] w-[34px] place-items-center rounded-full border text-[13px] font-semibold transition-transform group-hover/st:scale-110"
                  style={{ borderColor: c, color: n ? c : "var(--color-faint)", background: n ? `color-mix(in srgb, ${c} 12%, transparent)` : "transparent", boxShadow: n ? `0 0 20px -6px ${c}` : "none" }}>
              {n}
              {tone === "ai" && n > 0 && <span aria-hidden="true" className="absolute inset-0 animate-ping rounded-full border opacity-40" style={{ borderColor: c }} />}
            </span>
            <span className={`mt-1.5 max-w-full truncate text-[12px] group-hover/st:underline ${n ? "text-ink" : "text-mute"}`}>{label}</span>
            <span aria-hidden="true" className="mt-1 h-[3px] w-9 bg-white/[0.06]"><span className="block h-full" style={{ width: `${(n / peak) * 100}%`, background: c }} /></span>
            </button>
          </li>); })}
      </ol>
      </div>
    </section>
  );
}

/* ───────────────────────── lens 1: the factory ───────────────────────── */

/* Each department has a colour of its own, carried by its mascot, its bars and the rule beside its card. */
const DEPT: Record<string, string> = { radar: "#5b8cff", campaign: "#f2c14e", writer: "#a98bff", vision: "#4fd1e8", match: "#7bd389", cut: "#ff8c52", qc: "#ff6fae", publish: "#c3e86b" };
type Card = { key: string; label: string; role: string; to: string; state: Tone; head: string; unit: string; runs: Run[]; lines: [number, string, string][]; spark: number[]; done: number; doing: number; fail: number; p95: number | null };

function Factory({ all, projects, radar, camps, pub, agent, home, open, onPanel }: { all: Run[]; projects: Project[]; radar: Radar | null; camps: Campaign[]; pub: Publishing | null; agent: AgentTask[]; home: HomeLite | null; open: (id: string) => void; onPanel: (d: string) => void }) {
  const of = (prefixes: string[]) => all.filter((r) => prefixes.some((p) => r.pipeline.startsWith(p)));
  const lines = (rs: Run[]): [number, string, string][] => [...rs].sort((a, b) => b.created_at - a.created_at).slice(0, 3).map((r) => [r.created_at, PIPE[r.pipeline] ?? r.pipeline, statusName(r.status)]);
  const stateOf = (rs: Run[]): Tone => (rs.some((r) => r.status === "running") ? "ai" : rs.some((r) => waits(r.status)) ? "cue" : rs.some((r) => failing(r) && r.created_at > Date.now() / 1000 - 86400) ? "tally" : "mute");
  const stats = (rs: Run[]) => ({ runs: rs, done: rs.filter((r) => r.status === "succeeded").length, doing: rs.filter((r) => live(r.status) || waits(r.status)).length, fail: rs.filter(failing).length,
    p95: pct(rs.map((r) => took(details.get(r.run_id))).filter((x): x is number => x != null && x > 0), 0.95), spark: perHour(rs.map((r) => r.created_at)) });
  const none = { runs: [] as Run[], done: 0, doing: 0, fail: 0, p95: null, spark: perHour([]) };
  const lib = of(["library."]), src = of(["sourcing."]), cut = of(["edit."]);
  const writers = agent.filter((t) => t.status === "working" || t.status === "waiting_operator");
  const reviewing = projects.filter((p) => p.render?.status === "waiting_review");
  const posted = (pub?.publications ?? []).filter((x) => x.published_at);
  const said: [number, string, string][] = agent.flatMap((t) => t.log.map((l) => [l.at, l.role, l.text] as [number, string, string])).sort((a, b) => b[0] - a[0]).slice(0, 3);
  const cards: Card[] = [
    { key: "radar", label: tr("Radar"), role: tr("tìm · gợi ý"), to: "/ke-hoach?xem=radar", state: "mute", head: String(radar?.subjects.length ?? 0), unit: tr("chủ đề"),
      lines: (radar?.watched ?? []).slice(0, 3).map((w) => [0, w.topic, w.verdict] as [number, string, string]), ...none, done: (radar?.unused ?? []).length },
    { key: "campaign", label: tr("Chiến dịch"), role: tr("mục tiêu · thử nghiệm"), to: "/ke-hoach?xem=ket-qua", state: camps.some((c) => c.late) ? "cue" : "mute", head: String(camps.length), unit: tr("chiến dịch"),
      lines: camps.slice(0, 3).map((c) => [0, c.name, `${Math.round((c.share ?? 0) * 100)} %`] as [number, string, string]), ...none, done: camps.reduce((s, c) => s + c.published, 0) },
    { key: "writer", label: tr("Biên kịch"), role: tr("viết · phản biện"), to: "/du-an", state: writers.some((t) => t.status === "waiting_operator") ? "cue" : writers.length ? "ai" : "mute", head: String(writers.length), unit: tr("đang viết"),
      lines: said, ...none, spark: perHour(agent.flatMap((t) => t.log.map((l) => l.at))), done: agent.filter((t) => t.status === "done").length, doing: writers.length },
    { key: "vision", label: tr("Thị giác"), role: tr("nhập · xem · mô tả"), to: "/thu-vien", state: stateOf(lib), head: String(home?.counts.moments ?? 0), unit: tr("cảnh đã hiểu"), lines: lines(lib), ...stats(lib) },
    { key: "match", label: tr("Chọn clip"), role: tr("tìm · sinh hình"), to: "/du-an", state: stateOf(src), head: String(projects.reduce((s, p) => s + p.shots.filter((x) => x.selection?.status === "gap").length, 0)), unit: tr("câu thiếu hình"), lines: lines(src), ...stats(src) },
    { key: "cut", label: tr("Dựng"), role: tr("lời dẫn · ghép · phụ đề"), to: "/du-an", state: stateOf(cut), head: String(projects.reduce((s, p) => s + p.renders.length, 0)), unit: tr("bản dựng"), lines: lines(cut), ...stats(cut) },
    { key: "qc", label: tr("Kiểm duyệt"), role: tr("chấm · duyệt"), to: "/phong-chieu", state: reviewing.length ? "cue" : "mute", head: String(reviewing.length), unit: tr("chờ bạn"),
      lines: reviewing.slice(0, 3).map((p) => [0, p.title, tr("chờ duyệt")] as [number, string, string]), ...none, spark: perHour(projects.flatMap((p) => p.renders.map((r) => r.created_at))), done: projects.filter((p) => p.render?.status === "succeeded").length, doing: reviewing.length },
    { key: "publish", label: tr("Phát hành"), role: tr("đăng · đo"), to: "/ke-hoach?xem=ket-qua", state: pub?.due.length ? "cue" : "mute", head: String(posted.length), unit: tr("đã đăng"),
      lines: (pub?.due ?? []).slice(0, 3).map((d) => [0, d.title, tr("tới mốc số liệu")] as [number, string, string]), ...none, spark: perHour(posted.map((x) => x.published_at ?? 0)), done: posted.length, doing: pub?.due.length ?? 0 },
  ];
  return (
    <div className="grid gap-3 lg:h-full lg:min-h-0">
      {/* four departments each side in a 2×2, the dial between them, as on an instrument panel */}
      <div className="grid gap-3 md:grid-cols-2 lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(300px,1.8fr)_minmax(0,1fr)_minmax(0,1fr)] lg:grid-rows-2">
        <div className="md:col-span-2 lg:col-span-1 lg:col-start-3 lg:row-span-2 lg:row-start-1 lg:min-h-0"><Dial radar={radar} home={home} running={all.filter((r) => r.status === "running" || waits(r.status))} cards={cards} open={open} onPanel={onPanel} /></div>
        {cards.map((c, k) => <div key={c.key} className={`${SLOT[k]} lg:min-h-0`}><DeptCard c={c} side={k < 4 ? "left" : "right"} onOpen={() => onPanel(c.key)} /></div>)}
      </div>
    </div>
  );
}
/* Where each card sits on the wide panel: the left four in columns 1–2, the right four in columns 4–5. */
const SLOT = ["lg:col-start-1 lg:row-start-1", "lg:col-start-2 lg:row-start-1", "lg:col-start-1 lg:row-start-2", "lg:col-start-2 lg:row-start-2",
  "lg:col-start-4 lg:row-start-1", "lg:col-start-5 lg:row-start-1", "lg:col-start-4 lg:row-start-2", "lg:col-start-5 lg:row-start-2"];

/** One line glyph per department, drawn on a tinted tile in the department's colour; a lit corner means it is working. */
const GLYPH: Record<string, React.ReactNode> = {
  radar: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" strokeOpacity=".55" /><path d="M12 12 18.4 5.6" /><circle cx="15.6" cy="8.4" r="1.3" fill="currentColor" stroke="none" /></>,
  campaign: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" /><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21" strokeOpacity=".55" /></>,
  writer: <><path d="M6 3h8.5L19 7.5V21H6z" /><path d="M14.5 3v4.5H19" /><path d="M9 11.5h6.5M9 14.5h6.5M9 17.5h4" strokeOpacity=".7" /></>,
  vision: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="3.2" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /></>,
  match: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M7 5v14M17 5v14" strokeOpacity=".55" /><path d="m9.6 12.2 1.7 1.7 3.2-3.4" /></>,
  cut: <><circle cx="6" cy="6.5" r="2.6" /><circle cx="6" cy="17.5" r="2.6" /><path d="M8.2 8 20 18M8.2 16 20 6" /></>,
  qc: <><path d="M12 3 19 6v5.6c0 4.4-2.9 7.7-7 9.4-4.1-1.7-7-5-7-9.4V6z" /><path d="m9 12 2.1 2.1L15.2 10" /></>,
  publish: <><circle cx="12" cy="12" r="1.8" fill="currentColor" stroke="none" /><path d="M8.6 15.4a4.8 4.8 0 0 1 0-6.8M15.4 8.6a4.8 4.8 0 0 1 0 6.8" /><path d="M5.6 18.4a9 9 0 0 1 0-12.8M18.4 5.6a9 9 0 0 1 0 12.8" strokeOpacity=".55" /></>,
};
function DeptIcon({ kind, live }: { kind: string; live?: boolean }) {
  const c = DEPT[kind] ?? "var(--color-accent)";
  return (
    <span aria-hidden="true" className="dept-icon relative grid h-10 w-10 shrink-0 place-items-center" style={{ color: c, background: `color-mix(in srgb, ${c} 11%, transparent)`, boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${c} 38%, transparent)` }}>
      <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{GLYPH[kind]}</svg>
      {live && <span className="absolute -right-[3px] -top-[3px] flex h-2 w-2"><span className="absolute inset-0 animate-ping rounded-full opacity-70" style={{ background: c }} /><span className="relative h-2 w-2 rounded-full" style={{ background: c }} /></span>}
    </span>
  );
}

function DeptCard({ c, side, onOpen }: { c: Card; side: "left" | "right"; onOpen: () => void }) {
  const color = DEPT[c.key];
  const tag = { ai: tr("Đang làm"), cue: tr("Chờ bạn"), tally: tr("Lỗi"), proof: tr("Ổn"), accent: tr("Sẵn sàng"), mute: tr("Rảnh") }[c.state];
  const util = Math.round((c.spark.filter((v) => v > 0).length / 24) * 100);
  // Where the department's current work sits on its line: waiting to come in, at work, or gone out.
  const mark = c.doing ? (c.state === "cue" ? 0.82 : 0.5) : c.done ? 0.95 : 0.06;
  const now = c.runs.find((r) => r.status === "running" || waits(r.status));
  const bad = c.runs.filter(failing).sort((a, b) => b.created_at - a.created_at)[0];
  const last = c.lines[0];
  // One sentence for what this department is doing, waiting on, broke on, or last did.
  const line = now ? (waits(now.status) ? tv`Chờ bạn: ${PIPE[now.pipeline] ?? now.pipeline}` : (() => { const st = now.stages.find((x) => x.status === "running"); return tv`Đang ${st ? sn(st.stage_key, now.pipeline).toLowerCase() : PIPE[now.pipeline] ?? now.pipeline} · ${rid(now.run_id)}`; })())
    : c.state === "tally" && bad ? tv`Lỗi: ${PIPE[bad.pipeline] ?? bad.pipeline} · ${ago(bad.created_at)}`
    : (c.state === "ai" || c.state === "cue") && last ? `${last[1]} — ${last[2]}`
    : last ? tv`Gần nhất: ${last[1]}${last[0] ? ` · ${ago(last[0])}` : ""}` : tr("Chưa có hoạt động");
  const busy = c.state !== "mute";
  return (
    <button type="button" onClick={onOpen} aria-haspopup="dialog" title={tv`Điều khiển nhanh: ${c.label}`} className={`lab-card group relative flex h-full w-full flex-col overflow-hidden px-3 py-2.5 text-left ${busy ? "" : "dept-idle"}`}
            style={busy ? { boxShadow: `inset 0 0 0 1px color-mix(in srgb, ${c.state === "tally" ? "var(--color-tally)" : color} 45%, transparent)`, background: `color-mix(in srgb, ${c.state === "tally" ? "var(--color-tally)" : color} 6%, transparent)` } : undefined}>
      <span className={`absolute inset-y-0 w-[3px] ${side === "left" ? "left-0" : "right-0"}`} style={{ background: color, opacity: c.state === "mute" ? 0.55 : 1 }} />
      <span className={`flex items-start gap-3 ${side === "right" ? "flex-row-reverse text-right" : ""}`}>
        <DeptIcon kind={c.key} live={c.state === "ai"} />
        <span className="min-w-0 flex-1">
          <span className={`block truncate text-[15.5px] font-semibold uppercase tracking-[0.06em] ${busy ? "text-ink" : "text-mute"}`}>{c.label}</span>
          <span className="block truncate text-[12.5px] text-faint">{c.role}</span>
          <span className={`mt-1.5 flex items-center gap-2 ${side === "right" ? "justify-end" : ""}`}>
            <span className={`lab-tag ${c.state === "ai" ? "!border-ai/70 !text-ai" : c.state === "cue" ? "!border-cue/70 !text-cue" : c.state === "tally" ? "!border-tally/70 !text-tally" : ""}`}>{tag}</span>
            <span className="truncate text-[12.5px] text-mute"><span className="text-ink">{c.head}</span> {c.unit}</span>
          </span>
        </span>
      </span>
      <span className="lab-cap mt-2 flex items-center justify-between"><span>{tr("Tải 24 h")}</span><span className="text-ink">{util} %</span></span>
      <span className="mt-1 flex h-3.5 items-end gap-[2px] short:h-2" aria-hidden="true">{c.spark.map((v, k) => <span key={k} className="flex-1" style={{ height: `${v ? 30 + 70 * (v / Math.max(1, ...c.spark)) : 12}%`, background: v ? color : "rgba(255,255,255,0.07)" }} />)}</span>
      <span className={`mt-2 flex min-w-0 items-center gap-1.5 text-[12.5px] ${TXT[c.state] === "text-mute" ? "text-mute" : TXT[c.state]}`}>
        {c.state === "ai" ? <Spinner size={11} /> : <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: c.state === "mute" ? "var(--color-edge)" : "currentColor" }} />}
        <span className="min-w-0 truncate">{line}</span>
      </span>
      <span className="lab-cap mt-auto flex gap-2.5 overflow-hidden whitespace-nowrap border-t border-line pt-1.5 !text-[11.5px]"><span>{tv`Xong ${c.done}`}</span><span>{tv`Đang ${c.doing}`}</span><span className={c.fail ? "text-tally" : ""}>{tv`Lỗi ${c.fail}`}</span>{c.p95 != null && <span className="ml-auto hidden 2xl:inline">p95 {secs(c.p95)}</span>}</span>
    </button>
  );
}

/* A brain drawn as stacked contour lines, the way a scanner slices it; deterministic, so it does not shimmer between renders. */
const BRAIN = (() => {
  const paths: string[] = [];
  for (let i = 0; i <= 38; i++) {
    const v = -1 + (2 * i) / 38;                                   // top (-1) to bottom (+1) of the cerebrum
    const half = Math.sqrt(Math.max(0, 1 - v * v)) * (1 - 0.12 * Math.max(0, v)) * (1 + 0.08 * Math.exp(-((v - 0.35) ** 2) / 0.05));
    if (half < 0.05) continue;
    const pts: string[] = [];
    for (let j = 0; j <= 60; j++) {
      const u = -1 + (2 * j) / 60, x = u * half * 150;
      const fold = 3.2 * Math.sin(u * 13 + i * 0.9) * Math.sin(v * 7 + u * 3) + 2 * Math.sin(u * 29 + i * 1.7);
      const y = v * 108 + fold - 10 + Math.abs(u) * 6 * (v < 0 ? 1 : -0.3);
      pts.push(`${(300 + x).toFixed(1)},${(300 + y).toFixed(1)}`);
    }
    paths.push(pts.join(" "));
  }
  for (let i = 0; i <= 9; i++) {                                    // the cerebellum, tucked under the back
    const v = -1 + (2 * i) / 9, half = Math.sqrt(Math.max(0, 1 - v * v)) * 52, pts: string[] = [];
    for (let j = 0; j <= 30; j++) { const u = -1 + (2 * j) / 30; pts.push(`${(372 + u * half).toFixed(1)},${(392 + v * 26 + 1.5 * Math.sin(u * 17 + i)).toFixed(1)}`); }
    paths.push(pts.join(" "));
  }
  for (let i = 0; i <= 10; i++) { const y = 392 + i * 6, w = 15 - i * 0.6, pts: string[] = [];   // the stem, as short rings
    for (let j = 0; j <= 12; j++) { const u = -1 + (2 * j) / 12; pts.push(`${(318 + u * w + i * 1.2).toFixed(1)},${(y + 2 * Math.sin(u * 3)).toFixed(1)}`); } paths.push(pts.join(" ")); }
  return paths;
})();

/** The centre dial: a degree ring, the brain inside it, and the work in progress labelled round the rim with leader lines. */
function Dial({ radar, home, running, cards, open, onPanel }: { radar: Radar | null; home: HomeLite | null; running: Run[]; cards: Card[]; open: (id: string) => void; onPanel: (d: string) => void }) {
  const subjects = [...(radar?.subjects ?? [])].sort((a, b) => b.seconds - a.seconds);
  const tags: { text: string; color: string; act: () => void }[] = [
    ...running.slice(0, 4).map((r) => { const st = r.stages.find((s) => s.status === "running" || waits(s.status)); return { text: `${rid(r.run_id)} · ${st ? sn(st.stage_key, r.pipeline) : PIPE[r.pipeline] ?? r.pipeline}`, color: waits(r.status) ? "var(--color-cue)" : "var(--color-ai)", act: () => open(r.run_id) }; }),
    ...subjects.slice(0, 8 - Math.min(4, running.length)).map((s) => ({ text: s.subject.length > 15 ? s.subject.slice(0, 14) + "…" : s.subject, color: "var(--color-accent)", act: () => onPanel("radar") })),
  ];
  const at = [-48, -18, 18, 48, 132, 162, 198, 228];
  const pole = (deg: number, r: number) => { const a = ((deg - 90) * Math.PI) / 180; return [300 + r * Math.cos(a), 300 + r * Math.sin(a)]; };
  const busy = cards.filter((c) => c.state === "ai" || c.state === "cue");
  return (
    <div className="lab-card relative h-full min-h-[380px] overflow-hidden lg:min-h-0" aria-label={tr("Bộ não")}>
      <svg viewBox="-70 0 740 600" className="absolute inset-x-0 top-7 h-[calc(100%-60px)] w-full" preserveAspectRatio="xMidYMid meet" role="img" aria-label={tr("Các chủ đề trong kho footage")}>
        <circle cx="300" cy="300" r="250" fill="none" stroke="var(--color-accent)" strokeOpacity=".45" />
        {Array.from({ length: 72 }, (_, k) => { const [x1, y1] = pole(k * 5, 250), [x2, y2] = pole(k * 5, k % 6 === 0 ? 240 : 245); return <line key={k} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--color-accent)" strokeOpacity=".45" />; })}
        {[0, 90, 180, 270].map((d) => { const [x, y] = pole(d, 250); return <rect key={d} x={x - 3} y={y - 3} width="6" height="6" fill="var(--color-canvas)" stroke="var(--color-accent)" />; })}
        <path d={`M 300 50 A 250 250 0 0 1 ${pole(18, 250).join(" ")}`} fill="none" stroke="var(--color-cue)" strokeWidth="2" strokeOpacity=".8" />
        <g className="lab-breathe">{BRAIN.map((d, k) => <polyline key={k} points={d} fill="none" stroke="var(--color-accent)" strokeOpacity={0.42 + 0.22 * Math.cos(k / 5)} strokeWidth=".85" />)}</g>
        <line x1="150" y1="300" x2="450" y2="300" stroke="var(--color-accent)" strokeOpacity=".25" className="lab-scan" />
        {tags.map((t, k) => { const deg = at[k], [rx, ry] = pole(deg, 250), [bx, by] = pole(deg, 130), [ox, oy] = pole(deg, 268); const right = Math.sin((deg * Math.PI) / 180) >= 0; return (
          <g key={k} role="button" tabIndex={0} onClick={t.act} onKeyDown={(e) => { if (e.key === "Enter") t.act(); }} className="dial-tag cursor-pointer">
            <line x1={rx} y1={ry} x2={bx} y2={by} stroke={t.color} strokeOpacity=".5" strokeDasharray="2 3" />
            <line x1={rx} y1={ry} x2={ox} y2={oy} stroke={t.color} strokeOpacity=".7" />
            <circle cx={rx} cy={ry} r="3.6" fill={t.color} />
            <text x={ox + (right ? 6 : -6)} y={oy + 5} textAnchor={right ? "start" : "end"} className="lab-svgtag" style={{ fontSize: 17 }} fill={t.color}>{t.text}</text>
          </g>); })}
        <g className="orbit" style={{ transformOrigin: "300px 300px" }}>
          <g transform={`translate(${pole(70, 250).join(",")})`}><circle r="9" fill="var(--color-canvas)" stroke="var(--color-ink)" strokeOpacity=".8" /><circle r="3" fill="var(--color-ink)" />{[0, 60, 120, 180, 240, 300].map((a) => <line key={a} x1={Math.cos((a * Math.PI) / 180) * 10} y1={Math.sin((a * Math.PI) / 180) * 10} x2={Math.cos((a * Math.PI) / 180) * 17} y2={Math.sin((a * Math.PI) / 180) * 17} stroke="var(--color-ink)" strokeOpacity=".6" strokeDasharray="1.5 2" />)}</g>
        </g>
      </svg>
      <button type="button" onClick={() => onPanel("radar")} className="lab-cap absolute left-3 top-2.5 hover:text-ink hover:underline">{tr("Bộ não")} · {tv`${subjects.length} chủ đề · ${home?.counts.moments ?? 0} cảnh`}</button>
      <div className="lab-cap absolute bottom-2.5 left-3 right-3 flex flex-wrap justify-between gap-2">
        <span>{busy.length ? tv`Đang bận: ${busy.map((c) => c.label).join(", ")}` : tr("Không bộ phận nào bận")}</span>
        <span className="flex gap-3"><span style={{ color: "var(--color-ai)" }}>■ {tr("việc đang chạy")}</span><span style={{ color: "var(--color-accent)" }}>■ {tr("chủ đề nhiều footage nhất")}</span></span>
      </div>
    </div>
  );
}

/** Each department's lane: what waits, what is under way, what just finished, as boxed run numbers. */
function TaskBoard({ all: runs, open }: { all: Run[]; open: (id: string) => void }) {
  const groups: [string, string, string][] = [["vision", tr("Thị giác"), "library."], ["match", tr("Chọn clip"), "sourcing."], ["cut", tr("Dựng"), "edit."], ["publish", tr("Phát hành"), "publish."]];
  const lanes = groups.map(([key, label, pre]) => { const rs = runs.filter((r) => r.pipeline.startsWith(pre)); return { key, label, runs: rs, spark: perHour(rs.map((r) => r.created_at)) }; }).filter((c) => c.runs.length > 0);
  const all = lanes.flatMap((c) => c.runs);
  const q = all.filter((r) => r.status === "queued").length, wip = all.filter((r) => r.status === "running" || waits(r.status)).length;
  const p50 = pct(all.map((r) => took(details.get(r.run_id))).filter((x): x is number => x != null && x > 0), 0.5);
  const isDone = (r: Run) => r.status === "succeeded" || r.status === "failed" || r.status === "cancelled";
  const COLS = "grid grid-cols-[minmax(0,1fr)_36px_36px_40px_minmax(0,1.5fr)] items-center gap-2";
  return (
    <section className="lab-card flex h-full min-h-0 flex-col px-3 py-2" aria-label={tr("Bảng việc")}>
      <div className="mb-1.5 flex items-center gap-3"><span className="lab-cap text-ink">{tr("Bảng việc")}</span><span className="lab-cap ml-auto">{tv`Chờ ${q}`}</span><span className="lab-cap">{tv`Đang làm ${wip}`}</span><span className="lab-cap">p50 {secs(p50)}</span></div>
      <div className={`lab-cap !text-[10.5px] ${COLS}`}><span>{tr("Bộ phận")}</span><span className="text-right">{tr("chờ")}</span><span className="text-right">{tr("đang")}</span><span className="text-right">{tr("xong")}</span><span>{tr("gần nhất")}</span></div>
      {lanes.length === 0 && <p className="mt-2 text-[12.5px] text-faint">{tr("— chưa có việc nào")}</p>}
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {lanes.map((c) => { const n = (t: (r: Run) => boolean) => c.runs.filter(t).length; const recent = [...c.runs].sort((a, b) => Number(isDone(a)) - Number(isDone(b)) || b.created_at - a.created_at).slice(0, 2); return (
          <li key={c.key} className={`${COLS} border-t border-line/60 py-[5px]`}>
            <button type="button" onClick={() => goTo("/tien-trinh")} className="flex min-w-0 items-center gap-2 text-left text-[12.5px] hover:underline"><span className="h-2 w-2 shrink-0 rounded-[2px]" style={{ background: DEPT[c.key] }} /><span className="truncate">{c.label}</span></button>
            <span className="mono text-right text-[12.5px] text-mute">{n((r) => r.status === "queued")}</span>
            <span className="mono text-right text-[12.5px] text-ai">{n((r) => r.status === "running" || waits(r.status)) || <span className="text-faint">0</span>}</span>
            <span className="mono text-right text-[12.5px]">{n(isDone)}</span>
            <span className="flex min-w-0 gap-1 overflow-hidden">{recent.map((r) => (
              <button key={r.run_id} type="button" onClick={() => open(r.run_id)} title={`${PIPE[r.pipeline] ?? r.pipeline}: ${statusName(r.status)}`}
                      className="lab-tag shrink-0 whitespace-nowrap !normal-case hover:!text-ink" style={{ borderColor: failing(r) ? "var(--color-tally)" : isDone(r) ? DEPT[c.key] : waits(r.status) ? "var(--color-cue)" : "var(--color-ai)", color: failing(r) ? "var(--color-tally)" : undefined }}>{rid(r.run_id)}</button>))}</span>
          </li>); })}
      </ul>
    </section>
  );
}

/** Task fit: each recent run pulled toward the department that took it; a red ring marks one that failed. */
function RadViz({ all }: { all: Run[] }) {
  const groups: [string, string, string[]][] = [["vision", tr("Thị giác"), ["library."]], ["match", tr("Chọn clip"), ["sourcing."]], ["cut", tr("Dựng"), ["edit."]], ["publish", tr("Phát hành"), ["publish."]]];
  const cards = groups.map(([key, label, pre]) => ({ key, label, runs: all.filter((r) => pre.some((x) => r.pipeline.startsWith(x))) }));
  const pts = cards.flatMap((c, i) => [...c.runs].sort((a, b) => b.created_at - a.created_at).slice(0, 15).map((r, k) => ({ i, r, k })));
  const anchor = (i: number) => { const a = (i / cards.length) * Math.PI * 2 - Math.PI / 2; return [100 + 78 * Math.cos(a), 100 + 78 * Math.sin(a)]; };
  return (
    <section className="lab-card flex min-h-0 flex-col p-3" aria-label={tr("Phân bổ việc")}>
      <div className="lab-cap mb-1 flex justify-between"><span>{tr("Phân bổ việc")} · RADVIZ</span><span>{tv`n ${pts.length} · lỗi ${pts.filter((p) => failing(p.r)).length}`}</span></div>
      <div className="flex items-center gap-3">
        <svg viewBox="0 0 200 200" className="h-44 w-44 shrink-0" role="img" aria-label={tr("Phân bổ việc")}>
          <circle cx="100" cy="100" r="78" fill="none" stroke="var(--color-edge)" />
          {cards.map((c, i) => { const [x, y] = anchor(i); return <g key={c.key}><line x1="100" y1="100" x2={x} y2={y} stroke="var(--color-line)" /><rect x={x - 3} y={y - 3} width="6" height="6" fill={DEPT[c.key]} /></g>; })}
          {pts.map(({ i, r, k }) => { const [ax, ay] = anchor(i), f = 0.35 + ((k * 37) % 50) / 100, j = ((k * 53) % 21) - 10; const x = 100 + (ax - 100) * f + j * 0.6, y = 100 + (ay - 100) * f - j * 0.4;
            return failing(r) ? <circle key={r.run_id} cx={x} cy={y} r="3.4" fill="none" stroke="var(--color-tally)" /> : <circle key={r.run_id} cx={x} cy={y} r="2.2" fill={DEPT[cards[i].key]} opacity=".9" />; })}
        </svg>
        <ul className="lab-cap grid gap-1 !normal-case !tracking-normal">
          <li>{tr("chấm = một việc")}</li><li>{tr("hút về = bộ phận")}</li><li>{tr("màu = bộ phận")}</li><li className="text-tally">○ {tr("việc lỗi")}</li><li className="mt-1">{tr("15 việc gần nhất mỗi bộ phận")}</li>
        </ul>
      </div>
    </section>
  );
}

/** Two needles: work started in the last hour, and how long a cut takes at the 95th percentile. */
function Gauges({ all }: { all: Run[] }) {
  const hour = all.filter((r) => r.created_at > Date.now() / 1000 - 3600).length;
  const peak = Math.max(1, ...perHour(all.map((r) => r.created_at)));
  const cuts = all.filter((r) => r.pipeline === "edit.render").map((r) => took(details.get(r.run_id))).filter((x): x is number => x != null && x > 0);
  const p95 = pct(cuts, 0.95) ?? 0, top = Math.max(60, Math.ceil(((Math.max(...cuts, 1) * 1.2) / 30)) * 30);
  const dial = (value: number, max: number, label: string, shown: string, sub: string) => {
    const a = (v: number) => Math.PI * (0.75 + 1.5 * Math.min(1, v / max));
    const tick = (v: number, r1: number, r2: number) => [100 + r1 * Math.cos(a(v)), 100 + r1 * Math.sin(a(v)), 100 + r2 * Math.cos(a(v)), 100 + r2 * Math.sin(a(v))];
    return (
      <div className="flex flex-col items-center">
        <svg viewBox="0 0 200 170" className="h-32 w-36" role="img" aria-label={`${label}: ${shown}`}>
          {Array.from({ length: 31 }, (_, k) => { const [x1, y1, x2, y2] = tick((k / 30) * max, 70, k % 5 === 0 ? 60 : 65); return <line key={k} x1={x1} y1={y1} x2={x2} y2={y2} stroke={k > 25 ? "var(--color-tally)" : "var(--color-mute)"} strokeOpacity=".8" />; })}
          {Array.from({ length: 7 }, (_, k) => { const v = (k / 6) * max, [, , x, y] = tick(v, 0, 50); return <text key={k} x={x} y={y + 3} textAnchor="middle" className="lab-svgcap">{Math.round(v)}</text>; })}
          {(() => { const [, , x, y] = tick(value, 0, 64); return <line x1="100" y1="100" x2={x} y2={y} stroke="var(--color-ink)" strokeWidth="2" strokeLinecap="round" />; })()}
          <circle cx="100" cy="100" r="4" fill="var(--color-ink)" />
          <text x="100" y="138" textAnchor="middle" className="lab-svgbig">{shown}</text>
        </svg>
        <span className="lab-cap">{label}</span><span className="lab-cap !text-cue">{sub}</span>
      </div>
    );
  };
  return (
    <section className="lab-card flex min-h-0 flex-col justify-between p-3" aria-label={tr("Tốc độ và độ trễ")}>
      <div className="lab-cap mb-1 flex justify-between"><span>{tr("Tốc độ · độ trễ")}</span><span>{tr("cửa sổ 24 h")}</span></div>
      <div className="grid grid-cols-2">{dial(hour, Math.max(6, peak), tr("việc / giờ"), String(hour), tv`đỉnh 24 h ${peak}`)}{dial(p95, top, tr("p95 dựng (s)"), secs(p95), tv`${cuts.length} bản dựng`)}</div>
    </section>
  );
}

/** Load by hour on a polar grid: rings are the last seven days (today outside), sectors are the hours, now is outlined. */
function LoadGrid({ all, window = "" }: { all: Run[]; window?: string }) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const cell = (d: number, h: number) => all.filter((r) => { const t = new Date(r.created_at * 1000); return Math.floor((today.getTime() - new Date(t.getFullYear(), t.getMonth(), t.getDate()).getTime()) / 86400000) === 6 - d && t.getHours() === h; }).length;
  const grid = Array.from({ length: 7 }, (_, d) => Array.from({ length: 24 }, (_, h) => cell(d, h)));
  const peak = Math.max(1, ...grid.flat()), hourNow = new Date().getHours();
  const [a, b] = window.includes("-") ? window.split("-").map(Number) : [NaN, NaN];
  const inWin = (h: number) => !Number.isNaN(a) && !Number.isNaN(b) && (a <= b ? h >= a && h < b : h >= a || h < b);
  const WD = [tr("CN"), tr("T2"), tr("T3"), tr("T4"), tr("T5"), tr("T6"), tr("T7")];
  const day = (d: number) => { if (d === 6) return tr("Hôm nay"); const t = new Date(today); t.setDate(t.getDate() - (6 - d)); return WD[t.getDay()]; };
  const fill = (v: number) => (v ? `color-mix(in srgb, var(--color-accent) ${25 + 75 * (v / peak)}%, transparent)` : "rgba(255,255,255,0.05)");
  return (
    <section className="lab-card flex min-h-0 flex-col p-3" aria-label={tr("Tải theo giờ")}>
      <div className="lab-cap mb-2 flex justify-between"><span>{tr("Tải theo giờ")}</span><span>{tr("7 ngày × 24 giờ")}</span></div>
      <div className="grid min-h-0 flex-1 content-center gap-y-[3px]" style={{ gridTemplateColumns: "52px minmax(0,1fr)" }}>
        {grid.map((row, d) => (
          <div key={d} className="contents">
            <span className={`self-center text-[11.5px] ${d === 6 ? "text-ink" : "text-mute"}`}>{day(d)}</span>
            <span className="grid gap-[2px]" style={{ gridTemplateColumns: "repeat(24, minmax(0,1fr))" }}>{row.map((v, h) => (
              <span key={h} title={`${day(d)} ${String(h).padStart(2, "0")}:00 · ${v}`} className="h-3.5 rounded-[1px]" style={{ background: fill(v), outline: d === 6 && h === hourNow ? "1.5px solid var(--color-cue)" : "none", outlineOffset: -1 }} />))}</span>
          </div>))}
        <span />
        <span className="mt-1 grid gap-[2px]" style={{ gridTemplateColumns: "repeat(24, minmax(0,1fr))" }}>{Array.from({ length: 24 }, (_, h) => (
          <span key={h} className="relative h-3">{inWin(h) && <span className="absolute inset-x-0 top-0 h-[2px] bg-accent/70" />}{h % 6 === 0 && <span className="mono absolute left-0 top-[3px] text-[10.5px] text-faint">{String(h).padStart(2, "0")}</span>}</span>))}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-mute">
        <span className="flex items-center gap-1">{tr("ít")}{[0.2, 0.5, 0.8, 1].map((x) => <span key={x} className="h-2.5 w-3 rounded-[1px]" style={{ background: `color-mix(in srgb, var(--color-accent) ${25 + 75 * x}%, transparent)` }} />)}{tr("nhiều")}</span>
        <span className="flex items-center gap-1"><span className="h-2.5 w-3 rounded-[1px] outline outline-1 outline-cue" />{tr("giờ hiện tại")}</span>
        {window && <span className="flex items-center gap-1"><span className="h-[2px] w-3 bg-accent/70" />{tv`giờ phân tích ${window}`}</span>}
      </div>
    </section>
  );
}

/* ───────────────────────── lens 2: pipelines ───────────────────────── */

function Pipelines({ all, caps, agent, open }: { all: Run[]; caps: Caps | null; agent: AgentTask[]; open: (id: string) => void }) {
  const [unfold, setUnfold] = useState<string | null>(null);
  const tasks = agent.filter((t) => t.status !== "done" && t.status !== "cancelled");
  const defs = caps?.pipelines ?? [];
  const week = Date.now() / 1000 - 7 * 86400;
  return (
    <div className="grid gap-3 lg:h-full lg:min-h-0 lg:grid-rows-[auto_minmax(0,1fr)]">
      <Frame title={tr("Workflow của Trợ lý sản xuất")} icon="sparkles" tone="ai" end={tv`${tasks.length} việc đang làm, ${agent.length} tất cả`}>
        <ol className="scroll-x flex items-start pb-1">
          {STEPS.map(([k, label], i) => { const here = tasks.filter((t) => t.step === k); const wait = here.some((t) => t.status === "waiting_operator"); return (
            <li key={k} className="flex min-w-[88px] flex-1 items-start">
              <span className="flex w-full flex-col items-center gap-1 text-center">
                <span className={`mono grid h-7 min-w-7 place-items-center rounded-full border px-1.5 text-[12.5px] ${here.length ? (wait ? "border-cue/60 bg-cue/10 text-cue" : "border-ai/60 bg-ai/10 text-ai") : "border-line text-faint"}`}>{here.length || i + 1}</span>
                <span className="text-[12.5px] leading-tight text-mute">{label}</span>
                {here.slice(0, 2).map((t) => <button key={t.task_id} type="button" onClick={() => goTo(`/du-an/${t.project_id}`)} title={t.goal} className="mt-0.5 max-w-[84px] truncate rounded bg-ai/10 px-1.5 text-[12px] text-ai hover:bg-ai/20">{t.goal}</button>)}
              </span>
              {i < STEPS.length - 1 && <span className="mt-3.5 h-px w-3 shrink-0 bg-line" />}
            </li>); })}
        </ol>
      </Frame>
      <div className="grid gap-3 lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_340px]">
      <Frame className="lg:min-h-0" title={tr("Pipeline")} icon="layers" end={tv`${defs.length} pipeline, ${all.length} lần chạy`}>
        <div className="mono mb-1.5 hidden grid-cols-[180px_minmax(0,1fr)_56px_64px_64px_72px] gap-3 px-2 text-[11.5px] text-faint lg:grid"><span>{tr("pipeline")}</span><span>{tr("các bước")}</span><span className="text-right">{tr("đang")}</span><span className="text-right">{tr("7 ngày")}</span><span className="text-right">{tr("p95")}</span><span className="text-right">{tr("lần cuối")}</span></div>
        <ul className="grid min-h-0 content-start gap-1 overflow-y-auto">
          {defs.map((d) => {
            const rs = all.filter((r) => r.pipeline === d.pipeline).sort((a, b) => b.created_at - a.created_at);
            const act = rs.filter((r) => live(r.status) || waits(r.status));
            const recent = rs.filter((r) => r.created_at > week);
            const fails = recent.filter(failing).length;
            const times = rs.map((r) => took(details.get(r.run_id))).filter((x): x is number => x != null && x > 0);
            const stageState = (key: string): Tone => { const st = act.flatMap((r) => r.stages.filter((s) => s.stage_key === key).map((s) => s.status));
              return st.includes("running") ? "ai" : st.some(waits) ? "cue" : st.includes("failed") ? "tally" : st.includes("queued") ? "accent" : "mute"; };
            return (
              <li key={d.pipeline} className={`rounded-lg ${d.available ? "" : "opacity-60"}`}>
                <button type="button" onClick={() => setUnfold(unfold === d.pipeline ? null : d.pipeline)} aria-expanded={unfold === d.pipeline}
                        className="grid w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-white/[0.03] lg:grid-cols-[180px_minmax(0,1fr)_48px_88px_60px_80px]">
                  <span className="min-w-0"><span className="block truncate text-[14px] font-medium">{PIPE[d.pipeline] ?? d.pipeline}</span><span className="mono block truncate text-[12px] text-faint">{d.pipeline}</span></span>
                  <span className="scroll-x flex items-center">
                    {d.stages.map((s, i) => { const id = `${d.pipeline}/${s.key}`, t = stageState(s.key); return (
                      <span key={s.key} className="flex shrink-0 items-center">
                        {i > 0 && <span className={`h-px w-4 ${t !== "mute" ? BG[t] : "bg-line"}`} />}
                        <span title={`${sn(s.key, d.pipeline)}${s.requires.length ? tv`, cần ${s.requires.map((q) => ENGINE[q]?.[0] ?? q).join(", ")}` : ""}${s.available ? "" : tr(", chưa dùng được")}`}
                              className={`flex h-6 items-center gap-1 rounded-md border px-1.5 text-[12.5px] ${t === "ai" ? "border-ai/60 bg-ai/10 text-ai" : t === "cue" ? "border-cue/60 bg-cue/10 text-cue" : t === "tally" ? "border-tally/60 bg-tally/10 text-tally" : t === "accent" ? "border-accent/50 text-accent" : s.available ? "border-line text-mute" : "border-dashed border-line text-faint"}`}>
                          {t === "ai" && <Lamp tone="ai" pulse />}{sn(s.key, d.pipeline)}
                          {GATE.has(id) && <Icon name="eye" size={10} className="text-cue" />}{COSTLY.has(id) && <span className="text-cue">$</span>}{NIGHT.has(id) && <Icon name="clock" size={10} className="text-faint" />}
                        </span>
                      </span>); })}
                    {!d.available && <span className="ml-2 shrink-0 text-[12.5px] text-cue">{tv`thiếu ${d.missing.map((q) => ENGINE[q]?.[0] ?? q).join(", ")}`}</span>}
                  </span>
                  <span className={`mono hidden text-right text-[13px] lg:block ${act.length ? "text-ai" : "text-faint"}`}>{act.length}</span>
                  <span className="mono hidden text-right text-[13px] lg:block">{recent.length}{fails ? <span className="ml-1 text-tally">{tv`(${fails} lỗi)`}</span> : null}</span>
                  <span className="mono hidden text-right text-[13px] text-mute lg:block">{secs(pct(times, 0.95))}</span>
                  <span className="mono hidden text-right text-[12.5px] text-faint lg:block">{rs[0] ? ago(rs[0].created_at) : "–"}</span>
                </button>
                {unfold === d.pipeline && (
                  <ul className="mb-2 ml-2 grid gap-0.5 border-l border-line pl-3">
                    {rs.length === 0 && <li className="py-1 text-[13px] text-faint">{tr("Chưa chạy lần nào.")}</li>}
                    {rs.slice(0, 8).map((r) => (
                      <li key={r.run_id}><button type="button" onClick={() => open(r.run_id)} className="flex w-full items-center gap-2.5 rounded-md px-2 py-1 text-left text-[13px] hover:bg-white/[0.04]">
                        <Lamp tone={toneOf(r.status)} pulse={r.status === "running"} /><span className="mono text-faint">{clock(r.created_at)}</span><span className="text-mute">{statusName(r.status)}</span>
                        <span className="mono ml-auto text-faint">{secs(took(details.get(r.run_id)))}</span><Icon name="next" size={12} className="text-faint" /></button></li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
        <p className="mono mt-2 flex flex-wrap gap-4 px-2 text-[12px] text-faint"><span className="flex items-center gap-1"><Icon name="eye" size={10} className="text-cue" />{tr("chờ bạn duyệt")}</span><span><span className="text-cue">$</span> {tr("tốn tiền")}</span><span className="flex items-center gap-1"><Icon name="clock" size={10} />{tr("chạy nền, theo giờ phân tích")}</span></p>
      </Frame>
      <RadViz all={all} />
      </div>
    </div>
  );
}

/* ───────────────────────── lens 3: runtime ───────────────────────── */

function Runtime({ all, caps, ctl, auto, usage, home, reloadAuto, open }: { all: Run[]; caps: Caps | null; ctl: Control | null; auto: Autonomy | null; usage: Usage | null; home: HomeLite | null; reloadAuto: () => void; open: (id: string) => void }) {
  const runningNow = all.filter((r) => r.status === "running");
  const claim = (lane: string) => runningNow.filter((r) => details.get(r.run_id)?.attempts.some((a) => a.outcome == null && a.worker.startsWith(lane)));
  const used = home ? 1 - home.disk.free_bytes / home.disk.total_bytes : 0;
  // Every engine a step can ask for, with what the books say it has done.
  const needs = new Map<string, boolean>();
  for (const p of caps?.pipelines ?? []) for (const s of p.stages) for (const q of s.requires) needs.set(q, (needs.get(q) ?? false) || s.available);
  const books = new Map<string, { calls: number; seconds: number; failures: number; cost: number; runs: string }>();
  for (const t of usage?.tools_all ?? []) { const b = books.get(t.adapter) ?? { calls: 0, seconds: 0, failures: 0, cost: 0, runs: t.runs }; b.calls += t.calls; b.seconds += t.seconds; b.failures += t.failures; b.cost += t.cost; books.set(t.adapter, b); }
  const engines = [...new Set([...needs.keys(), ...books.keys()])];
  const window = ctl?.background_window ?? "";
  const level = async (n: number) => { try { await post("/api/v1/autonomy", { level: n }); toast(tr("Đã đổi mức tự chủ."), { tone: "proof" }); } catch (e) { toast((e as Error).message, { tone: "tally" }); } reloadAuto(); };
  const backup = async () => { try { await post("/api/v1/storage/backup"); toast(tr("Đã sao lưu."), { tone: "proof" }); } catch (e) { toast((e as Error).message, { tone: "tally" }); } };
  return (
    <div className="grid gap-3 lg:h-full lg:min-h-0 lg:grid-rows-[minmax(0,auto)_minmax(250px,1fr)]">
      <div className="grid gap-3 lg:min-h-0 lg:grid-cols-3">
        {([["interactive", tr("Làn ngay"), tr("việc bạn vừa bấm: chọn clip, dựng, nhập"), true], ["background", tr("Làn nền"), tr("việc nặng: xem và mô tả, nghe, làm nét"), ctl?.background_running_now ?? true]] as const).map(([lane, label, what, allowed]) => { const mine = claim(lane); return (
          <Frame key={lane} className="lg:overflow-y-auto" title={tv`Worker: ${label}`} icon="cpu" tone={mine.length ? "ai" : "accent"} end={<><Lamp tone={!allowed ? "cue" : mine.length ? "ai" : "proof"} pulse={mine.length > 0} />{!allowed ? tr("ngoài giờ") : mine.length ? tr("đang cầm việc") : tr("rảnh")}</>}>
            <p className="mb-2 text-[13px] text-faint">{what}</p>
            {mine.length === 0 && <p className="rounded-md bg-white/[0.03] px-2.5 py-2 text-[13px] text-mute">{!allowed ? tv`Chờ tới giờ phân tích ${window}` : tr("Không cầm việc nào.")}</p>}
            <ul className="grid gap-1">{mine.map((r) => { const at = details.get(r.run_id)?.attempts.find((x) => x.outcome == null); return (
              <li key={r.run_id}><button type="button" onClick={() => open(r.run_id)} className="flex w-full items-center gap-2 rounded-md bg-ai/[0.06] px-2.5 py-1.5 text-left text-[13px] hover:bg-ai/10">
                <Spinner size={11} /><span className="truncate">{PIPE[r.pipeline] ?? r.pipeline}</span><span className="text-mute">{at ? sn(at.stage_key, r.pipeline) : ""}</span><span className="mono ml-auto text-[12px] text-faint">{at ? secs(Date.now() / 1000 - at.started_at) : ""}</span></button></li>); })}</ul>
          </Frame>); })}
        <Frame className="lg:overflow-y-auto" title={tr("Điều khiển chung")} icon="sliders">
          <p className="mb-1.5 text-[13px] text-faint">{tr("Mức tự chủ")}</p>
          <select aria-label={tr("Mức tự chủ")} value={auto?.level ?? 0} onChange={(e) => level(Number(e.target.value))} className="mb-1 h-8 w-full pl-2.5 text-[13.5px]">
            {(auto?.levels ?? []).map((l) => <option key={l.level} value={l.level} disabled={!l.earned}>{`${l.level}. ${l.name}`}{l.earned ? "" : tr(" (chưa mở khoá)")}</option>)}
          </select>
          <p className="mb-3 line-clamp-2 text-[12.5px] text-faint short:hidden">{auto?.levels.find((l) => l.level === auto.level)?.does}</p>
          <div className="grid grid-cols-2 gap-2 text-[13px]">
            <button type="button" onClick={() => goTo("/he-thong?muc=control")} className="tile p-2 text-left"><span className="block text-faint">{tr("Giờ phân tích")}</span><span className="mono text-[14px]">{window || tr("cả ngày")}</span></button>
            <button type="button" onClick={() => goTo("/chi-phi")} className="tile p-2 text-left"><span className="block text-faint">{tr("Chi phí hôm nay")}</span><span className="mono text-[14px]">{(usage?.spent_today ?? 0).toFixed(2)} USD</span></button>
            <div className="tile p-2"><span className="block text-faint">{tr("Ổ đĩa trống")}</span><span className={`mono text-[14px] ${used > 0.9 ? "text-cue" : ""}`}>{home ? megabytes(home.disk.free_bytes) : "–"}</span></div>
            <button type="button" onClick={backup} className="tile p-2 text-left"><span className="block text-faint">{tr("Sao lưu")}</span><span className="flex items-center gap-1 text-[13.5px] text-accent"><Icon name="download" size={12} />{tr("Sao lưu ngay")}</span></button>
          </div>
        </Frame>
      </div>

      <div className="grid gap-3 lg:min-h-0 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1fr)]">
      <Frame className="lg:min-h-0" title={tr("Bộ máy")} icon="layers" end={tv`${engines.filter((e) => needs.get(e) !== false).length}/${engines.length} sẵn sàng`}>
        <ul className="grid min-h-0 content-start gap-2 overflow-y-auto sm:grid-cols-2">
          {engines.map((e) => { const [name, where] = ENGINE[e] ?? [e, books.get(e)?.runs === "cloud" ? "cloud" : "local"], ok = needs.get(e) !== false, bk = books.get(e); return (
            <li key={e} className={`tile p-2.5 ${ok ? "" : "!border-cue/40"}`}>
              <span className="flex items-center gap-2"><Lamp tone={ok ? "proof" : "cue"} /><span className="truncate text-[13.5px] font-medium">{name}</span><span className={`mono ml-auto rounded px-1 text-[11px] leading-4 ${where === "cloud" ? "bg-ai/15 text-ai" : "bg-white/[0.06] text-mute"}`}>{where === "cloud" ? tr("cloud") : tr("trên máy")}</span></span>
              <span className="mono mt-1.5 flex gap-3 text-[12px] text-faint"><span>{tv`${bk?.calls ?? 0} lần`}</span><span>{secs(bk?.seconds ?? 0)}</span>{bk?.failures ? <span className="text-tally">{tv`${bk.failures} lỗi`}</span> : null}{bk?.cost ? <span>{bk.cost.toFixed(2)} USD</span> : null}</span>
              {!ok && <span className="mt-1 block text-[12.5px] text-cue">{tr("Chưa dùng được, xem Hệ thống")}</span>}
            </li>); })}
        </ul>
      </Frame>
        <Gauges all={all} />
        <LoadGrid all={all} window={window} />
      </div>
    </div>
  );
}

/* ───────────────────────── always on the right: the event stream ───────────────────────── */

function Feed({ events, open }: { events: Event[]; open: (id: string) => void }) {
  const [only, setOnly] = useState<"all" | "alert">("all");
  const shown = events.filter((e) => only === "all" || e.tone === "cue" || e.tone === "tally");
  return (
    <section className="lab-card flex h-full min-h-0 flex-col px-3 py-2" aria-label={tr("Dòng sự kiện")}>
      <div className="mb-1.5 flex items-center gap-2"><span className="lab-cap text-ink">{tr("Sự kiện")}</span>
        <div className="lab-seg ml-auto scale-90 origin-right" role="radiogroup" aria-label={tr("Lọc sự kiện")}>
          <button type="button" role="radio" aria-checked={only === "all"} onClick={() => setOnly("all")}>{tr("Tất cả")}</button>
          <button type="button" role="radio" aria-checked={only === "alert"} onClick={() => setOnly("alert")}>{tr("Cần chú ý")}</button>
        </div>
      </div>
      <ol className="min-h-0 flex-1 overflow-y-auto pr-1 text-[12px] leading-snug">
        {shown.length === 0 && <li className="py-6 text-center text-faint">{tr("— chưa có sự kiện")}</li>}
        {shown.map((e) => (
          <li key={e.key}>
            <button type="button" disabled={!e.run} onClick={() => e.run && open(e.run)} className="flex w-full gap-2 py-[3px] text-left hover:bg-white/[0.03] disabled:cursor-default disabled:hover:bg-transparent">
              <span className="shrink-0 text-faint">{clock(e.at)}</span>
              <span className={`shrink-0 ${TXT[e.tone] === "text-faint" ? "text-mute" : TXT[e.tone]}`}>▪</span>
              <span className="min-w-0"><span className={`uppercase tracking-[0.04em] ${TXT[e.tone] === "text-faint" ? "text-ink" : TXT[e.tone]}`}>{e.who}</span> <span className="font-sans text-[12.5px] text-mute">{e.text}</span></span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

/* ───────────────────────── quick panel: act on a department without leaving the room ───────────────────────── */

const META: Record<string, { label: string; role: string; to: string }> = {
  radar: { label: tr("Radar"), role: tr("tìm · gợi ý"), to: "/ke-hoach?xem=radar" },
  campaign: { label: tr("Chiến dịch"), role: tr("mục tiêu · thử nghiệm"), to: "/ke-hoach?xem=ket-qua" },
  writer: { label: tr("Biên kịch"), role: tr("viết · phản biện"), to: "/du-an" },
  vision: { label: tr("Thị giác"), role: tr("nhập · xem · mô tả"), to: "/thu-vien" },
  match: { label: tr("Chọn clip"), role: tr("tìm · sinh hình"), to: "/du-an" },
  cut: { label: tr("Dựng"), role: tr("lời dẫn · ghép · phụ đề"), to: "/du-an" },
  qc: { label: tr("Kiểm duyệt"), role: tr("chấm · duyệt"), to: "/phong-chieu" },
  publish: { label: tr("Phát hành"), role: tr("đăng · đo"), to: "/ke-hoach?xem=ket-qua" },
};
/** Which department each station of the loop belongs to. */
const STATION = ["radar", "campaign", "writer", "vision", "match", "cut", "qc", "publish", "publish"];
const FIGURES: [string, string][] = [["views", tr("Lượt xem")], ["likes", tr("Thích")], ["comments", tr("Bình luận")], ["shares", tr("Chia sẻ")], ["watch_seconds", tr("Giây xem")]];

type Ctx = { all: Run[]; projects: Project[]; radar: Radar | null; camps: Campaign[]; pub: Publishing | null; agent: AgentTask[]; ctl: Control | null; home: HomeLite | null; reload: () => void; openRun: (id: string) => void };

function Sec({ title, end, children }: { title: string; end?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="border-b border-line px-5 py-4 last:border-b-0">
      <h3 className="mb-2.5 flex items-center gap-2 text-[13px] font-semibold text-ink">{title}<span className="ml-auto text-[12px] font-normal text-faint">{end}</span></h3>
      {children}
    </section>
  );
}
const Empty = ({ children }: { children: React.ReactNode }) => <p className="rounded-md bg-white/[0.03] px-3 py-2.5 text-[13px] text-mute">{children}</p>;
const Row = ({ children, className = "" }: { children: React.ReactNode; className?: string }) => <li className={`rounded-lg border border-line bg-white/[0.02] px-3 py-2.5 ${className}`}>{children}</li>;
const Field = "h-8 min-w-0 rounded-md px-2.5 text-[13px]";

function QuickPanel({ dept, ctx, look, close }: { dept: string; ctx: Ctx; look: Look; close: () => void }) {
  const m = META[dept];
  const [busy, setBusy] = useState<string | null>(null);
  // Esc closes the panel, unless a run opened from it sits on top; that one closes first.
  useEffect(() => { const key = (e: KeyboardEvent) => { if (e.key === "Escape" && !document.querySelector("aside.run-drawer")) close(); }; window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key); }, [close]);
  const act = async (key: string, fn: () => Promise<unknown>, done: string) => { setBusy(key); try { await fn(); toast(done, { tone: "proof" }); ctx.reload(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } setBusy(null); };
  const full = () => { close(); goTo(m.to); };
  // A floating window in the middle of the screen; drag it by its title bar, double-click the bar to bring it back. It remembers where you left it.
  const [pos, setPos] = useState<{ x: number; y: number }>(() => { try { return JSON.parse(localStorage.getItem("nx.control.quickpos") || "") as { x: number; y: number }; } catch { return { x: 0, y: 0 }; } });
  const win = useRef<HTMLElement | null>(null);
  const place = (x: number, y: number) => {
    const w = win.current?.offsetWidth ?? 560, h = win.current?.offsetHeight ?? 600, keep = 120;
    const mx = (innerWidth + w) / 2 - keep, my = (innerHeight + h) / 2 - keep;   // always leave part of the window on screen
    return { x: Math.max(-mx, Math.min(mx, x)), y: Math.max(-(innerHeight - h) / 2, Math.min(my, y)) };
  };
  const drag = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest("button, a, input, select")) return;
    e.preventDefault();
    const sx = e.clientX, sy = e.clientY, from = pos; let last = pos;
    const move = (ev: PointerEvent) => { last = place(from.x + ev.clientX - sx, from.y + ev.clientY - sy); setPos(last); };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); try { localStorage.setItem("nx.control.quickpos", JSON.stringify(last)); } catch { /* fine */ } };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };
  const center = () => { setPos({ x: 0, y: 0 }); try { localStorage.removeItem("nx.control.quickpos"); } catch { /* fine */ } };
  const body: Record<string, React.ReactNode> = {
    radar: <RadarQuick ctx={ctx} act={act} busy={busy} />, campaign: <CampaignQuick ctx={ctx} act={act} busy={busy} />, writer: <WriterQuick ctx={ctx} act={act} busy={busy} close={close} />,
    vision: <VisionQuick ctx={ctx} act={act} busy={busy} />, match: <MatchQuick ctx={ctx} act={act} busy={busy} close={close} />, cut: <CutQuick ctx={ctx} act={act} busy={busy} close={close} />,
    qc: <ReviewQuick ctx={ctx} act={act} busy={busy} />, publish: <PublishQuick ctx={ctx} act={act} busy={busy} />,
  };
  return createPortal(
    <div className={`${LOOK[look]} fixed inset-0 z-50`} style={{ background: "transparent" }} onClick={close}>
      <div className="absolute inset-0 bg-black/35" />
      <aside ref={win} role="dialog" aria-label={m.label} onClick={(e) => e.stopPropagation()}
             className="quick-win absolute left-1/2 top-1/2 flex max-h-[min(800px,88vh)] w-[560px] max-w-[94vw] flex-col overflow-hidden border border-edge shadow-[0_24px_80px_-12px_rgba(0,0,0,0.75)]"
             style={{ background: "var(--color-surface)", transform: `translate(calc(-50% + ${pos.x}px), calc(-50% + ${pos.y}px))` }}>
        <header onPointerDown={drag} onDoubleClick={center} title={tr("Kéo để di chuyển · bấm đúp để đưa về giữa")} className="flex cursor-move select-none items-center gap-3 border-b border-line px-5 py-3.5" style={{ touchAction: "none" }}>
          <span aria-hidden="true" className="-ml-2 grid grid-cols-2 gap-[3px] opacity-40">{Array.from({ length: 6 }, (_, k) => <span key={k} className="h-[3px] w-[3px] rounded-full bg-[var(--color-mute)]" />)}</span>
          <DeptIcon kind={dept} />
          <span className="min-w-0 flex-1"><span className="block truncate text-[16px] font-semibold text-ink">{m.label}</span><span className="block truncate text-[12.5px] text-faint">{m.role}</span></span>
          <button type="button" onClick={full} className="lab-btn"><Icon name="external" size={13} />{tr("Mở trang đầy đủ")}</button>
          <button type="button" onClick={close} aria-label={tr("Đóng")} className="grid h-8 w-8 place-items-center rounded-md text-mute hover:bg-white/[0.06] hover:text-ink"><Icon name="x" size={16} /></button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">{body[dept]}</div>
        <footer className="flex items-center gap-3 border-t border-line px-5 py-2.5 text-[12px] text-faint"><span>{tr("Esc để đóng · thay đổi ở đây được lưu ngay")}</span>{(pos.x !== 0 || pos.y !== 0) && <button type="button" onClick={center} className="ml-auto hover:text-ink hover:underline">{tr("Đưa về giữa")}</button>}</footer>
      </aside>
    </div>,
    document.body,
  );
}
type Act = (key: string, fn: () => Promise<unknown>, done: string) => Promise<void>;

/** Recent runs of one kind, each with the one fix that fits: run a failed step again, or stop one that is going. */
function RunRows({ runs, ctx, act, busy, none }: { runs: Run[]; ctx: Ctx; act: Act; busy: string | null; none: string }) {
  const list = [...runs].sort((a, b) => b.created_at - a.created_at).slice(0, 8);
  if (!list.length) return <Empty>{none}</Empty>;
  const open = runs.filter(failing);
  const dismiss = (ids: string[]) => act(ids.length > 1 ? "dismiss-all" : ids[0], () => post("/api/v1/runs/dismiss", { run_ids: ids }), ids.length > 1 ? tv`Đã bỏ qua ${ids.length} lỗi.` : tr("Đã bỏ qua lỗi này."));
  const cancel = async (r: Run) => { if (await ask(tr("Huỷ việc này?"), { body: tr("Các bước chưa chạy sẽ không chạy nữa. Kết quả các bước đã xong vẫn được giữ."), confirm: tr("Huỷ việc") })) act(r.run_id, () => post(`/api/v1/runs/${r.run_id}/cancel`), tr("Đã huỷ việc.")); };
  return (
    <ul className="grid gap-1.5">
      {open.length > 1 && <li className="flex justify-end"><Button size="sm" kind="quiet" busy={busy === "dismiss-all"} onClick={() => dismiss(open.map((r) => r.run_id))}>{tv`Bỏ qua cả ${open.length} lỗi`}</Button></li>}
      {list.map((r) => { const bad = failing(r) ? r.stages.find((s) => s.status === "failed") : undefined; const t = r.cleared ? "mute" : toneOf(r.status); return (
        <Row key={r.run_id} className="flex items-center gap-2.5">
          <button type="button" onClick={() => ctx.openRun(r.run_id)} className="flex min-w-0 flex-1 items-center gap-2.5 text-left hover:underline">
            <Lamp tone={t} pulse={r.status === "running"} />
            <span className="min-w-0 flex-1"><span className="block truncate text-[13px] text-ink">{PIPE[r.pipeline] ?? r.pipeline}</span><span className="mono block text-[11.5px] text-faint">{rid(r.run_id)} · {ago(r.created_at)}</span></span>
            <span className={`text-[12px] ${TXT[t]}`}>{r.cleared ? tr("Lỗi đã xử lý") : statusName(r.status)}</span>
          </button>
          {bad && <Button size="sm" busy={busy === r.run_id} onClick={() => act(r.run_id, () => post(`/api/v1/stages/${bad.stage_id}/retry`), tr("Đã cho chạy lại."))}><Icon name="refresh" size={12} />{tr("Chạy lại")}</Button>}
          {bad && <Button size="sm" kind="quiet" busy={busy === r.run_id} title={tr("Đã biết lỗi này; không tính nó là việc hỏng nữa")} onClick={() => dismiss([r.run_id])}>{tr("Bỏ qua")}</Button>}
          {live(r.status) && <Button size="sm" kind="quiet" busy={busy === r.run_id} onClick={() => cancel(r)}>{tr("Huỷ")}</Button>}
        </Row>); })}
    </ul>
  );
}

function RadarQuick({ ctx, act, busy }: { ctx: Ctx; act: Act; busy: string | null }) {
  const [topic, setTopic] = useState("");
  const topics = ctx.radar?.topics ?? [];
  const save = (next: string[], done: string) => act("topics", () => post("/api/v1/radar/topics", { topics: next }), done);
  const subjects = [...(ctx.radar?.subjects ?? [])].sort((a, b) => b.seconds - a.seconds).slice(0, 8);
  return (<>
    <Sec title={tr("Theo dõi chủ đề mới")}>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const t = topic.trim(); if (t && !topics.includes(t)) { save([...topics, t], tr("Đã thêm chủ đề.")); setTopic(""); } }}>
        <input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder={tr("Ví dụ: món ăn đường phố buổi tối")} aria-label={tr("Chủ đề muốn theo dõi")} className={`${Field} flex-1`} />
        <Button type="submit" size="sm" kind="primary" disabled={!topic.trim()} busy={busy === "topics"}><Icon name="plus" size={13} />{tr("Theo dõi")}</Button>
      </form>
    </Sec>
    <Sec title={tr("Đang theo dõi")} end={topics.length}>
      {(ctx.radar?.watched ?? []).length === 0 ? <Empty>{tr("Chưa theo dõi chủ đề nào.")}</Empty> : (
        <ul className="grid gap-1.5">{(ctx.radar?.watched ?? []).map((w) => (
          <Row key={w.topic} className="flex items-center gap-3">
            <span className="min-w-0 flex-1"><span className="block truncate text-[13px] text-ink">{w.topic}</span><span className="block text-[12px] text-faint">{tv`${w.moments} cảnh khớp · ${w.assets} video`}</span></span>
            <span className={`lab-tag ${w.verdict === tr("đủ hình để làm") ? "!text-proof" : w.verdict === tr("có ít hình") ? "!text-cue" : ""}`}>{w.verdict}</span>
            <button type="button" aria-label={tv`Bỏ theo dõi ${w.topic}`} onClick={() => save(topics.filter((t) => t !== w.topic), tr("Đã bỏ theo dõi."))} className="grid h-7 w-7 place-items-center rounded text-faint hover:bg-white/[0.06] hover:text-tally"><Icon name="x" size={13} /></button>
          </Row>))}</ul>)}
    </Sec>
    <Sec title={tr("Kho đang có nhiều hình nhất")} end={tr("bấm để làm video")}>
      <ul className="grid gap-1.5">{subjects.map((s) => (
        <Row key={s.subject} className="flex items-center gap-3">
          <span className="min-w-0 flex-1"><span className="block truncate text-[13px] text-ink">{s.subject}</span><span className="block text-[12px] text-faint">{tv`${s.videos} video · ${secs(s.seconds)}`}{s.unused_videos ? <span className="text-accent"> · {tv`${s.unused_videos} chưa dùng`}</span> : null}</span></span>
          <Button size="sm" busy={busy === s.subject} onClick={() => act(s.subject, () => post("/api/v1/projects", { title: s.subject, format: "landscape" }), tv`Đã tạo dự án “${s.subject}”.`)}><Icon name="plus" size={12} />{tr("Làm video")}</Button>
        </Row>))}</ul>
    </Sec>
  </>);
}

function CampaignQuick({ ctx, act, busy }: { ctx: Ctx; act: Act; busy: string | null }) {
  return (<>
    <Sec title={tr("Chiến dịch đang chạy")} end={ctx.camps.length}>
      {ctx.camps.length === 0 ? <Empty>{tr("Chưa có chiến dịch nào.")}</Empty> : (
        <ul className="grid gap-1.5">{ctx.camps.map((c) => { const share = Math.min(1, c.target ? c.reached / c.target : 0); return (
          <Row key={c.campaign_id}>
            <span className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-ink">{c.name}</span>{c.late > 0 && <span className="lab-tag !text-cue">{tv`${c.late} trễ`}</span>}<span className="mono text-[12px] text-mute">{Math.round(c.reached)}/{c.target}</span></span>
            <span className="mt-2 block h-1.5 bg-white/[0.06]"><span className="block h-full" style={{ width: `${share * 100}%`, background: c.pace?.on_pace === false ? "var(--color-cue)" : "var(--color-accent)" }} /></span>
            {c.pace && <span className="mt-1.5 block text-[12px] text-faint">{c.pace.text}</span>}
            {c.videos.length > 0 && <ul className="mt-2 grid gap-1">{c.videos.slice(0, 4).map((v) => (
              <li key={v.project_id}><button type="button" onClick={() => goTo(`/du-an/${v.project_id}`)} className="flex w-full items-center gap-2 text-left text-[12.5px] hover:underline">
                <Icon name={v.published ? "check" : "clock"} size={12} className={v.published ? "text-proof" : v.late ? "text-cue" : "text-faint"} /><span className="min-w-0 flex-1 truncate text-mute">{v.title}</span><span className="mono text-faint">{v.due_date ?? ""}</span></button></li>))}</ul>}
          </Row>); })}</ul>)}
    </Sec>
    <Sec title={tr("Tạo chiến dịch nhanh")}>
      <form className="grid grid-cols-2 gap-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const form = e.currentTarget; act("camp", async () => { await post("/api/v1/campaigns", { name: f.get("name"), target: Number(f.get("target") || 0), starts: f.get("starts") || null, ends: f.get("ends") || null, projects: [] }); form.reset(); }, tr("Đã tạo chiến dịch.")); }}>
        <input name="name" required placeholder={tr("Tên chiến dịch")} aria-label={tr("Tên chiến dịch")} className={`${Field} col-span-2`} />
        <label className="grid gap-1 text-[12px] text-mute">{tr("Mục tiêu lượt xem")}<input name="target" type="number" min="0" inputMode="numeric" className={`${Field} mono`} /></label>
        <span />
        <label className="grid gap-1 text-[12px] text-mute">{tr("Bắt đầu")}<input name="starts" type="date" className={Field} /></label>
        <label className="grid gap-1 text-[12px] text-mute">{tr("Kết thúc")}<input name="ends" type="date" className={Field} /></label>
        <span className="col-span-2 flex justify-end"><Button type="submit" size="sm" kind="primary" busy={busy === "camp"}><Icon name="plus" size={13} />{tr("Tạo chiến dịch")}</Button></span>
      </form>
    </Sec>
  </>);
}

function WriterQuick({ ctx, act, busy, close }: { ctx: Ctx; act: Act; busy: string | null; close: () => void }) {
  const [title, setTitle] = useState(""), [format, setFormat] = useState("landscape");
  const tasks = ctx.agent.filter((t) => t.status === "working" || t.status === "waiting_operator" || t.status === "failed");
  const noScript = ctx.projects.filter((p) => !p.script);
  const open = (id: string) => { close(); goTo(`/du-an/${id}?tab=script`); };
  return (<>
    <Sec title={tr("Trợ lý đang viết")} end={tasks.length}>
      {tasks.length === 0 ? <Empty>{tr("Trợ lý không viết kịch bản nào lúc này.")}</Empty> : (
        <ul className="grid gap-1.5">{tasks.map((t) => (
          <Row key={t.task_id}>
            <span className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-[13.5px] text-ink">{t.goal}</span><span className={`lab-tag ${t.status === "waiting_operator" ? "!text-cue" : t.status === "failed" ? "!text-tally" : "!text-ai"}`}>{t.status === "waiting_operator" ? tr("Chờ bạn") : t.status === "failed" ? tr("Lỗi") : STEPS.find(([k]) => k === t.step)?.[1] ?? t.step}</span></span>
            <ul className="mt-1.5 grid gap-0.5">{t.log.slice(-2).map((l) => <li key={l.at} className="truncate text-[12px] text-faint"><span className="text-mute">{l.role}</span> · {l.text}</li>)}</ul>
            <span className="mt-2 flex justify-end"><Button size="sm" kind={t.status === "waiting_operator" ? "primary" : "plain"} onClick={() => open(t.project_id)}>{t.status === "waiting_operator" ? tr("Trả lời trợ lý") : tr("Xem kịch bản")}</Button></span>
          </Row>))}</ul>)}
    </Sec>
    <Sec title={tr("Dự án chưa có kịch bản")} end={noScript.length}>
      {noScript.length === 0 ? <Empty>{tr("Dự án nào cũng đã có kịch bản.")}</Empty> : (
        <ul className="grid gap-1.5">{noScript.slice(0, 6).map((p) => (
          <Row key={p.project_id} className="flex items-center gap-3"><span className="min-w-0 flex-1 truncate text-[13px] text-ink">{p.title}</span><Button size="sm" onClick={() => open(p.project_id)}>{tr("Viết kịch bản")}</Button></Row>))}</ul>)}
    </Sec>
    <Sec title={tr("Tạo dự án mới")}>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); const t = title.trim(); if (!t) return; act("new", async () => { await post("/api/v1/projects", { title: t, format }); setTitle(""); }, tv`Đã tạo dự án “${t}”.`); }}>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={tr("Tên video")} aria-label={tr("Tên video")} className={`${Field} min-w-[180px] flex-1`} />
        <select value={format} onChange={(e) => setFormat(e.target.value)} aria-label={tr("Khung hình")} className={Field}><option value="landscape">{tr("Ngang 16:9")}</option><option value="portrait">{tr("Dọc 9:16")}</option><option value="square">{tr("Vuông 1:1")}</option></select>
        <Button type="submit" size="sm" kind="primary" disabled={!title.trim()} busy={busy === "new"}><Icon name="plus" size={13} />{tr("Tạo")}</Button>
      </form>
    </Sec>
  </>);
}

function VisionQuick({ ctx, act, busy }: { ctx: Ctx; act: Act; busy: string | null }) {
  const win = ctx.ctl?.background_window ?? "";
  const [from, setFrom] = useState(win.split("-")[0] ?? ""), [to, setTo] = useState(win.split("-")[1] ?? "");
  const runs = ctx.all.filter((r) => r.pipeline.startsWith("library."));
  return (<>
    <Sec title={tr("Giờ phân tích footage")} end={win ? tv`hiện tại ${win} giờ` : tr("hiện tại cả ngày")}>
      <p className="mb-2.5 text-[12.5px] text-faint">{tr("Xem và mô tả footage là việc nặng nhất. Để trống để chạy cả ngày.")}</p>
      <form className="flex flex-wrap items-center gap-2 text-[13px] text-mute" onSubmit={(e) => { e.preventDefault(); act("win", () => post("/api/v1/control/background-window", { window: from !== "" && to !== "" ? `${from}-${to}` : "" }), tr("Đã lưu giờ phân tích.")); }}>
        {tr("Từ")}<input value={from} onChange={(e) => setFrom(e.target.value)} type="number" min="0" max="23" inputMode="numeric" aria-label={tr("Từ giờ")} className={`${Field} mono w-16`} />
        {tr("giờ đến")}<input value={to} onChange={(e) => setTo(e.target.value)} type="number" min="0" max="23" inputMode="numeric" aria-label={tr("Đến giờ")} className={`${Field} mono w-16`} />{tr("giờ")}
        <span className="ml-auto flex gap-1.5">{win && <Button size="sm" kind="quiet" onClick={() => { setFrom(""); setTo(""); }}>{tr("Cả ngày")}</Button>}<Button type="submit" size="sm" kind="primary" busy={busy === "win"}>{tr("Lưu")}</Button></span>
      </form>
    </Sec>
    <Sec title={tr("Kho footage")}>
      <div className="grid grid-cols-3 gap-2">
        {([[tr("Cảnh đã hiểu"), String(ctx.home?.counts.moments ?? 0)], [tr("Video"), String(ctx.home?.counts.videos ?? 0)], [tr("Đang xử lý"), String(runs.filter((r) => live(r.status)).length)]] as const).map(([k, v]) => (
          <div key={k} className="rounded-lg border border-line px-3 py-2"><span className="block text-[12px] text-faint">{k}</span><span className="mono text-[18px] text-ink">{v}</span></div>))}
      </div>
    </Sec>
    <Sec title={tr("Việc gần đây")}><RunRows runs={runs} ctx={ctx} act={act} busy={busy} none={tr("Chưa có việc nhập hay phân tích nào.")} /></Sec>
  </>);
}

function MatchQuick({ ctx, act, busy, close }: { ctx: Ctx; act: Act; busy: string | null; close: () => void }) {
  const list = ctx.projects.filter((p) => { const s = projectState(p).step; return s === 1 || s === 2; });
  const approve = async (p: Project) => { if (await ask(tv`Duyệt các clip của “${p.title}”?`, { body: tr("Sau khi duyệt, dự án sẵn sàng để dựng."), confirm: tr("Duyệt clip") })) act(p.project_id, () => post(`/api/v1/projects/${p.project_id}/match/approve`), tr("Đã duyệt clip.")); };
  return (<>
    <Sec title={tr("Dự án đang chọn clip")} end={list.length}>
      {list.length === 0 ? <Empty>{tr("Không dự án nào đang ở bước chọn clip.")}</Empty> : (
        <ul className="grid gap-1.5">{list.map((p) => { const st = projectState(p); const gaps = p.shots.filter((x) => x.selection?.status === "gap").length; const busyRun = !!p.match && live(p.match.status); return (
          <Row key={p.project_id}>
            <span className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-[13.5px] text-ink">{p.title}</span><span className={`lab-tag ${st.tone === "cue" ? "!text-cue" : st.tone === "tally" ? "!text-tally" : ""}`}>{st.label}</span></span>
            <span className="mt-1 block text-[12px] text-faint">{tv`${p.shots.length} câu · ${gaps} câu thiếu hình`}</span>
            <span className="mt-2 flex justify-end gap-1.5">
              <Button size="sm" kind="quiet" onClick={() => { close(); goTo(`/du-an/${p.project_id}?tab=match`); }}>{tr("Xem clip")}</Button>
              {p.match?.status === "waiting_review" ? <Button size="sm" kind="primary" busy={busy === p.project_id} onClick={() => approve(p)}><Icon name="check" size={12} />{tr("Duyệt clip")}</Button>
                : !busyRun && <Button size="sm" busy={busy === p.project_id} onClick={() => act(p.project_id, () => post(`/api/v1/projects/${p.project_id}/match`), tr("Đã bắt đầu tìm clip."))}><Icon name="sparkles" size={12} />{p.match ? tr("Tìm lại clip") : tr("Tìm clip")}</Button>}
            </span>
          </Row>); })}</ul>)}
    </Sec>
    <Sec title={tr("Việc gần đây")}><RunRows runs={ctx.all.filter((r) => r.pipeline.startsWith("sourcing."))} ctx={ctx} act={act} busy={busy} none={tr("Chưa có việc chọn clip nào.")} /></Sec>
  </>);
}

function CutQuick({ ctx, act, busy, close }: { ctx: Ctx; act: Act; busy: string | null; close: () => void }) {
  const ready = ctx.projects.filter((p) => projectState(p).step === 3);
  const render = async (p: Project) => { if (await ask(tv`Dựng “${p.title}”?`, { body: tr("Máy sẽ ghép clip, lồng lời dẫn và phụ đề. Việc này chạy trên máy của bạn."), confirm: tr("Dựng video") })) act(p.project_id, () => post(`/api/v1/projects/${p.project_id}/render`), tr("Đã bắt đầu dựng.")); };
  return (<>
    <Sec title={tr("Sẵn sàng hoặc đang dựng")} end={ready.length}>
      {ready.length === 0 ? <Empty>{tr("Chưa có dự án nào sẵn sàng để dựng.")}</Empty> : (
        <ul className="grid gap-1.5">{ready.map((p) => { const going = !!p.render && live(p.render.status); return (
          <Row key={p.project_id} className="flex items-center gap-3">
            <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] text-ink">{p.title}</span><span className="block text-[12px] text-faint">{projectState(p).label}{p.renders.length ? tv` · ${p.renders.length} bản đã dựng` : ""}</span></span>
            {going ? <span className="flex items-center gap-1.5 text-[12.5px] text-ai"><Spinner size={11} />{tr("Đang dựng")}</span>
              : <Button size="sm" kind="primary" busy={busy === p.project_id} onClick={() => render(p)}><Icon name="scissors" size={12} />{p.renders.length ? tr("Dựng lại") : tr("Dựng video")}</Button>}
            <Button size="sm" kind="quiet" onClick={() => { close(); goTo(`/du-an/${p.project_id}?tab=timeline`); }}>{tr("Timeline")}</Button>
          </Row>); })}</ul>)}
    </Sec>
    <Sec title={tr("Việc gần đây")}><RunRows runs={ctx.all.filter((r) => r.pipeline.startsWith("edit."))} ctx={ctx} act={act} busy={busy} none={tr("Chưa dựng video nào.")} /></Sec>
  </>);
}

function ReviewQuick({ ctx, act, busy }: { ctx: Ctx; act: Act; busy: string | null }) {
  const waiting = ctx.projects.filter((p) => p.render?.status === "waiting_review");
  const [why, setWhy] = useState<Record<string, string>>({});
  return (
    <Sec title={tr("Bản dựng chờ bạn duyệt")} end={waiting.length}>
      {waiting.length === 0 ? <Empty>{tr("Không có bản dựng nào chờ duyệt.")}</Empty> : (
        <ul className="grid gap-3">{waiting.map((p) => { const r = p.renders[0]; return (
          <Row key={p.project_id}>
            <span className="mb-2 flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-ink">{p.title}</span>{r && <span className={`lab-tag ${r.qc.passed ? "!text-proof" : "!text-cue"}`}>{r.qc.passed ? tr("Qua kiểm tra") : tr("Có lưu ý")}</span>}</span>
            {r && <video src={r.url} controls preload="metadata" className={`w-full rounded-md bg-black ${r.qc.format === "portrait" ? "mx-auto aspect-[9/16] max-h-[340px] w-auto" : "aspect-video"}`} />}
            {r && <span className="mt-1.5 block text-[12px] text-faint">{tv`${secs(r.qc.duration)} · ${r.qc.gaps} chỗ thiếu hình`}</span>}
            <input value={why[p.project_id] ?? ""} onChange={(e) => setWhy({ ...why, [p.project_id]: e.target.value })} placeholder={tr("Cần sửa gì? (khi chưa được)")} aria-label={tr("Lý do dựng lại")} className={`${Field} mt-2 w-full`} />
            <span className="mt-2 flex justify-end gap-1.5">
              <Button size="sm" busy={busy === `n${p.project_id}`} onClick={() => act(`n${p.project_id}`, () => post(`/api/v1/projects/${p.project_id}/render/decision`, { approve: false, comment: why[p.project_id] || null }), tr("Đã gửi yêu cầu dựng lại."))}>{tr("Chưa được, dựng lại")}</Button>
              <Button size="sm" kind="primary" busy={busy === `y${p.project_id}`} onClick={() => act(`y${p.project_id}`, () => post(`/api/v1/projects/${p.project_id}/render/decision`, { approve: true }), tr("Đã duyệt bản dựng."))}><Icon name="check" size={12} />{tr("Duyệt")}</Button>
            </span>
          </Row>); })}</ul>)}
    </Sec>
  );
}

function PublishQuick({ ctx, act, busy }: { ctx: Ctx; act: Act; busy: string | null }) {
  const due = ctx.pub?.due ?? [];
  const recent = [...(ctx.pub?.publications ?? [])].sort((a, b) => (b.published_at ?? 0) - (a.published_at ?? 0)).slice(0, 6);
  return (<>
    <Sec title={tr("Tới hạn ghi số liệu")} end={due.length}>
      {due.length === 0 ? <Empty>{tr("Chưa bài nào tới mốc ghi số liệu.")}</Empty> : (
        <ul className="grid gap-2">{due.map((d) => (
          <Row key={`${d.publication_id}-${d.mark}`}>
            <span className="flex items-center gap-2"><span className="min-w-0 flex-1 truncate text-[13.5px] text-ink">{d.title}</span><span className="lab-tag !text-cue">{tv`mốc ${d.mark} giờ`}</span></span>
            <span className="block text-[12px] text-faint">{d.target}</span>
            <form className="mt-2 grid grid-cols-5 gap-1.5" onSubmit={(e) => { e.preventDefault(); const form = e.currentTarget; const body = Object.fromEntries([...new FormData(form).entries()].filter(([, v]) => String(v).trim() !== "")); if (!Object.keys(body).length) return; act(d.publication_id, async () => { await post(`/api/v1/publications/${d.publication_id}/metrics`, body); form.reset(); }, tr("Đã ghi số liệu.")); }}>
              {FIGURES.map(([k, n]) => <label key={k} className="grid gap-1 text-[11.5px] text-mute">{n}<input name={k} type="number" min="0" inputMode="decimal" className={`${Field} mono w-full !px-1.5`} /></label>)}
              <span className="col-span-5 flex justify-end"><Button type="submit" size="sm" kind="primary" busy={busy === d.publication_id}>{tr("Ghi số liệu")}</Button></span>
            </form>
          </Row>))}</ul>)}
    </Sec>
    <Sec title={tr("Bài đăng gần đây")}>
      {recent.length === 0 ? <Empty>{tr("Chưa đăng bài nào.")}</Empty> : (
        <ul className="grid gap-1.5">{recent.map((p) => { const views = p.snapshots.at(-1)?.figures.views; return (
          <Row key={p.publication_id} className="flex items-center gap-3">
            <span className="min-w-0 flex-1"><span className="block truncate text-[13px] text-ink">{p.title}</span><span className="block text-[12px] text-faint">{p.target}{p.published_at ? ` · ${ago(p.published_at)}` : ""}{p.error ? <span className="text-tally"> · {p.error}</span> : null}</span></span>
            {views != null && <span className="mono text-[12.5px] text-mute">{tv`${Math.round(views)} lượt xem`}</span>}
            {p.url && <a href={p.url} target="_blank" rel="noreferrer" aria-label={tr("Mở bài đăng")} className="grid h-7 w-7 place-items-center rounded text-faint hover:bg-white/[0.06] hover:text-ink"><Icon name="external" size={13} /></a>}
          </Row>); })}</ul>)}
    </Sec>
  </>);
}

/* ───────────────────────── a single run, opened from anywhere ───────────────────────── */

function RunDrawer({ id, close }: { id: string; close: () => void }) {
  const [d, setD] = useState<Detail | null>(details.get(id) ?? null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { let stop = false; const load = async () => { const x = await detailOf(id, true); if (!stop) setD(x); }; load(); const t = window.setInterval(load, 3000); return () => { stop = true; window.clearInterval(t); }; }, [id]);
  useEffect(() => { const key = (e: KeyboardEvent) => { if (e.key === "Escape") close(); }; window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key); }, [close]);
  const act = async (what: () => Promise<unknown>, done: string) => { setBusy(true); try { await what(); toast(done, { tone: "proof" }); setD(await detailOf(id, true)); } catch (e) { toast((e as Error).message, { tone: "tally" }); } setBusy(false); };
  const cancel = async () => { if (await ask(tr("Huỷ việc này?"), { body: tr("Các bước chưa chạy sẽ không chạy nữa. Kết quả các bước đã xong vẫn được giữ."), confirm: tr("Huỷ việc") })) act(() => post(`/api/v1/runs/${id}/cancel`), tr("Đã huỷ việc.")); };
  return createPortal(
    <div className="fixed inset-0 z-50" onClick={close}>
      <div className="scrim absolute inset-0" />
      <aside role="dialog" aria-label={tr("Chi tiết việc")} onClick={(e) => e.stopPropagation()} className="drawer run-drawer absolute inset-y-0 right-0 flex w-[460px] max-w-[94vw] flex-col border-l border-line bg-surface">
        <header className="flex items-center gap-3 border-b border-line px-5 py-4">
          <span className="min-w-0 flex-1"><span className="block truncate text-[15px] font-semibold">{d ? PIPE[d.pipeline] ?? d.pipeline : tr("Đang mở…")}</span><span className="mono block truncate text-[12.5px] text-faint">{id}</span></span>
          {d && <span className={`mono rounded border px-2 text-[12.5px] leading-5 ${TXT[toneOf(d.status)]} border-current/40`}>{statusName(d.status)}</span>}
          <button type="button" onClick={close} className="grid h-8 w-8 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink" aria-label={tr("Đóng")}><Icon name="x" /></button>
        </header>
        {!d ? <div className="grid flex-1 place-items-center"><Spinner /></div> : (
          <div className="flex-1 overflow-y-auto px-5 py-4">
            <dl className="mono mb-4 grid grid-cols-3 gap-2 text-[12.5px]">
              <div className="tile p-2"><dt className="text-faint">{tr("bắt đầu")}</dt><dd className="text-[13.5px]">{clock(d.created_at)}</dd></div>
              <div className="tile p-2"><dt className="text-faint">{tr("tổng thời gian")}</dt><dd className="text-[13.5px]">{secs(took(d))}</dd></div>
              <div className="tile p-2"><dt className="text-faint">{tr("chi phí")}</dt><dd className="text-[13.5px]">{d.cost.toFixed(2)} USD</dd></div>
            </dl>
            <p className="mb-2 text-[13px] text-faint">{tr("Các bước")}</p>
            <ol className="mb-5 grid gap-1.5">
              {d.stages.map((s) => { const tries = d.attempts.filter((a) => a.stage_key === s.stage_key); const t = toneOf(s.status); return (
                <li key={s.stage_id} className="rounded-lg border border-line bg-white/[0.02] p-2.5">
                  <div className="flex items-center gap-2"><Lamp tone={t} pulse={s.status === "running"} /><span className="text-[14px] font-medium">{sn(s.stage_key, d.pipeline)}</span><span className={`text-[13px] ${TXT[t]}`}>{statusName(s.status)}</span>
                    <span className="ml-auto flex gap-1.5">
                      {s.status === "failed" && <Button size="sm" busy={busy} onClick={() => act(() => post(`/api/v1/stages/${s.stage_id}/retry`), tr("Đã cho chạy lại bước này."))}><Icon name="refresh" size={12} />{tr("Chạy lại")}</Button>}
                      {s.status === "blocked" && <Button size="sm" busy={busy} onClick={() => act(() => post(`/api/v1/stages/${s.stage_id}/resume`), tr("Đã cho chạy tiếp."))}><Icon name="play" size={12} />{tr("Tiếp tục")}</Button>}
                    </span></div>
                  {s.blocked_reason && <p className="mt-1 text-[13px] text-cue">{s.blocked_reason}</p>}
                  {tries.length > 0 && <ul className="mono mt-1.5 grid gap-0.5 text-[12px] text-faint">{tries.map((a) => (
                    <li key={a.number} className="flex flex-wrap gap-x-3"><span>{tv`lần ${a.number}`}</span><span>{a.worker}</span><span>{clock(a.started_at)}</span><span>{a.seconds != null ? secs(a.seconds) : tr("đang chạy")}</span>
                      {a.error_message && <span className="w-full whitespace-pre-wrap font-sans text-[12.5px] text-tally">{a.error_code ? `${a.error_code}: ` : ""}{a.error_message}</span>}</li>))}</ul>}
                </li>); })}
            </ol>
          </div>
        )}
        {d && (live(d.status) || waits(d.status)) && <footer className="flex justify-end gap-2 border-t border-line px-5 py-3"><Button kind="danger" busy={busy} onClick={cancel}><Icon name="x" size={13} />{tr("Huỷ việc")}</Button></footer>}
      </aside>
    </div>, document.body);
}
