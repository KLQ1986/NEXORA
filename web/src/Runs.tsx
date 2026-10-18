import { PIPE } from "./Notices";
import { t as tr, tv, locale } from "./i18n";
import { useState } from "react";
import { call, post, REASONS, stageName, STATUS_NAMES, usePoll, type Asset, type Project, type Run } from "./api";
import { Button, Empty, Icon, OpsSide, Page, StageRail, Tag, Readout } from "./parts";

const PIPELINES = PIPE;
const ICONS: Record<string, string> = { "library.ingest": "film", "library.ingest_image": "image", "library.ingest_audio": "music", "sourcing.generate": "spark", "library.understand": "eye", "sourcing.match": "sparkles", "edit.render": "scissors" };

type Detail = Run & { attempts: { stage_key: string; number: number; outcome: string | null; worker: string; started_at: number; seconds: number | null; error_code: string | null; error_message: string | null }[];
                      events: { at: number; kind: string; stage_key: string | null; actor: string }[] };
const clock = (t: number) => new Date(t * 1000).toLocaleTimeString(locale);
const OUTCOMES: Record<string, string> = { succeeded: tr("Xong"), failed: tr("Lỗi"), unknown: tr("Chưa rõ kết quả"), cancelled: tr("Đã huỷ") };
const toneOf = (r: Run) => (r.status === "succeeded" ? "proof" : r.status === "failed" ? (r.cleared ? "mute" : "tally") : r.status === "blocked" || r.status === "waiting_review" ? "cue" : r.status === "running" ? "ai" : "mute") as "proof" | "tally" | "cue" | "ai" | "mute";

/** What happened inside one run: every attempt with how long it took, and why the failed ones failed. */
function RunDetail({ id, pipeline, reload }: { id: string; pipeline: string; reload: () => void }) {
  const { data: d } = usePoll<Detail>(`/api/v1/runs/${id}/detail`, 3000);
  if (!d) return <p className="px-4 pb-4 text-[13px] text-mute">{tr("Đang tải chi tiết…")}</p>;
  const total = d.attempts.reduce((sum, a) => sum + (a.seconds ?? 0), 0);
  const live = ["queued", "running", "blocked", "waiting_review"].includes(d.status);
  const peak = Math.max(...d.attempts.map((a) => a.seconds ?? 0), 0.1);
  return (
    <div className="border-t border-line bg-canvas/60 px-4 py-4">
      <div className="mb-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12.5px] text-mute">
        <span className="flex items-center gap-1.5"><Icon name="clock" size={13} />{tr("Bắt đầu")} <span className="mono text-ink">{clock(d.created_at)}</span></span>
        <span>{tr("Tổng thời gian chạy")} <span className="mono text-ink">{total.toFixed(1)}s</span></span><span className="mono text-faint">{d.run_id}</span>
        {live && <span className="ml-auto"><Button size="sm" kind="danger" onClick={async () => { await post(`/api/v1/runs/${id}/cancel`).catch(() => {}); reload(); }}>{tr("Huỷ lần chạy này")}</Button></span>}
      </div>
      {d.attempts.length > 0 ? (
        <table className="w-full text-left text-[13px]">
          <thead className="eyebrow"><tr className="[&>th]:pb-2 [&>th]:pr-3"><th>{tr("Bước")}</th><th>{tr("Lần")}</th><th>{tr("Lúc")}</th><th className="w-1/4">{tr("Thời gian")}</th><th>{tr("Kết quả")}</th></tr></thead>
          <tbody className="divide-y divide-line border-t border-line">
            {d.attempts.map((a, i) => (
              <tr key={i} className="align-top [&>td]:py-2 [&>td]:pr-3"><td>{stageName(a.stage_key, pipeline)}</td><td className="mono text-mute">{a.number}</td><td className="mono text-mute">{clock(a.started_at)}</td>
                <td>{a.seconds == null ? <span className="text-ai">{tr("đang chạy…")}</span> : <span className="flex items-center gap-2"><span className="h-1.5 rounded-full bg-gradient-to-r from-accent to-ai" style={{ width: `${Math.max(4, (a.seconds / peak) * 100)}%` }} /><span className="mono shrink-0 text-[12px] text-mute">{a.seconds.toFixed(1)}s</span></span>}</td>
                <td className={a.outcome === "failed" ? "text-tally" : a.outcome === "succeeded" ? "text-proof" : ""}>{a.outcome ? OUTCOMES[a.outcome] ?? a.outcome : STATUS_NAMES.running}{a.error_code && <span className="block break-words text-[12px] text-mute">{REASONS[a.error_code] ?? a.error_code}{a.error_message ? `: ${a.error_message}` : ""}</span>}</td></tr>
            ))}
          </tbody>
        </table>
      ) : <p className="text-[13px] text-mute">{tr("Chưa bước nào bắt đầu chạy.")}</p>}
    </div>
  );
}

type Filter = "all" | "live" | "attention" | "done";

export default function Runs() {
  const [open, setOpen] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const { data: runs, error, reload } = usePoll<Run[]>("/api/v1/runs");
  const { data: lib } = usePoll<{ assets: Asset[] }>("/api/v1/library", 5000);
  const { data: projects } = usePoll<Project[]>("/api/v1/projects", 8000);
  const names = new Map<string, string>([...(lib?.assets ?? []).map((a) => [a.asset_id, a.name] as [string, string]),
    ...(projects ?? []).filter((p) => p.script).map((p) => [p.script!.script_id, p.title] as [string, string])]);
  const resume = async (stageId: string) => { await call(`/api/v1/stages/${stageId}/resume`, { method: "POST" }).catch(() => {}); reload(); };
  const all = runs ?? [];
  const kind = (r: Run): Filter => (["queued", "running"].includes(r.status) ? "live" : ["blocked", "failed", "waiting_review"].includes(r.status) || r.stalled ? "attention" : "done");
  const count = (f: Filter) => (f === "all" ? all.length : all.filter((r) => kind(r) === f).length);
  const shown = all.filter((r) => filter === "all" || kind(r) === filter);
  const tiles: [Filter, string, string, "ink" | "ai" | "cue" | "proof"][] = [["all", tr("Tất cả"), "layers", "ink"], ["live", tr("Đang chạy"), "pulse", "ai"], ["attention", tr("Cần bạn"), "alert", "cue"], ["done", tr("Đã xong"), "check", "proof"]];
  return (
    <Page side={<OpsSide />} eyebrow={tr("Vận hành")} title={tr("Tiến trình")} note={tr("Mọi lần chạy và từng bước của nó. Bấm vào một dòng để xem từng lần thử, thời gian và lỗi.")}>
      {error && <p className="mb-4 text-tally">{tv`Không tải được danh sách: ${error}`}</p>}
      {runs && runs.length === 0 && <Empty icon="pulse" title={tr("Chưa có việc nào chạy")}>{tr("Mỗi khi bạn thêm footage hoặc bắt đầu một video, các bước xử lý sẽ hiện ở đây.")}</Empty>}
      {all.length > 0 && (
        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4" role="radiogroup" aria-label={tr("Lọc tiến trình")}>
          {tiles.map(([f, name, icon, color]) => <Readout key={f} label={name} value={count(f)} icon={icon} tone={color} on={filter === f} onClick={() => setFilter(f)} />)}
        </div>
      )}
      <ul className="grid gap-2">
        {shown.map((r) => {
          const stuck = r.stages.filter((s) => s.status === "blocked" || s.status === "failed");
          const now = r.stages.find((s) => s.status === "running");
          const done = r.stages.filter((s) => s.status === "succeeded" || s.status === "skipped").length;
          const t = toneOf(r);
          return (
            <li key={r.run_id} className={`panel overflow-hidden ${open === r.run_id ? "!border-edge" : ""}`}>
              <div className="grid gap-x-5 gap-y-3 p-3.5 md:grid-cols-[minmax(0,1fr)_minmax(0,320px)_150px] md:items-center">
                <button type="button" aria-expanded={open === r.run_id} onClick={() => setOpen(open === r.run_id ? null : r.run_id)} className="flex min-w-0 items-center gap-3 text-left">
                  <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${t === "ai" ? "bg-ai/12 text-ai" : t === "cue" ? "bg-cue/12 text-cue" : t === "tally" ? "bg-tally/12 text-tally" : "bg-raised text-mute"}`}><Icon name={ICONS[r.pipeline] ?? "pulse"} size={17} /></span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{PIPELINES[r.pipeline] ?? r.pipeline}<span className="ml-2 font-normal text-mute">{names.get(r.subject_ref ?? "") ?? (r.subject_ref?.startsWith("scr_") ? tr("phiên bản kịch bản cũ") : r.subject_ref)}</span></span>
                    <span className="block truncate text-[12.5px] text-mute">{now ? <span className="text-ai">{tv`Đang ở bước ${stageName(now.stage_key, r.pipeline)}`}</span> : tv`${done}/${r.stages.length} bước`}<span className="mono ml-3">{new Date(r.created_at * 1000).toLocaleString(locale, { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" })}</span></span>
                  </span>
                  <Icon name="down" size={14} className={`ml-auto shrink-0 text-faint transition-transform md:hidden ${open === r.run_id ? "rotate-180" : ""}`} />
                </button>
                <StageRail stages={r.stages} name={(k) => stageName(k, r.pipeline)} />
                <p className="flex items-center gap-2 md:justify-end">{r.stalled ? <Tag tone="cue">{tr("Có vẻ bị treo")}</Tag> : r.held ? <Tag>{tr("Chờ tới giờ phân tích")}</Tag> : <Tag tone={t}>{r.cleared ? tr("Lỗi đã xử lý") : STATUS_NAMES[r.status] ?? r.status}</Tag>}
                  <button type="button" onClick={() => setOpen(open === r.run_id ? null : r.run_id)} className="hidden h-7 w-7 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink md:grid" aria-label={tr("Chi tiết")}><Icon name="down" size={14} className={`transition-transform ${open === r.run_id ? "rotate-180" : ""}`} /></button></p>
              </div>
              {stuck.length > 0 && (
                <div className="grid gap-2 border-t border-line px-4 py-2.5">
                  {stuck.map((s) => (
                    <div key={s.stage_id} className="flex flex-wrap items-center gap-3 text-[13px]">
                      <Icon name="alert" size={14} className={s.status === "failed" ? "text-tally" : "text-cue"} />
                      <span className={s.status === "failed" ? "text-tally" : "text-cue"}>{tv`Bước ${stageName(s.stage_key, r.pipeline)}`} {s.status === "failed" ? tr("thất bại") : tr("đang dừng")}{s.blocked_reason ? `: ${REASONS[s.blocked_reason] ?? s.blocked_reason}` : ""}</span>
                      {s.status === "blocked" && <Button size="sm" onClick={() => resume(s.stage_id)}><Icon name="play" size={12} />{tr("Chạy tiếp")}</Button>}
                      {s.status === "failed" && <Button size="sm" onClick={async () => { await post(`/api/v1/stages/${s.stage_id}/retry`).catch(() => {}); reload(); }}><Icon name="refresh" size={13} />{tr("Thử lại bước này")}</Button>}
                      {s.status === "failed" && !r.cleared && <Button size="sm" kind="quiet" title={tr("Đã biết lỗi này; không tính nó là việc hỏng nữa")} onClick={async () => { await post("/api/v1/runs/dismiss", { run_ids: [r.run_id] }).catch(() => {}); reload(); }}>{tr("Bỏ qua lỗi")}</Button>}
                    </div>
                  ))}
                </div>
              )}
              {open === r.run_id && <RunDetail id={r.run_id} pipeline={r.pipeline} reload={reload} />}
            </li>
          );
        })}
      </ul>
    </Page>
  );
}
