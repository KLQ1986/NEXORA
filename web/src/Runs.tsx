import { call, REASONS, STAGE_NAMES, usePoll, type Asset, type Run } from "./api";
import { Button, StageRail, StatusText } from "./parts";

const PIPELINES: Record<string, string> = { "library.ingest": "Nhập footage", "library.understand": "Hiểu video" };

export default function Runs() {
  const { data: runs, error, reload } = usePoll<Run[]>("/api/v1/runs");
  const { data: lib } = usePoll<{ assets: Asset[] }>("/api/v1/library", 5000);
  const names = new Map((lib?.assets ?? []).map((a) => [a.asset_id, a.name]));
  const resume = async (stageId: string) => { await call(`/api/v1/stages/${stageId}/resume`, { method: "POST" }).catch(() => {}); reload(); };
  return (
    <section className="flex-1 overflow-y-auto p-6">
      <h1 className="mb-4 text-2xl font-semibold tracking-tight">Tiến trình</h1>
      {error && <p className="text-tally">Không tải được danh sách: {error}</p>}
      {runs && runs.length === 0 && <p className="max-w-md text-mute">Chưa có việc nào chạy. Mỗi khi bạn thêm footage hoặc bắt đầu một video, các bước xử lý sẽ hiện ở đây.</p>}
      <ul className="divide-y divide-line border-y border-line">
        {(runs ?? []).map((r) => {
          const stuck = r.stages.filter((s) => s.status === "blocked" || s.status === "failed");
          const now = r.stages.find((s) => s.status === "running");
          return (
            <li key={r.run_id} className="grid gap-x-6 gap-y-2 px-2 py-3 md:grid-cols-[minmax(0,1fr)_260px_140px] md:items-center">
              <div className="min-w-0">
                <p className="truncate font-medium">{PIPELINES[r.pipeline] ?? r.pipeline}: {names.get(r.subject_ref ?? "") ?? r.subject_ref}</p>
                {now && <p className="text-sm text-mute">Đang ở bước {STAGE_NAMES[now.stage_key] ?? now.stage_key}</p>}
                {stuck.map((s) => (
                  <div key={s.stage_id} className="mt-1 flex flex-wrap items-center gap-3 text-sm">
                    <span className={s.status === "failed" ? "text-tally" : "text-cue"}>
                      Bước {STAGE_NAMES[s.stage_key] ?? s.stage_key} {s.status === "failed" ? "thất bại" : "đang dừng"}{s.blocked_reason ? `: ${REASONS[s.blocked_reason] ?? s.blocked_reason}` : ""}
                    </span>
                    {s.status === "blocked" && <Button onClick={() => resume(s.stage_id)}>Chạy tiếp</Button>}
                  </div>
                ))}
              </div>
              <StageRail stages={r.stages} />
              <p className="text-sm md:text-right"><StatusText status={r.status} /></p>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
