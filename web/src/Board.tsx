import { useState } from "react";
import { stageName, timecode, usePoll, type BoardEvent, type Project } from "./api";
import { Icon, Section, Tag, TimeChip } from "./parts";

const RAIL = [
  { key: "script", label: "Kịch bản", icon: "edit" }, { key: "match", label: "Chọn clip", icon: "sparkles" }, { key: "match_review", label: "Duyệt clip", icon: "check" },
  { key: "narration", label: "Lời dẫn", icon: "mic" }, { key: "segments", label: "Dựng từng cảnh", icon: "scissors" }, { key: "assemble", label: "Ghép và kiểm tra", icon: "layers" }, { key: "render_review", label: "Duyệt bản dựng", icon: "play" },
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

/** The production of one project at a glance. Read-only: decisions are taken on the screens it links to. */
export default function Board({ project: p }: { project: Project }) {
  const { data } = usePoll<{ events: BoardEvent[]; cost: number }>(`/api/v1/projects/${p.project_id}/board`, 2500);
  const all = data?.events ?? [];
  const [at, setAt] = useState<number | null>(null);          // replay position: number of events shown; null = live
  const shown = at === null ? all : all.slice(0, at);
  const { done, active, waiting } = railState(p, shown);
  const latest = p.renders[0];
  const tone = (kind: string) => (kind === "stage.waiting_review" || kind === "stage.blocked" ? "bg-cue" : kind === "stage.failed" ? "bg-tally" : kind === "stage.succeeded" || kind === "review.decided" ? "bg-proof" : "bg-faint");
  const feed = [...shown].reverse().filter((e) => WORDS[e.kind] && e.kind !== "stage.ready");
  const accepted = p.shots.filter((s) => s.selection?.status === "accepted").length;
  const gaps = p.shots.filter((s) => s.selection?.status === "gap").length;
  return (
    <div className="grid gap-6">
      {(p.render?.stalled || p.match?.stalled) && <p className="cue-card flex items-center gap-2 px-4 py-3 text-cue"><Icon name="alert" />Một bước đang chạy nhưng đã lâu không báo tiến độ, có thể bị treo. Hệ thống sẽ tự thu hồi và chạy lại; xem chi tiết ở mục Tiến trình.</p>}
      <div className="panel overflow-hidden">
        <ol className="grid grid-cols-7 gap-0 px-3 pb-4 pt-5" aria-label="Các công đoạn">
          {RAIL.map((s, i) => {
            const w = waiting.has(s.key), a = active.has(s.key), d = done.has(s.key);
            return (
              <li key={s.key} className="relative flex flex-col items-center text-center">
                {i > 0 && <span className={`absolute top-[17px] h-0.5 rounded-full ${d || a || w ? "bg-proof/45" : "bg-line"}`} style={{ left: "calc(-50% + 24px)", right: "calc(50% + 24px)" }} />}
                <span className={`relative z-10 grid h-9 w-9 place-items-center rounded-full border ${w ? "border-cue/60 bg-cue/15 text-cue shadow-[0_0_18px_-2px_var(--color-cue)]" : a ? "border-ai/60 bg-ai/15 text-ai shadow-[0_0_18px_-2px_var(--color-ai)]" : d ? "border-proof/40 bg-proof/15 text-proof" : "border-line bg-raised text-faint"}`}>
                  <Icon name={d && !w && !a ? "check" : s.icon} size={16} />{a && <span className="ping absolute inset-0 rounded-full bg-ai/30" />}</span>
                <p className={`mt-2 px-1 text-[12px] leading-tight ${w ? "font-medium text-cue" : a ? "font-medium text-ai" : d ? "text-mute" : "text-faint"}`}>{s.label}</p>
              </li>
            );
          })}
        </ol>
        {all.length > 1 && (
          <div className="flex flex-wrap items-center gap-3 border-t border-line bg-raised/30 px-5 py-3">
            <label htmlFor="replay" className="flex items-center gap-2 text-[12.5px] font-medium"><Icon name="refresh" size={14} className="text-mute" />Xem lại quá trình</label>
            <input id="replay" type="range" min={0} max={all.length} value={at ?? all.length} onChange={(e) => { const v = Number(e.target.value); setAt(v >= all.length ? null : v); }} className="min-w-40 flex-1" />
            <span className="mono w-24 text-right text-[12px] text-mute">{at === null ? "● Trực tiếp" : shown.length ? clock(shown[shown.length - 1].at) : "Lúc bắt đầu"}</span>
            {at !== null && <button type="button" onClick={() => setAt(null)} className="link text-[12.5px]">Về hiện tại</button>}
          </div>
        )}
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="grid gap-6">
          <Section title="Các cảnh" icon="grid" note={p.shots.length ? <span className="flex flex-wrap gap-x-3"><span>{p.shots.length} câu</span><span className="text-proof">{accepted} đã duyệt</span>{gaps > 0 && <span className="text-cue">{gaps} thiếu hình</span>}</span> : undefined}>
            {p.shots.length === 0 && <p className="panel px-4 py-6 text-mute">Dự án chưa có kịch bản. Viết kịch bản ở thẻ Làm video để các cảnh hiện ra ở đây.</p>}
            <ol className="grid grid-cols-2 gap-3 sm:grid-cols-3 2xl:grid-cols-4">
              {p.shots.map((s, i) => {
                const sel = s.selection;
                const src = sel && sel.status !== "gap" ? sel.frame_url ?? sel.asset?.thumbnail_url ?? s.keyframe_url : s.keyframe_url;
                return (
                  <li key={s.shot_id} className={`panel overflow-hidden ${sel?.status === "gap" ? "!border-cue/40" : ""}`}>
                    <div className={`relative aspect-video overflow-hidden ${sel?.status === "gap" ? "hatch-cue bg-surface" : "bg-black"}`}>
                      {src && <img src={src} alt="" loading="lazy" className="h-full w-full object-cover" />}
                      {sel?.status === "gap" && <span className="absolute inset-0 grid place-items-center"><Tag tone="cue">Thiếu hình</Tag></span>}
                      {!sel && <span className="absolute inset-0 grid place-items-center bg-raised text-[12.5px] text-faint">Chưa chọn</span>}
                      <TimeChip className="absolute left-1.5 top-1.5">{String(i + 1).padStart(2, "0")}</TimeChip>
                      {sel?.status === "accepted" && <span className="absolute right-1.5 top-1.5 grid h-5 w-5 place-items-center rounded-full bg-proof text-canvas" title="Đã duyệt"><Icon name="check" size={12} /></span>}
                      {sel && sel.t_in != null && sel.asset && !sel.asset.still && <TimeChip className="absolute bottom-1.5 right-1.5">{timecode(sel.t_in)}</TimeChip>}
                    </div>
                    <div className="px-3 py-2.5">
                      <p className="line-clamp-2 text-[12.5px] leading-snug">{s.text}</p>
                      {sel && sel.asset && <p className="mt-1 truncate text-[11px] text-faint">{sel.asset.name}</p>}
                    </div>
                  </li>
                );
              })}
            </ol>
          </Section>
          {latest && (
            <Section title="Bản dựng" icon="play">
              <ul className="panel rows overflow-hidden">
                {p.renders.map((r, i) => (
                  <li key={r.render_id} className="grid items-center gap-x-4 gap-y-1 px-4 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
                    <span className="mono min-w-0 truncate text-[13px]">{new Date(r.created_at * 1000).toLocaleString("vi-VN")}{i === 0 ? <span className="ml-2 font-sans text-accent">mới nhất</span> : null}</span>
                    <span className="mono text-[12px] text-mute">{timecode(r.qc.duration)}</span>
                    <Tag tone={r.review ? (r.review.approved ? "proof" : "tally") : r.qc.passed ? "mute" : "tally"}>{r.review ? (r.review.approved ? "Đã duyệt" : "Không duyệt") : r.qc.passed ? "Kiểm tra đạt" : "Kiểm tra không đạt"}</Tag>
                    <a className="flex items-center gap-1 text-[12.5px] text-mute hover:text-ink" href={r.url} target="_blank" rel="noreferrer"><Icon name="external" size={13} />Mở</a>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </div>
        <div className="grid gap-6">
          <Section title="Kịch bản" icon="edit" note={p.script ? `Phiên bản ${p.script.version}` : undefined}>
            <div className="panel max-h-80 overflow-y-auto bg-[#0d0e12] px-6 py-5 font-mono text-[12.5px] leading-relaxed">
              <p className="mb-4 text-center uppercase tracking-[0.2em] text-mute">{p.title}</p>
              {p.shots.length === 0 && <p className="text-center text-faint">Chưa có kịch bản.</p>}
              {p.shots.map((s, i) => <p key={s.shot_id} className="mb-2.5">{s.scene && s.scene !== p.shots[i - 1]?.scene && <span className="mb-1.5 mt-4 block font-semibold uppercase tracking-wide text-accent">{s.scene}</span>}<span className="mr-2 text-faint">{String(i + 1).padStart(2, "0")}</span>{s.text}{s.brief && <span className="block pl-7 text-faint">(hình: {s.brief})</span>}{s.selection?.status === "gap" && <span className="ml-2 text-cue">[thiếu hình]</span>}</p>)}
            </div>
          </Section>
          <Section title="Hoạt động" icon="pulse" note={<span className="mono">{(data?.cost ?? 0).toFixed(2)} USD{(data?.cost ?? 0) === 0 ? <span className="font-sans"> · mọi thứ chạy trên máy</span> : ""}</span>}>
            <ol className="panel max-h-[34rem] overflow-y-auto px-4 py-2">
              {feed.map((e, i) => (
                <li key={i} className="relative grid grid-cols-[14px_minmax(0,1fr)_auto] items-start gap-x-3 py-2 text-[13px]">
                  {i < feed.length - 1 && <span className="absolute bottom-0 left-[6.5px] top-5 w-px bg-line" />}
                  <span className={`relative mt-1.5 h-2 w-2 justify-self-center rounded-full ring-4 ring-surface ${tone(e.kind)}`} />
                  <span className="min-w-0"><span className={e.kind === "stage.waiting_review" || e.kind === "stage.blocked" ? "font-medium text-cue" : e.kind === "stage.failed" ? "font-medium text-tally" : "font-medium"}>{WORDS[e.kind]}</span>
                    <span className="text-mute">{e.stage_key ? ` · ${stageName(e.stage_key, e.pipeline).toLowerCase()}` : e.pipeline === "sourcing.match" ? " · chọn clip" : " · dựng video"}</span></span>
                  <span className="mono text-[11px] text-faint">{clock(e.at)}</span>
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
