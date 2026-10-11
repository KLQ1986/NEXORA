import { useEffect, useRef, useState } from "react";
import { post, projectState, timecode, usePoll, type AgentTask, type Asset, type Candidate, type Project, type RenderItem, type Shot } from "./api";
import Board from "./Board";
import { Button, Filmstrip, Icon, Page, Section, StageRail, Steps, Tag } from "./parts";
import Timeline from "./Timeline";

function Clip({ url, tIn, tOut, poster }: { url: string | null; tIn: number; tOut: number; poster: string | null }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => { const v = ref.current; if (!v) return; const tick = () => { if (v.currentTime >= tOut) v.currentTime = tIn; }; v.addEventListener("timeupdate", tick); return () => v.removeEventListener("timeupdate", tick); }, [tIn, tOut, url]);
  if (!url) return poster ? <img src={poster} alt="" className="aspect-video w-full rounded-sm bg-black object-cover" /> : <div className="aspect-video w-full rounded-sm bg-raised" />;
  return <video ref={ref} key={`${url}${tIn}`} src={`${url}#t=${tIn},${tOut}`} poster={poster ?? undefined} muted playsInline controls preload="metadata" className="aspect-video w-full rounded-sm bg-black" />;
}

function ShotRow({ shot, n, locked, changed }: { shot: Shot; n: number; locked: boolean; changed: () => void }) {
  const sel = shot.selection;
  const [query, setQuery] = useState("");
  const [stock, setStock] = useState<string | null>(null);
  const findStock = async () => { setStock("Đang tìm trên các kho miễn phí"); try { const r = await post<{ found: boolean }>(`/api/v1/shots/${shot.shot_id}/stock`, { query }); setStock(r.found ? null : "Không tìm thấy clip nào. Thử từ khoá tiếng Anh khác."); } catch (e) { setStock((e as Error).message); } changed(); };
  const act = async (path: string, body?: unknown) => { await post(`/api/v1/shots/${shot.shot_id}/${path}`, body).catch(() => {}); changed(); };
  return (
    <li className="grid gap-5 py-5 md:grid-cols-[1.75rem_minmax(0,1fr)_300px]">
      <span className="tc grid h-6 w-6 place-items-center rounded-full bg-raised text-[12px] text-mute">{n}</span>
      <div className="min-w-0">
        <p className="text-[15px] leading-relaxed">{shot.text}</p>
        {!sel && <p className="mt-1 text-sm text-mute">Chưa tìm clip cho câu này.</p>}
        {sel?.status === "gap" && <p className="mt-1 text-sm text-cue">Chưa có hình cho câu này. Video sẽ hiện một nền trơn kèm phụ đề, cho tới khi bạn quay thêm, thêm footage, hoặc sửa câu.</p>}
        {sel && sel.status !== "gap" && <details className="group mt-1.5 text-[13px] text-mute"><summary className="cursor-pointer list-none break-words"><span className="line-clamp-2 group-open:line-clamp-none">Vì sao chọn: {sel.reason}</span><span className="text-faint underline underline-offset-2 group-open:hidden">Xem đầy đủ</span></summary></details>}
        {sel?.status === "gap" && !locked && (
          <form className="mt-2 flex max-w-xl flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (query.trim()) findStock(); }}>
            <label htmlFor={`stock-${shot.shot_id}`} className="sr-only">Từ khoá tìm clip stock</label>
            <input id={`stock-${shot.shot_id}`} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Từ khoá tiếng Anh, ví dụ: fishing boat at sea" className="min-w-0 flex-1 rounded border border-line bg-canvas px-3 py-1.5 placeholder:text-mute/70" />
            <Button disabled={!query.trim()} onClick={findStock}>Tìm clip stock miễn phí</Button>
            {stock && <p className="w-full text-sm text-mute">{stock}</p>}
          </form>
        )}
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
            <Clip url={sel.asset.proxy_url} tIn={sel.t_in} tOut={sel.t_out} poster={sel.frame_url ?? sel.asset.thumbnail_url} />
            <p className="tc mt-1 truncate text-xs text-mute">{sel.asset.name}{sel.asset.still ? ", ảnh tĩnh" : `, ${timecode(sel.t_in)} đến ${timecode(sel.t_out)}`}{sel.decided_by === "operator" ? ", bạn chọn" : ""}</p>
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
            {s.selection && s.selection.status !== "gap" && (s.selection.frame_url ?? s.selection.asset?.thumbnail_url) && <img src={(s.selection.frame_url ?? s.selection.asset?.thumbnail_url)!} alt="" className="h-full w-full object-cover opacity-90" />}
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

const TASK_STATES: Record<string, string> = { working: "Đang làm", waiting_operator: "Chờ bạn", done: "Xong", failed: "Dừng vì lỗi" };

/** What the producer agent did for this project, role by role, in the order it happened. */
function AgentLog({ projectId }: { projectId: string }) {
  const { data } = usePoll<{ tasks: AgentTask[] }>(`/api/v1/agent/tasks?project_id=${projectId}`, 3000);
  const task = data?.tasks[0];
  if (!task) return null;
  return (
    <details className="panel mb-7 max-w-4xl px-5 py-3.5" open={task.status !== "done"}>
      <summary className="flex cursor-pointer items-center gap-2 font-medium"><Icon name="spark" />Trợ lý sản xuất: <span className={task.status === "waiting_operator" ? "text-cue" : task.status === "failed" ? "text-tally" : task.status === "done" ? "text-proof" : "text-mute"}>{TASK_STATES[task.status] ?? task.status}</span></summary>
      <ol className="mt-2 grid gap-1">
        {task.log.map((e, i) => <li key={i} className="grid grid-cols-[5rem_6.5rem_minmax(0,1fr)] gap-2 text-sm"><span className="tc text-mute">{new Date(e.at * 1000).toLocaleTimeString("vi-VN")}</span><span className="text-mute">{e.role}</span><span>{e.text}</span></li>)}
      </ol>
    </details>
  );
}

const STEPS = ["Kịch bản", "Chọn clip", "Duyệt clip", "Dựng video", "Duyệt bản dựng"];

function Detail({ id, back }: { id: string; back: () => void }) {
  const { data: p, reload } = usePoll<Project>(`/api/v1/projects/${id}`, 2500);
  const [text, setText] = useState<string | null>(null);
  const [topic, setTopic] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"work" | "timeline" | "board">("work");
  const [takes, setTakes] = useState<string | null>(null);
  const [music, setMusic] = useState<string | null>(null);
  const [style, setStyle] = useState<string | null>(null);
  const [budget, setBudget] = useState<string | null>(null);
  const [why, setWhy] = useState("");
  const { data: lib } = usePoll<{ assets: Asset[] }>("/api/v1/library", 30000);
  const tracks = (lib?.assets ?? []).filter((a) => a.kind === "audio" && a.online);
  const stored = p ? p.shots.map((s) => s.text).join("\n") : null;
  const last = useRef<string | null>(null);
  // The editor follows the stored script (after a reorder on the timeline, for example) unless the operator has typed something not yet saved.
  useEffect(() => { if (stored === null) return; if (text === null || text.trim() === (last.current ?? "").trim()) setText(stored); last.current = stored; }, [stored]);
  if (!p) return <Page title="Dự án" back={{ label: "Dự án", onClick: back }}><p className="text-mute">Đang mở dự án</p></Page>;
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
  const st = projectState(p);
  const patch = (body: Record<string, unknown>) => run(() => post(`/api/v1/projects/${id}`, body, "PATCH"));
  // The one thing to do next, always in the same place.
  const next = dirty ? { label: "Lưu kịch bản", go: () => run(() => post(`/api/v1/projects/${id}/script`, { lines: (text ?? "").split("\n") }, "PUT")) }
    : !p.script ? null
    : reviewing ? { label: "Duyệt các clip này", go: () => run(() => post(`/api/v1/projects/${id}/match/approve`)) }
    : renderReview ? { label: "Duyệt bản dựng", go: () => run(() => post(`/api/v1/projects/${id}/render/decision`, { approve: true })) }
    : !p.match && !approved ? { label: "Tìm clip cho kịch bản", go: () => run(() => post(`/api/v1/projects/${id}/match`)) }
    : approved && !latest && !rendering ? { label: "Dựng video", go: () => run(() => post(`/api/v1/projects/${id}/render`)) }
    : null;
  const field = "mb-1.5 block text-[13px] font-medium";
  return (
    <Page title={p.title} back={{ label: "Dự án", onClick: back }} wide
          note={<>{st.label}{p.shots.length ? `, ${p.shots.length} câu` : ""}, {FORMATS[p.format] ?? p.format}{latest ? `, bản dựng ${timecode(latest.qc.duration)}` : ""}</>}
          actions={<>
            <div className="flex rounded-md border border-line p-0.5" role="tablist">
              {([["work", "Làm video"], ["timeline", "Dòng thời gian"], ["board", "Bảng theo dõi"]] as const).map(([key, label]) => (
                <button key={key} type="button" role="tab" aria-selected={tab === key} onClick={() => setTab(key)} className={`h-8 rounded px-3 text-[13px] ${tab === key ? "bg-raised font-medium" : "text-mute hover:text-ink"}`}>{label}</button>
              ))}
            </div>
            {next && <Button kind="primary" disabled={busy || (next.label === "Lưu kịch bản" && !(text ?? "").trim())} onClick={next.go}>{next.label}</Button>}
          </>}>
      <ol className={`mb-7 grid max-w-3xl grid-cols-5 gap-1.5 ${tab === "board" ? "hidden" : ""}`} aria-label="Các bước làm video">
        {STEPS.map((label, i) => (
          <li key={label} aria-current={i === step ? "step" : undefined}>
            <div className={`h-1 rounded-full ${i < step ? "bg-proof" : i === step ? ((i === 2 || i === 4) ? "bg-cue" : "bg-ink") : "bg-line"}`} />
            <p className={`mt-1.5 text-[13px] ${i === step ? "font-medium" : i < step ? "text-mute" : "text-faint"}`}>{label}</p>
          </li>
        ))}
      </ol>
      {note && <p className="panel mb-5 max-w-3xl border-tally/50 px-4 py-3 text-tally">{note}</p>}
      <AgentLog projectId={id} />
      {tab === "board" && <Board project={p} />}
      {tab === "timeline" && <Timeline project={p} reload={reload} busy={busy} rerender={() => run(() => post(`/api/v1/projects/${id}/render`))} />}

      <div className={`grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_340px] ${tab === "work" ? "" : "hidden"}`}>
        <div className="grid min-w-0 gap-10">
          <Section title="Kịch bản" note="Mỗi dòng là một câu lời dẫn. Hệ thống tìm một clip cho từng câu.">
            <textarea value={text ?? ""} onChange={(e) => setText(e.target.value)} rows={Math.max(5, (text ?? "").split("\n").length + 1)} aria-label="Kịch bản"
                      className="w-full p-4 text-[15px] leading-[1.9]" placeholder="Chợ Hội An buổi sáng tấp nập người mua kẻ bán." />
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Button disabled={busy || !dirty || !(text ?? "").trim()} onClick={() => run(() => post(`/api/v1/projects/${id}/script`, { lines: (text ?? "").split("\n") }, "PUT"))}>Lưu kịch bản</Button>
              <span className="ml-auto" />
              <label htmlFor="topic" className="sr-only">Chủ đề để viết nháp</label>
              <input id="topic" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Chủ đề, ví dụ: một buổi sáng ở chợ" className="w-64 px-3" />
              <Button disabled={busy || !topic.trim()} onClick={() => run(async () => { const r = await post<{ lines: string[] }>(`/api/v1/projects/${id}/draft`, { topic }); if (r.lines.length) setText(r.lines.join("\n")); else setNote("Mô hình không viết được câu nào. Hãy thử chủ đề khác."); })}><Icon name="spark" />Viết nháp từ kho footage</Button>
            </div>
            {dirty && p.script && <p className="mt-2 text-[13px] text-mute">Lưu sẽ tạo phiên bản kịch bản mới; các clip đã chọn cho phiên bản cũ không áp dụng nữa.</p>}
          </Section>

          {p.script && (
            <Section title="Clip cho từng câu"
                     note={reviewing ? <span className="text-cue">Xem từng clip, đổi sang phương án khác nếu cần, rồi duyệt.{gaps > 0 ? ` Còn ${gaps} câu chưa có hình.` : ""}</span> : matching ? "Đang tìm trong kho footage" : approved ? <span className="text-proof">Đã duyệt</span> : undefined}
                     actions={<>
                       <Button size="sm" disabled={busy || !!matching || dirty} onClick={() => run(() => post(`/api/v1/projects/${id}/match`))}>{p.match ? "Tìm lại clip" : "Tìm clip cho kịch bản"}</Button>
                       {reviewing && <Button size="sm" kind="primary" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/match/approve`))}>Duyệt các clip này</Button>}
                     </>}>
              {p.shots.some((s) => s.selection) && <div className="mb-1"><TimelineStrip shots={p.shots} /></div>}
              <ol className="rows border-y border-line">
                {p.shots.map((s, i) => <ShotRow key={s.shot_id} shot={s} n={i + 1} locked={!!rendering} changed={reload} />)}
              </ol>
            </Section>
          )}

          {approved && (
            <Section title="Bản dựng"
                     note={rendering ? "Đang dựng" : undefined}
                     actions={<>{rendering && p.render && <div className="w-40"><StageRail stages={p.render.stages} /></div>}
                       <Button size="sm" disabled={busy || !!rendering} onClick={() => run(() => post(`/api/v1/projects/${id}/render`))}>{latest ? "Dựng lại" : "Dựng video"}</Button></>}>
              {p.render?.status === "failed" && <p className="mb-3 text-tally">Lần dựng vừa rồi thất bại ở bước {p.render.stages.find((s) => s.status === "failed")?.stage_key}. Xem chi tiết ở mục Tiến trình, rồi bấm dựng lại.</p>}
              {p.render?.status === "blocked" && <p className="mb-3 text-cue">Việc dựng đang dừng và cần bạn xử lý. Xem ở mục Tiến trình.</p>}
              {!latest && !rendering && <p className="panel px-4 py-5 text-mute">Các clip đã được duyệt. Bấm Dựng video để hệ thống đọc lời dẫn, vẽ phụ đề và ghép cảnh.</p>}
              {latest && (
                <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                  <video key={latest.url} src={latest.url} controls className={`w-full rounded-md bg-black ${latest.qc.format === "portrait" ? "mx-auto aspect-[9/16] max-h-[70vh] w-auto" : latest.qc.format === "square" ? "aspect-square max-h-[70vh]" : "aspect-video"}`} />
                  <div className="min-w-0">
                    <div className="panel rows mb-4">
                      {Object.entries(latest.qc.checks).map(([name, ok]) => <p key={name} className="flex items-center justify-between gap-3 px-4 py-2.5"><span>{name}</span><Tag tone={ok ? "proof" : "tally"}>{ok ? "Đạt" : "Không đạt"}</Tag></p>)}
                      {latest.qc.gaps > 0 && <p className="flex items-center justify-between gap-3 px-4 py-2.5"><span>Câu dùng nền trơn vì thiếu hình</span><Tag tone="cue">{latest.qc.gaps}</Tag></p>}
                    </div>
                    <p className="mb-4 text-[13px]"><a className="underline underline-offset-2" href={`/api/v1/renders/${latest.render_id}/edl`} download>Tải danh sách cắt (EDL)</a> <span className="text-mute">để dựng tiếp trong DaVinci Resolve từ file gốc</span></p>
                    {(latest.qc.findings ?? []).length > 0 && (
                      <div className="mb-4">
                        <h3 className="mb-1.5 text-[13px] font-semibold">Nên xem lại</h3>
                        <ul className="panel rows">
                          {(latest.qc.findings ?? []).map((f, i) => (
                            <li key={i} className="px-4 py-2.5"><p><span className={f.severity === "cao" ? "text-cue" : "font-medium"}>Câu {f.shot}, {f.check.toLowerCase()}:</span> {f.text}</p><p className="text-[13px] text-mute">{f.fix}</p></li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {renderReview && (
                      <div className="panel border-cue/40 p-4">
                        <label htmlFor="why" className={field}>Ghi chú nếu chưa được</label>
                        <textarea id="why" value={why} onChange={(e) => setWhy(e.target.value)} rows={2} placeholder="Ví dụ: 0:07 cảnh xay cà phê bị tối, đổi cảnh khác" className="mb-3 w-full p-2.5" />
                        <div className="flex flex-wrap gap-2">
                          <Button kind="primary" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/render/decision`, { approve: true }))}>Duyệt bản dựng</Button>
                          <Button disabled={busy} onClick={() => run(async () => { await post(`/api/v1/projects/${id}/render/decision`, { approve: false, comment: why }); setWhy(""); })}>Chưa được, dựng lại</Button>
                        </div>
                      </div>
                    )}
                    {p.render?.status === "succeeded" && <><p className="mb-4 text-proof">Bạn đã duyệt bản dựng này.</p><PackagePanel render={latest} reload={reload} /></>}
                    {p.renders.length > 1 && (
                      <details className="mt-5">
                        <summary className="cursor-pointer text-[13px] text-mute hover:text-ink">Các bản dựng trước ({p.renders.length - 1})</summary>
                        <ul className="panel rows mt-2">
                          {p.renders.slice(1, 6).map((r) => (
                            <li key={r.render_id} className="px-4 py-2.5 text-[13px]"><a className="underline underline-offset-2" href={r.url} target="_blank" rel="noreferrer">{new Date(r.created_at * 1000).toLocaleString("vi-VN")}</a>
                              <span className="text-mute">, dài {timecode(r.qc.duration)}{r.review ? (r.review.approved ? ", đã duyệt" : ", không duyệt") : ""}</span>
                              {r.review?.comment && <p className="text-mute">Ghi chú: {r.review.comment}</p>}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                </div>
              )}
            </Section>
          )}
        </div>

        <aside className="grid gap-4 xl:sticky xl:top-0" aria-label="Thiết lập của dự án">
          <div className="panel grid gap-5 p-5">
            <div>
              <p className={field} id="format-label">Khung hình</p>
              <div className="flex rounded-md border border-line p-0.5" role="radiogroup" aria-labelledby="format-label">
                {Object.entries(FORMATS).map(([key, label]) => (
                  <button key={key} type="button" role="radio" aria-checked={p.format === key} disabled={busy} onClick={() => patch({ format: key })}
                          className={`h-8 flex-1 rounded text-[13px] ${p.format === key ? "bg-raised font-medium" : "text-mute hover:text-ink"}`}>{label}</button>
                ))}
              </div>
            </div>
            <form onSubmit={(e) => { e.preventDefault(); patch({ music_path: (music ?? "").trim() || null }); }}>
              <label htmlFor="music" className={field}>Nhạc nền</label>
              <div className="flex gap-2">
                <input id="music" list="tracks" value={music ?? p.music_path ?? ""} onChange={(e) => setMusic(e.target.value)} placeholder="Chọn trong thư viện hoặc dán đường dẫn" className="min-w-0 flex-1 px-3" />
                <Button disabled={busy || music === null || (music ?? "") === (p.music_path ?? "")} onClick={() => patch({ music_path: (music ?? "").trim() || null })}>Lưu</Button>
              </div>
              <datalist id="tracks">{tracks.map((a) => <option key={a.asset_id} value={a.path}>{`${a.name}, ${timecode(a.duration)}`}</option>)}</datalist>
              <p className="mt-1.5 text-[13px] text-mute">Nhạc tự nhỏ lại khi có lời dẫn.</p>
            </form>
            <form onSubmit={(e) => { e.preventDefault(); patch({ narration_dir: (takes ?? "").trim() || null }); }}>
              <label htmlFor="takes" className={field}>Lời dẫn bạn tự thu</label>
              <div className="flex gap-2">
                <input id="takes" value={takes ?? p.narration_dir ?? ""} onChange={(e) => setTakes(e.target.value)} placeholder="Thư mục chứa 1.wav, 2.m4a" className="min-w-0 flex-1 px-3" />
                <Button disabled={busy || takes === null || (takes ?? "") === (p.narration_dir ?? "")} onClick={() => patch({ narration_dir: (takes ?? "").trim() || null })}>Lưu</Button>
              </div>
              <p className="mt-1.5 text-[13px] text-mute">{!p.narration_dir ? "Đặt tên file theo số câu. Câu nào không có file thì dùng giọng máy." : p.own_takes.length ? `Đã có bản thu cho câu ${p.own_takes.join(", ")}. Các câu còn lại dùng giọng máy.` : "Chưa thấy file thu âm nào trong thư mục này."}</p>
            </form>
            <label className="flex items-start gap-2.5"><input type="checkbox" className="mt-0.5" checked={p.auto_accept} disabled={busy} onChange={(e) => patch({ auto_accept: e.target.checked ? 1 : 0 })} />
              <span>Tự duyệt clip<span className="block text-[13px] text-mute">Chỉ khi mọi câu đều có clip và mô hình chấm chắc chắn.</span></span></label>
          </div>

          {p.script && (
            <div className="panel grid gap-4 p-5">
              <div><h2 className="text-[15px] font-semibold">Sinh hình bằng AI</h2>
                <p className="mt-1 text-[13px] text-mute">Cho phim hoạt hình, hoặc khi kho footage không có hình. Hệ thống sinh ảnh tĩnh cho mỗi câu để bạn duyệt, rồi mới sinh video.</p></div>
              {!p.generators.image || !p.generators.video ? (
                <p className="text-[13px] text-cue">Chưa có nhà cung cấp sinh ảnh và sinh video. Cần khoá API của một nhà cung cấp để bật.</p>
              ) : (
                <>
                  <form onSubmit={(e) => { e.preventDefault(); patch({ style: (style ?? "").trim() || null }); }}>
                    <label htmlFor="style" className={field}>Phong cách hình</label>
                    <div className="flex gap-2"><input id="style" value={style ?? p.style ?? ""} onChange={(e) => setStyle(e.target.value)} placeholder="Ví dụ: hoạt hình màu nước" className="min-w-0 flex-1 px-3" />
                      <Button disabled={busy || style === null} onClick={() => patch({ style: (style ?? "").trim() || null })}>Lưu</Button></div>
                  </form>
                  <form onSubmit={(e) => { e.preventDefault(); patch({ budget_cap: budget === "" || budget === null ? null : Number(budget) }); }}>
                    <label htmlFor="budget" className={field}>Ngân sách cho dự án (USD)</label>
                    <div className="flex gap-2"><input id="budget" type="number" min="0" step="0.5" value={budget ?? p.budget_cap ?? ""} onChange={(e) => setBudget(e.target.value)} placeholder="Không giới hạn" className="tc min-w-0 flex-1 px-3" />
                      <Button disabled={busy || budget === null} onClick={() => patch({ budget_cap: budget === "" || budget === null ? null : Number(budget) })}>Lưu</Button></div>
                    <p className="tc mt-1.5 text-[13px] text-mute">Đã tiêu {p.spent.toFixed(2)} USD{p.budget_cap != null ? ` trên ${p.budget_cap.toFixed(2)} USD` : ""}.</p>
                  </form>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button disabled={busy || dirty || (!!p.generate && ["queued", "running"].includes(p.generate.status))} onClick={() => run(() => post(`/api/v1/projects/${id}/generate`))}>{p.generate ? "Sinh lại" : "Sinh ảnh cho từng câu"}</Button>
                    {p.generate?.status === "waiting_review" && <Button kind="primary" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/generate/approve`))}>
                      {p.generate.stages.find((s) => s.status === "waiting_review")?.stage_key === "keyframes" ? "Duyệt ảnh, sinh video" : "Duyệt các clip này"}</Button>}
                    {p.generate && ["queued", "running"].includes(p.generate.status) && <span className="text-[13px] text-mute">Đang sinh</span>}
                    {p.generate?.status === "blocked" && <span className="text-[13px] text-cue">Đang dừng, xem ở mục Tiến trình</span>}
                  </div>
                  {p.shots.some((s) => s.keyframe_url) && (
                    <ol className="grid grid-cols-3 gap-2">
                      {p.shots.map((s, i) => <li key={s.shot_id} title={`${i + 1}. ${s.text}`}>{s.keyframe_url ? <img src={s.keyframe_url} alt="" className="aspect-video w-full rounded bg-black object-cover" /> : <div className="aspect-video rounded bg-raised" />}</li>)}
                    </ol>
                  )}
                </>
              )}
            </div>
          )}
        </aside>
      </div>
    </Page>
  );
}

export default function Projects({ sub, go }: { sub: string | null; go: (to: string) => void }) {
  const { data, reload } = usePoll<Project[]>("/api/v1/projects", 5000);
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [format, setFormat] = useState("landscape");
  const [mode, setMode] = useState<"none" | "new" | "agent">("none");
  const { data: agent, reload: reloadAgent } = usePoll<{ tasks: AgentTask[] }>("/api/v1/agent/tasks", 4000);
  const [agentNote, setAgentNote] = useState<string | null>(null);
  if (sub) return <Detail key={sub} id={sub} back={() => go("/du-an")} />;
  const create = async () => { const p = await post<Project>("/api/v1/projects", { title: title.trim(), format }); setTitle(""); reload(); go(`/du-an/${p.project_id}`); };
  const assign = async () => { setAgentNote(null); try { const t = await post<AgentTask>("/api/v1/agent/tasks", { goal: goal.trim(), format }); setGoal(""); reloadAgent(); reload(); go(`/du-an/${t.project_id}`); } catch (err) { setAgentNote((err as Error).message); } };
  const working = new Map((agent?.tasks ?? []).filter((t) => t.status === "working" || t.status === "waiting_operator").map((t) => [t.project_id, t]));
  const formats = (
    <div className="flex rounded-md border border-line p-0.5" role="radiogroup" aria-label="Khung hình">
      {Object.entries(FORMATS).map(([k, v]) => <button key={k} type="button" role="radio" aria-checked={format === k} onClick={() => setFormat(k)} className={`h-8 rounded px-2.5 text-[13px] ${format === k ? "bg-raised font-medium" : "text-mute hover:text-ink"}`}>{v}</button>)}
    </div>
  );
  return (
    <Page title="Dự án" note="Mỗi dự án là một video, từ kịch bản tới bản dựng đã duyệt."
          actions={<><Button onClick={() => setMode(mode === "agent" ? "none" : "agent")}><Icon name="spark" />Giao cho trợ lý</Button><Button kind="primary" onClick={() => setMode(mode === "new" ? "none" : "new")}><Icon name="plus" />Dự án mới</Button></>}>
      {mode === "new" && (
        <form className="panel rise mb-8 max-w-3xl p-5" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create(); }}>
          <label htmlFor="title" className="mb-1.5 block font-medium">Tên video</label>
          <div className="flex flex-wrap gap-2">
            <input id="title" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ví dụ: Một buổi sáng ở chợ Hội An" className="min-w-0 flex-1 px-3" />
            {formats}<Button kind="primary" disabled={!title.trim()} onClick={create}>Tạo dự án</Button>
          </div>
        </form>
      )}
      {mode === "agent" && (
        <form className="panel rise mb-8 max-w-3xl p-5" onSubmit={(e) => { e.preventDefault(); if (goal.trim()) assign(); }}>
          <label htmlFor="goal" className="mb-1 block font-medium">Video bạn muốn làm</label>
          <p className="mb-3 text-[13px] text-mute">Trợ lý tự viết kịch bản từ kho footage, tìm clip, lấp chỗ thiếu bằng clip stock miễn phí rồi dựng. Nó dừng lại chờ bạn duyệt clip và duyệt bản dựng.</p>
          <div className="flex flex-wrap gap-2">
            <input id="goal" autoFocus value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Ví dụ: một phút về buổi sáng ở chợ Hội An" className="min-w-0 flex-1 px-3" />
            {formats}<Button kind="primary" disabled={!goal.trim()} onClick={assign}>Giao việc</Button>
          </div>
          {agentNote && <p className="mt-2 text-tally">{agentNote}</p>}
        </form>
      )}
      {data && data.length === 0 && <p className="panel max-w-2xl px-5 py-8 text-mute">Chưa có dự án nào. Bấm Dự án mới để tự viết kịch bản, hoặc Giao cho trợ lý để nó viết và dựng bản đầu tiên từ kho footage của bạn.</p>}
      <ul className="grid gap-3">
        {(data ?? []).map((p) => {
          const st = projectState(p);
          const task = working.get(p.project_id);
          const latest = p.renders[0];
          return (
            <li key={p.project_id}>
              <a href={`/du-an/${p.project_id}`} onClick={(e) => { e.preventDefault(); go(`/du-an/${p.project_id}`); }}
                 className="panel grid items-center gap-x-6 gap-y-3 p-3 transition-colors hover:border-faint md:grid-cols-[minmax(0,5fr)_minmax(0,4fr)_auto]">
                <Filmstrip shots={p.shots} height={64} />
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-medium">{p.title}</p>
                  <p className="tc truncate text-[13px] text-mute">{p.shots.length ? `${p.shots.length} câu` : "Chưa có kịch bản"}, {FORMATS[p.format] ?? p.format}{latest ? `, bản dựng ${timecode(latest.qc.duration)}` : ""}{task ? ", trợ lý đang làm" : ""}</p>
                </div>
                <div className="flex items-center gap-4 md:justify-end md:pr-2"><Steps step={st.step} tone={st.tone} /><span className="w-36 md:text-right"><Tag tone={st.tone}>{st.label}</Tag></span></div>
              </a>
            </li>
          );
        })}
      </ul>
    </Page>
  );
}
