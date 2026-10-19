import { t as tr } from "./i18n";
import { usePoll, type AgentTask, type Project } from "./api";
import { goTo, Icon } from "./parts";

/** The whole production of one video as a line of nodes (Mission Control, design 2026-10-19): where the work stands, lit on the
    node it is at, and every node a way to that step's own screen below. The state is read from the assistant's step when an
    assistant works on the video, else from where the project stands. */
export type Screen = "script" | "storyboard" | "cut" | "publish";
type NodeState = "done" | "now" | "wait" | "fail" | "later";

const NODES: [string, string, string, Screen][] = [
  ["brief", tr("Nhiệm vụ"), "bolt", "script"], ["research", tr("Nghiên cứu"), "globe", "script"], ["write", tr("Kịch bản"), "edit", "script"],
  ["facts", tr("Kiểm chứng"), "shield", "script"], ["match", tr("Tìm clip"), "search", "storyboard"], ["stock", tr("Stock"), "film", "storyboard"],
  ["storyboard", tr("Storyboard"), "layers", "storyboard"], ["render", tr("Dựng"), "scissors", "cut"], ["qc", tr("QC"), "check", "cut"],
  ["review", tr("Duyệt"), "eye", "cut"], ["publish", tr("Xuất bản"), "external", "publish"],
];
const AT_STEP: Record<string, string> = { topic: "research", topic_wait: "research", research: "research", source: "research", write: "write", critique: "write",
  facts: "facts", matching: "match", gaps: "stock", review: "storyboard", cut: "render", cutting: "render" };
const SAID: Record<NodeState, string> = { done: tr("Xong"), now: tr("Đang chạy"), wait: tr("Chờ bạn"), fail: tr("Lỗi"), later: tr("Chưa tới") };

/** Which node the video is at, and how. */
export function pipelineAt(p: Project, task?: AgentTask | null): { at: number; mode: NodeState } {
  const idx = (k: string) => NODES.findIndex((n) => n[0] === k);
  const matching = p.match && ["queued", "running"].includes(p.match.status);
  const rendering = p.render && ["queued", "running"].includes(p.render.status);
  if (p.render?.status === "waiting_review") return { at: idx("review"), mode: "wait" };
  if (rendering) return { at: idx("render"), mode: "now" };
  if (p.renders[0]?.package) return { at: NODES.length, mode: "done" };
  if (p.renders.length && p.script?.match_approved && !rendering) return { at: idx("publish"), mode: "now" };
  if (task && ["working", "waiting_operator", "failed", "paused"].includes(task.status) && AT_STEP[task.step]) {
    const mode: NodeState = task.status === "failed" ? "fail" : task.status === "waiting_operator" ? "wait" : "now";
    return { at: idx(AT_STEP[task.step]), mode };
  }
  if (!p.script) return { at: idx("write"), mode: "now" };
  if (matching) return { at: idx("match"), mode: "now" };
  if (p.match?.status === "waiting_review") return { at: idx("storyboard"), mode: "wait" };
  if (!p.script.match_approved) return { at: idx("storyboard"), mode: "now" };
  return { at: idx("render"), mode: "now" };
}

function nodeStates(p: Project, task?: AgentTask | null): NodeState[] {
  const { at, mode } = pipelineAt(p, task);
  const qcFailed = p.renders[0]?.qc && p.renders[0].qc.passed === false;
  return NODES.map(([k], i) => (k === "qc" && qcFailed && at >= i ? "fail" : i < at ? "done" : i === at ? mode : "later"));
}

const TONE: Record<NodeState, string> = {
  done: "border-proof/50 bg-proof/10 text-proof", now: "border-accent bg-accent/15 text-accent", wait: "border-cue bg-cue/15 text-cue",
  fail: "border-tally bg-tally/15 text-tally", later: "border-line bg-white/[0.02] text-faint",
};

/** `place`: the screen open below, whose nodes are marked; `onScreen`: open a screen in place (else the page goes there). */
export default function Pipeline({ project: p, place, onScreen, compact = false, extra }: { project: Project; place?: Screen; onScreen?: (s: Screen) => void;
  compact?: boolean; extra?: React.ReactNode }) {
  const { data } = usePoll<{ tasks: AgentTask[] }>(`/api/v1/agent/tasks?project_id=${p.project_id}`, 4000);
  const task = data?.tasks[0];
  const states = nodeStates(p, task);
  const open = (s: Screen) => {
    if (onScreen && s !== "storyboard" && place !== "storyboard") return onScreen(s);
    goTo(s === "storyboard" ? `/du-an/${p.project_id}/storyboard` : `/du-an/${p.project_id}?tab=${s}`);
  };
  return (
    <div className={`pipe-grid scroll-x flex items-center ${compact ? "gap-0 py-1.5" : "gap-0 px-1 py-2.5"}`} role="navigation" aria-label={tr("Dây chuyền sản xuất video")}>
      {NODES.map(([k, label, icon, screen], i) => {
        const st = states[i];
        const here = place === screen;
        return (
          <span key={k} className="flex shrink-0 items-center">
            {i > 0 && <span className={`pipe-link ${compact ? "w-3" : "w-5"} shrink-0 ${states[i - 1] === "done" && (st === "done" || st === "now" || st === "wait") ? (st === "now" ? "live" : "done") : ""}`} aria-hidden="true" />}
            <button type="button" onClick={() => open(screen)} title={`${label}: ${SAID[st]}${task && pipelineAt(p, task).at === i ? ` · ${tr("trợ lý")}` : ""}`}
                    className={`pipe-node ${st} group relative flex shrink-0 items-center gap-1.5 rounded-md border ${TONE[st]} ${compact ? "h-7 px-1.5" : "h-9 px-2"} transition-colors hover:brightness-125 ${here ? "ring-1 ring-ink/60 ring-offset-1 ring-offset-canvas" : ""}`}>
              <span className={`mono ${compact ? "hidden" : ""} text-[9.5px] opacity-70`}>{`N${String(i + 1).padStart(2, "0")}`}</span>
              <Icon name={st === "done" ? "check" : icon} size={compact ? 12 : 13} />
              <span className={`${compact ? "text-[11px]" : "text-[12px]"} whitespace-nowrap font-medium`}>{label}</span>
              {(st === "now" || st === "wait") && <span className={`absolute -right-1 -top-1 h-2 w-2 rounded-full ${st === "now" ? "bg-accent" : "bg-cue"}`}><span className={`ping absolute inset-0 rounded-full ${st === "now" ? "bg-accent" : "bg-cue"}`} /></span>}
            </button>
          </span>);
      })}
      {extra && <><span className="mx-3 h-5 w-px shrink-0 bg-line" aria-hidden="true" />{extra}</>}
    </div>
  );
}
