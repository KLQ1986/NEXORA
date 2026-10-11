import { useEffect, useRef, useState } from "react";
import { post, projectState, scriptText, stageName, timecode, usePoll, type Idea, type Source, type AgentTask, type Asset, type Settings, type Candidate, type Project, type RenderItem, type Shot } from "./api";
import Board from "./Board";
import { Button, Empty, Filmstrip, Icon, Meter, Page, Section, Seg, StageRail, Steps, Tabs, Tag, TimeChip } from "./parts";
import Timeline from "./Timeline";

const VERDICT: Record<string, [string, "proof" | "tally" | "cue"]> = { supported: ["Nguồn xác nhận", "proof"], contradicted: ["Trái với nguồn", "tally"], not_found: ["Chưa có căn cứ", "cue"] };

function Clip({ url, tIn, tOut, poster }: { url: string | null; tIn: number; tOut: number; poster: string | null }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => { const v = ref.current; if (!v) return; const tick = () => { if (v.currentTime >= tOut) v.currentTime = tIn; }; v.addEventListener("timeupdate", tick); return () => v.removeEventListener("timeupdate", tick); }, [tIn, tOut, url]);
  if (!url) return poster ? <img src={poster} alt="" className="aspect-video w-full rounded-lg bg-black object-cover" /> : <div className="aspect-video w-full rounded-lg bg-raised" />;
  return <video ref={ref} key={`${url}${tIn}`} src={`${url}#t=${tIn},${tOut}`} poster={poster ?? undefined} muted playsInline controls preload="metadata" className="aspect-video w-full rounded-lg bg-black" />;
}

function ShotRow({ shot, n, locked, changed, heading, sources = [] }: { shot: Shot; n: number; locked: boolean; changed: () => void; heading?: string | null; sources?: Source[] }) {
  const note = async (body: Record<string, unknown>) => { await post(`/api/v1/shots/${shot.shot_id}`, body, "PATCH").catch(() => {}); changed(); };
  const sel = shot.selection;
  const [brief, setBrief] = useState<string | null>(null);
  const [screen, setScreen] = useState<string | null>(null);
  const saveNotes = async () => { await post(`/api/v1/shots/${shot.shot_id}`, { brief: brief ?? shot.brief ?? "", screen_text: screen ?? shot.screen_text ?? "" }, "PATCH").catch(() => {}); setBrief(null); setScreen(null); changed(); };
  const [query, setQuery] = useState("");
  const [stock, setStock] = useState<string | null>(null);
  const findStock = async () => { setStock("Đang tìm trên các kho miễn phí…"); try { const r = await post<{ found: boolean }>(`/api/v1/shots/${shot.shot_id}/stock`, { query }); setStock(r.found ? null : "Không tìm thấy clip nào. Thử từ khoá tiếng Anh khác."); } catch (e) { setStock((e as Error).message); } changed(); };
  const act = async (path: string, body?: unknown) => { await post(`/api/v1/shots/${shot.shot_id}/${path}`, body).catch(() => {}); changed(); };
  const gap = sel?.status === "gap";
  const notes = [shot.brief && `hình cần có “${shot.brief}”`, shot.screen_text && `chữ trên màn hình “${shot.screen_text}”`, shot.target_seconds && `giữ ${shot.target_seconds} giây`, shot.sound_cue && `âm thanh “${shot.sound_cue}”`, shot.is_fact && (shot.source ? `dữ kiện, nguồn “${shot.source}”` : "dữ kiện chưa có nguồn")].filter(Boolean);
  return (
    <li>
      {heading && <p className="eyebrow mb-2 mt-3 flex items-center gap-2 text-accent"><Icon name="clapper" size={13} />{heading}</p>}
      <div className={`grid gap-5 rounded-xl border p-4 md:grid-cols-[minmax(0,1fr)_320px] ${gap ? "border-cue/35 bg-cue/[0.03]" : "border-line bg-surface"}`}>
        <div className="min-w-0">
          <div className="flex items-start gap-3">
            <span className="mono grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-overlay text-[12px] text-mute">{String(n).padStart(2, "0")}</span>
            <div className="min-w-0 flex-1">
              <p className="text-[15px] leading-relaxed">{shot.text}</p>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {sel?.decided_by === "operator" && <Tag tone="accent">Bạn chọn</Tag>}
                {sel?.status === "accepted" && <Tag tone="proof">Đã duyệt</Tag>}
                {gap && <Tag tone="cue">Thiếu hình</Tag>}
                {!sel && <Tag>Chưa tìm clip</Tag>}
              </div>
            </div>
          </div>
          <div className="ml-10">
            {gap && <p className="mt-2 text-[13px] text-cue">Chưa có hình cho câu này. Video sẽ hiện một nền trơn kèm phụ đề, cho tới khi bạn quay thêm, thêm footage, hoặc sửa câu.</p>}
            {sel && !gap && sel.reason && (
              <details className="ai-card group mt-3 px-3 py-2.5 text-[13px]">
                <summary className="flex cursor-pointer list-none gap-2"><Icon name="sparkles" size={14} className="mt-0.5 text-ai" />
                  <span className="min-w-0 flex-1"><span className="font-medium text-ai">Vì sao chọn </span><span className="line-clamp-2 text-mute group-open:line-clamp-none">{sel.reason}</span></span></summary>
              </details>
            )}
            {gap && !locked && (
              <form className="mt-3 grid max-w-xl gap-2 2xl:grid-cols-[minmax(0,1fr)_auto]" onSubmit={(e) => { e.preventDefault(); if (query.trim()) findStock(); }}>
                <label htmlFor={`stock-${shot.shot_id}`} className="sr-only">Từ khoá tìm clip stock</label>
                <input id={`stock-${shot.shot_id}`} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Từ khoá tiếng Anh, ví dụ: fishing boat at sea" className="h-9 min-w-0 px-3" />
                <span><Button disabled={!query.trim()} onClick={findStock}><Icon name="globe" size={15} />Tìm clip stock miễn phí</Button></span>
                {stock && <p className="text-[13px] text-mute 2xl:col-span-2">{stock}</p>}
              </form>
            )}
            {sel && sel.alternates.length > 0 && !locked && (
              <div className="mt-3">
                <p className="eyebrow mb-1.5">Phương án khác</p>
                <ul className="flex flex-wrap gap-2">
                  {sel.alternates.map((a: Candidate, i: number) => (
                    <li key={a.moment_id} className="w-[124px]">
                      <button type="button" onClick={() => act("swap", { alternate: i })} title={a.reason} className="group block w-full text-left">
                        <span className="relative block overflow-hidden rounded-md ring-1 ring-line transition-shadow group-hover:ring-accent">
                          <img src={a.frame_url} alt="" className="aspect-video w-full bg-black object-cover opacity-75 transition-opacity group-hover:opacity-100" />
                          <TimeChip className="absolute bottom-1 left-1 !h-[18px] !px-1.5 !text-[10px]">{timecode(a.t_in)}</TimeChip>
                          <span className="absolute inset-0 hidden place-items-center bg-black/40 text-[11.5px] font-medium group-hover:grid">Dùng cảnh này</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px]">
              {sel && !gap && !locked && <button type="button" className="link" onClick={() => act("gap")}>Không clip nào hợp</button>}
              <details className="group w-full">
                <summary className="link inline-flex cursor-pointer list-none items-center gap-1"><Icon name="edit" size={13} />{notes.length ? `Ghi chú: ${notes.join(", ")}` : "Thêm ghi chú cho câu này"}</summary>
                <form className="panel-raised mt-2 grid max-w-xl gap-3 p-3.5" onSubmit={(e) => { e.preventDefault(); saveNotes(); }}>
                  <label className="grid gap-1"><span className="text-mute">Hình cần có (dùng để tìm clip khi lời dẫn không tả hình)</span><input value={brief ?? shot.brief ?? ""} onChange={(e) => setBrief(e.target.value)} placeholder="Ví dụ: cận cảnh bàn tay rót cà phê" className="px-3" /></label>
                  <label className="grid gap-1"><span className="text-mute">Chữ trên màn hình (để trống thì hiện đúng lời dẫn)</span><input value={screen ?? shot.screen_text ?? ""} onChange={(e) => setScreen(e.target.value)} placeholder="Ví dụ: Hội An, 6 giờ sáng" className="px-3" /></label>
                  <div><Button size="sm" disabled={brief === null && screen === null} onClick={saveNotes}>Lưu ghi chú</Button></div>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-3">
                    <label className="flex items-center gap-2 text-mute">Giữ hình ít nhất<input type="number" min="0" step="0.5" defaultValue={shot.target_seconds ?? ""} onBlur={(e) => note({ target_seconds: e.target.value })} className="mono h-8 w-20 px-2" />giây</label>
                    <label className="flex min-w-0 flex-1 items-center gap-2 text-mute">Âm thanh<input defaultValue={shot.sound_cue ?? ""} onBlur={(e) => note({ sound_cue: e.target.value })} placeholder="Ví dụ: tiếng chợ, ngừng nhạc" className="h-8 min-w-0 flex-1 px-2" /></label>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                    <label className="flex items-center gap-2"><input type="checkbox" checked={shot.is_fact} onChange={(e) => note({ is_fact: e.target.checked })} />Câu này nêu một dữ kiện</label>
                    {shot.is_fact && (sources.length ? <select aria-label="Nguồn của dữ kiện" value={shot.source ?? ""} onChange={(e) => note({ source: e.target.value })} className="h-8 pl-2"><option value="">Chưa gắn nguồn</option>{sources.map((src) => <option key={src.title}>{src.title}</option>)}</select>
                      : <span className="text-cue">Thêm nguồn ở bảng Nguồn tham khảo bên phải rồi gắn vào đây.</span>)}
                    {shot.is_fact && shot.fact_check && <Tag tone={VERDICT[shot.fact_check.verdict][1]}>{VERDICT[shot.fact_check.verdict][0]}</Tag>}
                  </div>
                  {shot.is_fact && shot.fact_check && (shot.fact_check.quote || shot.fact_check.note) && (
                    <p className="border-l-2 border-edge pl-2 text-[12.5px] text-mute">{shot.fact_check.quote && <>“{shot.fact_check.quote}” </>}{shot.fact_check.source && <span className="text-faint">({shot.fact_check.source}) </span>}{shot.fact_check.note}</p>)}
                </form>
              </details>
            </div>
          </div>
        </div>
        <div>
          {sel && !gap && sel.asset && sel.t_in != null && sel.t_out != null ? (
            <>
              <Clip url={sel.asset.proxy_url} tIn={sel.t_in} tOut={sel.t_out} poster={sel.frame_url ?? sel.asset.thumbnail_url} />
              <p className="mt-1.5 flex items-center gap-2 text-[12px] text-mute"><Icon name="film" size={13} className="text-faint" /><span className="min-w-0 flex-1 truncate">{sel.asset.name}</span>
                <span className="mono shrink-0 text-faint">{sel.asset.still ? "ảnh tĩnh" : `${timecode(sel.t_in)}–${timecode(sel.t_out)}`}</span></p>
            </>
          ) : <div className={`grid aspect-video place-items-center rounded-lg text-[13px] ${gap ? "hatch-cue border border-dashed border-cue/60 text-cue" : "border border-dashed border-edge bg-raised/50 text-faint"}`}>
                <span className="flex flex-col items-center gap-1.5"><Icon name={gap ? "alert" : "image"} size={20} />{gap ? "Thiếu hình" : "Chưa có clip"}</span></div>}
        </div>
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
    <div className="panel p-3">
      <div className="flex h-16 gap-0.5 overflow-hidden rounded-md" role="list" aria-label="Bản dựng theo thời gian">
        {items.map(({ s, d }, i) => (
          <div key={s.shot_id} role="listitem" title={`${i + 1}. ${s.text}`} style={{ width: `${(d / total) * 100}%` }}
               className={`relative min-w-0 ${s.selection?.status === "gap" ? "hatch-cue bg-raised" : !s.selection ? "hatch bg-raised" : "bg-black"}`}>
            {s.selection && s.selection.status !== "gap" && (s.selection.frame_url ?? s.selection.asset?.thumbnail_url) && <img src={(s.selection.frame_url ?? s.selection.asset?.thumbnail_url)!} alt="" className="h-full w-full object-cover opacity-90" />}
            <span className="mono absolute left-1 top-1 rounded bg-black/70 px-1 text-[10px]">{i + 1}</span>
          </div>
        ))}
      </div>
      <div className="mono mt-1.5 flex text-[10.5px] text-faint">
        {items.map(({ s, d }) => { const at = t; t += d; return <span key={s.shot_id} style={{ width: `${(d / total) * 100}%` }} className="truncate">{timecode(at)}</span>; })}
        <span className="ml-auto pl-1">{timecode(total)}</span>
      </div>
    </div>
  );
}

function PackagePanel({ render, reload }: { render: RenderItem; reload: () => void }) {
  const pkg = render.package;
  const base = `/api/v1/renders/${render.render_id}/package`;
  if (!pkg) return <div className="panel p-4"><Button kind="primary" onClick={async () => { await post(base, {}); reload(); }}><Icon name="layers" />Chuẩn bị gói xuất bản</Button><p className="mt-2 text-[13px] text-mute">Tạo file video, phụ đề rời và ảnh đại diện trong một thư mục để bạn đăng tay.</p></div>;
  return (
    <div className="panel p-4">
      <h3 className="mb-1 flex items-center gap-2 font-semibold"><Icon name="layers" size={16} className="text-accent" />Gói xuất bản</h3>
      <p className="mb-3 text-[13px] text-mute">Chọn ảnh đại diện. Mọi file nằm trong thư mục <span className="mono break-all text-ink">{pkg.folder}</span></p>
      <div className="mb-3 grid grid-cols-3 gap-2">
        {pkg.thumbnails.map((name) => (
          <button key={name} type="button" aria-pressed={pkg.thumbnail === name} onClick={async () => { await post(base, { thumbnail: name }); reload(); }}
                  className={`overflow-hidden rounded-md ring-2 transition ${pkg.thumbnail === name ? "ring-accent" : "opacity-60 ring-transparent hover:opacity-100"}`}>
            <img src={`${base}/${name}`} alt="Ảnh đại diện ứng viên" className="aspect-video w-full object-cover" />
          </button>
        ))}
      </div>
      <p className="font-medium">{pkg.title}</p>
      <p className="mb-3 line-clamp-3 text-[13px] text-mute">{pkg.description}</p>
      <div className="flex flex-wrap gap-2">
        <a className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${pkg.video}`} download><Icon name="download" size={14} />Video</a>
        <a className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${pkg.captions}`} download><Icon name="captions" size={14} />Phụ đề (SRT)</a>
        <a className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${pkg.thumbnail}`} download><Icon name="image" size={14} />Ảnh đại diện</a>
      </div>
    </div>
  );
}

const CRITERIA: Record<string, string> = { hop_khan_gia: "Hợp người xem", co_hinh: "Có hình trong kho", moi_la: "Mới lạ", de_lam: "Dễ làm" };
const TASK_STATES: Record<string, string> = { working: "Đang làm", waiting_operator: "Chờ bạn", done: "Xong", failed: "Dừng vì lỗi" };

/** What the producer agent did for this project, role by role, in the order it happened. */
function AgentLog({ projectId }: { projectId: string }) {
  const { data } = usePoll<{ tasks: AgentTask[] }>(`/api/v1/agent/tasks?project_id=${projectId}`, 3000);
  const task = data?.tasks[0];
  if (!task) return null;
  return (
    <details className="ai-card mb-6 px-4 py-3" open={task.status !== "done"}>
      <summary className="flex cursor-pointer list-none items-center gap-2.5 font-medium">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-ai/15 text-ai"><Icon name="sparkles" size={15} /></span>Trợ lý sản xuất
        <Tag tone={task.status === "waiting_operator" ? "cue" : task.status === "failed" ? "tally" : task.status === "done" ? "proof" : "ai"}>{TASK_STATES[task.status] ?? task.status}</Tag>
        <span className="ml-auto truncate text-[12.5px] font-normal text-mute">{task.goal}</span><Icon name="down" size={14} className="text-faint" />
      </summary>
      <ol className="mt-3 grid gap-1.5 border-t border-ai/15 pt-3">
        {task.log.map((e, i) => <li key={i} className="grid grid-cols-[4.5rem_7rem_minmax(0,1fr)] gap-2 text-[13px]"><span className="mono text-faint">{new Date(e.at * 1000).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}</span><span className="truncate text-ai">{e.role}</span><span>{e.text}</span></li>)}
      </ol>
    </details>
  );
}

const STEPS = [["Kịch bản", "edit"], ["Chọn clip", "sparkles"], ["Duyệt clip", "check"], ["Dựng video", "scissors"], ["Duyệt bản dựng", "play"]] as const;

/** Where the video stands: five stations on one line. The current one is lit; the two review gates turn amber when they wait. */
function Pipeline({ step }: { step: number }) {
  return (
    <ol className="panel mb-6 flex items-center gap-2 overflow-x-auto px-4 py-3.5" aria-label="Các bước làm video">
      {STEPS.map(([label, icon], i) => {
        const done = i < step, now = i === step, gate = now && (i === 2 || i === 4);
        return (
          <li key={label} aria-current={now ? "step" : undefined} className={`flex min-w-0 items-center gap-2.5 ${i < STEPS.length - 1 ? "flex-1" : ""}`}>
            <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-full border text-[12px] ${done ? "border-proof/40 bg-proof/15 text-proof" : gate ? "border-cue/60 bg-cue/15 text-cue shadow-[0_0_14px_-2px_var(--color-cue)]" : now ? "border-accent/60 bg-accent/15 text-accent shadow-[0_0_14px_-2px_var(--color-accent)]" : "border-line bg-raised text-faint"}`}>
              <Icon name={done ? "check" : icon} size={15} /></span>
            <span className={`whitespace-nowrap text-[13px] ${now ? "font-medium text-ink" : done ? "hidden text-mute lg:inline" : "hidden text-faint lg:inline"}`}>{label}</span>
            {i < STEPS.length - 1 && <span className={`h-px min-w-4 flex-1 ${done ? "bg-proof/40" : "bg-line"}`} />}
          </li>
        );
      })}
    </ol>
  );
}

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
  const { data: prefs } = usePoll<Settings>("/api/v1/settings", 30000);
  const cut = useRef<HTMLVideoElement>(null);
  const stored = p ? scriptText(p.shots) : null;
  const last = useRef<string | null>(null);
  // The editor follows the stored script (after a reorder on the timeline, for example) unless the operator has typed something not yet saved.
  useEffect(() => { if (stored === null) return; if (text === null || text.trim() === (last.current ?? "").trim()) setText(stored); last.current = stored; }, [stored]);
  if (!p) return <Page title="Dự án" back={{ label: "Dự án", onClick: back }}><p className="text-mute">Đang mở dự án…</p></Page>;
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setNote(null); try { await fn(); } catch (e) { setNote((e as Error).message); } setBusy(false); reload(); };
  const saved = scriptText(p.shots);
  const dirty = text !== null && text.trim() !== saved.trim();
  const matching = p.match && ["queued", "running"].includes(p.match.status);
  const reviewing = p.match?.status === "waiting_review";
  const approved = !!p.script?.match_approved;
  const rendering = p.render && ["queued", "running"].includes(p.render.status);
  const latest = p.renders.find(() => true);
  const renderReview = p.render?.status === "waiting_review";
  const step = !p.script ? 0 : !p.match ? 1 : matching ? 1 : reviewing ? 2 : !approved ? 1 : !p.render || rendering ? 3 : renderReview ? 4 : 5;
  const gaps = p.shots.filter((s) => s.selection?.status === "gap").length;
  const st = projectState(p);
  const patch = (body: Record<string, unknown>) => run(() => post(`/api/v1/projects/${id}`, body, "PATCH"));
  const lines = (text ?? "").split("\n").filter((l) => l.trim() && !l.trim().startsWith("#")).length;
  // The one thing to do next, always in the same place.
  const next = dirty ? { label: "Lưu kịch bản", icon: "check", go: () => run(() => post(`/api/v1/projects/${id}/script`, { lines: (text ?? "").split("\n") }, "PUT")) }
    : !p.script ? null
    : reviewing ? { label: "Duyệt các clip này", icon: "check", go: () => run(() => post(`/api/v1/projects/${id}/match/approve`)) }
    : renderReview ? { label: "Duyệt bản dựng", icon: "check", go: () => run(() => post(`/api/v1/projects/${id}/render/decision`, { approve: true })) }
    : !p.match && !approved ? { label: "Tìm clip cho kịch bản", icon: "sparkles", go: () => run(() => post(`/api/v1/projects/${id}/match`)) }
    : approved && !latest && !rendering ? { label: "Dựng video", icon: "scissors", go: () => run(() => post(`/api/v1/projects/${id}/render`)) }
    : null;
  const field = "field-label";
  const card = "panel grid gap-4 p-4";
  const facts = (p?.shots ?? []).filter((s) => s.is_fact);
  return (
    <Page title={p.title} back={{ label: "Tất cả dự án", onClick: back }} wide
          note={<span className="flex flex-wrap items-center gap-x-3 gap-y-1"><Tag tone={st.tone}>{st.label}</Tag><span className="flex items-center gap-1.5"><Icon name="captions" size={13} />{p.shots.length} câu</span>
            <span className="flex items-center gap-1.5"><Icon name="image" size={13} />{FORMATS[p.format] ?? p.format}</span>{latest && <span className="mono flex items-center gap-1.5"><Icon name="play" size={12} />{timecode(latest.qc.duration)}</span>}
            {p.template && <span className="flex items-center gap-1.5"><Icon name="layers" size={13} />{p.template}</span>}</span>}
          tabs={<Tabs value={tab} onChange={(k) => { setTab(k); document.querySelector("main .overflow-y-auto")?.scrollTo(0, 0); }} items={[{ key: "work", label: "Làm video", icon: "edit" }, { key: "timeline", label: "Dòng thời gian", icon: "timeline" }, { key: "board", label: "Bảng theo dõi", icon: "board" }]} />}
          actions={next && <Button kind="primary" disabled={busy || (next.label === "Lưu kịch bản" && !(text ?? "").trim())} onClick={next.go}><Icon name={next.icon} />{next.label}</Button>}>
      {tab === "work" && <Pipeline step={step} />}
      {note && <p className="mb-5 flex items-center gap-2 rounded-xl border border-tally/40 bg-tally/10 px-4 py-3 text-tally"><Icon name="alert" />{note}</p>}
      <AgentLog projectId={id} />
      {tab === "board" && <Board project={p} />}
      {tab === "timeline" && <Timeline project={p} reload={reload} busy={busy} rerender={() => run(() => post(`/api/v1/projects/${id}/render`))} />}

      <div className={`grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_360px] ${tab === "work" ? "" : "hidden"}`}>
        <div className="grid min-w-0 gap-10">
          <Section title="Kịch bản" icon="edit" note="Mỗi dòng là một câu lời dẫn; hệ thống tìm một clip cho từng câu. Dòng bắt đầu bằng dấu # là tên một cảnh.">
            <div className={`panel overflow-hidden ${dirty ? "glow" : ""}`}>
              <div className="flex flex-wrap items-center gap-3 border-b border-line bg-raised/40 px-4 py-2 text-[12px] text-mute">
                <span className="mono">{p.script ? `v${p.script.version}` : "bản nháp"}</span><span className="mono">{lines} câu</span>
                {dirty && <span className="flex items-center gap-1.5 text-accent"><span className="h-1.5 w-1.5 rounded-full bg-accent" />Chưa lưu</span>}
                <span className="ml-auto" />
                <Button size="sm" disabled={busy || !dirty || !(text ?? "").trim()} onClick={() => run(() => post(`/api/v1/projects/${id}/script`, { lines: (text ?? "").split("\n") }, "PUT"))}>Lưu kịch bản</Button>
              </div>
              <textarea value={text ?? ""} onChange={(e) => setText(e.target.value)} rows={Math.max(6, (text ?? "").split("\n").length + 1)} aria-label="Kịch bản"
                        className="bare block w-full !rounded-none px-5 py-4 text-[15px] leading-[1.95]" placeholder="Chợ Hội An buổi sáng tấp nập người mua kẻ bán." />
              <form className="flex flex-wrap items-center gap-2 border-t border-line bg-ai/[0.04] px-4 py-2.5" onSubmit={(e) => e.preventDefault()}>
                <Icon name="sparkles" size={15} className="text-ai" />
                <label htmlFor="topic" className="sr-only">Chủ đề để viết nháp</label>
                <input id="topic" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Viết nháp từ kho footage — nhập chủ đề, ví dụ: một buổi sáng ở chợ" className="bare h-8 min-w-0 flex-1 px-1" />
                <Button kind="ai" size="sm" disabled={busy || !topic.trim()} onClick={() => run(async () => { const r = await post<{ lines: string[] }>(`/api/v1/projects/${id}/draft`, { topic }); if (r.lines.length) setText(r.lines.join("\n")); else setNote("Mô hình không viết được câu nào. Hãy thử chủ đề khác."); })}>Viết nháp</Button>
              </form>
            </div>
            {dirty && p.script && <p className="mt-2 text-[12.5px] text-mute">Lưu sẽ tạo phiên bản kịch bản mới; các clip đã chọn cho phiên bản cũ không áp dụng nữa.</p>}
            {p.script && !dirty && (
              <div className="mt-3 rounded-xl border border-line bg-raised/30 px-4 py-3 text-[13px]">
                <div className="flex flex-wrap items-center gap-2"><Icon name="eye" size={15} className="text-ai" /><span className="font-medium">Phản biện kịch bản</span>
                  <span className="text-faint">{p.script.critique == null ? "Chưa xin nhận xét cho phiên bản này." : p.script.critique.length ? `${p.script.critique.length} điểm nên sửa` : "Không có điểm nào cần sửa."}</span>
                  <span className="ml-auto flex gap-2">
                    <Button size="sm" kind="ai" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/critique`))}>{p.script.critique == null ? "Xin nhận xét" : "Nhận xét lại"}</Button>
                    {!!p.script.critique?.length && <Button size="sm" disabled={busy || !!rendering} title="Tạo phiên bản kịch bản mới; clip của những câu bị đổi phải tìm lại" onClick={() => run(async () => { const r = await post<{ revised: boolean }>(`/api/v1/projects/${id}/revise`); if (!r.revised) setNote("Bản viết lại không khác bản cũ nên kịch bản được giữ nguyên."); setText(null); })}>Viết lại theo nhận xét</Button>}
                  </span></div>
                {!!p.script.critique?.length && <ul className="mt-2 grid gap-1.5">{p.script.critique.map((c, i) => (
                  <li key={i} className="flex gap-2.5"><span className="mono w-14 shrink-0 text-faint">{c.line ? `Câu ${c.line}` : "Cả bài"}</span><span className="min-w-0">{c.issue}{c.fix && <span className="text-mute"> {c.fix}</span>}</span></li>))}</ul>}
              </div>
            )}
          </Section>

          {p.script && (
            <Section title="Clip cho từng câu" icon="film"
                     note={reviewing ? <span className="text-cue">Xem từng clip, đổi sang phương án khác nếu cần, rồi duyệt.{gaps > 0 ? ` Còn ${gaps} câu chưa có hình.` : ""}</span> : matching ? <span className="text-ai">Đang tìm trong kho footage…</span> : approved ? <span className="text-proof">Đã duyệt</span> : undefined}
                     actions={<>
                       <Button size="sm" disabled={busy || !!matching || dirty} onClick={() => run(() => post(`/api/v1/projects/${id}/match`))}><Icon name="refresh" size={14} />{p.match ? "Tìm lại clip" : "Tìm clip cho kịch bản"}</Button>
                       {reviewing && <Button size="sm" kind="primary" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/match/approve`))}><Icon name="check" size={14} />Duyệt các clip này</Button>}
                     </>}>
              {matching && p.match && <div className="mb-3"><StageRail stages={p.match.stages} labels /></div>}
              {p.shots.some((s) => s.selection) && <div className="mb-4"><TimelineStrip shots={p.shots} /></div>}
              <ol className="grid gap-3">
                {p.shots.map((s, i) => <ShotRow key={s.shot_id} shot={s} n={i + 1} locked={!!rendering} changed={reload} heading={s.scene && s.scene !== p.shots[i - 1]?.scene ? s.scene : null} sources={p.research} />)}
              </ol>
            </Section>
          )}

          {approved && (
            <Section title="Bản dựng" icon="play"
                     note={rendering ? <span className="text-ai">Đang dựng…</span> : undefined}
                     actions={<>{rendering && p.render && <div className="w-48"><StageRail stages={p.render.stages} name={(k) => stageName(k, "edit.render")} /></div>}
                       <Button size="sm" disabled={busy || !!rendering} onClick={() => run(() => post(`/api/v1/projects/${id}/render`))}><Icon name="scissors" size={14} />{latest ? "Dựng lại" : "Dựng video"}</Button></>}>
              {p.render?.status === "failed" && <p className="mb-3 text-tally">Lần dựng vừa rồi thất bại ở bước {p.render.stages.find((s) => s.status === "failed")?.stage_key}. Xem chi tiết ở mục Tiến trình, rồi bấm dựng lại.</p>}
              {p.render?.status === "blocked" && <p className="mb-3 text-cue">Việc dựng đang dừng và cần bạn xử lý. Xem ở mục Tiến trình.</p>}
              {!latest && !rendering && <Empty icon="scissors" title="Sẵn sàng dựng">Các clip đã được duyệt. Bấm Dựng video để hệ thống đọc lời dẫn, vẽ phụ đề và ghép cảnh.</Empty>}
              {latest && (
                <div className="grid gap-6 2xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                  <div className="panel overflow-hidden bg-black p-0">
                    <video ref={cut} key={latest.url} src={latest.url} controls className={`w-full bg-black ${latest.qc.format === "portrait" ? "mx-auto aspect-[9/16] max-h-[70vh] w-auto" : latest.qc.format === "square" ? "mx-auto aspect-square max-h-[70vh] w-auto" : "aspect-video"}`} />
                  </div>
                  <div className="grid min-w-0 content-start gap-4">
                    {latest.qc.draft && <p className="cue-card px-4 py-3 text-[13px] text-cue">Bản nháp: một số cảnh được cắt từ bản xem vì không tìm thấy file gốc. Cắm lại ổ chứa footage rồi dựng lại để có bản cuối.</p>}
                    <div className="panel overflow-hidden">
                      <p className="eyebrow flex items-center justify-between border-b border-line px-4 py-2.5"><span>Kiểm tra chất lượng</span><Tag tone={latest.qc.passed ? "proof" : "tally"}>{latest.qc.passed ? "Đạt" : "Không đạt"}</Tag></p>
                      <div className="rows">
                        {Object.entries(latest.qc.checks).map(([name, ok]) => <p key={name} className="flex items-center justify-between gap-3 px-4 py-2 text-[13px]"><span>{name}</span><span className={`flex items-center gap-1 ${ok ? "text-proof" : "text-tally"}`}><Icon name={ok ? "check" : "x"} size={14} />{ok ? "Đạt" : "Không đạt"}</span></p>)}
                        {latest.qc.gaps > 0 && <p className="flex items-center justify-between gap-3 px-4 py-2 text-[13px]"><span>Câu dùng nền trơn vì thiếu hình</span><span className="mono text-cue">{latest.qc.gaps}</span></p>}
                      </div>
                    </div>
                    {(latest.qc.findings ?? []).length > 0 && (
                      <div className="ai-card overflow-hidden">
                        <p className="eyebrow flex items-center gap-2 border-b border-ai/15 px-4 py-2.5 !text-ai"><Icon name="sparkles" size={13} />Nên xem lại</p>
                        <ul className="rows">
                          {(latest.qc.findings ?? []).map((f, i) => (
                            <li key={i} className="px-4 py-2.5 text-[13px]"><p><span className={f.severity === "cao" ? "font-medium text-cue" : "font-medium"}>Câu {f.shot}, {f.check.toLowerCase()}:</span> {f.text}</p><p className="text-mute">{f.fix}</p></li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {renderReview && (
                      <div className="cue-card p-4">
                        <label htmlFor="why" className={field}>Ghi chú nếu chưa được</label>
                        <textarea id="why" value={why} onChange={(e) => setWhy(e.target.value)} rows={2} placeholder="Ví dụ: 0:07 cảnh xay cà phê bị tối, đổi cảnh khác" className="mb-3 w-full p-2.5" />
                        <div className="flex flex-wrap gap-2">
                          <Button onClick={() => setWhy(`${why}${why && !why.endsWith(" ") ? " " : ""}${timecode(cut.current?.currentTime ?? 0)} `)}><Icon name="clock" size={14} />Ghi mốc đang xem</Button>
                          <Button kind="primary" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/render/decision`, { approve: true }))}><Icon name="check" size={14} />Duyệt bản dựng</Button>
                          <Button disabled={busy} onClick={() => run(async () => { await post(`/api/v1/projects/${id}/render/decision`, { approve: false, comment: why }); setWhy(""); })}>Chưa được, dựng lại</Button>
                        </div>
                      </div>
                    )}
                    {p.render?.status === "succeeded" && <><p className="flex items-center gap-2 text-proof"><Icon name="check" />Bạn đã duyệt bản dựng này.</p><PackagePanel render={latest} reload={reload} /></>}
                    <p className="text-[13px]"><a className="inline-flex items-center gap-1.5 text-ink underline decoration-edge underline-offset-4 hover:decoration-mute" href={`/api/v1/renders/${latest.render_id}/edl`} download><Icon name="download" size={14} />Tải danh sách cắt (EDL)</a> <span className="text-mute">để dựng tiếp trong DaVinci Resolve từ file gốc</span></p>
                    {p.renders.length > 1 && (
                      <details className="panel group px-4 py-3">
                        <summary className="flex cursor-pointer list-none items-center justify-between text-[13px] text-mute hover:text-ink">Các bản dựng trước ({p.renders.length - 1})<Icon name="down" size={14} className="transition-transform group-open:rotate-180" /></summary>
                        <ul className="rows mt-2">
                          {p.renders.slice(1, 6).map((r) => (
                            <li key={r.render_id} className="py-2 text-[13px]"><a className="mono link" href={r.url} target="_blank" rel="noreferrer">{new Date(r.created_at * 1000).toLocaleString("vi-VN")}</a>
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
          <div className={card}>
            <h2 className="flex items-center gap-2 text-[14px] font-semibold"><Icon name="sliders" size={15} className="text-mute" />Thiết lập</h2>
            <div>
              <label htmlFor="template" className={field}>Mẫu định dạng</label>
              <select id="template" value={p.template ?? ""} disabled={busy} onChange={(e) => e.target.value && run(() => post(`/api/v1/projects/${id}/template`, { name: e.target.value }))} className="w-full pl-2.5">
                <option value="">Chưa dùng mẫu</option>{(prefs?.templates ?? []).map((t) => <option key={t.name}>{t.name}</option>)}
              </select>
              <p className="mt-1.5 text-[12px] text-faint">Mẫu đặt sẵn khung hình, giọng đọc, mức nhạc và cách duyệt. Sửa mẫu ở mục Hệ thống.</p>
            </div>
            <div>
              <p className={field} id="format-label">Khung hình</p>
              <div className="seg w-full" role="radiogroup" aria-labelledby="format-label">
                {Object.entries(FORMATS).map(([key, label]) => (
                  <button key={key} type="button" role="radio" aria-checked={p.format === key} disabled={busy} onClick={() => patch({ format: key })} className="flex-1">{label}</button>
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
              <p className="mt-1.5 text-[12px] text-faint">Nhạc tự nhỏ lại khi có lời dẫn.</p>
            </form>
            <form onSubmit={(e) => { e.preventDefault(); patch({ narration_dir: (takes ?? "").trim() || null }); }}>
              <label htmlFor="takes" className={field}>Lời dẫn bạn tự thu</label>
              <div className="flex gap-2">
                <input id="takes" value={takes ?? p.narration_dir ?? ""} onChange={(e) => setTakes(e.target.value)} placeholder="Thư mục chứa 1.wav, 2.m4a" className="min-w-0 flex-1 px-3" />
                <Button disabled={busy || takes === null || (takes ?? "") === (p.narration_dir ?? "")} onClick={() => patch({ narration_dir: (takes ?? "").trim() || null })}>Lưu</Button>
              </div>
              <p className="mt-1.5 text-[12px] text-faint">{!p.narration_dir ? "Đặt tên file theo số câu. Câu nào không có file thì dùng giọng máy." : p.own_takes.length ? `Đã có bản thu cho câu ${p.own_takes.join(", ")}. Các câu còn lại dùng giọng máy.` : "Chưa thấy file thu âm nào trong thư mục này."}</p>
            </form>
            <div><label htmlFor="due" className={field}>Ngày dự định đăng</label>
              <input id="due" type="date" defaultValue={p.due_date ?? ""} key={p.due_date ?? "none"} onChange={(e) => patch({ due_date: e.target.value })} className="mono mt-1.5 h-9 w-full px-3" /></div>
            <label className="flex items-start gap-2.5 rounded-lg border border-line bg-raised/50 p-3"><input type="checkbox" className="mt-0.5" checked={p.auto_accept} disabled={busy} onChange={(e) => patch({ auto_accept: e.target.checked ? 1 : 0 })} />
              <span className="text-[13px]">Tự duyệt clip<span className="block text-[12px] text-faint">Chỉ khi mọi câu đều có clip và mô hình chấm chắc chắn.</span></span></label>
          </div>

          <div className={card}>
            <div><h2 className="flex items-center gap-2 text-[14px] font-semibold"><Icon name="link" size={15} className="text-mute" />Nguồn tham khảo<span className="mono ml-auto text-[12px] font-normal text-faint">{p.research.length}</span></h2>
              <p className="mt-1 text-[12px] text-faint">Câu nào nêu dữ kiện thì gắn với một nguồn ở đây. Dữ kiện chưa có nguồn sẽ bị nêu ra khi kiểm tra bản dựng.</p></div>
            <ul className="rows empty:hidden">
              {p.research.map((src) => (
                <li key={src.title} className="py-2 text-[13px]"><div className="flex justify-between gap-2"><span className="min-w-0 font-medium">{/^https?:\/\//i.test(src.url) ? <a href={src.url} target="_blank" rel="noreferrer" className="underline decoration-edge underline-offset-2">{src.title}</a> : src.title}</span>
                  <button type="button" className="link shrink-0" onClick={() => patch({ research: p.research.filter((x) => x.title !== src.title) })}>Bỏ</button></div>
                  <p className="text-mute">{[src.publisher, src.date].filter(Boolean).join(", ")}</p>{src.passage && <p className="mt-0.5 border-l-2 border-edge pl-2 text-mute">“{src.passage}”</p>}</li>
              ))}
            </ul>
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; const url = String(new FormData(f).get("url") ?? "").trim(); if (url) run(async () => { await post(`/api/v1/projects/${id}/sources/read`, { url }); f.reset(); }); }}>
              <input name="url" type="url" aria-label="Địa chỉ trang web cần đọc" placeholder="Dán địa chỉ bài viết để hệ thống đọc" className="min-w-0 flex-1 px-3" />
              <Button type="submit" disabled={busy} title="Chỉ địa chỉ này được gửi ra ngoài máy"><Icon name="globe" size={14} />Đọc</Button>
            </form>
            {p.script && <div className="flex flex-wrap gap-2 border-t border-line pt-3">
              <Button size="sm" kind="ai" disabled={busy} onClick={() => run(async () => { const r = await post<{ found: number }>(`/api/v1/projects/${id}/facts/find`); if (!r.found) setNote("Không thấy câu nào nêu dữ kiện cần kiểm chứng."); })}>Tìm câu nêu dữ kiện</Button>
              <Button size="sm" disabled={busy || !p.shots.some((s) => s.is_fact)} title={p.shots.some((s) => s.is_fact) ? "So từng câu nêu dữ kiện với các nguồn ở trên" : "Chưa có câu nào được đánh dấu là dữ kiện"} onClick={() => run(() => post(`/api/v1/projects/${id}/facts/check`))}>Đối chiếu với nguồn</Button>
              {facts.length > 0 && <p className="w-full text-[12px] text-faint">{facts.length} câu nêu dữ kiện: {facts.filter((s) => s.fact_check?.verdict === "supported").length} có nguồn xác nhận, {facts.filter((s) => s.fact_check?.verdict === "contradicted").length} trái nguồn, {facts.filter((s) => !s.fact_check || s.fact_check.verdict === "not_found").length} chưa có căn cứ.</p>}
            </div>}
            <details className="group">
              <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[13px] text-accent"><Icon name="plus" size={14} />Tự nhập một nguồn</summary>
              <form className="mt-3 grid gap-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const src = Object.fromEntries(["title", "publisher", "date", "url", "passage"].map((k) => [k, String(f.get(k) ?? "")])); if (!src.title.trim()) return; patch({ research: [...p.research, src] }); e.currentTarget.reset(); }}>
                <input name="title" aria-label="Tên nguồn" placeholder="Tên nguồn, ví dụ: Niên giám thống kê 2025" className="px-3" />
                <div className="flex gap-2"><input name="publisher" aria-label="Nơi xuất bản" placeholder="Nơi xuất bản" className="min-w-0 flex-1 px-3" /><input name="date" aria-label="Ngày" placeholder="Ngày" className="w-24 px-3" /></div>
                <input name="url" aria-label="Đường dẫn" placeholder="Đường dẫn (nếu có)" className="px-3" />
                <textarea name="passage" aria-label="Đoạn trích" rows={2} placeholder="Đoạn trích chứng minh dữ kiện" className="p-2.5" />
                <div><Button type="submit">Thêm nguồn</Button></div>
              </form>
            </details>
          </div>

          {p.script && (
            <div className="ai-card grid gap-4 p-4">
              <div><h2 className="flex items-center gap-2 text-[14px] font-semibold"><Icon name="spark" size={15} className="text-ai" />Sinh hình bằng AI</h2>
                <p className="mt-1 text-[12px] text-mute">Cho phim hoạt hình, hoặc khi kho footage không có hình. Hệ thống sinh ảnh tĩnh cho mỗi câu để bạn duyệt, rồi mới sinh video.</p></div>
              {!p.generators.image || !p.generators.video ? (
                <p className="rounded-lg border border-cue/30 bg-cue/5 px-3 py-2 text-[12.5px] text-cue">Chưa có nhà cung cấp sinh ảnh và sinh video. Cần khoá API của một nhà cung cấp để bật.</p>
              ) : (
                <>
                  <form onSubmit={(e) => { e.preventDefault(); patch({ style: (style ?? "").trim() || null }); }}>
                    <label htmlFor="style" className={field}>Phong cách hình</label>
                    <div className="flex gap-2"><input id="style" value={style ?? p.style ?? ""} onChange={(e) => setStyle(e.target.value)} placeholder="Ví dụ: hoạt hình màu nước" className="min-w-0 flex-1 px-3" />
                      <Button disabled={busy || style === null} onClick={() => patch({ style: (style ?? "").trim() || null })}>Lưu</Button></div>
                  </form>
                  <form onSubmit={(e) => { e.preventDefault(); patch({ budget_cap: budget === "" || budget === null ? null : Number(budget) }); }}>
                    <label htmlFor="budget" className={field}>Ngân sách cho dự án (USD)</label>
                    <div className="flex gap-2"><input id="budget" type="number" min="0" step="0.5" value={budget ?? p.budget_cap ?? ""} onChange={(e) => setBudget(e.target.value)} placeholder="Không giới hạn" className="mono min-w-0 flex-1 px-3" />
                      <Button disabled={busy || budget === null} onClick={() => patch({ budget_cap: budget === "" || budget === null ? null : Number(budget) })}>Lưu</Button></div>
                    <p className="mono mt-1.5 text-[12px] text-mute">Đã tiêu {p.spent.toFixed(2)} USD{p.budget_cap != null ? ` trên ${p.budget_cap.toFixed(2)} USD` : ""}</p>
                    {p.budget_cap != null && <div className="mt-1.5"><Meter share={p.spent / p.budget_cap} tone={p.spent >= p.budget_cap ? "cue" : "ai"} /></div>}
                  </form>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button kind="ai" disabled={busy || dirty || (!!p.generate && ["queued", "running"].includes(p.generate.status))} onClick={() => run(() => post(`/api/v1/projects/${id}/generate`))}>{p.generate ? "Sinh lại" : "Sinh ảnh cho từng câu"}</Button>
                    {p.generate?.status === "waiting_review" && <Button kind="primary" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/generate/approve`))}>
                      {p.generate.stages.find((s) => s.status === "waiting_review")?.stage_key === "keyframes" ? "Duyệt ảnh, sinh video" : "Duyệt các clip này"}</Button>}
                    {p.generate && ["queued", "running"].includes(p.generate.status) && <span className="text-[13px] text-ai">Đang sinh…</span>}
                    {p.generate?.status === "blocked" && <span className="text-[13px] text-cue">Đang dừng, xem ở mục Tiến trình</span>}
                  </div>
                  {p.shots.some((s) => s.keyframe_url) && (
                    <ol className="grid grid-cols-3 gap-2">
                      {p.shots.map((s, i) => <li key={s.shot_id} title={`${i + 1}. ${s.text}`}>{s.keyframe_url ? <img src={s.keyframe_url} alt="" className="aspect-video w-full rounded-md bg-black object-cover" /> : <div className="aspect-video rounded-md bg-raised" />}</li>)}
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

type Filter = "all" | "active" | "waiting" | "done";
const FILTERS: [Filter, string][] = [["all", "Tất cả"], ["active", "Đang làm"], ["waiting", "Chờ bạn"], ["done", "Đã xong"]];

export default function Projects({ sub, go }: { sub: string | null; go: (to: string) => void }) {
  const { data, reload } = usePoll<Project[]>("/api/v1/projects", 5000);
  const [title, setTitle] = useState("");
  const [goal, setGoal] = useState("");
  const [format, setFormat] = useState("landscape");
  const [mode, setMode] = useState<"none" | "new" | "agent" | "ideas">(() => (new URLSearchParams(window.location.search).has("moi") ? "new" : "none"));
  const [filter, setFilter] = useState<Filter>("all");
  const [view, setView] = useState<"grid" | "list">(() => { try { return (localStorage.getItem("nx.projects.view") as "grid" | "list") ?? "grid"; } catch { return "grid"; } });
  const { data: ideas, reload: reloadIdeas } = usePoll<{ ideas: Idea[] }>("/api/v1/ideas", 60000);
  const [thinking, setThinking] = useState(false);
  const propose = async () => { setThinking(true); setAgentNote(null); try { await post("/api/v1/ideas"); } catch (e) { setAgentNote((e as Error).message); } setThinking(false); reloadIdeas(); };
  const { data: agent, reload: reloadAgent } = usePoll<{ tasks: AgentTask[] }>("/api/v1/agent/tasks", 4000);
  const [agentNote, setAgentNote] = useState<string | null>(null);
  const [urls, setUrls] = useState("");
  useEffect(() => { if (!sub && new URLSearchParams(window.location.search).has("moi")) setMode("new"); }, [sub, window.location.search]);
  if (sub) return <Detail key={sub} id={sub} back={() => go("/du-an")} />;
  const create = async () => { const p = await post<Project>("/api/v1/projects", { title: title.trim(), format }); setTitle(""); reload(); go(`/du-an/${p.project_id}`); };
  const assign = async () => { setAgentNote(null); try { const t = await post<AgentTask>("/api/v1/agent/tasks", { goal: goal.trim(), format, urls: urls.split("\n").map((u) => u.trim()).filter(Boolean) }); setGoal(""); setUrls(""); reloadAgent(); reload(); go(`/du-an/${t.project_id}`); } catch (err) { setAgentNote((err as Error).message); } };
  const working = new Map((agent?.tasks ?? []).filter((t) => t.status === "working" || t.status === "waiting_operator").map((t) => [t.project_id, t]));
  const setLook = (v: "grid" | "list") => { setView(v); try { localStorage.setItem("nx.projects.view", v); } catch { /* fine */ } };
  const formats = <Seg label="Khung hình" value={format} onChange={setFormat} items={Object.entries(FORMATS) as [string, string][]} />;
  const all = data ?? [];
  const bucket = (p: Project): Filter => { const st = projectState(p); return st.step === 5 ? "done" : st.tone === "cue" || st.tone === "tally" ? "waiting" : "active"; };
  const shown = all.filter((p) => filter === "all" || bucket(p) === filter);
  const toggle = (m: typeof mode) => { setMode(mode === m ? "none" : m); if (window.location.search) window.history.replaceState({}, "", "/du-an"); };
  return (
    <Page eyebrow="Sản xuất" title="Dự án" note="Mỗi dự án là một video, từ kịch bản tới bản dựng đã duyệt."
          actions={<><Button kind="quiet" onClick={() => toggle("ideas")}><Icon name="spark" />Gợi ý ý tưởng</Button><Button kind="ai" onClick={() => toggle("agent")}><Icon name="sparkles" />Giao cho trợ lý</Button><Button kind="primary" onClick={() => toggle("new")}><Icon name="plus" />Dự án mới</Button></>}>
      {mode === "new" && (
        <form className="panel glow rise mb-6 max-w-3xl p-5" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create(); }}>
          <div className="mb-3 flex items-center gap-2.5"><span className="grid h-8 w-8 place-items-center rounded-lg bg-accent/15 text-accent"><Icon name="clapper" size={16} /></span><p className="font-semibold">Video mới</p>
            <button type="button" onClick={() => toggle("new")} className="ml-auto text-faint hover:text-ink" aria-label="Đóng"><Icon name="x" /></button></div>
          <label htmlFor="title" className="field-label">Tên video</label>
          <div className="flex flex-wrap gap-2">
            <input id="title" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ví dụ: Một buổi sáng ở chợ Hội An" className="h-10 min-w-0 flex-1 px-3" />
            {formats}<Button kind="primary" disabled={!title.trim()} onClick={create}>Tạo dự án</Button>
          </div>
        </form>
      )}
      {mode === "agent" && (
        <form className="ai-card rise mb-6 max-w-3xl p-5" onSubmit={(e) => { e.preventDefault(); if (goal.trim()) assign(); }}>
          <div className="mb-1 flex items-center gap-2.5"><span className="grid h-8 w-8 place-items-center rounded-lg bg-ai/15 text-ai"><Icon name="sparkles" size={16} /></span><label htmlFor="goal" className="font-semibold">Video bạn muốn làm</label>
            <button type="button" onClick={() => toggle("agent")} className="ml-auto text-faint hover:text-ink" aria-label="Đóng"><Icon name="x" /></button></div>
          <p className="mb-3 ml-[42px] text-[13px] text-mute">Trợ lý tự viết kịch bản từ kho footage, tìm clip, lấp chỗ thiếu bằng clip stock miễn phí rồi dựng. Nó dừng lại chờ bạn duyệt clip và duyệt bản dựng.</p>
          <div className="flex flex-wrap gap-2">
            <input id="goal" autoFocus value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Ví dụ: một phút về buổi sáng ở chợ Hội An" className="h-10 min-w-0 flex-1 px-3" />
            {formats}<Button kind="primary" disabled={!goal.trim()} onClick={assign}>Giao việc</Button>
          </div>
          <details className="mt-3 text-[13px]"><summary className="cursor-pointer list-none text-accent">Cho trợ lý đọc trước vài bài viết</summary>
            <textarea value={urls} onChange={(e) => setUrls(e.target.value)} rows={3} aria-label="Địa chỉ các bài viết, mỗi dòng một địa chỉ" placeholder={"Mỗi dòng một địa chỉ, tối đa 5\nhttps://…"} className="mono mt-2 w-full p-2.5 text-[12.5px]" />
            <p className="mt-1 text-[12px] text-faint">Trợ lý đọc các trang này, rồi đối chiếu những câu nêu dữ kiện trong kịch bản với chúng. Chỉ địa chỉ được gửi ra ngoài máy.</p></details>
          {agentNote && <p className="mt-2 text-tally">{agentNote}</p>}
        </form>
      )}
      {mode === "ideas" && (
        <div className="panel rise mb-6 p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div><h2 className="flex items-center gap-2 text-[15px] font-semibold"><Icon name="spark" size={16} className="text-ai" />Ý tưởng làm được từ kho footage</h2><p className="text-[13px] text-mute">Mô hình đề xuất; điểm “có hình” được đo từ kho, không lấy theo ý mô hình. Ý tưởng có rủi ro xếp sau.</p></div>
            <div className="flex gap-2"><Button kind="ai" disabled={thinking} onClick={propose}>{thinking ? "Đang nghĩ…" : (ideas?.ideas.length ? "Gợi ý lại" : "Gợi ý ý tưởng")}</Button><Button kind="quiet" onClick={() => toggle("ideas")}><Icon name="x" /></Button></div>
          </div>
          {agentNote && <p className="mb-2 text-tally">{agentNote}</p>}
          {ideas && ideas.ideas.length === 0 && !thinking && <p className="text-mute">Chưa có gợi ý nào. Kho cần có footage đã được mô tả.</p>}
          <ul className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
            {(ideas?.ideas ?? []).map((it) => (
              <li key={it.title} className="panel-raised flex flex-col p-4">
                <div className="mb-1 flex items-start justify-between gap-3"><p className="font-medium">{it.title}</p><span className="mono shrink-0 rounded-md bg-accent/15 px-1.5 text-[12px] text-accent">{it.total}</span></div>
                <p className="mb-3 text-[13px] text-mute">{it.summary}</p>
                <dl className="mb-3 grid grid-cols-2 gap-x-5 gap-y-1.5 text-[12.5px]">
                  {Object.entries(CRITERIA).map(([key, name]) => (
                    <div key={key} className="flex items-center justify-between gap-2"><dt className="text-mute">{name}</dt>
                      <dd className="flex gap-0.5" aria-label={`${it.scores[key]} trên 5`}>{[1, 2, 3, 4, 5].map((n) => <span key={n} className={`h-1.5 w-3 rounded-full ${n <= (it.scores[key] ?? 0) ? "bg-gradient-to-r from-accent to-ai" : "bg-overlay"}`} />)}</dd></div>
                  ))}
                </dl>
                {it.risk && <p className="mb-3 text-[12.5px] text-cue">Rủi ro: {it.risk}</p>}
                <div className="mt-auto"><Button size="sm" kind="ai" onClick={async () => { const t = await post<AgentTask>("/api/v1/agent/tasks", { goal: `${it.title}. ${it.summary}`, format }); reloadAgent(); reload(); go(`/du-an/${t.project_id}`); }}><Icon name="sparkles" size={14} />Giao cho trợ lý làm</Button></div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {data && data.length === 0 && <Empty icon="clapper" title="Chưa có dự án nào" action={<Button kind="primary" onClick={() => setMode("new")}><Icon name="plus" />Dự án mới</Button>}>Bấm Dự án mới để tự viết kịch bản, hoặc Giao cho trợ lý để nó viết và dựng bản đầu tiên từ kho footage của bạn.</Empty>}
      {all.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <div className="seg" role="radiogroup" aria-label="Lọc dự án">
            {FILTERS.map(([k, name]) => { const n = k === "all" ? all.length : all.filter((p) => bucket(p) === k).length; return (
              <button key={k} type="button" role="radio" aria-checked={filter === k} onClick={() => setFilter(k)}>{name}<span className="mono ml-1.5 text-[11px] text-faint">{n}</span></button>); })}
          </div>
          <span className="ml-auto" />
          <div className="seg" role="radiogroup" aria-label="Cách xem">
            <button type="button" role="radio" aria-checked={view === "grid"} onClick={() => setLook("grid")} aria-label="Lưới"><Icon name="grid" size={15} /></button>
            <button type="button" role="radio" aria-checked={view === "list"} onClick={() => setLook("list")} aria-label="Danh sách"><Icon name="list" size={15} /></button>
          </div>
        </div>
      )}
      {shown.length === 0 && all.length > 0 && <p className="panel px-5 py-6 text-mute">Không có dự án nào ở mục này.</p>}
      {view === "grid" ? (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {shown.map((p) => {
            const st = projectState(p); const task = working.get(p.project_id); const latest = p.renders[0];
            return (
              <li key={p.project_id}><a href={`/du-an/${p.project_id}`} onClick={(e) => { e.preventDefault(); go(`/du-an/${p.project_id}`); }}
                 className="panel group block overflow-hidden transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-edge">
                <div className="relative"><Filmstrip shots={p.shots} height={150} />
                  <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-surface via-surface/10 to-transparent" />
                  <span className="absolute left-2.5 top-2.5 rounded-full bg-black/55 backdrop-blur"><Tag tone={st.tone}>{st.label}</Tag></span>
                  {latest && <span className="chip mono absolute right-2.5 top-2.5"><Icon name="play" size={11} />{timecode(latest.qc.duration)}</span>}
                  {task && <span className="chip absolute bottom-2.5 left-2.5 !text-ai"><Icon name="sparkles" size={12} />Trợ lý đang làm</span>}
                </div>
                <div className="px-4 pb-4 pt-1.5">
                  <p className="truncate text-[15px] font-medium">{p.title}</p>
                  <p className="mt-0.5 truncate text-[12.5px] text-mute">{p.shots.length ? `${p.shots.length} câu` : "Chưa có kịch bản"} · {FORMATS[p.format] ?? p.format}</p>
                  <div className="mt-3 flex items-center justify-between"><Steps step={st.step} tone={st.tone} /><span className="mono text-[11px] text-faint">{new Date(p.created_at * 1000).toLocaleDateString("vi-VN")}</span></div>
                </div>
              </a></li>
            );
          })}
        </ul>
      ) : (
        <ul className="panel rows overflow-hidden">
          {shown.map((p) => {
            const st = projectState(p); const task = working.get(p.project_id); const latest = p.renders[0];
            return (
              <li key={p.project_id}>
                <a href={`/du-an/${p.project_id}`} onClick={(e) => { e.preventDefault(); go(`/du-an/${p.project_id}`); }}
                   className="grid items-center gap-x-6 gap-y-3 p-3 transition-colors hover:bg-white/[0.02] sm:grid-cols-[220px_minmax(0,1fr)_auto]">
                  <Filmstrip shots={p.shots} height={56} className="rounded-md" />
                  <div className="min-w-0">
                    <p className="truncate text-[15px] font-medium">{p.title}</p>
                    <p className="truncate text-[13px] text-mute">{p.shots.length ? `${p.shots.length} câu` : "Chưa có kịch bản"}, {FORMATS[p.format] ?? p.format}{latest ? <span className="mono">, {timecode(latest.qc.duration)}</span> : ""}{task ? <span className="text-ai">, trợ lý đang làm</span> : ""}</p>
                  </div>
                  <div className="flex items-center gap-4 sm:justify-end sm:pr-2"><Steps step={st.step} tone={st.tone} /><span className="sm:w-40 sm:text-right"><Tag tone={st.tone}>{st.label}</Tag></span></div>
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </Page>
  );
}
