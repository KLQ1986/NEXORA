import { useState } from "react";
import { call, post, REASONS, stageName, STATUS_NAMES, usePoll, type Asset, type Project, type Run } from "./api";
import { Button, Page, StageRail, Tag } from "./parts";

const PIPELINES: Record<string, string> = { "library.ingest": "Nhập footage", "library.ingest_image": "Nhập ảnh", "library.ingest_audio": "Nhập nhạc", "sourcing.generate": "Sinh hình bằng AI", "library.understand": "Xem và mô tả video", "sourcing.match": "Chọn clip cho kịch bản", "edit.render": "Dựng video" };

type Detail = Run & { attempts: { stage_key: string; number: number; outcome: string | null; worker: string; started_at: number; seconds: number | null; error_code: string | null; error_message: string | null }[];
                      events: { at: number; kind: string; stage_key: string | null; actor: string }[] };
const clock = (t: number) => new Date(t * 1000).toLocaleTimeString("vi-VN");
const OUTCOMES: Record<string, string> = { succeeded: "Xong", failed: "Lỗi", unknown: "Chưa rõ kết quả", cancelled: "Đã huỷ" };

/** What happened inside one run: every attempt with how long it took, and why the failed ones failed. */
function RunDetail({ id, pipeline, reload }: { id: string; pipeline: string; reload: () => void }) {
  const { data: d } = usePoll<Detail>(`/api/v1/runs/${id}/detail`, 3000);
  if (!d) return <p className="py-2 text-sm text-mute">Đang tải chi tiết</p>;
  const total = d.attempts.reduce((sum, a) => sum + (a.seconds ?? 0), 0);
  const live = ["queued", "running", "blocked", "waiting_review"].includes(d.status);
  return (
    <div className="col-span-full mb-1 rounded-md bg-canvas p-4">
      <div className="mb-2 flex flex-wrap items-center gap-4 text-sm text-mute">
        <span className="tc">Bắt đầu {clock(d.created_at)}</span><span className="tc">Tổng thời gian chạy {total.toFixed(1)} giây</span><span className="tc">{d.run_id}</span>
        {live && <span className="ml-auto"><Button kind="danger" onClick={async () => { await post(`/api/v1/runs/${id}/cancel`).catch(() => {}); reload(); }}>Huỷ lần chạy này</Button></span>}
      </div>
      <table className="w-full text-left text-sm">
        <thead className="text-mute"><tr><th className="py-1 font-medium">Bước</th><th className="font-medium">Lần thử</th><th className="font-medium">Lúc</th><th className="font-medium">Mất</th><th className="font-medium">Kết quả</th></tr></thead>
        <tbody className="divide-y divide-line">
          {d.attempts.map((a, i) => (
            <tr key={i} className="align-top"><td className="py-1.5">{stageName(a.stage_key, pipeline)}</td><td className="tc">{a.number}</td><td className="tc">{clock(a.started_at)}</td>
              <td className="tc">{a.seconds == null ? "đang chạy" : `${a.seconds.toFixed(1)} giây`}</td>
              <td className={a.outcome === "failed" ? "text-tally" : ""}>{a.outcome ? OUTCOMES[a.outcome] ?? a.outcome : STATUS_NAMES.running}{a.error_code && <span className="block break-words text-mute">{REASONS[a.error_code] ?? a.error_code}{a.error_message ? `: ${a.error_message}` : ""}</span>}</td></tr>
          ))}
        </tbody>
      </table>
      {d.attempts.length === 0 && <p className="text-sm text-mute">Chưa bước nào bắt đầu chạy.</p>}
    </div>
  );
}

export default function Runs() {
  const [open, setOpen] = useState<string | null>(null);
  const { data: runs, error, reload } = usePoll<Run[]>("/api/v1/runs");
  const { data: lib } = usePoll<{ assets: Asset[] }>("/api/v1/library", 5000);
  const { data: projects } = usePoll<Project[]>("/api/v1/projects", 8000);
  const names = new Map<string, string>([...(lib?.assets ?? []).map((a) => [a.asset_id, a.name] as [string, string]),
    ...(projects ?? []).filter((p) => p.script).map((p) => [p.script!.script_id, p.title] as [string, string])]);
  const resume = async (stageId: string) => { await call(`/api/v1/stages/${stageId}/resume`, { method: "POST" }).catch(() => {}); reload(); };
  return (
    <Page title="Tiến trình" note="Mọi lần chạy và từng bước của nó. Bấm vào một dòng để xem từng lần thử, thời gian và lỗi.">
      {error && <p className="text-tally">Không tải được danh sách: {error}</p>}
      {runs && runs.length === 0 && <p className="panel max-w-xl px-4 py-6 text-mute">Chưa có việc nào chạy. Mỗi khi bạn thêm footage hoặc bắt đầu một video, các bước xử lý sẽ hiện ở đây.</p>}
      <ul className="panel rows overflow-hidden empty:hidden">
        {(runs ?? []).map((r) => {
          const stuck = r.stages.filter((s) => s.status === "blocked" || s.status === "failed");
          const now = r.stages.find((s) => s.status === "running");
          return (
            <li key={r.run_id} className="grid gap-x-6 gap-y-2 px-4 py-3 md:grid-cols-[minmax(0,1fr)_220px_150px] md:items-center">
              <div className="min-w-0">
                <button type="button" aria-expanded={open === r.run_id} onClick={() => setOpen(open === r.run_id ? null : r.run_id)} className="block max-w-full truncate text-left font-medium hover:underline">{PIPELINES[r.pipeline] ?? r.pipeline}: {names.get(r.subject_ref ?? "") ?? (r.subject_ref?.startsWith("scr_") ? "phiên bản kịch bản cũ" : r.subject_ref)}</button>
                {now && <p className="text-sm text-mute">Đang ở bước {stageName(now.stage_key, r.pipeline)}</p>}
                {stuck.map((s) => (
                  <div key={s.stage_id} className="mt-1 flex flex-wrap items-center gap-3 text-sm">
                    <span className={s.status === "failed" ? "text-tally" : "text-cue"}>
                      Bước {stageName(s.stage_key, r.pipeline)} {s.status === "failed" ? "thất bại" : "đang dừng"}{s.blocked_reason ? `: ${REASONS[s.blocked_reason] ?? s.blocked_reason}` : ""}
                    </span>
                    {s.status === "blocked" && <Button onClick={() => resume(s.stage_id)}>Chạy tiếp</Button>}
                  </div>
                ))}
              </div>
              <StageRail stages={r.stages} />
              <p className="md:text-right">{r.held ? <Tag>Chờ tới giờ phân tích</Tag> : <Tag tone={r.status === "succeeded" ? "proof" : r.status === "failed" ? "tally" : r.status === "blocked" || r.status === "waiting_review" ? "cue" : "mute"}>{STATUS_NAMES[r.status] ?? r.status}</Tag>}</p>
              {open === r.run_id && <RunDetail id={r.run_id} pipeline={r.pipeline} reload={reload} />}
            </li>
          );
        })}
      </ul>
    </Page>
  );
}
