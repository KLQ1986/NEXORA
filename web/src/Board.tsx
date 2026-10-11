import { useState } from "react";
import { stageName, timecode, usePoll, type BoardEvent, type Project } from "./api";

const RAIL = [
  { key: "script", label: "Kịch bản" }, { key: "match", label: "Chọn clip" }, { key: "match_review", label: "Duyệt clip" },
  { key: "narration", label: "Lời dẫn" }, { key: "segments", label: "Dựng từng cảnh" }, { key: "assemble", label: "Ghép và kiểm tra" }, { key: "render_review", label: "Duyệt bản dựng" },
];
const WORDS: Record<string, string> = {
  "run.submitted": "Bắt đầu", "stage.claimed": "Đang làm", "stage.succeeded": "Xong", "stage.waiting_review": "Chờ bạn duyệt", "stage.blocked": "Dừng, cần bạn xử lý",
  "stage.failed": "Thất bại", "stage.retry_wait": "Sẽ thử lại", "review.decided": "Bạn đã quyết định", "stage.ready": "Sẵn sàng", "stage.cancelled": "Đã huỷ",
};
const clock = (t: number) => new Date(t * 1000).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** Which rail steps are done, active or waiting, from the events seen so far. Used live and for replay. */
function railState(p: Project, events: BoardEvent[]) {
  const done = new Set<string>(), active = new Set<string>(), waiting = new Set<string>();
  if (p.script) done.add("script");
  for (const e of events) {
    const k = e.stage_key;
    if (!k) continue;
    if (e.kind === "stage.claimed") { active.add(k); waiting.delete(k === "match" ? "match_review" : "render_review"); }
    if (e.kind === "stage.waiting_review") { active.delete(k); done.add(k); waiting.add(k === "match" ? "match_review" : "render_review"); }
    if (e.kind === "stage.succeeded") { active.delete(k); done.add(k); if (k === "match") { waiting.delete("match_review"); done.add("match_review"); } if (k === "assemble") { waiting.delete("render_review"); done.add("render_review"); } }
    if (e.kind === "stage.ready" && e.pipeline === "sourcing.match") { done.delete("match_review"); }
  }
  return { done, active, waiting };
}

export default function Board({ project: p }: { project: Project }) {
  const { data } = usePoll<{ events: BoardEvent[]; cost: number }>(`/api/v1/projects/${p.project_id}/board`, 2500);
  const all = data?.events ?? [];
  const [at, setAt] = useState<number | null>(null);          // replay position: number of events shown; null = live
  const shown = at === null ? all : all.slice(0, at);
  const { done, active, waiting } = railState(p, shown);
  const latest = p.renders[0];
  return (
    <div className="grid max-w-6xl gap-8">
      <ol className="grid grid-cols-7 gap-1" aria-label="Các công đoạn">
        {RAIL.map((s) => (
          <li key={s.key}>
            <div className={`h-2 rounded-full ${waiting.has(s.key) ? "bg-cue" : active.has(s.key) ? "animate-pulse bg-ink" : done.has(s.key) ? "bg-proof" : "bg-line"}`} />
            <p className={`mt-1 text-sm ${waiting.has(s.key) || active.has(s.key) ? "font-medium" : "text-mute"}`}>{s.label}</p>
          </li>
        ))}
      </ol>

      {all.length > 1 && (
        <div className="flex items-center gap-3">
          <label htmlFor="replay" className="text-sm text-mute">Xem lại quá trình</label>
          <input id="replay" type="range" min={0} max={all.length} value={at ?? all.length} onChange={(e) => { const v = Number(e.target.value); setAt(v >= all.length ? null : v); }} className="w-80 accent-[var(--color-cue)]" />
          <span className="tc text-sm text-mute">{at === null ? "Hiện tại" : shown.length ? clock(shown[shown.length - 1].at) : "Lúc bắt đầu"}</span>
        </div>
      )}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div>
          <h2 className="mb-2 text-[15px] font-semibold">Các cảnh</h2>
          <ol className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-4">
            {p.shots.map((s, i) => {
              const sel = s.selection;
              return (
                <li key={s.shot_id}>
                  <div className={`relative aspect-video overflow-hidden rounded-sm ${sel?.status === "gap" ? "border border-dashed border-cue" : "bg-raised"}`}>
                    {sel?.frame_url && sel.status !== "gap" && <img src={sel.frame_url} alt="" className="h-full w-full object-cover" />}
                    {sel?.status === "gap" && <span className="absolute inset-0 grid place-items-center text-sm text-cue">Thiếu hình</span>}
                    {!sel && <span className="absolute inset-0 grid place-items-center text-sm text-mute">Chưa chọn</span>}
                    <span className="tc absolute left-1 top-1 rounded-sm bg-canvas/80 px-1 text-xs">{i + 1}</span>
                    {sel?.status === "accepted" && <span className="absolute bottom-1 right-1 h-2 w-2 rounded-full bg-proof" title="Đã duyệt" />}
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm">{s.text}</p>
                  {sel && sel.t_in != null && sel.asset && <p className="tc truncate text-xs text-mute">{sel.asset.name}, {timecode(sel.t_in)}</p>}
                </li>
              );
            })}
          </ol>
          {p.shots.length === 0 && <p className="text-mute">Dự án chưa có kịch bản. Viết kịch bản ở thẻ Làm video để các cảnh hiện ra ở đây.</p>}
          {latest && (
            <div className="mt-8">
              <h2 className="mb-2 text-[15px] font-semibold">Bản dựng</h2>
              <ul className="divide-y divide-line border-y border-line">
                {p.renders.map((r) => (
                  <li key={r.render_id} className="flex flex-wrap items-center justify-between gap-3 py-2">
                    <span className="tc">{new Date(r.created_at * 1000).toLocaleString("vi-VN")}, dài {timecode(r.qc.duration)}</span>
                    <span className={r.qc.passed ? "text-proof" : "text-tally"}>{r.qc.passed ? "Kiểm tra đạt" : "Kiểm tra không đạt"}</span>
                    <a className="underline" href={r.url} target="_blank" rel="noreferrer">Mở video</a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
        <aside>
          <h2 className="mb-2 text-[15px] font-semibold">Hoạt động</h2>
          <p className="tc mb-2 text-sm text-mute">Chi phí mô hình: {(data?.cost ?? 0).toFixed(2)} USD{(data?.cost ?? 0) === 0 ? " (đang chạy trên máy, không tốn phí)" : ""}</p>
          <ol className="max-h-[28rem] divide-y divide-line overflow-y-auto border-y border-line">
            {[...shown].reverse().filter((e) => WORDS[e.kind] && e.kind !== "stage.ready").map((e, i) => (
              <li key={i} className="grid grid-cols-[4.6rem_1fr] gap-2 py-1.5 text-sm">
                <span className="tc text-mute">{clock(e.at)}</span>
                <span><span className={e.kind === "stage.waiting_review" || e.kind === "stage.blocked" ? "text-cue" : e.kind === "stage.failed" ? "text-tally" : ""}>{WORDS[e.kind]}</span>
                  {e.stage_key ? `: ${stageName(e.stage_key, e.pipeline)}` : e.pipeline === "sourcing.match" ? ": chọn clip" : ": dựng video"}</span>
              </li>
            ))}
            {shown.length === 0 && <li className="py-2 text-sm text-mute">Chưa có hoạt động nào.</li>}
          </ol>
        </aside>
      </div>
    </div>
  );
}
