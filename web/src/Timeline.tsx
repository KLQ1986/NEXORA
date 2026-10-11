import { useEffect, useMemo, useRef, useState } from "react";
import { post, timecode, type Candidate, type Project, type Shot } from "./api";
import { Button } from "./parts";

const ZOOMS = [1, 2, 4];
const estimate = (s: Shot) => (s.selection && s.selection.t_in != null && s.selection.t_out != null && s.selection.t_out > s.selection.t_in
  ? s.selection.t_out - s.selection.t_in : Math.max(2.5, s.text.split(/\s+/).length / 2.6));
const thumb = (s: Shot) => (s.selection && s.selection.status !== "gap" ? s.selection.frame_url ?? s.selection.asset?.thumbnail_url ?? s.keyframe_url : null);

/** The cut as an editor reads it: one row per kind of material, time running left to right, the playhead tied to the rendered video. */
export default function Timeline({ project: p, reload, rerender, busy }: { project: Project; reload: () => void; rerender: () => void; busy: boolean }) {
  const video = useRef<HTMLVideoElement>(null);
  const [now, setNow] = useState(0);
  const [picked, setPicked] = useState(0);
  const [zoom, setZoom] = useState(1);
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
  if (!p.shots.length) return <p className="max-w-xl text-mute">Chưa có kịch bản. Viết kịch bản ở thẻ Làm video, rồi quay lại đây để xem bản dựng theo thời gian.</p>;

  const pct = (t: number) => `${(t / total) * 100}%`;
  const sel = current.shot.selection;
  const act = async (path: string, body?: unknown) => { setNote(null); await post(`/api/v1/shots/${current.shot.shot_id}/${path}`, body).catch((e) => setNote((e as Error).message)); reload(); };
  const cropped = p.format !== "landscape";
  const seen = rendered?.[current.i]?.focus_x;
  const length = sel && sel.t_in != null && sel.t_out != null ? sel.t_out - sel.t_in : 0;
  const slip = (by: number) => { if (!sel || sel.t_in == null || sel.t_out == null) return; const a = Math.max(0, Math.min(sel.t_in + by, Math.max(0, (sel.asset?.duration ?? sel.t_out) - length))); act("trim", { t_in: a, t_out: a + length }); };
  const ticks = Array.from({ length: Math.floor(total / (total > 90 ? 15 : 5)) + 1 }, (_, k) => k * (total > 90 ? 15 : 5));
  const row = "relative h-9";
  const label = "flex h-9 items-center text-sm text-mute";

  return (
    <div className="grid max-w-7xl gap-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div>
          {rendered
            ? <video ref={video} key={latest.url} src={latest.url} controls onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)} className="max-h-[52vh] w-full rounded bg-black" />
            : <div className="grid aspect-video max-h-[52vh] w-full place-items-center rounded bg-surface p-6 text-center text-mute">{latest ? (latest.qc.shots ? "Kịch bản đã đổi sau bản dựng gần nhất. Dựng lại để xem." : "Bản dựng gần nhất được làm trước khi có màn hình này nên thiếu thông tin từng cảnh. Dựng lại để xem.") : "Chưa có bản dựng. Bên dưới là bố cục dự kiến theo các clip đang chọn."}</div>}
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <span className="tc text-lg">{timecode(now)} <span className="text-mute">/ {timecode(total)}</span></span>
            {rendered && <span className="text-mute">Đang ở câu {playing.i + 1}</span>}
            {stale > 0 && <span className="text-cue">{stale} cảnh đã đổi nhưng chưa dựng lại</span>}
            <span className="ml-auto" />
            {(stale > 0 || !rendered) && p.script?.match_approved && <Button kind="primary" disabled={busy} onClick={rerender}>{rendered ? "Dựng lại với thay đổi" : "Dựng video"}</Button>}
            <div className="flex gap-1" role="radiogroup" aria-label="Độ phóng của dòng thời gian">
              {ZOOMS.map((z) => <button key={z} type="button" role="radio" aria-checked={zoom === z} onClick={() => setZoom(z)} className={`tc rounded border px-2 py-1 text-sm ${zoom === z ? "border-ink bg-raised" : "border-line text-mute hover:text-ink"}`}>{z}×</button>)}
            </div>
          </div>
        </div>

        <aside aria-label="Cảnh đang chọn" className="min-w-0 border-l border-line pl-5">
          <p className="tc text-sm text-mute">Câu {current.i + 1} trên {items.length}, từ {timecode(current.at)}, dài {current.d.toFixed(1)} giây</p>
          <p className="mb-3 mt-1 text-base">{current.shot.text}</p>
          {current.gap
            ? <p className="text-cue">Câu này chưa có hình. Thêm hình ở thẻ Làm video.</p>
            : (
              <>
                <p className="break-words text-sm">{sel?.asset?.name}</p>
                {sel?.asset?.still
                  ? <p className="tc text-sm text-mute">Ảnh tĩnh, có chuyển động đẩy máy chậm</p>
                  : <p className="tc text-sm text-mute">Lấy từ {timecode(sel?.t_in)} đến {timecode(sel?.t_out)} trong clip gốc dài {timecode(sel?.asset?.duration)}</p>}
                {!sel?.asset?.still && (
                  <div className="mt-3">
                    <p className="mb-1 text-sm font-medium" id="slip">Trượt đoạn lấy trong clip gốc</p>
                    <div className="flex flex-wrap gap-1" role="group" aria-labelledby="slip">
                      {[[-2, "Sớm hơn 2 giây"], [-0.5, "Sớm hơn nửa giây"], [0.5, "Muộn hơn nửa giây"], [2, "Muộn hơn 2 giây"]].map(([by, name]) => (
                        <button key={name} type="button" onClick={() => slip(by as number)} className="rounded border border-line px-2 py-1 text-sm hover:border-mute">{name}</button>
                      ))}
                    </div>
                  </div>
                )}
                {sel?.reason && <p className="mt-3 break-words text-sm text-mute">Vì sao chọn: {sel.reason}</p>}
              </>
            )}
          {!current.gap && sel && sel.angles.length > 0 && (
            <div className="mt-4">
              <p className="mb-1 text-sm font-medium">Góc máy khác, cùng thời điểm</p>
              <div className="flex flex-wrap gap-1">{sel.angles.map((a) => <button key={a.asset_id} type="button" onClick={() => act("angle", { asset_id: a.asset_id })} className="rounded border border-line px-2 py-1 text-sm hover:border-mute">{a.name} ở {timecode(a.t_in)}</button>)}</div>
            </div>
          )}
          {!current.gap && cropped && (
            <div className="mt-4">
              <p className="mb-1 text-sm font-medium" id="focus">Giữ phần nào của hình khi cắt khung</p>
              <div className="flex flex-wrap gap-1" role="radiogroup" aria-labelledby="focus">
                {([[null, "Hệ thống tự chọn"], [0.15, "Bên trái"], [0.5, "Chính giữa"], [0.85, "Bên phải"]] as const).map(([x, name]) => (
                  <button key={name} type="button" role="radio" aria-checked={(sel?.focus_x ?? null) === x} onClick={() => act("focus", { x })}
                          className={`rounded border px-2 py-1 text-sm ${(sel?.focus_x ?? null) === x ? "border-ink bg-raised" : "border-line text-mute hover:text-ink"}`}>{name}</button>
                ))}
              </div>
              {sel?.focus_x == null && seen != null && <p className="tc mt-1 text-sm text-mute">Bản dựng gần nhất lấy quanh điểm {Math.round(seen * 100)}% tính từ mép trái.</p>}
            </div>
          )}
          {!current.gap && (
            <div className="mt-4">
              <p className="mb-1 text-sm font-medium">Chèn hình khác khi nói tới một từ</p>
              {(sel?.inserts ?? []).map((ins) => (
                <p key={ins.keyword} className="mb-1 flex items-baseline justify-between gap-2 text-sm"><span className="min-w-0 truncate" title={ins.reason}>Tới “{ins.keyword}” thì chuyển hình</span>
                  <button type="button" className="shrink-0 text-mute underline underline-offset-2 hover:text-ink" onClick={() => act("inserts/remove", { keyword: ins.keyword })}>Bỏ</button></p>
              ))}
              <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (word.trim()) { await act("inserts", { keyword: word.trim() }); setWord(""); } }}>
                <label htmlFor="word" className="sr-only">Từ trong câu</label>
                <input id="word" value={word} onChange={(e) => setWord(e.target.value)} placeholder="Một từ có trong câu" className="min-w-0 flex-1 rounded border border-line bg-canvas px-2 py-1 text-sm placeholder:text-mute/70" />
                <button type="submit" disabled={!word.trim()} className="rounded border border-line px-2 py-1 text-sm hover:border-mute disabled:opacity-40">Tìm và chèn</button>
              </form>
            </div>
          )}
          {note && <p className="mt-2 text-sm text-tally">{note}</p>}
          {sel && sel.alternates.length > 0 && (
            <div className="mt-4">
              <p className="mb-1 text-sm font-medium">Đổi sang cảnh khác</p>
              <ul className="grid grid-cols-3 gap-2">
                {sel.alternates.slice(0, 6).map((a: Candidate, k: number) => (
                  <li key={a.moment_id}><button type="button" title={a.reason} onClick={() => act("swap", { alternate: k })} className="group block w-full text-left">
                    <img src={a.frame_url} alt="" className="aspect-video w-full rounded-sm bg-black object-cover opacity-80 group-hover:opacity-100" />
                    <span className="tc block truncate text-xs text-mute group-hover:text-ink">{timecode(a.t_in)}</span></button></li>
                ))}
              </ul>
            </div>
          )}
          {findings.filter((f) => f.shot === current.i + 1).map((f, k) => (
            <div key={k} className="mt-4 border-l-2 border-cue pl-3"><p>{f.check}: {f.text}</p><p className="text-sm text-mute">{f.fix}</p></div>
          ))}
          {current.stale && <p className="mt-4 text-sm text-cue">Cảnh này đã đổi sau bản dựng gần nhất. Video phía trên vẫn là bản cũ.</p>}
        </aside>
      </div>

      <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-3">
        <div className="pt-5">
          <p className={`${label} h-16`}>Hình</p><p className={label}>Lời dẫn</p><p className={label}>Phụ đề</p><p className={label}>Nhạc</p>
        </div>
        <div className="overflow-x-auto pb-2">
          <div className="relative" style={{ width: `${zoom * 100}%` }}
               onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); const t = ((e.clientX - r.left) / r.width) * total; setPicked(at(t).i); seek(t); }}>
            <div className="tc relative h-5 text-[11px] text-mute">
              {ticks.map((t) => <span key={t} className="absolute border-l border-line pl-1" style={{ left: pct(t) }}>{timecode(t)}</span>)}
            </div>
            <div className="relative h-16" role="list" aria-label="Hình theo thời gian">
              {items.map((it) => {
                const src = thumb(it.shot);
                const flagged = findings.some((f) => f.shot === it.i + 1);
                return (
                  <button key={it.shot.shot_id} type="button" role="listitem" aria-current={it.i === current.i} title={`${it.i + 1}. ${it.shot.text}`}
                          onClick={(e) => { e.stopPropagation(); choose(it.i); }} style={{ left: pct(it.at), width: pct(it.d) }}
                          className={`absolute inset-y-0 overflow-hidden border-r border-canvas ${it.gap ? "hatch bg-raised" : "bg-black"} ${it.i === current.i ? "z-10 outline outline-2 -outline-offset-2 outline-ink" : ""}`}>
                    {src && <img src={src} alt="" className="h-full w-full object-cover opacity-90" />}
                    <span className="tc absolute left-1 top-0.5 rounded-sm bg-canvas/80 px-1 text-[11px]">{it.i + 1}</span>
                    {(it.shot.selection?.inserts ?? []).map((ins) => <span key={ins.keyword} className="absolute inset-y-0 w-px bg-ink" style={{ left: `${ins.at * 100}%` }} title={`Chuyển hình ở “${ins.keyword}”`} />)}
                    {(flagged || it.stale) && <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-cue" title={it.stale ? "Đã đổi, chưa dựng lại" : "Nên xem lại"} />}
                  </button>
                );
              })}
            </div>
            <div className={row}>
              {items.map((it) => <div key={it.shot.shot_id} style={{ left: pct(it.at), width: pct(it.d) }} title={it.own ? "Giọng bạn thu" : "Giọng máy"}
                                      className={`absolute inset-y-1 truncate border-r border-canvas px-1.5 text-xs leading-7 ${it.own ? "bg-proof/30" : "bg-raised"}`}>{it.own ? "Giọng bạn" : "Giọng máy"}</div>)}
            </div>
            <div className={row}>
              {items.map((it) => <div key={it.shot.shot_id} style={{ left: pct(it.at), width: pct(it.d) }} className="absolute inset-y-1 truncate border-r border-canvas bg-surface px-1.5 text-xs leading-7">{it.shot.text}</div>)}
            </div>
            <div className={row}>
              {p.music_path
                ? <div className="absolute inset-x-0 inset-y-1 truncate bg-surface px-1.5 text-xs leading-7">{p.music_path.split("/").pop()}, tự nhỏ lại khi có lời dẫn</div>
                : <div className="absolute inset-x-0 inset-y-1 truncate border border-dashed border-line px-1.5 text-xs leading-7 text-mute">Không có nhạc nền</div>}
            </div>
            {rendered && <div className="pointer-events-none absolute bottom-0 top-5 z-20 w-0.5 bg-cue" style={{ left: pct(now) }} />}
          </div>
        </div>
      </div>
      <p className="text-sm text-mute">Bấm vào một cảnh để chọn. Phím mũi tên trái, phải để sang cảnh kề bên; phím cách để phát hoặc dừng.</p>
    </div>
  );
}
