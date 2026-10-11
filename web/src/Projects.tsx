import { useEffect, useRef, useState } from "react";
import { post, timecode, usePoll, type Candidate, type Project, type RenderItem, type Shot } from "./api";
import Board from "./Board";
import { Button, StageRail } from "./parts";

function Clip({ url, tIn, tOut, poster }: { url: string | null; tIn: number; tOut: number; poster: string | null }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => { const v = ref.current; if (!v) return; const tick = () => { if (v.currentTime >= tOut) v.currentTime = tIn; }; v.addEventListener("timeupdate", tick); return () => v.removeEventListener("timeupdate", tick); }, [tIn, tOut, url]);
  if (!url) return poster ? <img src={poster} alt="" className="aspect-video w-full rounded-sm bg-black object-cover" /> : <div className="aspect-video w-full rounded-sm bg-raised" />;
  return <video ref={ref} key={`${url}${tIn}`} src={`${url}#t=${tIn},${tOut}`} poster={poster ?? undefined} muted playsInline controls preload="metadata" className="aspect-video w-full rounded-sm bg-black" />;
}

function ShotRow({ shot, n, locked, changed }: { shot: Shot; n: number; locked: boolean; changed: () => void }) {
  const sel = shot.selection;
  const act = async (path: string, body?: unknown) => { await post(`/api/v1/shots/${shot.shot_id}/${path}`, body).catch(() => {}); changed(); };
  return (
    <li className="grid gap-4 py-4 md:grid-cols-[2rem_minmax(0,1fr)_280px]">
      <span className="tc text-mute">{n}</span>
      <div className="min-w-0">
        <p className="text-base">{shot.text}</p>
        {!sel && <p className="mt-1 text-sm text-mute">Chưa tìm clip cho câu này.</p>}
        {sel?.status === "gap" && <p className="mt-1 text-sm text-cue">Chưa có hình cho câu này. Video sẽ hiện một nền trơn kèm phụ đề, cho tới khi bạn quay thêm, thêm footage, hoặc sửa câu.</p>}
        {sel && sel.status !== "gap" && <p className="mt-1 text-sm text-mute">Vì sao chọn: {sel.reason}</p>}
        {sel && sel.alternates.length > 0 && !locked && (
          <div className="mt-3">
            <p className="mb-1 text-sm text-mute">Phương án khác</p>
            <ul className="flex flex-wrap gap-2">
              {sel.alternates.map((a: Candidate, i: number) => (
                <li key={a.moment_id} className="w-32">
                  <button type="button" onClick={() => act("swap", { alternate: i })} title={a.reason} className="group block w-full text-left">
                    <img src={a.frame_url} alt="" className="aspect-video w-full rounded-sm bg-black object-cover opacity-80 group-hover:opacity-100" />
                    <span className="tc block truncate text-xs text-mute group-hover:text-ink">Dùng cảnh ở {timecode(a.t_in)}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {sel && sel.status !== "gap" && !locked && <button type="button" className="mt-2 text-sm text-mute underline decoration-line underline-offset-2 hover:text-ink" onClick={() => act("gap")}>Không clip nào hợp</button>}
      </div>
      <div>
        {sel && sel.status !== "gap" && sel.asset && sel.t_in != null && sel.t_out != null ? (
          <>
            <Clip url={sel.asset.proxy_url} tIn={sel.t_in} tOut={sel.t_out} poster={sel.frame_url} />
            <p className="tc mt-1 truncate text-xs text-mute">{sel.asset.name}, {timecode(sel.t_in)} đến {timecode(sel.t_out)}{sel.decided_by === "operator" ? ", bạn chọn" : ""}</p>
          </>
        ) : <div className={`grid aspect-video place-items-center rounded-sm text-sm ${sel?.status === "gap" ? "border border-dashed border-cue text-cue" : "bg-raised text-mute"}`}>{sel?.status === "gap" ? "Thiếu hình" : "Chưa có clip"}</div>}
      </div>
    </li>
  );
}

const FORMATS: Record<string, string> = { landscape: "Ngang 16:9", portrait: "Dọc 9:16", square: "Vuông 1:1" };

/** The cut laid out to scale: one block per shot, as wide as it lasts. */
function TimelineStrip({ shots }: { shots: Shot[] }) {
  const items = shots.map((s) => ({ s, d: s.selection && s.selection.t_in != null && s.selection.t_out != null ? s.selection.t_out - s.selection.t_in : Math.max(2.5, s.text.split(/\s+/).length / 2.6) }));
  const total = items.reduce((sum, i) => sum + i.d, 0) || 1;
  let t = 0;
  return (
    <div>
      <div className="flex h-16 gap-px overflow-hidden rounded-sm" role="list" aria-label="Bản dựng theo thời gian">
        {items.map(({ s, d }, i) => (
          <div key={s.shot_id} role="listitem" title={`${i + 1}. ${s.text}`} style={{ width: `${(d / total) * 100}%` }}
               className={`relative min-w-0 ${s.selection?.status === "gap" || !s.selection ? "hatch bg-raised" : "bg-black"}`}>
            {s.selection?.frame_url && s.selection.status !== "gap" && <img src={s.selection.frame_url} alt="" className="h-full w-full object-cover opacity-90" />}
            <span className="tc absolute left-1 top-0.5 rounded-sm bg-canvas/80 px-1 text-[11px]">{i + 1}</span>
          </div>
        ))}
      </div>
      <div className="tc mt-1 flex text-[11px] text-mute">
        {items.map(({ s, d }) => { const at = t; t += d; return <span key={s.shot_id} style={{ width: `${(d / total) * 100}%` }} className="truncate">{timecode(at)}</span>; })}
        <span className="ml-auto pl-1">{timecode(total)}</span>
      </div>
    </div>
  );
}

function PackagePanel({ render, reload }: { render: RenderItem; reload: () => void }) {
  const pkg = render.package;
  const base = `/api/v1/renders/${render.render_id}/package`;
  if (!pkg) return <div><Button kind="primary" onClick={async () => { await post(base, {}); reload(); }}>Chuẩn bị gói xuất bản</Button><p className="mt-1 text-sm text-mute">Tạo file video, phụ đề rời và ảnh đại diện trong một thư mục để bạn đăng tay.</p></div>;
  return (
    <div>
      <h3 className="mb-1 font-semibold">Gói xuất bản</h3>
      <p className="mb-2 text-sm text-mute">Chọn ảnh đại diện. Mọi file nằm trong thư mục <span className="break-all">{pkg.folder}</span></p>
      <div className="mb-2 flex gap-2">
        {pkg.thumbnails.map((name) => (
          <button key={name} type="button" aria-pressed={pkg.thumbnail === name} onClick={async () => { await post(base, { thumbnail: name }); reload(); }}
                  className={`w-36 rounded-sm border-2 ${pkg.thumbnail === name ? "border-cue" : "border-transparent opacity-70 hover:opacity-100"}`}>
            <img src={`${base}/${name}`} alt="Ảnh đại diện ứng viên" className="aspect-video w-full rounded-sm object-cover" />
          </button>
        ))}
      </div>
      <p className="font-medium">{pkg.title}</p>
      <p className="mb-2 line-clamp-3 text-sm text-mute">{pkg.description}</p>
      <p className="flex flex-wrap gap-4 text-sm"><a className="underline" href={`${base}/${pkg.video}`} download>Tải video</a><a className="underline" href={`${base}/${pkg.captions}`} download>Tải phụ đề (SRT)</a><a className="underline" href={`${base}/${pkg.thumbnail}`} download>Tải ảnh đại diện</a></p>
    </div>
  );
}

const STEPS = ["Kịch bản", "Chọn clip", "Duyệt clip", "Dựng video", "Duyệt bản dựng"];

function Detail({ id, back }: { id: string; back: () => void }) {
  const { data: p, reload } = usePoll<Project>(`/api/v1/projects/${id}`, 2500);
  const [text, setText] = useState<string | null>(null);
  const [topic, setTopic] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"work" | "board">("work");
  const [music, setMusic] = useState<string | null>(null);
  useEffect(() => { if (p && text === null) setText(p.shots.map((s) => s.text).join("\n")); }, [p, text]);
  if (!p) return <section className="p-6 text-mute">Đang mở dự án</section>;
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setNote(null); try { await fn(); } catch (e) { setNote((e as Error).message); } setBusy(false); reload(); };
  const saved = p.shots.map((s) => s.text).join("\n");
  const dirty = text !== null && text.trim() !== saved.trim();
  const matching = p.match && ["queued", "running"].includes(p.match.status);
  const reviewing = p.match?.status === "waiting_review";
  const approved = !!p.script?.match_approved;
  const rendering = p.render && ["queued", "running"].includes(p.render.status);
  const latest = p.renders.find((r) => true);
  const renderReview = p.render?.status === "waiting_review";
  const step = !p.script ? 0 : !p.match ? 1 : matching ? 1 : reviewing ? 2 : !approved ? 1 : !p.render || rendering ? 3 : renderReview ? 4 : 5;
  const gaps = p.shots.filter((s) => s.selection?.status === "gap").length;
  return (
    <section className="flex-1 overflow-y-auto p-6">
      <button type="button" onClick={back} className="mb-2 text-sm text-mute hover:text-ink">Tất cả dự án</button>
      <h1 className="mb-4 text-2xl font-semibold tracking-tight">{p.title}</h1>
      <ol className="mb-8 grid max-w-4xl grid-cols-5 gap-1" aria-label="Các bước làm video">
        {STEPS.map((label, i) => (
          <li key={label} aria-current={i === step ? "step" : undefined}>
            <div className={`h-1.5 rounded-full ${i < step ? "bg-proof" : i === step ? ((i === 2 || i === 4) ? "bg-cue" : "bg-ink") : "bg-line"}`} />
            <p className={`mt-1 text-sm ${i === step ? "font-medium" : "text-mute"}`}>{label}</p>
          </li>
        ))}
      </ol>
      {note && <p className="mb-4 text-tally">{note}</p>}
      <div className="mb-6 flex gap-1 border-b border-line" role="tablist">
        {([["work", "Làm video"], ["board", "Bảng theo dõi"]] as const).map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
                  className={`-mb-px border-b-2 px-3 py-2 ${tab === key ? "border-ink font-medium" : "border-transparent text-mute hover:text-ink"}`}>{label}</button>
        ))}
      </div>
      {tab === "board" && <Board project={p} />}

      <div className={`grid max-w-6xl gap-10 ${tab === "board" ? "hidden" : ""}`}>
        <div className="flex flex-wrap items-end gap-6">
          <div>
            <p className="mb-1 font-medium" id="format-label">Khung hình</p>
            <div className="flex gap-1" role="radiogroup" aria-labelledby="format-label">
              {Object.entries(FORMATS).map(([key, label]) => (
                <button key={key} type="button" role="radio" aria-checked={p.format === key} disabled={busy}
                        onClick={() => run(() => post(`/api/v1/projects/${id}`, { format: key }, "PATCH"))}
                        className={`rounded border px-3 py-1.5 text-sm ${p.format === key ? "border-ink bg-raised font-medium" : "border-line text-mute hover:text-ink"}`}>{label}</button>
              ))}
            </div>
          </div>
          <form className="flex min-w-0 flex-1 items-end gap-2" onSubmit={(e) => { e.preventDefault(); run(() => post(`/api/v1/projects/${id}`, { music_path: (music ?? "").trim() || null }, "PATCH")); }}>
            <div className="min-w-0 flex-1">
              <label htmlFor="music" className="mb-1 block font-medium">Nhạc nền</label>
              <input id="music" value={music ?? p.music_path ?? ""} onChange={(e) => setMusic(e.target.value)} placeholder="Đường dẫn tới file nhạc bạn có quyền dùng (để trống nếu không cần)"
                     className="w-full rounded border border-line bg-canvas px-3 py-1.5 placeholder:text-mute/70" />
            </div>
            <Button disabled={busy || music === null || (music ?? "") === (p.music_path ?? "")} onClick={() => run(() => post(`/api/v1/projects/${id}`, { music_path: (music ?? "").trim() || null }, "PATCH"))}>Lưu nhạc</Button>
          </form>
        </div>
        <div>
          <h2 className="mb-1 text-lg font-semibold">Kịch bản</h2>
          <p className="mb-2 text-mute">Mỗi dòng là một câu lời dẫn. Hệ thống tìm một clip cho từng câu.</p>
          <textarea value={text ?? ""} onChange={(e) => setText(e.target.value)} rows={Math.max(5, (text ?? "").split("\n").length + 1)} aria-label="Kịch bản"
                    className="w-full max-w-3xl rounded border border-line bg-canvas p-3 text-base leading-relaxed" placeholder="Chợ Hội An buổi sáng tấp nập người mua kẻ bán." />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <Button kind={dirty ? "primary" : "plain"} disabled={busy || !dirty || !(text ?? "").trim()} onClick={() => run(() => post(`/api/v1/projects/${id}/script`, { lines: (text ?? "").split("\n") }, "PUT"))}>Lưu kịch bản</Button>
            <span className="mx-2 hidden h-5 w-px bg-line sm:block" />
            <label htmlFor="topic" className="sr-only">Chủ đề để viết nháp</label>
            <input id="topic" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Chủ đề, ví dụ: một buổi sáng ở chợ" className="w-64 rounded border border-line bg-canvas px-3 py-1.5 placeholder:text-mute/70" />
            <Button disabled={busy || !topic.trim()} onClick={() => run(async () => { const r = await post<{ lines: string[] }>(`/api/v1/projects/${id}/draft`, { topic }); if (r.lines.length) setText(r.lines.join("\n")); else setNote("Mô hình không viết được câu nào. Hãy thử chủ đề khác."); })}>Viết nháp từ kho footage</Button>
          </div>
          {dirty && p.script && <p className="mt-2 text-sm text-mute">Lưu sẽ tạo phiên bản kịch bản mới; các clip đã chọn cho phiên bản cũ không áp dụng nữa.</p>}
        </div>

        {p.script && (
          <div>
            <div className="mb-2 flex flex-wrap items-center gap-3">
              <h2 className="text-lg font-semibold">Clip cho từng câu</h2>
              <Button kind={!p.match ? "primary" : "plain"} disabled={busy || !!matching || dirty} onClick={() => run(() => post(`/api/v1/projects/${id}/match`))}>{p.match ? "Tìm lại clip" : "Tìm clip cho kịch bản"}</Button>
              {matching && <span className="text-mute">Đang tìm trong kho footage</span>}
              {reviewing && <Button kind="primary" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/match/approve`))}>Duyệt các clip này</Button>}
              {approved && <span className="text-proof">Đã duyệt</span>}
            </div>
            {p.shots.some((s) => s.selection) && <div className="mb-4 max-w-4xl"><TimelineStrip shots={p.shots} /></div>}
            {reviewing && <p className="mb-2 text-cue">Xem từng clip. Đổi sang phương án khác nếu cần, rồi duyệt để dựng video.{gaps > 0 ? ` Còn ${gaps} câu chưa có hình.` : ""}</p>}
            <ol className="divide-y divide-line border-y border-line">
              {p.shots.map((s, i) => <ShotRow key={s.shot_id} shot={s} n={i + 1} locked={!!rendering} changed={reload} />)}
            </ol>
          </div>
        )}

        {approved && (
          <div>
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <h2 className="text-lg font-semibold">Bản dựng</h2>
              <Button kind={!latest ? "primary" : "plain"} disabled={busy || !!rendering} onClick={() => run(() => post(`/api/v1/projects/${id}/render`))}>{latest ? "Dựng lại" : "Dựng video"}</Button>
              {rendering && p.render && <div className="w-56"><StageRail stages={p.render.stages} /></div>}
              {rendering && <span className="text-mute">Đang dựng</span>}
            </div>
            {p.render?.status === "failed" && <p className="mb-3 text-tally">Lần dựng vừa rồi thất bại ở bước {p.render.stages.find((s) => s.status === "failed")?.stage_key}. Xem chi tiết ở mục Tiến trình, rồi bấm dựng lại.</p>}
            {p.render?.status === "blocked" && <p className="mb-3 text-cue">Việc dựng đang dừng và cần bạn xử lý. Xem ở mục Tiến trình.</p>}
            {latest && (
              <div className="grid gap-6 lg:grid-cols-[minmax(0,640px)_1fr]">
                <video key={latest.url} src={latest.url} controls className="aspect-video w-full rounded bg-black" />
                <div>
                  <h3 className="mb-1 font-semibold">Kiểm tra tự động</h3>
                  <ul className="mb-3">
                    {Object.entries(latest.qc.checks).map(([name, ok]) => <li key={name} className={ok ? "" : "text-tally"}>{ok ? "Đạt" : "Không đạt"}: {name}</li>)}
                    {latest.qc.gaps > 0 && <li className="text-cue">Có {latest.qc.gaps} câu đang dùng nền trơn vì thiếu hình</li>}
                  </ul>
                  <p className="tc mb-4 text-mute">Dài {timecode(latest.qc.duration)}, {FORMATS[latest.qc.format ?? "landscape"]}{latest.qc.music ? ", có nhạc nền" : ""}</p>
                  {(latest.qc.findings ?? []).length > 0 && (
                    <div className="mb-4">
                      <h3 className="mb-1 font-semibold">Nên xem lại</h3>
                      <ul className="divide-y divide-line border-y border-line">
                        {(latest.qc.findings ?? []).map((f, i) => (
                          <li key={i} className="py-2"><p><span className={f.severity === "cao" ? "text-cue" : ""}>Câu {f.shot}, {f.check.toLowerCase()}:</span> {f.text}</p><p className="text-sm text-mute">{f.fix}</p></li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {renderReview && (
                    <div className="flex flex-wrap gap-2">
                      <Button kind="primary" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/render/decision`, { approve: true }))}>Duyệt bản dựng</Button>
                      <Button disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/render/decision`, { approve: false }))}>Chưa được, dựng lại</Button>
                    </div>
                  )}
                  {p.render?.status === "succeeded" && <><p className="mb-4 text-proof">Bạn đã duyệt bản dựng này.</p><PackagePanel render={latest} reload={reload} /></>}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

export default function Projects({ sub, go }: { sub: string | null; go: (to: string) => void }) {
  const { data, reload } = usePoll<Project[]>("/api/v1/projects", 5000);
  const [title, setTitle] = useState("");
  if (sub) return <Detail key={sub} id={sub} back={() => go("/du-an")} />;
  const create = async () => { const p = await post<Project>("/api/v1/projects", { title: title.trim() }); setTitle(""); reload(); go(`/du-an/${p.project_id}`); };
  return (
    <section className="flex-1 overflow-y-auto p-6">
      <h1 className="mb-4 text-2xl font-semibold tracking-tight">Dự án</h1>
      <form className="mb-5 flex max-w-xl gap-2" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create(); }}>
        <label htmlFor="title" className="sr-only">Tên video</label>
        <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Tên video mới, ví dụ: Một buổi sáng ở chợ Hội An" className="min-w-0 flex-1 rounded border border-line bg-canvas px-3 py-1.5 placeholder:text-mute/70" />
        <Button kind="primary" disabled={!title.trim()} onClick={create}>Tạo dự án</Button>
      </form>
      {data && data.length === 0 && <p className="max-w-md text-mute">Chưa có dự án nào. Mỗi dự án là một video: bạn viết kịch bản, hệ thống tìm clip trong kho footage, rồi dựng thành video có lời dẫn và phụ đề.</p>}
      <ul className="max-w-3xl divide-y divide-line border-y border-line">
        {(data ?? []).map((p) => {
          const state = p.render?.status === "succeeded" ? "Đã xong" : p.render?.status === "waiting_review" || p.match?.status === "waiting_review" ? "Chờ bạn duyệt"
            : p.render || p.match ? "Đang làm" : p.script ? "Có kịch bản" : "Chưa có kịch bản";
          return (
            <li key={p.project_id}>
              <a href={`/du-an/${p.project_id}`} onClick={(e) => { e.preventDefault(); go(`/du-an/${p.project_id}`); }} className="flex items-center justify-between gap-4 px-2 py-3 hover:bg-surface/60">
                <span className="font-medium">{p.title}</span>
                <span className={state === "Chờ bạn duyệt" ? "text-cue" : state === "Đã xong" ? "text-proof" : "text-mute"}>{state}{p.shots.length ? `, ${p.shots.length} câu` : ""}</span>
              </a>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
