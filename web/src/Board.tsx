import { useState } from "react";
import { stageName, timecode, usePoll, type BoardEvent, type Project } from "./api";
import { Section, Tag } from "./parts";

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
  const tone = (kind: string) => (kind === "stage.waiting_review" || kind === "stage.blocked" ? "bg-cue" : kind === "stage.failed" ? "bg-tally" : kind === "stage.succeeded" || kind === "review.decided" ? "bg-proof" : "bg-faint");
  const feed = [...shown].reverse().filter((e) => WORDS[e.kind] && e.kind !== "stage.ready");
  return (
    <div className="grid gap-6">
      {(p.render?.stalled || p.match?.stalled) && <p className="panel border-cue/50 px-4 py-3 text-cue">Một bước đang chạy nhưng đã lâu không báo tiến độ, có thể bị treo. Hệ thống sẽ tự thu hồi và chạy lại; xem chi tiết ở mục Tiến trình.</p>}
      <div className="panel p-5">
        <ol className="grid grid-cols-7 gap-1.5" aria-label="Các công đoạn">
          {RAIL.map((s, i) => (
            <li key={s.key}>
              <div className={`h-1.5 rounded-full ${waiting.has(s.key) ? "bg-cue" : active.has(s.key) ? "animate-pulse bg-ink" : done.has(s.key) ? "bg-proof" : "bg-line"}`} />
              <p className={`mt-2 text-[13px] ${waiting.has(s.key) ? "font-medium text-cue" : active.has(s.key) ? "font-medium" : done.has(s.key) ? "text-mute" : "text-faint"}`}><span className="tc mr-1.5 text-faint">{i + 1}</span>{s.label}</p>
            </li>
          ))}
        </ol>
        {all.length > 1 && (
          <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-line pt-4">
            <label htmlFor="replay" className="text-[13px] font-medium">Xem lại quá trình</label>
            <input id="replay" type="range" min={0} max={all.length} value={at ?? all.length} onChange={(e) => { const v = Number(e.target.value); setAt(v >= all.length ? null : v); }} className="min-w-40 flex-1 accent-[var(--color-ink)]" />
            <span className="tc w-24 text-right text-[13px] text-mute">{at === null ? "Hiện tại" : shown.length ? clock(shown[shown.length - 1].at) : "Lúc bắt đầu"}</span>
            {at !== null && <button type="button" onClick={() => setAt(null)} className="text-[13px] text-mute underline underline-offset-2 hover:text-ink">Về hiện tại</button>}
          </div>
        )}
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid gap-6">
          <Section title="Các cảnh" note={p.shots.length ? `${p.shots.length} câu, ${p.shots.filter((s) => s.selection?.status === "accepted").length} đã duyệt, ${p.shots.filter((s) => s.selection?.status === "gap").length} thiếu hình` : undefined}>
            {p.shots.length === 0 && <p className="panel px-4 py-6 text-mute">Dự án chưa có kịch bản. Viết kịch bản ở thẻ Làm video để các cảnh hiện ra ở đây.</p>}
            <ol className="grid grid-cols-2 gap-x-3 gap-y-5 sm:grid-cols-3 2xl:grid-cols-4">
              {p.shots.map((s, i) => {
                const sel = s.selection;
                const src = sel && sel.status !== "gap" ? sel.frame_url ?? sel.asset?.thumbnail_url ?? s.keyframe_url : s.keyframe_url;
                return (
                  <li key={s.shot_id}>
                    <div className={`relative aspect-video overflow-hidden rounded-md ${sel?.status === "gap" ? "hatch border border-cue/60 bg-surface" : "bg-black"}`}>
                      {src && <img src={src} alt="" loading="lazy" className="h-full w-full object-cover" />}
                      {sel?.status === "gap" && <span className="absolute inset-0 grid place-items-center"><Tag tone="cue">Thiếu hình</Tag></span>}
                      {!sel && <span className="absolute inset-0 grid place-items-center bg-surface text-[13px] text-faint">Chưa chọn</span>}
                      <span className="tc absolute left-1.5 top-1.5 rounded bg-canvas/85 px-1.5 text-[11px] leading-5">{i + 1}</span>
                      {sel?.status === "accepted" && <span className="absolute bottom-1.5 right-1.5 h-2 w-2 rounded-full bg-proof ring-2 ring-canvas/70" title="Đã duyệt" />}
                    </div>
                    <p className="mt-2 line-clamp-2 text-[13px] leading-snug">{s.text}</p>
                    {sel && sel.t_in != null && sel.asset && <p className="tc mt-0.5 truncate text-[12px] text-faint">{sel.asset.name}{sel.asset.still ? "" : `, ${timecode(sel.t_in)}`}</p>}
                  </li>
                );
              })}
            </ol>
          </Section>
          {latest && (
            <Section title="Bản dựng">
              <ul className="panel rows">
                {p.renders.map((r, i) => (
                  <li key={r.render_id} className="grid items-center gap-x-4 gap-y-1 px-4 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
                    <span className="tc min-w-0 truncate">{new Date(r.created_at * 1000).toLocaleString("vi-VN")}{i === 0 ? <span className="text-mute">, mới nhất</span> : null}</span>
                    <span className="tc text-[13px] text-mute">dài {timecode(r.qc.duration)}</span>
                    <Tag tone={r.review ? (r.review.approved ? "proof" : "tally") : r.qc.passed ? "mute" : "tally"}>{r.review ? (r.review.approved ? "Đã duyệt" : "Không duyệt") : r.qc.passed ? "Kiểm tra đạt" : "Kiểm tra không đạt"}</Tag>
                    <a className="text-[13px] underline underline-offset-2" href={r.url} target="_blank" rel="noreferrer">Mở video</a>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>
        <div className="grid gap-6">
        <Section title="Kịch bản" note={p.script ? `Phiên bản ${p.script.version}` : undefined}>
          <div className="panel max-h-72 overflow-y-auto px-6 py-5 font-[ui-monospace,Menlo,monospace] text-[13px] leading-relaxed">
            <p className="mb-3 text-center tracking-wide text-mute">{p.title}</p>
            {p.shots.length === 0 && <p className="text-center text-faint">Chưa có kịch bản.</p>}
            {p.shots.map((s, i) => <p key={s.shot_id} className="mb-2.5">{s.scene && s.scene !== p.shots[i - 1]?.scene && <span className="mb-1.5 mt-3 block uppercase tracking-wide text-mute">{s.scene}</span>}<span className="mr-2 text-faint">{String(i + 1).padStart(2, "0")}</span>{s.text}{s.brief && <span className="block pl-7 text-faint">(hình: {s.brief})</span>}{s.selection?.status === "gap" && <span className="ml-2 text-cue">[thiếu hình]</span>}</p>)}
          </div>
        </Section>
        <Section title="Hoạt động" note={`Chi phí: ${(data?.cost ?? 0).toFixed(2)} USD${(data?.cost ?? 0) === 0 ? ", mọi thứ chạy trên máy" : ""}`}>
          <ol className="panel max-h-[34rem] overflow-y-auto px-4 py-2">
            {feed.map((e, i) => (
              <li key={i} className="relative grid grid-cols-[14px_minmax(0,1fr)_auto] items-start gap-x-2.5 py-2 text-[13px]">
                {i < feed.length - 1 && <span className="absolute bottom-0 left-[6.5px] top-5 w-px bg-line" />}
                <span className={`relative mt-1.5 h-2 w-2 justify-self-center rounded-full ${tone(e.kind)}`} />
                <span className="min-w-0"><span className={e.kind === "stage.waiting_review" || e.kind === "stage.blocked" ? "font-medium text-cue" : e.kind === "stage.failed" ? "font-medium text-tally" : "font-medium"}>{WORDS[e.kind]}</span>
                  <span className="text-mute">{e.stage_key ? `, ${stageName(e.stage_key, e.pipeline).toLowerCase()}` : e.pipeline === "sourcing.match" ? ", chọn clip" : ", dựng video"}</span></span>
                <span className="tc text-faint">{clock(e.at)}</span>
              </li>
            ))}
            {shown.length === 0 && <li className="py-3 text-[13px] text-mute">Chưa có hoạt động nào.</li>}
          </ol>
        </Section>
        </div>
      </div>
    </div>
  );
}
