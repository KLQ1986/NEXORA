import { PIPE } from "./Notices";
import { t as tr, tv, locale } from "./i18n";
import { useState } from "react";
import { megabytes, post, projectState, REASONS, stageName, timecode, usePoll, type AgentTask, type Asset, type CalendarRow, type Channel, type Project, type Publishing, type Radar, type Stage } from "./api";
import { Button, Empty, Icon, Page, Skeleton, StageRail, toast } from "./parts";

type Item = { gaps?: number; run_id: string; pipeline: string; name: string; link: string; status: string; held: boolean; stage_key: string | null; reason?: string | null; stages?: Stage[] };
type HomeData = {
  attention: Item[]; running: Item[]; gaps: { project_id: string; title: string; gaps: number }[];
  offline_volumes: { volume_id: string; mount_path: string; files: number }[]; problems: { name: string; detail: string; fix: string | null }[];
  unavailable: { pipeline: string; missing: string[] }[]; agent: AgentTask[];
  counts: { videos: number; photos: number; music: number; footage_seconds: number; projects: number; moments: number };
  disk: { free_bytes: number; total_bytes: number }; spent_today: number; kill_switch: boolean;
  recent: { project_id: string; title: string; created_at: number; renders: number }[];
};

const WORK = PIPE;
const WORK_ICON: Record<string, string> = { "library.ingest": "film", "library.ingest_image": "image", "library.ingest_audio": "music", "library.understand": "eye",
  "sourcing.match": "sparkles", "sourcing.generate": "spark", "edit.render": "scissors" };
const ASK: Record<string, (i: Item) => string> = {
  waiting_review: (i) => (i.pipeline === "edit.render" ? tr("Bản dựng chờ bạn duyệt") : i.pipeline === "sourcing.generate" ? tr("Hình vừa sinh chờ bạn duyệt") : tr("Các clip đã chọn chờ bạn duyệt")),
  blocked: (i) => tv`${WORK[i.pipeline] ?? i.pipeline} đang dừng: ${REASONS[i.reason ?? ""] ?? i.reason ?? tr("cần bạn xử lý")}`,
  failed: (i) => tv`${WORK[i.pipeline] ?? i.pipeline} thất bại ở bước ${stageName(i.stage_key ?? "", i.pipeline)}`,
};
const NEEDS: Record<string, string> = { model: tr("mô hình thị giác (Ollama)"), voice: tr("giọng đọc"), image_gen: tr("nhà cung cấp sinh ảnh"), video_gen: tr("nhà cung cấp sinh video"), ffmpeg: "FFmpeg", ffprobe: "FFprobe", graphics: tr("bộ vẽ phụ đề") };
const hours = (s: number) => (s >= 3600 ? `${(s / 3600).toFixed(1)}h` : timecode(s));

type Tone = "cue" | "tally" | "ai" | "accent" | "proof";
const TEXT: Record<Tone, string> = { cue: "text-cue", tally: "text-tally", ai: "text-ai", accent: "text-accent", proof: "text-proof" };
const TINT: Record<Tone, string> = { cue: "bg-cue/12 text-cue", tally: "bg-tally/12 text-tally", ai: "bg-ai/12 text-ai", accent: "bg-accent/12 text-accent", proof: "bg-proof/12 text-proof" };

type Next = { p: Project; label: string; hint: string; to: string; icon: string; tone: Tone; rank: number };
/** What a project needs next, in one verb, and the screen where it is done. */
function nextFor(p: Project): Next | null {
  const busy = (r: Project["render"]) => !!r && ["queued", "running"].includes(r.status);
  const latest = p.renders[0];
  const gaps = p.shots.filter((s) => s.selection?.status === "gap").length;
  const base = `/du-an/${p.project_id}`;
  if (!p.script) return { p, label: tr("Viết kịch bản"), hint: tr("Chưa có kịch bản"), to: `${base}?tab=script`, icon: "edit", tone: "accent", rank: 3 };
  if (p.render?.status === "waiting_review" && latest) return { p, label: tr("Duyệt bản dựng"), hint: tv`Bản dựng ${timecode(latest.qc.duration)} chờ bạn xem`, to: `/phong-chieu?r=${latest.render_id}`, icon: "screen", tone: "cue", rank: 0 };
  if (p.match?.status === "waiting_review") return { p, label: tr("Duyệt clip"), hint: gaps ? tv`${p.shots.length} câu, còn ${gaps} câu thiếu hình` : tv`${p.shots.length} câu đã có clip`, to: `${base}?tab=clips`, icon: "check", tone: "cue", rank: 0 };
  if (p.render?.status === "failed" || p.match?.status === "failed") return { p, label: tr("Xem lỗi"), hint: tr("Một bước vừa thất bại"), to: `${base}?tab=${p.render?.status === "failed" ? "cut" : "clips"}`, icon: "alert", tone: "tally", rank: 1 };
  if (p.render?.status === "blocked" || p.match?.status === "blocked") return { p, label: tr("Xử lý chỗ dừng"), hint: tr("Một bước đang dừng chờ bạn"), to: `${base}?tab=${p.render ? "cut" : "clips"}`, icon: "alert", tone: "cue", rank: 1 };
  if (busy(p.render)) return { p, label: tr("Đang dựng"), hint: tr("Máy đang đọc lời dẫn và ghép cảnh"), to: `${base}?tab=cut`, icon: "scissors", tone: "ai", rank: 4 };
  if (busy(p.match)) return { p, label: tr("Đang tìm clip"), hint: tr("Máy đang tìm trong kho footage"), to: `${base}?tab=clips`, icon: "sparkles", tone: "ai", rank: 4 };
  if (p.script.match_approved && !latest) return { p, label: tr("Dựng video"), hint: tr("Clip đã duyệt, sẵn sàng dựng"), to: `${base}?tab=cut`, icon: "scissors", tone: "accent", rank: 2 };
  if (p.render?.status === "succeeded" && latest && !latest.package) return { p, label: tr("Đóng gói để đăng"), hint: tr("Bản dựng đã duyệt"), to: `${base}?tab=publish`, icon: "globe", tone: "accent", rank: 2 };
  if (p.render?.status === "succeeded") return null;
  return { p, label: p.match ? tr("Tìm lại clip") : tr("Tìm clip"), hint: tv`Kịch bản ${p.shots.length} câu`, to: `${base}?tab=clips`, icon: "sparkles", tone: "accent", rank: 3 };
}

/** The picture a project is recognised by: its first shot, as chosen if there is a choice. */
function poster(p: Project): string | null {
  for (const s of p.shots) {
    const sel = s.selection;
    const src = sel && sel.status !== "gap" ? sel.frame_url ?? sel.asset?.thumbnail_url ?? s.keyframe_url : s.keyframe_url;
    if (src) return src;
  }
  return null;
}

/** The six places a video passes through, in order. Two of them wait for the operator. */
const LINE: { step: number; label: string; icon: string; waits?: boolean }[] = [
  { step: 0, label: tr("Kịch bản"), icon: "edit" },
  { step: 1, label: tr("Chọn clip"), icon: "sparkles" },
  { step: 2, label: tr("Duyệt clip"), icon: "check", waits: true },
  { step: 3, label: tr("Dựng"), icon: "scissors" },
  { step: 4, label: tr("Duyệt bản dựng"), icon: "screen", waits: true },
  { step: 5, label: tr("Đã xong"), icon: "star" },
];

function Tile({ label, value, sub, icon, tone, to, go, share, quiet }: { label: string; value: string; sub: string; icon: string; tone: Tone; to: string; go: (to: string) => void; share?: number; quiet?: boolean }) {
  return (
    <a href={to} onClick={(e) => { e.preventDefault(); go(to); }} className="tile group relative flex min-w-0 flex-col p-3 2xl:p-4">
      <span className="flex items-start justify-between gap-3"><span className="truncate text-[13px] text-mute">{label}</span><Icon name={icon} size={17} className={TEXT[tone]} /></span>
      <span className="mono mt-1.5 text-[22px] font-semibold leading-none tracking-tight 2xl:mt-2 2xl:text-[26px]">{value}</span>
      {share != null
        ? <span className="mt-3 block h-1 overflow-hidden rounded-full bg-white/[0.06]"><span className={`block h-full rounded-full ${share > 0.9 && !quiet ? "bg-cue" : "bg-gradient-to-r from-accent-deep to-accent"}`} style={{ width: `${Math.max(2, share * 100)}%` }} /></span>
        : <span className="mt-2 truncate text-[12px] text-faint">{sub}</span>}
      {share != null && <span className="mt-1.5 truncate text-[12px] text-faint">{sub}</span>}
    </a>
  );
}

/** A titled panel. A filling panel takes the height it is given and scrolls its own content, so the overview fits one screen. */
function Panel({ title, icon, tone = "accent", end, children, className = "", fill = false }: { title: string; icon: string; tone?: Tone; end?: React.ReactNode; children: React.ReactNode; className?: string; fill?: boolean }) {
  return (
    <section className={`panel flex min-h-0 min-w-0 flex-col p-4 2xl:p-5 ${className}`} aria-label={title}>
      <h2 className="mb-3 flex shrink-0 items-center gap-2 text-[15px] font-semibold"><Icon name={icon} size={16} className={TEXT[tone]} />{title}<span className="ml-auto flex items-center text-[12.5px] font-normal">{end}</span></h2>
      {fill ? <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div> : children}
    </section>
  );
}

const DAY = 86400000;
const dayKey = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
/* Two series, checked for colour-blind separation on this panel's surface: cuts in blue, posts in orange. */
const CUT = "#46c8e0", POST = "#9b87ff";

/** Fourteen days of output: how many cuts the machine made and how many videos went out, one pair of bars a day. */
function Rhythm({ projects, posted }: { projects: Project[]; posted: number[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Array.from({ length: 14 }, (_, k) => new Date(today.getTime() - (13 - k) * DAY));
  const keys = days.map(dayKey);
  const count = (stamps: number[]) => keys.map((k) => stamps.filter((t) => dayKey(new Date(t * 1000)) === k).length);
  const cuts = count(projects.flatMap((p) => p.renders.map((r) => r.created_at)));
  const posts = count(posted);
  const top = Math.max(1, ...cuts, ...posts);
  const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex shrink-0 flex-wrap items-center gap-x-5 gap-y-1 text-[12.5px] text-mute">
        <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: CUT }} />{tr("Bản dựng")}<span className="mono text-ink">{sum(cuts)}</span></span>
        <span className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: POST }} />{tr("Đã đăng")}<span className="mono text-ink">{sum(posts)}</span></span>
      </div>
      <div className="relative flex min-h-[150px] flex-1 flex-col xl:min-h-[90px]" onMouseLeave={() => setHover(null)}>
        <div className="pointer-events-none absolute inset-x-0 top-0 border-t border-dashed border-white/[0.06]" /><span className="mono pointer-events-none absolute -top-2 right-0 text-[10.5px] text-faint">{top}</span>
        <div className="flex min-h-0 flex-1 items-end gap-1 border-b border-line" role="img" aria-label={tr("Số bản dựng và số video đăng mỗi ngày trong 14 ngày qua")}>
          {days.map((d, k) => (
            <div key={k} className={`relative flex h-full flex-1 items-end justify-center gap-[2px] rounded-t-md transition-colors ${hover === k ? "bg-white/[0.04]" : ""}`} onMouseEnter={() => setHover(k)}>
              <span className="w-full max-w-[12px] rounded-t-[4px]" style={{ height: `${(cuts[k] / top) * 100}%`, minHeight: cuts[k] ? 3 : 0, background: CUT }} />
              <span className="w-full max-w-[12px] rounded-t-[4px]" style={{ height: `${(posts[k] / top) * 100}%`, minHeight: posts[k] ? 3 : 0, background: POST }} />
              {hover === k && (
                <span className={`dialog pointer-events-none absolute bottom-full z-10 mb-2 w-max px-3 py-2 text-[12px] ${k > 9 ? "right-0" : k < 4 ? "left-0" : "left-1/2 -translate-x-1/2"}`}>
                  <span className="mb-1 block text-mute">{d.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "numeric" })}</span>
                  <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-sm" style={{ background: CUT }} />{tr("Bản dựng")}<span className="mono ml-auto pl-3">{cuts[k]}</span></span>
                  <span className="flex items-center gap-2"><span className="h-2 w-2 rounded-sm" style={{ background: POST }} />{tr("Đã đăng")}<span className="mono ml-auto pl-3">{posts[k]}</span></span>
                </span>
              )}
            </div>
          ))}
        </div>
        <div className="mt-1.5 flex gap-1">{days.map((d, k) => <span key={k} className={`mono flex-1 text-center text-[10.5px] ${k === 13 ? "text-accent" : "text-faint"}`}>{k % 2 === 1 || k === 13 ? d.getDate() : ""}</span>)}</div>
      </div>
      <table className="sr-only"><caption>{tr("Nhịp 14 ngày")}</caption><thead><tr><th>{tr("Ngày")}</th><th>{tr("Bản dựng")}</th><th>{tr("Đã đăng")}</th></tr></thead>
        <tbody>{days.map((d, k) => <tr key={k}><td>{d.toLocaleDateString(locale)}</td><td>{cuts[k]}</td><td>{posts[k]}</td></tr>)}</tbody></table>
    </div>
  );
}

type Cadence = { channel: string; per_week: number; short: number; weeks: { from: string; planned: number; short: number }[] };

/** Each channel against the pace it promised for this week: a bar of slots, filled for each video planned. */
function Cadences({ channels, cadence, today, go }: { channels: Channel[]; cadence: Cadence[]; today: string; go: (to: string) => void }) {
  const paced = channels.filter((c) => c.per_week > 0);
  if (!paced.length) return (
    <div className="rounded-lg bg-white/[0.03] px-4 py-4 text-center short:py-2.5">
      <p className="text-[13px] text-mute">{tr("Chưa có kênh nào đặt nhịp đăng.")}</p>
      <button type="button" onClick={() => go("/ke-hoach")} className="link mt-2 text-[12.5px]">{tr("Thêm kênh")}</button>
    </div>
  );
  return (
    <ul className="grid gap-3.5">
      {paced.map((c) => {
        const weeks = cadence.find((x) => x.channel === c.name)?.weeks ?? [];
        const now = [...weeks].reverse().find((w) => w.from <= today) ?? weeks[0];
        const planned = now ? now.planned : 0, need = Math.max(c.per_week, planned), behind = now ? now.short > 0 : true;
        return (
          <li key={c.name}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[13px]"><span className="truncate font-medium">{c.name}</span>
              <span className={`mono shrink-0 text-[12px] ${behind ? "text-cue" : "text-proof"}`}>{planned}/{c.per_week}{behind && now ? <span className="ml-1.5 font-sans">{tv`thiếu ${now.short}`}</span> : null}</span></div>
            <div className="flex gap-1" aria-hidden="true">{Array.from({ length: Math.min(need, 14) }, (_, k) => <span key={k} className={`h-1.5 flex-1 rounded-full ${k < planned ? (behind ? "bg-cue" : "bg-proof") : "bg-white/[0.07]"}`} />)}</div>
          </li>
        );
      })}
    </ul>
  );
}

/** The next seven days of the publishing calendar: what is due each day, and which days are still open. */
function Upcoming({ rows, go }: { rows: CalendarRow[]; go: (to: string) => void }) {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Array.from({ length: 7 }, (_, k) => new Date(today.getTime() + k * DAY));
  const late = rows.filter((r) => r.due_date && r.due_date < dayKey(today) && !r.ready);
  const soon = days.some((d) => rows.some((r) => r.due_date === dayKey(d)));
  // A week with nothing on it is one line and a way to plan it, not seven empty rows.
  if (!soon && !late.length) return (
    <div className="rounded-lg bg-white/[0.03] px-4 py-5 text-center short:py-2.5">
      <p className="text-[13px] text-mute">{tr("Chưa có video nào xếp lịch trong 7 ngày tới.")}</p>
      <button type="button" onClick={() => go("/ke-hoach")} className="link mt-2 text-[12.5px]">{tr("Xếp lịch đăng")}</button>
    </div>
  );
  return (
    <div className="grid gap-1">
      {late.length > 0 && <button type="button" onClick={() => go("/ke-hoach")} className="mb-1 flex items-center gap-2 rounded-lg bg-cue/10 px-3 py-2 text-left text-[12.5px] text-cue"><Icon name="alert" size={14} />{tv`${late.length} video đã quá ngày đăng`}</button>}
      {days.map((d, k) => {
        const due = rows.filter((r) => r.due_date === dayKey(d));
        return (
          <div key={k} className="flex items-start gap-3 rounded-lg px-2 py-1.5">
            <span className={`mono w-[72px] shrink-0 whitespace-nowrap pt-0.5 text-[12px] ${k === 0 ? "font-medium text-accent" : "text-faint"}`}>{k === 0 ? tr("Hôm nay") : `${d.toLocaleDateString(locale, { weekday: "short" })} ${d.getDate()}/${d.getMonth() + 1}`}</span>
            <span className="grid min-w-0 flex-1 gap-1">
              {due.length === 0 && <span className="text-[12.5px] text-faint/70">{tr("Trống")}</span>}
              {due.map((r) => (
                <button key={r.project_id} type="button" onClick={() => go(`/du-an/${r.project_id}`)} className="flex min-w-0 items-center gap-2 text-left text-[13px] hover:text-accent">
                  <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${r.ready ? "bg-proof" : "bg-cue"}`} title={r.ready ? tr("Đã sẵn sàng") : tr("Chưa xong")} /><span className="truncate">{r.title}</span></button>
              ))}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** The first screen: a control room for the factory. Where every video stands, what waits for the operator, how output is
 *  going, what is due, and what the machine is doing. */
export default function Home({ go }: { go: (to: string) => void }) {
  const { data: d, error } = usePoll<HomeData>("/api/v1/home", 3000);
  const { data: projects } = usePoll<Project[]>("/api/v1/projects", 6000);
  const { data: cal } = usePoll<{ projects: CalendarRow[]; today: string; channels: Channel[]; cadence: Cadence[] }>("/api/v1/calendar", 30000);
  const { data: radar } = usePoll<Radar>("/api/v1/radar", 120000);
  const { data: lib } = usePoll<{ assets: Asset[] }>("/api/v1/library", 60000);
  const { data: pub } = usePoll<Publishing>("/api/v1/publishing", 60000);
  const open = (to: string) => (e: React.MouseEvent) => { e.preventDefault(); go(to); };
  if (!d) return (
    <Page full title={tr("Tổng quan")} note={error ? tv`Không tải được: ${error}` : tr("Đang mở…")}>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]" aria-busy="true">
        <div className="panel grid gap-4 p-5"><div className="grid grid-cols-2 gap-3 lg:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="tile grid gap-3 p-4"><Skeleton height={12} className="w-20" /><Skeleton height={26} className="w-16" /></div>)}</div><Skeleton height={120} /></div>
        <div className="panel h-64" />
      </div>
    </Page>);

  const list = projects ?? [];
  const stuck = d.attention.filter((i) => i.status !== "waiting_review");
  const queue = list.map(nextFor).filter((x): x is Next => !!x).sort((a, b) => a.rank - b.rank || b.p.created_at - a.p.created_at);
  const waiting = queue.filter((n) => n.rank === 0).length + stuck.length;
  const busy = d.running.length + d.agent.length;
  const done = list.filter((p) => projectState(p).step === 5).length;
  const c = d.counts;
  const used = 1 - d.disk.free_bytes / d.disk.total_bytes;
  const byStep = LINE.map((s) => list.filter((p) => projectState(p).step === s.step));
  // The same next step for several projects is one line of work, not several.
  const groups: Next[][] = [];
  for (const n of queue) { const g = groups.find((x) => x[0].label === n.label); if (g) g.push(n); else groups.push([n]); }
  const renders = list.flatMap((p) => p.renders.map((r) => ({ p, r }))).sort((a, b) => b.r.created_at - a.r.created_at).slice(0, 3);
  const posted = (pub?.publications ?? []).map((x) => x.published_at).filter((t): t is number => !!t);
  const videos = (lib?.assets ?? []).filter((a) => a.kind === "video" && !a.rejected);
  const understood = videos.filter((a) => a.understand?.status === "succeeded").length;
  const dueMetrics = pub?.due ?? [];
  const best = (pub?.publications ?? []).filter((x) => x.published_at && x.snapshots.length).map((x) => ({ x, views: x.snapshots[x.snapshots.length - 1].figures.views ?? 0 }))
    .sort((a, b) => b.views - a.views).slice(0, 3);
  // Footage nobody has used yet comes first; when every shot has been used, the subjects the library holds most of are still the strongest starts.
  const fresh = (radar?.unused ?? []).filter((x) => x.unused_videos > 0).sort((a, b) => b.unused_seconds - a.unused_seconds);
  const ideas = (fresh.length ? fresh : [...(radar?.subjects ?? [])].sort((a, b) => b.seconds - a.seconds)).slice(0, 4);
  const startFrom = async (subject: string) => { try { const p = await post<Project>("/api/v1/projects", { title: subject, format: "landscape" }); go(`/du-an/${p.project_id}?tab=script`); } catch (e) { toast((e as Error).message, { tone: "tally" }); } };

  return (
    <Page full flush title={tr("Tổng quan")}>
      {/* On a desktop the overview is one screen: every panel takes a share of the height and scrolls inside itself if it must. */}
      <div className="h-full overflow-y-auto p-4 md:p-5 xl:overflow-hidden">
      <div className="grid items-start gap-4 xl:h-full xl:grid-cols-[minmax(0,1fr)_320px] xl:items-stretch 2xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex min-h-0 min-w-0 flex-col gap-4">
          <Panel className="shrink-0" title={tr("Dây chuyền sản xuất")} icon="pulse"
                 end={<span className="inline-flex h-6 items-center gap-1.5 rounded-full border border-proof/30 bg-proof/10 px-2.5 text-[11.5px] font-medium text-proof"><span className="ping relative h-1.5 w-1.5 rounded-full bg-proof" />{tr("Trực tiếp")}</span>}>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">
              <Tile go={go} to="/phong-chieu" label={tr("Chờ bạn")} value={String(waiting)} sub={waiting ? tr("Duyệt hoặc xử lý chỗ dừng") : tr("Không có gì đang chờ")} icon="bell" tone="cue" />
              <Tile go={go} to="/tien-trinh" label={tr("Máy đang chạy")} value={String(busy)} sub={busy ? (WORK[d.running[0]?.pipeline] ?? tr("Trợ lý sản xuất")) : tr("Máy đang rảnh")} icon="cpu" tone="ai" />
              <Tile go={go} to="/du-an" label={tr("Dự án")} value={String(c.projects)} sub={tv`${done} đã xong`} icon="clapper" tone="proof" />
              <Tile go={go} to="/thu-vien" label={tr("Kho footage")} value={hours(c.footage_seconds)} sub={videos.length ? tv`${understood}/${videos.length} video đã được hiểu` : tv`${c.videos} video`} icon="film" tone="accent" share={videos.length ? understood / videos.length : undefined} quiet />
              <Tile go={go} to="/he-thong" label={tr("Ổ đĩa trống")} value={megabytes(d.disk.free_bytes)} sub={tv`Đã dùng ${Math.round(used * 100)}%`} icon="disk" tone={used > 0.9 ? "cue" : "accent"} share={used} />
            </div>
            <ol className="scroll-x mt-3 flex gap-px overflow-hidden rounded-xl border border-line bg-line">
              {LINE.map((s, k) => {
                const here = byStep[k], hot = s.waits && here.length > 0, empty = here.length === 0;
                return (
                  <li key={s.step} className={`relative flex min-h-[96px] flex-col gap-2 p-3 short:min-h-0 short:py-2.5 2xl:min-h-[124px] ${empty ? "min-w-[96px] flex-[0.6]" : "min-w-[150px] flex-[1.4]"} ${hot ? "bg-cue/[0.06]" : "bg-surface"}`}>
                    <span className={`absolute inset-x-0 top-0 h-0.5 ${hot ? "bg-cue" : empty ? "bg-transparent" : "bg-accent/60"}`} />
                    <span className={`flex items-center gap-1.5 truncate text-[12px] ${hot ? "text-cue" : empty ? "text-faint" : "text-mute"}`}><Icon name={s.icon} size={13} />{s.label}</span>
                    <span className={`mono text-[22px] font-semibold leading-none ${empty ? "text-faint/60" : hot ? "text-cue" : "text-ink"}`}>{here.length}</span>
                    {!empty && (
                      <span className="mt-auto grid grid-cols-2 gap-1 short:hidden">
                        {here.slice(0, here.length > 4 ? 3 : 4).map((p) => { const src = poster(p); return (
                          <a key={p.project_id} href={`/du-an/${p.project_id}`} onClick={open(`/du-an/${p.project_id}`)} title={p.title} aria-label={p.title}
                             className="block aspect-video overflow-hidden rounded-md ring-1 ring-white/5 transition-[box-shadow,filter] hover:brightness-125 hover:ring-accent/60">
                            {src ? <img src={src} alt="" className="h-full w-full object-cover" /> : <span className="hatch block h-full w-full" />}</a>); })}
                        {here.length > 4 && <span className="mono grid aspect-video place-items-center rounded-md bg-white/[0.04] text-[12px] text-mute">+{here.length - 3}</span>}
                      </span>
                    )}
                  </li>
                );
              })}
            </ol>
          </Panel>

          <div className="grid min-h-0 gap-4 lg:grid-cols-2 xl:min-h-[170px] xl:flex-1">
            <Panel fill title={tr("Việc tiếp theo")} icon="bolt" tone="cue">
              {stuck.length + d.offline_volumes.length + d.problems.length + dueMetrics.length === 0 && groups.length === 0 && (projects
                ? <Empty icon="clapper" title={tr("Chưa có việc gì")} action={<Button kind="primary" onClick={() => go("/du-an?moi=1")}><Icon name="plus" />{tr("Làm video mới")}</Button>}>{tr("Viết một kịch bản, hệ thống sẽ tìm clip và dựng thành video.")}</Empty>
                : <Skeleton height={120} />)}
              <ul className="grid gap-1">
                {stuck.map((i) => (
                  <li key={i.run_id}><a href={i.link} onClick={open(i.link)} className="flex items-center gap-3 rounded-lg p-2 transition-colors hover:bg-white/[0.04]">
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${i.status === "failed" ? TINT.tally : TINT.cue}`}><Icon name="alert" size={16} /></span>
                    <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium">{i.name}</span><span className={`block truncate text-[12.5px] ${i.status === "failed" ? "text-tally" : "text-cue"}`}>{ASK[i.status]?.(i) ?? i.status}</span></span></a></li>
                ))}
                {d.offline_volumes.map((v) => (
                  <li key={v.volume_id}><a href="/he-thong" onClick={open("/he-thong")} className="flex items-center gap-3 rounded-lg p-2 transition-colors hover:bg-white/[0.04]">
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${TINT.cue}`}><Icon name="disk" size={16} /></span>
                    <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium">{v.mount_path}</span><span className="block truncate text-[12.5px] text-cue">{tv`Không tìm thấy nơi chứa ${v.files} file footage`}</span></span></a></li>
                ))}
                {d.problems.map((p) => (
                  <li key={p.name}><a href="/he-thong" onClick={open("/he-thong")} className="flex items-center gap-3 rounded-lg p-2 transition-colors hover:bg-white/[0.04]">
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${TINT.tally}`}><Icon name="cpu" size={16} /></span>
                    <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium">{p.name}</span><span className="block truncate text-[12.5px] text-tally">{p.detail}</span></span></a></li>
                ))}
                {dueMetrics.slice(0, 3).map((m) => (
                  <li key={`${m.publication_id}-${m.mark}`}><a href="/ke-hoach?xem=ket-qua" onClick={open("/ke-hoach?xem=ket-qua")} className="flex items-center gap-3 rounded-lg p-2 transition-colors hover:bg-white/[0.04]">
                    <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${TINT.cue}`}><Icon name="pulse" size={16} /></span>
                    <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium">{m.title}</span><span className="block truncate text-[12.5px] text-cue">{tv`Tới mốc ghi số liệu ${m.mark < 48 ? tv`${m.mark} giờ` : tv`${Math.round(m.mark / 24)} ngày`} sau khi đăng`}</span></span>
                    <span className={`inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-[12px] font-medium ${TINT.cue}`}><Icon name="edit" size={13} />{tr("Ghi số liệu")}</span></a></li>
                ))}
                {groups.slice(0, 5).map((g) => { const n = g[0], many = g.length > 1; const to = many ? (n.label === tr("Duyệt bản dựng") ? "/phong-chieu" : "/du-an") : n.to; return (
                  <li key={n.label}><a href={to} onClick={open(to)} className="group flex items-center gap-3 rounded-lg p-2 transition-colors hover:bg-white/[0.04]">
                    <span className="relative h-9 w-14 shrink-0">
                      {g.slice(0, 3).reverse().map((x, k, arr) => { const src = poster(x.p); const shift = (arr.length - 1 - k) * 5; return src
                        ? <img key={x.p.project_id} src={src} alt="" className="absolute h-9 w-12 rounded-md object-cover ring-2 ring-surface" style={{ left: shift, top: 0 }} />
                        : <span key={x.p.project_id} className="hatch absolute h-9 w-12 rounded-md ring-2 ring-surface" style={{ left: shift, top: 0 }} />; })}
                    </span>
                    <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium">{many ? tv`${g.length} video` : n.p.title}</span>
                      <span className="block truncate text-[12.5px] text-mute">{many ? g.map((x) => x.p.title).join(", ") : n.hint}</span></span>
                    <span className={`inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md px-2.5 text-[12px] font-medium ${TINT[n.tone]}`}><Icon name={n.icon} size={13} />{n.label}</span></a></li>); })}
              </ul>
            </Panel>

            <Panel fill title={tr("Nhịp 14 ngày")} icon="pulse"><Rhythm projects={list} posted={posted} /></Panel>
          </div>

          {(ideas.length > 0 || best.length > 0) && (
            <div className={`grid shrink-0 items-stretch gap-4 ${ideas.length && best.length ? "lg:grid-cols-2" : ""}`}>
              {ideas.length > 0 && (
                <Panel title={tr("Cơ hội từ kho footage")} icon="radar" end={<button type="button" onClick={() => go("/ke-hoach?xem=radar")} className="link">{tr("Radar cơ hội")}</button>}>
                  <ul className={`grid gap-2 sm:grid-cols-2 ${best.length ? "" : "2xl:grid-cols-4"}`}>
                    {ideas.map((x, k) => (
                      <li key={x.subject} className={`flex items-center gap-3 rounded-lg bg-white/[0.03] p-2.5 ${k > 1 ? "short:hidden" : ""}`}>
                        <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium first-letter:uppercase">{x.subject}</span>
                          <span className="block truncate text-[12.5px] text-mute">{fresh.length ? tv`${x.unused_videos} video chưa dùng, ${hours(x.unused_seconds)} hình` : tv`${x.videos} video, ${hours(x.seconds)} hình trong kho`}</span></span>
                        <Button size="sm" onClick={() => startFrom(x.subject)}><Icon name="plus" size={13} />{tr("Làm video")}</Button>
                      </li>
                    ))}
                  </ul>
                </Panel>
              )}
              {best.length > 0 && (
                <Panel title={tr("Video đăng hiệu quả nhất")} icon="star" end={<button type="button" onClick={() => go("/ke-hoach?xem=ket-qua")} className="link">{tr("Kết quả")}</button>}>
                  <ul className="grid gap-1">
                    {best.map(({ x, views }, k) => (
                      <li key={x.publication_id} className="flex items-center gap-3 rounded-lg p-2">
                        <span className={`mono grid h-7 w-7 shrink-0 place-items-center rounded-md text-[12px] ${k === 0 ? "bg-accent/15 text-accent" : "bg-white/[0.05] text-mute"}`}>{k + 1}</span>
                        <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium">{x.title}</span><span className="block truncate text-[12px] text-faint">{x.target}</span></span>
                        <span className="mono shrink-0 text-[14px] font-medium">{views.toLocaleString(locale)}<span className="ml-1 text-[11.5px] font-normal text-faint">{tr("lượt xem")}</span></span>
                      </li>
                    ))}
                  </ul>
                </Panel>
              )}
            </div>
          )}
        </div>

        <aside className="flex min-h-0 flex-col gap-4">
          <Panel className="shrink-0" title={tr("Tiến độ kênh tuần này")} icon="globe" end={<button type="button" onClick={() => go("/ke-hoach")} className="link">{tr("Kênh")}</button>}>
            <Cadences channels={cal?.channels ?? []} cadence={cal?.cadence ?? []} today={cal?.today ?? dayKey(new Date())} go={go} />
          </Panel>
          <Panel fill className="xl:min-h-[120px] xl:flex-1" title={tr("Lịch đăng 7 ngày tới")} icon="calendar" end={<button type="button" onClick={() => go("/ke-hoach")} className="link">{tr("Mở lịch")}</button>}>
            <Upcoming rows={cal?.projects ?? []} go={go} />
          </Panel>

          <Panel className="shrink-0" title={tr("Bản dựng mới nhất")} icon="screen" end={<button type="button" onClick={() => go("/phong-chieu")} className="link">{tr("Phòng chiếu")}</button>}>
            {renders.length === 0 && <p className="text-[13px] text-mute">{tr("Chưa có bản dựng nào.")}</p>}
            <ul className="grid gap-2">
              {renders.map(({ p, r }, k) => { const src = r.package ? `/api/v1/renders/${r.render_id}/package/${r.package.thumbnail}` : poster(p); const ok = r.review?.approved;
                const wait = p.renders[0]?.render_id === r.render_id && p.render?.status === "waiting_review"; return (
                <li key={r.render_id} className={k > 1 ? "short:hidden" : ""}><a href={`/phong-chieu?r=${r.render_id}`} onClick={open(`/phong-chieu?r=${r.render_id}`)} className="group flex items-center gap-3 rounded-lg p-1.5 transition-colors hover:bg-white/[0.04]">
                  <span className="relative h-12 w-20 shrink-0 overflow-hidden rounded-md bg-black">
                    {src ? <img src={src} alt="" className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105" /> : <span className="hatch block h-full w-full" />}
                    <span className="chip mono absolute bottom-1 right-1 !h-[18px] !px-1.5 !text-[10.5px]">{timecode(r.qc.duration)}</span></span>
                  <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium">{p.title}</span>
                    <span className={`block truncate text-[12px] ${wait ? "text-cue" : ok ? "text-proof" : "text-faint"}`}>{wait ? tr("Chờ bạn duyệt") : ok ? tr("Đã duyệt") : new Date(r.created_at * 1000).toLocaleDateString(locale)}</span></span>
                  <Icon name="play" size={15} className="text-faint transition-colors group-hover:text-accent" /></a></li>); })}
            </ul>
          </Panel>

          <Panel fill className="xl:max-h-[38%] xl:shrink-0 xl:short:max-h-[24%]" title={tr("Máy đang làm gì")} icon="cpu" tone="ai" end={<button type="button" onClick={() => go("/tien-trinh")} className="link">{tr("Tiến trình")}</button>}>
            {busy === 0 && <p className="flex items-center gap-2.5 rounded-lg bg-white/[0.03] px-3 py-2.5 text-[13px] text-mute"><span className="h-2 w-2 rounded-full bg-proof" />{tr("Máy đang rảnh.")}</p>}
            <ul className="grid gap-2">
              {d.running.map((i) => (
                <li key={i.run_id} className="rounded-lg bg-white/[0.03] p-3">
                  <div className="mb-2.5 flex items-center gap-3">
                    <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${TINT.ai}`}><Icon name={WORK_ICON[i.pipeline] ?? "pulse"} size={15} /></span>
                    <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium">{WORK[i.pipeline] ?? i.pipeline}<span className="ml-2 font-normal text-mute">{i.name}</span></span>
                      <span className="block truncate text-[12px] text-mute">{i.held ? tr("Chờ tới giờ phân tích") : i.stage_key ? tv`Bước ${stageName(i.stage_key, i.pipeline)}` : tr("Trong hàng đợi")}</span></span>
                  </div>
                  <StageRail stages={i.stages ?? []} name={(k) => stageName(k, i.pipeline)} />
                </li>
              ))}
              {d.agent.map((t) => (
                <li key={t.task_id}><a href={`/du-an/${t.project_id}`} onClick={open(`/du-an/${t.project_id}`)} className="flex items-start gap-3 rounded-lg bg-ai/[0.06] p-3 transition-colors hover:bg-ai/10">
                  <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-lg ${TINT.ai}`}><Icon name="sparkles" size={15} /></span>
                  <span className="min-w-0"><span className="block truncate text-[13.5px] font-medium">{tv`Trợ lý sản xuất: ${t.goal}`}</span>
                    <span className={`line-clamp-2 text-[12.5px] ${t.status === "waiting_operator" ? "text-cue" : "text-mute"}`}>{t.log[t.log.length - 1]?.text}</span></span></a></li>
              ))}
            </ul>
            {d.unavailable.length > 0 && (
              <div className="mt-3 border-t border-line pt-3">
                <p className="mb-2 text-[12.5px] text-faint">{tr("Chưa dùng được trên máy này")}</p>
                <ul className="grid gap-1.5">
                  {d.unavailable.map((u) => (
                    <li key={u.pipeline} className="flex items-start gap-2.5 text-[13px]"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cue" />
                      <span><span className="font-medium">{WORK[u.pipeline] ?? u.pipeline}</span><span className="block text-[12.5px] text-mute">{tv`Thiếu ${u.missing.map((m) => NEEDS[m] ?? m).join(", ")}`}</span></span></li>
                  ))}
                </ul>
              </div>
            )}
          </Panel>
        </aside>
      </div>
      </div>
    </Page>
  );
}
