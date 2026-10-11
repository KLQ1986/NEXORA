import { useEffect, useMemo, useRef, useState } from "react";
import { post, timecode, type Candidate, type Project, type Shot } from "./api";
import { Button, Icon, Seg, Tag } from "./parts";

const ZOOMS = [[1, "1×"], [2, "2×"], [4, "4×"]] as const;
const estimate = (s: Shot) => (s.selection && s.selection.t_in != null && s.selection.t_out != null && s.selection.t_out > s.selection.t_in
  ? s.selection.t_out - s.selection.t_in : Math.max(2.5, s.text.split(/\s+/).length / 2.6));
const thumb = (s: Shot) => (s.selection && s.selection.status !== "gap" ? s.selection.frame_url ?? s.selection.asset?.thumbnail_url ?? s.keyframe_url : null);
/** A drawn voice envelope: not measured, just a sign that this lane carries speech. Stable per shot. */
function Wave({ seed }: { seed: number }) {
  const bars = Array.from({ length: 64 }, (_, k) => 0.25 + 0.75 * Math.abs(Math.sin(k * 0.9 + seed * 2.3) * Math.cos(k * 0.37 + seed)));
  return <svg className="h-5 w-full min-w-0 opacity-70" preserveAspectRatio="none" viewBox="0 0 128 20" aria-hidden="true">{bars.map((h, k) => <rect key={k} x={k * 2} y={10 - h * 9} width="1.2" height={h * 18} rx="0.6" fill="currentColor" />)}</svg>;
}
const chipBtn = "inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-2.5 text-[12.5px] transition-colors hover:border-edge hover:bg-overlay disabled:opacity-40";

/** The cut as an editor reads it: one track per kind of material, time running left to right, the playhead tied to the rendered video. */
export default function Timeline({ project: p, reload, rerender, busy }: { project: Project; reload: () => void; rerender: () => void; busy: boolean }) {
  const video = useRef<HTMLVideoElement>(null);
  const [now, setNow] = useState(0);
  const [picked, setPicked] = useState(0);
  const [zoom, setZoom] = useState<number>(1);
  const [word, setWord] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const latest = p.renders[0];
  // A render describes the script it was made from. After the script changes, its timings no longer apply.
  const rendered = latest && latest.qc.shots && latest.qc.shots.length === p.shots.length && latest.qc.shots.every((r, i) => r.text === p.shots[i].text) ? latest.qc.shots : null;
  const items = useMemo(() => {
    let at = 0;
    return p.shots.map((shot, i) => {
      const r = rendered?.[i];
      const d = r?.duration ?? estimate(shot);
      const sel = shot.selection;
      const gap = !sel || sel.status === "gap";
      const words = (list?: { keyword: string }[]) => (list ?? []).map((x) => x.keyword).join("|");
      const stale = !!r && (gap !== r.gap || (!gap && (sel!.asset?.asset_id !== r.asset_id || Math.abs((sel!.t_in ?? 0) - (r.t_in ?? 0)) > 0.05
        || words(sel!.inserts) !== words(r.inserts) || (sel!.focus_x != null && sel!.focus_x !== r.focus_x))));
      const item = { shot, i, at, d, gap, stale, own: r ? !!r.own_voice : p.own_takes.includes(i + 1) };
      at += d;
      return item;
    });
  }, [p.shots, rendered, p.own_takes]);
  const total = items.reduce((sum, it) => sum + it.d, 0) || 1;
  const stale = items.filter((it) => it.stale).length;
  const findings = rendered ? latest.qc.findings ?? [] : [];
  const current = items[Math.min(picked, items.length - 1)];
  const at = (t: number) => items.reduce((hit, it) => (t >= it.at ? it : hit), items[0]);
  const playing = at(now);

  const seek = (t: number) => { const v = video.current; if (v && rendered) { v.currentTime = Math.max(0, Math.min(t, total - 0.05)); setNow(v.currentTime); } };
  const choose = (i: number) => { setPicked(i); seek(items[i].at + 0.02); };
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const on = e.target instanceof Element ? e.target : null;
      if (on?.closest("input, textarea, select, video") || (e.key === " " && on?.closest("button"))) return;       // typing, and pressing a focused button, keep their meaning
      if (e.key === "ArrowRight") { e.preventDefault(); choose(Math.min(items.length - 1, picked + 1)); }
      if (e.key === "ArrowLeft") { e.preventDefault(); choose(Math.max(0, picked - 1)); }
      if (e.key === " ") { e.preventDefault(); const v = video.current; if (v) v.paused ? v.play() : v.pause(); }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });
  if (!p.shots.length) return <p className="panel max-w-xl px-5 py-6 text-mute">Chưa có kịch bản. Viết kịch bản ở thẻ Làm video, rồi quay lại đây để xem bản dựng theo thời gian.</p>;

  const pct = (t: number) => `${(t / total) * 100}%`;
  const sel = current.shot.selection;
  const act = async (path: string, body?: unknown) => { setNote(null); await post(`/api/v1/shots/${current.shot.shot_id}/${path}`, body).catch((e) => setNote((e as Error).message)); reload(); };
  const cropped = p.format !== "landscape";
  const move = async (by: number) => { const ids = p.shots.map((s) => s.shot_id); const j = current.i + by; [ids[current.i], ids[j]] = [ids[j], ids[current.i]]; setNote(null); await post(`/api/v1/projects/${p.project_id}/reorder`, { shot_ids: ids }).catch((e) => setNote((e as Error).message)); setPicked(j); reload(); };
  const seen = rendered?.[current.i]?.focus_x;
  const length = sel && sel.t_in != null && sel.t_out != null ? sel.t_out - sel.t_in : 0;
  const slip = (by: number) => { if (!sel || sel.t_in == null || sel.t_out == null) return; const a = Math.max(0, Math.min(sel.t_in + by, Math.max(0, (sel.asset?.duration ?? sel.t_out) - length))); act("trim", { t_in: a, t_out: a + length }); };
  const ticks = Array.from({ length: Math.floor(total / (total > 90 ? 15 : 5)) + 1 }, (_, k) => k * (total > 90 ? 15 : 5));
  const TRACKS = [["Hình", "film", "h-[72px]"], ["Lời dẫn", "mic", "h-10"], ["Phụ đề", "captions", "h-10"], ["Nhạc", "music", "h-10"]] as const;
  const head = "eyebrow mb-2";

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 lg:h-[min(54vh,600px)] lg:grid-cols-[minmax(0,1fr)_390px]">
        <div className="panel flex min-h-0 flex-col overflow-hidden">
          <div className="relative flex min-h-0 flex-1 bg-black">
            {rendered
              ? <video ref={video} key={latest.url} src={latest.url} controls onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)} className="min-h-0 w-full flex-1 object-contain" />
              : <div className="grid min-h-[240px] w-full flex-1 place-items-center p-6 text-center text-mute"><span className="flex max-w-md flex-col items-center gap-2"><Icon name="play" size={26} className="text-faint" />{latest ? (latest.qc.shots ? "Kịch bản đã đổi sau bản dựng gần nhất. Dựng lại để xem." : "Bản dựng gần nhất được làm trước khi có màn hình này nên thiếu thông tin từng cảnh. Dựng lại để xem.") : "Chưa có bản dựng. Bên dưới là bố cục dự kiến theo các clip đang chọn."}</span></div>}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-3 border-t border-line px-4 py-2.5">
            <span className="mono text-[17px] font-medium">{timecode(now)} <span className="text-faint">/ {timecode(total)}</span></span>
            {rendered && <span className="text-[13px] text-mute">Câu {playing.i + 1}</span>}
            {stale > 0 && <Tag tone="cue">{stale} cảnh đổi, chưa dựng lại</Tag>}
            <span className="ml-auto" />
            {(stale > 0 || !rendered) && p.script?.match_approved && <Button kind="primary" size="sm" disabled={busy} onClick={rerender}><Icon name="scissors" size={14} />{rendered ? "Dựng lại với thay đổi" : "Dựng video"}</Button>}
            <Seg label="Độ phóng của dòng thời gian" value={zoom} onChange={setZoom} items={ZOOMS} />
          </div>
        </div>

        <aside aria-label="Cảnh đang chọn" className="panel min-h-0 min-w-0 overflow-y-auto">
          <div className="sticky top-0 z-10 border-b border-line bg-surface/95 px-4 py-3 backdrop-blur">
            <div className="flex items-center justify-between gap-2"><span className="eyebrow">Inspector · Câu {current.i + 1}/{items.length}</span>
              <span className="mono text-[11.5px] text-faint">{timecode(current.at)} · {current.d.toFixed(1)}s</span></div>
            <p className="mt-1.5 text-[14.5px] leading-snug">{current.shot.text}</p>
          </div>
          <div className="grid gap-5 p-4">
            {current.gap
              ? <p className="rounded-lg border border-cue/30 bg-cue/5 px-3 py-2 text-[13px] text-cue">Câu này chưa có hình. Thêm hình ở thẻ Làm video.</p>
              : (
                <div>
                  <p className="flex items-center gap-2 break-words text-[13px]"><Icon name="film" size={14} className="text-faint" />{sel?.asset?.name}</p>
                  <p className="mono mt-0.5 text-[12px] text-mute">{sel?.asset?.still ? "Ảnh tĩnh, đẩy máy chậm" : `${timecode(sel?.t_in)} → ${timecode(sel?.t_out)} trong clip ${timecode(sel?.asset?.duration)}`}</p>
                  {!sel?.asset?.still && (
                    <div className="mt-3">
                      <p className={head} id="slip">Trượt đoạn lấy</p>
                      <div className="flex flex-wrap gap-1.5" role="group" aria-labelledby="slip">
                        {[[-2, "−2s"], [-0.5, "−0.5s"], [0.5, "+0.5s"], [2, "+2s"]].map(([by, name]) => (
                          <button key={name} type="button" onClick={() => slip(by as number)} className={`${chipBtn} mono`} title={(by as number) < 0 ? "Lấy sớm hơn" : "Lấy muộn hơn"}>{name}</button>
                        ))}
                      </div>
                    </div>
                  )}
                  {sel?.reason && <details className="ai-card group mt-3 px-3 py-2 text-[12.5px]"><summary className="flex cursor-pointer list-none gap-2"><Icon name="sparkles" size={13} className="mt-0.5 text-ai" /><span className="line-clamp-3 text-mute group-open:line-clamp-none"><span className="font-medium text-ai">Vì sao chọn </span>{sel.reason}</span></summary></details>}
                </div>
              )}
            {!current.gap && sel && sel.angles.length > 0 && (
              <div>
                <p className={head}>Góc máy khác, cùng thời điểm</p>
                <div className="flex flex-wrap gap-1.5">{sel.angles.map((a) => <button key={a.asset_id} type="button" onClick={() => act("angle", { asset_id: a.asset_id })} className={chipBtn}>{a.name} <span className="mono text-faint">{timecode(a.t_in)}</span></button>)}</div>
              </div>
            )}
            {!current.gap && cropped && (
              <div>
                <p className={head} id="focus">Giữ phần nào khi cắt khung</p>
                <div className="seg flex-wrap" role="radiogroup" aria-labelledby="focus">
                  {([[null, "Tự chọn"], [0.15, "Trái"], [0.5, "Giữa"], [0.85, "Phải"]] as const).map(([x, name]) => (
                    <button key={name} type="button" role="radio" aria-checked={(sel?.focus_x ?? null) === x} onClick={() => act("focus", { x })}>{name}</button>
                  ))}
                </div>
                {sel?.focus_x == null && seen != null && <p className="mono mt-1.5 text-[12px] text-mute">Bản dựng gần nhất lấy quanh điểm {Math.round(seen * 100)}% từ mép trái.</p>}
              </div>
            )}
            {!current.gap && (
              <div>
                <p className={head}>Chèn hình khác khi nói tới một từ</p>
                {(sel?.inserts ?? []).map((ins) => (
                  <p key={ins.keyword} className="mb-1.5 flex items-baseline justify-between gap-2 text-[13px]"><span className="min-w-0 truncate" title={ins.reason}>Tới “{ins.keyword}” thì chuyển hình</span>
                    <button type="button" className="link shrink-0" onClick={() => act("inserts/remove", { keyword: ins.keyword })}>Bỏ</button></p>
                ))}
                <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (word.trim()) { await act("inserts", { keyword: word.trim() }); setWord(""); } }}>
                  <label htmlFor="word" className="sr-only">Từ trong câu</label>
                  <input id="word" value={word} onChange={(e) => setWord(e.target.value)} placeholder="Một từ có trong câu" className="h-8 min-w-0 flex-1 px-2.5 text-[13px]" />
                  <button type="submit" disabled={!word.trim()} className={chipBtn}>Tìm và chèn</button>
                </form>
              </div>
            )}
            {note && <p className="text-[13px] text-tally">{note}</p>}
            {sel && sel.alternates.length > 0 && (
              <div>
                <p className={head}>Đổi sang cảnh khác</p>
                <ul className="grid grid-cols-3 gap-2">
                  {sel.alternates.slice(0, 6).map((a: Candidate, k: number) => (
                    <li key={a.moment_id}><button type="button" title={a.reason} onClick={() => act("swap", { alternate: k })} className="group block w-full text-left">
                      <span className="relative block overflow-hidden rounded-md ring-1 ring-line group-hover:ring-accent"><img src={a.frame_url} alt="" className="aspect-video w-full bg-black object-cover opacity-75 group-hover:opacity-100" />
                        <span className="chip mono absolute bottom-1 left-1 !h-4 !px-1 !text-[9.5px]">{timecode(a.t_in)}</span></span></button></li>
                  ))}
                </ul>
              </div>
            )}
            {findings.filter((f) => f.shot === current.i + 1).map((f, k) => (
              <div key={k} className="rounded-lg border-l-2 border-cue bg-cue/5 py-2 pl-3 pr-2 text-[13px]"><p>{f.check}: {f.text}</p><p className="text-mute">{f.fix}</p></div>
            ))}
            {items.length > 1 && (
              <div>
                <p className={head} id="move">Đổi vị trí câu</p>
                <div className="flex gap-1.5" role="group" aria-labelledby="move">
                  <button type="button" disabled={current.i === 0} onClick={() => move(-1)} className={chipBtn}><Icon name="back" size={13} />Lên trước</button>
                  <button type="button" disabled={current.i === items.length - 1} onClick={() => move(1)} className={chipBtn}>Lùi sau<Icon name="next" size={13} /></button>
                </div>
              </div>
            )}
            {current.stale && <p className="text-[13px] text-cue">Cảnh này đã đổi sau bản dựng gần nhất. Video phía trên vẫn là bản cũ.</p>}
          </div>
        </aside>
      </div>

      <div className="panel grid grid-cols-[112px_minmax(0,1fr)] overflow-hidden">
        <div className="border-r border-line bg-raised/40">
          <div className="h-7 border-b border-line" />
          {TRACKS.map(([name, icon, h]) => <p key={name} className={`flex items-center gap-2 border-b border-line px-3 text-[12.5px] text-mute last:border-b-0 ${h}`}><Icon name={icon} size={14} className="text-faint" />{name}</p>)}
        </div>
        <div className="overflow-x-auto">
          <div className="relative" style={{ width: `${zoom * 100}%` }}
               onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); const t = ((e.clientX - r.left) / r.width) * total; setPicked(at(t).i); seek(t); }}>
            <div className="mono relative h-7 border-b border-line bg-raised/30 text-[10px] text-faint">
              {ticks.map((t) => <span key={t} className="absolute top-0 h-full border-l border-edge pl-1 pt-1.5" style={{ left: pct(t) }}>{timecode(t)}</span>)}
            </div>
            <div className="relative h-[72px] border-b border-line" role="list" aria-label="Hình theo thời gian">
              {items.map((it) => {
                const src = thumb(it.shot);
                const flagged = findings.some((f) => f.shot === it.i + 1);
                return (
                  <button key={it.shot.shot_id} type="button" role="listitem" aria-current={it.i === current.i} title={`${it.i + 1}. ${it.shot.text}`}
                          onClick={(e) => { e.stopPropagation(); choose(it.i); }} style={{ left: pct(it.at), width: pct(it.d) }}
                          className={`absolute inset-y-1.5 overflow-hidden rounded-md border-x border-canvas ${it.gap ? "hatch-cue bg-raised" : "bg-black"} ${it.i === current.i ? "z-10 ring-2 ring-accent shadow-[0_0_16px_-2px_var(--color-accent)]" : ""}`}>
                    {src && <img src={src} alt="" className="h-full w-full object-cover opacity-90" />}
                    <span className="mono absolute left-1 top-1 rounded bg-black/70 px-1 text-[10px]">{it.i + 1}</span>
                    {(it.shot.selection?.inserts ?? []).map((ins) => <span key={ins.keyword} className="absolute inset-y-0 w-0.5 bg-ai" style={{ left: `${ins.at * 100}%` }} title={`Chuyển hình ở “${ins.keyword}”`} />)}
                    {(flagged || it.stale) && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-cue ring-2 ring-black/50" title={it.stale ? "Đã đổi, chưa dựng lại" : "Nên xem lại"} />}
                  </button>
                );
              })}
            </div>
            <div className="relative h-10 border-b border-line">
              {items.map((it) => <div key={it.shot.shot_id} style={{ left: pct(it.at), width: pct(it.d) }} title={it.own ? "Giọng bạn thu" : "Giọng máy"}
                                      className={`absolute inset-y-1.5 flex items-center gap-1 overflow-hidden rounded border-x border-canvas px-1.5 text-[11px] ${it.own ? "bg-proof/25 text-proof" : "bg-ai/15 text-ai"}`}>
                <Wave seed={it.i} />
              </div>)}
            </div>
            <div className="relative h-10 border-b border-line">
              {items.map((it) => <div key={it.shot.shot_id} style={{ left: pct(it.at), width: pct(it.d) }} className="absolute inset-y-1.5 truncate rounded border-x border-canvas bg-accent/20 px-1.5 text-[11px] leading-7 text-ink/90">{it.shot.text}</div>)}
            </div>
            <div className="relative h-10">
              {p.music_path
                ? <div className="absolute inset-x-0 inset-y-1.5 truncate rounded bg-[#4f7cff]/20 px-2 text-[11px] leading-7 text-[#9db4ff]">♪ {p.music_path.split("/").pop()} · tự nhỏ lại khi có lời dẫn</div>
                : <div className="absolute inset-x-0 inset-y-1.5 truncate rounded border border-dashed border-line px-2 text-[11px] leading-6 text-faint">Không có nhạc nền</div>}
            </div>
            {rendered && <div className="pointer-events-none absolute bottom-0 top-0 z-20 w-px bg-cue shadow-[0_0_8px_var(--color-cue)]" style={{ left: pct(now) }}><span className="absolute -left-[5px] top-0 h-0 w-0 border-x-[5px] border-t-[7px] border-x-transparent border-t-cue" /></div>}
          </div>
        </div>
      </div>
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-faint"><span>Bấm vào một cảnh để chọn</span><span><kbd className="mono rounded border border-line px-1">←</kbd> <kbd className="mono rounded border border-line px-1">→</kbd> sang cảnh kề bên</span><span><kbd className="mono rounded border border-line px-1">Space</kbd> phát / dừng</span></p>
    </div>
  );
}
