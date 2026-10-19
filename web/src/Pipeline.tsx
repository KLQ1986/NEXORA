import { t as tr, tv, locale } from "./i18n";
import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { usePoll, type AgentTask, type Project } from "./api";
import { goTo, Icon } from "./parts";

/** The whole production of one video (Mission Control, design 2026-10-19): four parent tasks, each holding its child steps, every
    step lit by where the work stands, with what it has to show (lines, clips, candidates) and, under the pointer, what it does,
    what the assistant last said about it and when. A step opens its screen below. The state is read from the assistant's step
    when an assistant works on the video, else from where the project stands. */
export type Screen = "script" | "storyboard" | "cut" | "publish";
type NodeState = "done" | "now" | "wait" | "fail" | "later";
type Child = { key: string; label: string; icon: string; about: string; roles: string[]; ui: boolean };   // ui: the step has a screen of its own
type Group = { key: string; label: string; screen: Screen; children: Child[] };

const GROUPS: Group[] = [
  { key: "script", label: tr("Kịch bản"), screen: "script", children: [
    { key: "brief", label: tr("Nhiệm vụ"), icon: "bolt", about: tr("Mục tiêu của video: chủ đề, thời lượng, thể loại, khung hình."), roles: ["Điều phối"], ui: false },
    { key: "research", label: tr("Nghiên cứu"), icon: "globe", about: tr("Claude Code tìm nguồn trên web cho chủ đề (video theo chủ đề) hoặc đọc các trang bạn đưa."), roles: ["Nghiên cứu"], ui: false },
    { key: "write", label: tr("Viết"), icon: "edit", about: tr("Viết lời dẫn từng câu, rồi người phản biện nhận xét và viết lại."), roles: ["Biên kịch", "Phản biện"], ui: true },
    { key: "facts", label: tr("Kiểm chứng"), icon: "shield", about: tr("Đối chiếu từng câu nêu dữ kiện với nguồn: xác nhận, trái nguồn, hay chưa có nguồn."), roles: ["Kiểm chứng"], ui: true } ] },
  { key: "pictures", label: tr("Hình ảnh"), screen: "storyboard", children: [
    { key: "match", label: tr("Tìm clip"), icon: "search", about: tr("Tìm trong Thư viện một đoạn footage cho từng câu, có giám khảo mô hình nhìn."), roles: ["Tìm hình"], ui: true },
    { key: "stock", label: tr("Stock"), icon: "film", about: tr("Câu thiếu hình: chấm ứng viên stock qua ảnh xem trước; chỉ tải khi bạn chọn (hoặc bật tự tải)."), roles: ["Tìm stock"], ui: true },
    { key: "storyboard", label: tr("Storyboard"), icon: "layers", about: tr("Bạn xem từng shot, chọn hoặc đổi clip, rồi duyệt storyboard để dựng."), roles: [], ui: true } ] },
  { key: "cut", label: tr("Dựng"), screen: "cut", children: [
    { key: "render", label: tr("Dựng"), icon: "scissors", about: tr("Ghép clip, lời dẫn, phụ đề, nhạc thành bản dựng."), roles: ["Dựng phim"], ui: true },
    { key: "qc", label: tr("QC"), icon: "check", about: tr("Kiểm tra tự động: khung đen, lặng, mở đầu, phụ đề, bản quyền."), roles: [], ui: false },
    { key: "review", label: tr("Duyệt"), icon: "eye", about: tr("Bạn xem bản dựng trong Phòng chiếu hoặc tại đây, duyệt hoặc trả lại kèm lý do."), roles: [], ui: true } ] },
  { key: "publish", label: tr("Xuất bản"), screen: "publish", children: [
    { key: "publish", label: tr("Đóng gói & đăng"), icon: "external", about: tr("Gói video, phụ đề rời, ảnh đại diện, tiêu đề, mô tả có ghi công; đăng lên kênh."), roles: [], ui: true } ] },
];
const NODES = GROUPS.flatMap((g) => g.children.map((c) => ({ ...c, group: g })));
const AT_STEP: Record<string, string> = { topic: "research", topic_wait: "research", research: "research", source: "research", write: "write", critique: "write",
  facts: "facts", matching: "match", gaps: "stock", review: "storyboard", cut: "render", cutting: "render" };
const SAID: Record<NodeState, string> = { done: tr("Xong"), now: tr("Đang chạy"), wait: tr("Chờ bạn"), fail: tr("Lỗi"), later: tr("Chưa tới") };
const RING: Record<NodeState, string> = {
  done: "border-proof/60 text-proof bg-proof/10", now: "border-accent text-accent bg-accent/15", wait: "border-cue text-cue bg-cue/15",
  fail: "border-tally text-tally bg-tally/15", later: "border-white/15 text-faint bg-white/[0.02]",
};
const TEXT: Record<NodeState, string> = { done: "text-proof", now: "text-accent", wait: "text-cue", fail: "text-tally", later: "text-faint" };
const BAR: Record<NodeState, string> = { done: "bg-proof", now: "bg-accent", wait: "bg-cue", fail: "bg-tally", later: "bg-white/20" };

/** Which step the video is at, and how. */
export function pipelineAt(p: Project, task?: AgentTask | null): { at: number; mode: NodeState } {
  const idx = (k: string) => NODES.findIndex((n) => n.key === k);
  const matching = p.match && ["queued", "running"].includes(p.match.status);
  const rendering = p.render && ["queued", "running"].includes(p.render.status);
  if (p.render?.status === "waiting_review") return { at: idx("review"), mode: "wait" };
  if (rendering) return { at: idx("render"), mode: "now" };
  if (p.renders[0]?.package) return { at: NODES.length, mode: "done" };
  if (p.renders.length && p.script?.match_approved) return { at: idx("publish"), mode: "now" };
  if (task && ["working", "waiting_operator", "failed", "paused"].includes(task.status) && AT_STEP[task.step]) {
    return { at: idx(AT_STEP[task.step]), mode: task.status === "failed" ? "fail" : task.status === "waiting_operator" ? "wait" : "now" };
  }
  if (!p.script) return { at: idx("write"), mode: "now" };
  if (matching) return { at: idx("match"), mode: "now" };
  if (p.match?.status === "waiting_review") return { at: idx("storyboard"), mode: "wait" };
  if (!p.script.match_approved) return { at: idx("storyboard"), mode: "now" };
  return { at: idx("render"), mode: "now" };
}

function states(p: Project, task?: AgentTask | null): NodeState[] {
  const { at, mode } = pipelineAt(p, task);
  const qcFailed = p.renders[0]?.qc && p.renders[0].qc.passed === false;
  return NODES.map((n, i) => (n.key === "qc" && qcFailed && at >= i ? "fail" : i < at ? "done" : i === at ? mode : "later"));
}

/** What a step has to show, measured on the project: the short line under its name. */
function figure(key: string, p: Project, task?: AgentTask | null, loaded = true): string {
  const n = p.shots.length, facts = p.shots.filter((s) => s.is_fact), pictured = p.shots.filter((s) => s.selection && s.selection.status !== "gap").length;
  const latest = p.renders[0];
  switch (key) {
    case "brief": return !loaded ? "…" : task ? tr("có trợ lý") : tr("tự làm");
    case "research": return task?.log.some((e) => e.role === "Nghiên cứu") ? tr("có nguồn") : "—";
    case "write": return n ? tv`${n} câu` : "—";
    case "facts": return facts.length ? tv`${facts.filter((s) => s.fact_check?.verdict === "supported").length}/${facts.length} có nguồn` : "—";
    case "match": return n ? tv`${pictured}/${n} có clip` : "—";
    case "stock": { const c = task?.log.filter((e) => e.role === "Tìm stock").length ?? 0; return c ? tv`${Math.max(0, n - pictured)} câu chờ chọn` : "—"; }
    case "storyboard": return p.script?.match_approved ? tr("đã duyệt") : p.match?.status === "waiting_review" ? tr("chờ duyệt") : "—";
    case "render": return p.renders.length ? tv`${p.renders.length} bản dựng` : "—";
    case "qc": return latest?.qc ? (latest.qc.passed ? tr("đạt") : tr("chưa đạt")) : "—";
    case "review": return p.render?.status === "waiting_review" ? tr("chờ bạn") : latest && p.script?.match_approved ? tr("đã duyệt") : "—";
    case "publish": return latest?.package ? tr("đã đóng gói") : "—";
  }
  return "—";
}

function ago(at: number): string {
  const s = Math.max(0, Date.now() / 1000 - at);
  return s < 60 ? tr("vừa xong") : s < 3600 ? tv`${Math.round(s / 60)} phút trước` : s < 86400 ? tv`${Math.round(s / 3600)} giờ trước` : new Date(at * 1000).toLocaleDateString(locale);
}

type Hover = { i: number; x: number; y: number } | null;

/** `place`: the screen open below, whose parent is marked; `onScreen`: open a screen in place (else the page goes there). */
export default function Pipeline({ project: p, place, onScreen, compact = false, extra }: { project: Project; place?: Screen; onScreen?: (s: Screen) => void;
  compact?: boolean; extra?: React.ReactNode }) {
  const { data } = usePoll<{ tasks: AgentTask[] }>(`/api/v1/agent/tasks?project_id=${p.project_id}`, 4000);
  const task = data?.tasks[0];
  const st = states(p, task);
  const [hover, setHover] = useState<Hover>(null);
  // A parent task that is done folds to one mark so the line fits the screen; the operator may unfold it again.
  const [unfolded, setUnfolded] = useState<Set<string>>(new Set());
  const fold = (key: string) => setUnfolded((u) => { const n = new Set(u); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  // The whole line is scaled down, in proportion, to fit the width it is given (never below 60 %; past that it scrolls).
  const frame = useRef<HTMLDivElement>(null), line = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  useLayoutEffect(() => {
    if (compact || !frame.current || !line.current) return;
    const fit = () => { const room = frame.current!.clientWidth, need = line.current!.scrollWidth; setZoom(need > 0 ? Math.max(0.6, Math.min(1, room / need)) : 1); };
    fit();
    const watch = new ResizeObserver(fit);
    watch.observe(frame.current);
    return () => watch.disconnect();
  }, [compact, unfolded, place, p.project_id, task?.step, task?.status]);
  const timer = useRef<number | undefined>(undefined);
  const open = (s: Screen) => {
    if (onScreen && s !== "storyboard" && place !== "storyboard") return onScreen(s);
    goTo(s === "storyboard" ? `/du-an/${p.project_id}/storyboard` : `/du-an/${p.project_id}?tab=${s}`);
  };
  const show = (i: number, el: HTMLElement) => { window.clearTimeout(timer.current); const r = el.getBoundingClientRect(); setHover({ i, x: r.left + r.width / 2, y: r.bottom + 8 }); };
  const hide = () => { timer.current = window.setTimeout(() => setHover(null), 80); };
  const groupState = (g: Group): NodeState => {
    const s = g.children.map((c) => st[NODES.findIndex((n) => n.key === c.key)]);
    return s.includes("fail") ? "fail" : s.includes("wait") ? "wait" : s.includes("now") ? "now" : s.every((x) => x === "done") ? "done" : "later";
  };
  let k = -1;
  return (
    <div ref={frame} className={`pipe-grid ${zoom < 0.6 + 1e-6 ? "scroll-x" : "overflow-hidden"} ${compact ? "py-1" : "py-3"}`} role="navigation" aria-label={tr("Dây chuyền sản xuất video")}>
    <div ref={line} className={`flex w-max items-stretch ${compact ? "" : "mx-auto"}`} style={compact ? undefined : { zoom }}>
      {GROUPS.map((g, gi) => {
        const gs = groupState(g);
        const done = g.children.filter((c) => st[NODES.findIndex((n) => n.key === c.key)] === "done").length;
        const folded = !compact && gs === "done" && !unfolded.has(g.key) && place !== g.screen;
        const quiet = !compact && gs === "later";                  // not reached yet: names only, the card has the rest
        return (
          <div key={g.key} className="flex shrink-0 items-center">
            {gi > 0 && <span className={`pipe-link ${compact ? "w-3" : "w-4"} ${gs === "later" ? "" : gs === "now" && st[NODES.findIndex((n) => n.key === g.children[0].key) - 1] === "done" ? "live" : "done"}`} aria-hidden="true" />}
            <section className={`pipe-group ${gs} relative rounded-lg border ${place === g.screen ? "border-accent/70" : "border-white/10"} bg-black/30 backdrop-blur-sm ${compact ? "px-1.5 py-1" : "px-2 pb-2 pt-2"}`}>
              {!compact && (
                <header className="mb-1.5 flex items-center gap-2">
                  <span className="mono text-[11px] text-faint">{`G${gi + 1}`}</span>
                  <button type="button" onClick={() => open(g.screen)} className={`text-[13.5px] font-semibold uppercase tracking-[0.1em] ${TEXT[gs]} hover:underline`}>{g.label}</button>
                  <span className={`text-[12px] ${TEXT[gs]}`}>{SAID[gs]}</span>
                  <span className="ml-auto mono text-[11px] text-faint">{done}/{g.children.length}</span>
                  {gs === "done" && place !== g.screen && <button type="button" onClick={() => fold(g.key)} title={folded ? tr("Mở ra xem từng bước") : tr("Thu gọn")} aria-label={folded ? tr("Mở ra xem từng bước") : tr("Thu gọn")}
                                                               className="grid h-5 w-5 place-items-center rounded text-faint hover:bg-white/10 hover:text-ink"><Icon name={folded ? "next" : "back"} size={11} /></button>}
                </header>)}
              {!compact && <span className="absolute inset-x-3 top-[33px] h-px bg-white/[0.06]"><span className={`block h-px ${BAR[gs]} transition-all`} style={{ width: `${(100 * done) / g.children.length}%` }} /></span>}
              {folded ? (
                <button type="button" onClick={() => fold(g.key)} title={g.children.map((c) => c.label).join(" · ")}
                        className="pipe-step ui flex flex-col items-center gap-1.5 rounded-lg px-2 py-2 text-center">
                  <span className="whitespace-nowrap text-[15px] font-semibold text-ink">{tv`${g.children.length} bước xong`}</span>
                  <span className="pipe-node done relative grid h-14 w-14 shrink-0 place-items-center rounded-full border-2 border-proof/60 bg-proof/10 text-proof"><Icon name="check" size={24} /></span>
                </button>
              ) : (
              <div className={`flex ${compact ? "items-center" : "items-end"}`}>
                {g.children.map((c, ci) => {
                  k = NODES.findIndex((n) => n.key === c.key);
                  const s = st[k], i = k;
                  return (
                    <span key={c.key} className={`flex ${compact ? "items-center" : "items-end"}`}>
                      {ci > 0 && compact && <span className={`pipe-link w-2 ${st[i - 1] === "done" ? (s === "now" ? "live" : s === "later" ? "" : "done") : ""}`} aria-hidden="true" />}
                      <button type="button" onClick={c.ui ? () => open(g.screen) : undefined} aria-disabled={!c.ui || undefined}
                              onMouseEnter={(e) => show(i, e.currentTarget)} onMouseLeave={hide} onFocus={(e) => show(i, e.currentTarget)} onBlur={hide}
                              aria-label={`${c.label}: ${SAID[s]}${c.ui ? "" : ` (${tr("bước tự động, không có màn hình riêng")})`}`}
                              className={`pipe-step ${c.ui ? "ui" : "auto"} group relative flex items-center rounded-lg text-left ${compact ? "gap-1.5 px-0.5 py-0.5" : `flex-col-reverse gap-1.5 py-2 text-center ${quiet ? "px-3" : "px-4"}`}`}>
                        {/* The line between steps, drawn by each step as two halves meeting its neighbours', so it is one line whatever the labels' widths. */}
                        {!compact && ci > 0 && <span aria-hidden="true" className={`pipe-link pointer-events-none absolute bottom-[35px] left-0 right-1/2 mr-7 ${st[i - 1] === "done" ? (s === "now" ? "live" : s === "later" ? "" : "done") : ""}`} />}
                        {!compact && ci < g.children.length - 1 && <span aria-hidden="true" className={`pipe-link pointer-events-none absolute bottom-[35px] left-1/2 right-0 ml-7 ${s === "done" ? (st[i + 1] === "now" ? "live" : st[i + 1] === "later" ? "" : "done") : ""}`} />}
                        <span className={`pipe-node ${s} relative grid shrink-0 place-items-center rounded-full border ${RING[s]} ${compact ? "h-5 w-5" : "h-14 w-14 border-2"}`}>
                          <Icon name={s === "done" ? "check" : s === "fail" ? "alert" : c.icon} size={compact ? 10 : 24} />
                          {(s === "now" || s === "wait") && <span className={`absolute rounded-full ${compact ? "-right-0.5 -top-0.5 h-2 w-2" : "-right-0.5 -top-0.5 h-3.5 w-3.5"} ${s === "now" ? "bg-accent" : "bg-cue"}`}><span className={`ping absolute inset-0 rounded-full ${s === "now" ? "bg-accent" : "bg-cue"}`} /></span>}
                        </span>
                        {!compact && (
                          <span className="grid justify-items-center gap-0.5 leading-tight">
                            <span className="whitespace-nowrap text-[15px] font-semibold text-ink"><span className="mono mr-1.5 text-[11px] font-normal text-faint">{`N${String(i + 1).padStart(2, "0")}`}</span>{c.label}</span>
                            {!quiet && <span className={`whitespace-nowrap text-[12.5px] ${TEXT[s]}`}>{SAID[s]}<span className="text-faint"> · {figure(c.key, p, task, !!data)}</span></span>}
                          </span>)}
                      </button>
                    </span>);
                })}
              </div>)}
            </section>
          </div>);
      })}
      {extra && <><span className="mx-3 h-6 w-px shrink-0 self-center bg-line" aria-hidden="true" /><span className="flex shrink-0 items-center gap-1 self-center">{extra}</span></>}
    </div>
      {hover && createPortal(<Card i={hover.i} x={hover.x} y={hover.y} p={p} task={task} state={st[hover.i]} keep={() => window.clearTimeout(timer.current)} leave={hide} />, document.body)}
    </div>
  );
}

/** What a step is, where it stands and what was last said about it, under the pointer. */
function Card({ i, x, y, p, task, state, keep, leave }: { i: number; x: number; y: number; p: Project; task?: AgentTask | null; state: NodeState; keep: () => void; leave: () => void }) {
  const n = NODES[i];
  const said = task?.log.filter((e) => n.roles.includes(e.role)) ?? [];
  const last = said[said.length - 1];
  const left = Math.min(Math.max(12, x - 160), window.innerWidth - 332);
  return (
    <div role="tooltip" onMouseEnter={keep} onMouseLeave={leave} style={{ left, top: y }}
         className="pop fixed z-50 w-80 rounded-xl border border-accent/30 bg-surface/95 p-3 text-[12.5px] shadow-[0_0_0_1px_rgba(70,200,224,.08),0_12px_40px_-8px_rgba(0,0,0,.7),0_0_32px_-12px_rgba(70,200,224,.5)] backdrop-blur">
      <div className="mb-1.5 flex items-center gap-2">
        <span className={`grid h-6 w-6 place-items-center rounded-full border ${RING[state]}`}><Icon name={n.icon} size={12} /></span>
        <span className="font-semibold">{n.label}</span><span className="mono text-[10px] text-faint">{`${n.group.label.toUpperCase()} · N${String(i + 1).padStart(2, "0")}`}</span>
        <span className={`ml-auto text-[11.5px] font-medium ${TEXT[state]}`}>{SAID[state]}</span>
      </div>
      <p className="mb-2 text-mute">{n.about}</p>
      <p className="mb-2"><span className="text-faint">{tr("Số liệu: ")}</span>{figure(n.key, p, task)}</p>
      {last && <div className="mb-2 rounded-md border border-line bg-black/30 px-2 py-1.5">
        <p className="mb-0.5 flex items-center gap-1.5 text-[11px] text-faint"><Icon name="sparkles" size={10} className="text-ai" />{last.role} · {ago(last.at)}{said.length > 1 ? tv` · ${said.length} lần` : ""}</p>
        <p className="line-clamp-4 text-[12px] text-ink/90">{last.text}</p>
      </div>}
      {n.ui ? <p className="text-[11px] text-accent">{tv`Bấm để mở màn hình ${({ script: tr("Kịch bản"), storyboard: tr("Storyboard"), cut: tr("Dựng & duyệt"), publish: tr("Xuất bản") } as Record<Screen, string>)[n.group.screen]}`}</p>
        : <p className="text-[11px] text-faint">{tr("Bước tự động: chạy trong nền, không có màn hình riêng.")}</p>}
    </div>);
}
