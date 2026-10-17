import { t as tr, tv, locale } from "./i18n";
import { useEffect, useMemo, useRef, useState } from "react";
import { call, megabytes, post, timecode, usePoll, type Asset, type Hit, type Moment, type Op, type Project, type Publication, type Publishing, type Radar, type RenderItem, type Rights, type RoughPlan, type TrashView } from "./api";

const LEVEL: Record<string, string> = { segment: tr("CẢNH"), scene: tr("CẢNH"), event: tr("SỰ KIỆN"), speech: tr("LỜI NÓI"), note: tr("GHI CHÚ"), frame: tr("KHUNG HÌNH"), text: tr("CHỮ TRÊN HÌNH"), sound: tr("ÂM THANH") };
import { ask, Button, Icon, Page, RangeStrip, Seg, SkeletonCards, Spinner, Tabs, TimeChip, toast, goTo } from "./parts";
import { StructureStrip } from "./Structure";
import { AssetProfile } from "./Profile";
import { AssetDossier } from "./Dossier";
import { AssetStory } from "./Story";

function AddFootage({ onDone }: { onDone: () => void }) {
  const [path, setPath] = useState("");
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!path.trim()) return;
    setBusy(true);
    try {
      const r = await call<{ registered: unknown[] }>("/api/v1/assets/register", { method: "POST", body: JSON.stringify({ path: path.trim() }) });
      setNote({ ok: true, text: r.registered.length ? tv`Đã thêm ${r.registered.length} file. Hệ thống đang xử lý.` : tr("Thư mục này không có file nào dùng được.") });
      setPath(""); onDone();
    } catch (e) { setNote({ ok: false, text: (e as Error).message }); }
    setBusy(false);
  };
  return (
    <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <label htmlFor="path" className="sr-only">{tr("Đường dẫn tới video hoặc thư mục")}</label>
      <span className="relative min-w-0 flex-1"><Icon name="folder" size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
        <input id="path" value={path} onChange={(e) => setPath(e.target.value)} placeholder={tr("Đường dẫn tới video, ảnh, nhạc hoặc thư mục, ví dụ /Volumes/Footage/DaLat")} className="mono h-10 w-full pl-9 pr-3 text-[13px]" /></span>
      <Button kind="primary" disabled={busy || !path.trim()} onClick={submit}>{tr("Thêm vào thư viện")}</Button>
      {note && <p className={`w-full text-[13px] ${note.ok ? "text-proof" : "text-tally"}`}>{note.text}</p>}
    </form>
  );
}

function Moments({ asset, t, seek, similar }: { asset: Asset; t: number; seek: (s: number) => void; similar: (m: Moment) => void }) {
  const { data, reload } = usePoll<{ video: Moment | null; segments: Moment[]; frames: Moment[] }>(`/api/v1/assets/${asset.asset_id}/moments`, 6000);
  const [editing, setEditing] = useState<string | null>(null);
  const [looking, setLooking] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const deepen = async (id: string) => { setLooking(id); setFailed(null); try { await post(`/api/v1/moments/${id}/deepen`); } catch (e) { setFailed((e as Error).message); } setLooking(null); reload(); };
  const [draft, setDraft] = useState("");
  if (!data) return null;
  if (!data.segments.length) return <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-[13px] text-mute">{asset.understand && asset.understand.status !== "succeeded" ? tr("Hệ thống đang xem video này. Mô tả sẽ hiện ra khi xong.") : tr("Video này chưa được mô tả.")}</p>;
  const save = async (id: string) => { await post(`/api/v1/moments/${id}`, { text: draft }, "PATCH"); setEditing(null); reload(); };
  return (
    <div className="grid gap-3">
      {data.video && <div className="ai-card p-3.5 text-[13px]"><p className="eyebrow mb-1.5 flex items-center gap-1.5 !text-ai"><Icon name="sparkles" size={12} />{tr("Tóm tắt video")}</p><p className="leading-relaxed">{data.video.text}</p></div>}
      {failed && <p className="text-[12.5px] text-tally">{failed}</p>}
      <ol className="grid gap-2">
        {data.segments.map((m) => {
          const now = t >= m.t_start && t < m.t_end;
          const frames = data.frames.filter((f) => f.t_start >= m.t_start && f.t_start < m.t_end);
          return (
            <li key={m.moment_id} className={`rounded-xl border p-2.5 transition-colors ${now ? "border-accent/50 bg-accent/[0.06]" : "border-line bg-raised/40 hover:border-edge"}`}>
              <div className="flex gap-3">
                <button type="button" onClick={() => seek(m.t_start)} className="group relative w-28 shrink-0 overflow-hidden rounded-md bg-black" title={tr("Tới đoạn này")}>
                  {m.frame_url ? <img src={m.frame_url} alt="" loading="lazy" className="aspect-video w-full object-cover transition-opacity group-hover:opacity-80" /> : <span className="grid aspect-video place-items-center text-faint"><Icon name="film" /></span>}
                  <TimeChip className="absolute bottom-1 left-1 !h-[18px] !px-1.5 !text-[10px]">{timecode(m.t_start)}</TimeChip>
                </button>
                <div className="min-w-0 flex-1">
                  {m.title && <p className={`mb-0.5 text-[13px] font-medium ${now ? "text-accent" : ""}`}>{m.title}</p>}
                  {editing === m.moment_id ? (
                    <div><textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} className="w-full p-2 text-[13px]" aria-label={tr("Sửa mô tả")} />
                      <div className="mt-1.5 flex gap-2"><Button size="sm" kind="primary" onClick={() => save(m.moment_id)}>{tr("Lưu mô tả")}</Button><Button size="sm" onClick={() => setEditing(null)}>{tr("Bỏ")}</Button></div></div>
                  ) : <p className="line-clamp-3 text-[12.5px] leading-relaxed text-mute">{m.text}</p>}
                </div>
              </div>
              {editing !== m.moment_id && (
                <div className="mt-2 flex items-center gap-3 pl-[124px] text-[11.5px]">
                  <span className="mono rounded bg-overlay px-1.5 text-faint">{tr("CẢNH")}</span>
                  {m.source === "human" && <span className="text-accent">{tr("Bạn đã sửa")}</span>}
                  <span className="ml-auto" />
                  {frames.length === 0 && <button type="button" className="link" disabled={looking !== null} title={tr("Mô hình xem từng khung hình của đoạn này và tả riêng từng khung")} onClick={() => deepen(m.moment_id)}>{looking === m.moment_id ? tr("Đang xem…") : tr("Xem kỹ từng khung")}</button>}
                  <button type="button" className="link" onClick={() => { setEditing(m.moment_id); setDraft(m.text); }}>{tr("Sửa")}</button>
                  <button type="button" className="flex items-center gap-1 text-ai hover:underline" onClick={() => similar(m)}><Icon name="sparkles" size={12} />{tr("Tìm cảnh giống")}</button>
                </div>
              )}
              {frames.length > 0 && (
                <ol className="mt-2.5 grid gap-1.5 border-t border-line pt-2.5">
                  {frames.map((f) => (
                    <li key={f.moment_id} className="flex gap-2.5 text-[12px]">
                      <button type="button" onClick={() => seek(f.t_start)} className="mono w-10 shrink-0 text-left text-accent hover:underline">{timecode(f.t_start)}</button>
                      <span className="min-w-0 leading-relaxed text-mute">{f.text}</span></li>))}
                </ol>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** The recording cut by its words: which sentences stay, which go and why. The operator may overrule any of them. */
function RoughCutPanel({ asset, seek }: { asset: Asset; seek: (s: number) => void }) {
  const [plan, setPlan] = useState<RoughPlan | null>(null);
  const [keep, setKeep] = useState<Set<number>>(new Set());
  const [note, setNote] = useState<string | null>(null);
  const open = async () => { const p = await call<RoughPlan>(`/api/v1/assets/${asset.asset_id}/roughcut`); setPlan(p); setKeep(new Set(p.sentences.filter((s) => s.keep).map((s) => s.index))); };
  const make = async () => { try { const p = await post<Project>(`/api/v1/assets/${asset.asset_id}/roughcut`, { keep: [...keep].sort((a, b) => a - b) }); window.history.pushState(null, "", `/du-an/${p.project_id}`); window.dispatchEvent(new PopStateEvent("popstate")); } catch (e) { setNote((e as Error).message); } };
  if (!plan) return <div className="ai-card flex flex-wrap items-center gap-3 p-3 text-[13px]"><Icon name="scissors" size={15} className="text-ai" /><span className="min-w-0 flex-1">{tr("Dựng thô theo lời nói: bỏ khoảng lặng, tiếng đệm và những câu nói lại.")}</span><Button size="sm" kind="ai" onClick={open}>{tr("Xem bản cắt đề xuất")}</Button></div>;
  const seconds = plan.sentences.filter((s) => keep.has(s.index)).reduce((sum, s) => sum + s.t_out - s.t_in, 0);
  return (
    <div className="ai-card p-3 text-[13px]">
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1"><Icon name="scissors" size={15} className="text-ai" /><span className="font-medium">{tr("Bản cắt đề xuất")}</span>
        <span className="mono text-mute">{tv`giữ ${timecode(seconds)} trên ${timecode(plan.source_seconds)}`}</span></p>
      <ol className="mt-2 grid gap-1">
        {plan.sentences.map((s) => (
          <li key={s.index} className="flex items-start gap-2">
            {s.take_of !== null || s.takes.length > 0
              ? <input type="radio" className="mt-1" name={`take-${s.take_of ?? s.index}`} aria-label={tv`Dùng lần nói này cho câu ${(s.take_of ?? s.index) + 1}`} title={tr("Các lần nói của cùng một câu: chọn lần muốn dùng")} checked={keep.has(s.index)}
                       onChange={() => { const group = plan.sentences.filter((x) => (x.take_of ?? x.index) === (s.take_of ?? s.index)).map((x) => x.index); const next = new Set([...keep].filter((i) => !group.includes(i))); next.add(s.index); setKeep(next); }} />
              : <input type="checkbox" className="mt-1" aria-label={tv`Giữ câu ${s.index + 1}`} checked={keep.has(s.index)} onChange={(e) => { const next = new Set(keep); if (e.target.checked) next.add(s.index); else next.delete(s.index); setKeep(next); }} />}
            <button type="button" onClick={() => seek(s.t_in)} className="mono mt-0.5 w-10 shrink-0 text-left text-[12px] text-accent hover:underline">{timecode(s.t_in)}</button>
            <span className={`min-w-0 flex-1 ${keep.has(s.index) ? "" : "text-faint line-through"}`}>{s.text}{s.take_of !== null && <span className="ml-2 text-[12px] text-faint">{tv`lần nói khác của câu ${s.take_of + 1}`}</span>}{s.reason && s.take_of === null && <span className="ml-2 text-[12px] text-cue no-underline">{s.reason}</span>}{s.doubtful && <span className="ml-2 text-[12px] text-cue">{tr("nghe chưa rõ")}</span>}</span>
          </li>
        ))}
      </ol>
      <div className="mt-3 flex flex-wrap items-center gap-2"><Button size="sm" kind="primary" disabled={keep.size === 0} onClick={make}>{tv`Tạo dự án từ ${keep.size} câu này`}</Button><Button size="sm" onClick={() => setPlan(null)}>{tr("Thôi")}</Button>{note && <span className="text-tally">{note}</span>}</div>
      <p className="mt-2 text-[12px] text-faint">{tr("Mỗi câu thành một cảnh dùng chính hình và tiếng của đoạn đó. Dự án mới sẵn sàng để dựng ngay.")}</p>
    </div>
  );
}

/** What was said, sentence by sentence. A word the model was unsure of is shown dotted, so a wrong word is easy to spot. */
function Speech({ asset, t, seek }: { asset: Asset; t: number; seek: (s: number) => void }) {
  const { data } = usePoll<{ speech: Moment[] }>(`/api/v1/assets/${asset.asset_id}/moments`, 6000);
  const [note, setNote] = useState<string | null>(null);
  const listen = () => post(`/api/v1/assets/${asset.asset_id}/transcribe`).then(() => setNote(tr("Đã xếp việc nghe lại.")), (e) => setNote((e as Error).message));
  const busy = !!asset.transcribe && ["queued", "running"].includes(asset.transcribe.status);
  if (!data) return null;
  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center gap-3 text-[12.5px] text-mute">
        {asset.speech ? <span><span className="mono text-ink">{asset.speech.words}</span> {tr("từ trong")} <span className="mono text-ink">{asset.speech.sentences}</span> {tr("câu")}{asset.speech.doubtful > 0 && <>, <span className="text-cue">{tv`${asset.speech.doubtful} từ nghe chưa chắc`}</span></>}</span>
          : <span>{busy ? tr("Hệ thống đang nghe đoạn này.") : tr("Đoạn này chưa được nghe.")}</span>}
        <span className="ml-auto"><Button size="sm" disabled={busy} onClick={listen}>{asset.speech ? tr("Nghe lại") : tr("Nghe lời nói")}</Button></span>
      </div>
      {note && <p className="text-[12.5px] text-mute">{note}</p>}
      {asset.speech && data.speech.length > 0 && <RoughCutPanel asset={asset} seek={seek} />}
      {asset.speech && data.speech.length === 0 && <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-[13px] text-mute">{tr("Không nghe thấy lời nói nào trong đoạn này.")}</p>}
      <ol className="grid gap-1.5">
        {data.speech.map((m) => (
          <li key={m.moment_id} className={`flex gap-3 rounded-lg px-2.5 py-2 text-[13px] ${t >= m.t_start && t < m.t_end ? "bg-accent/[0.08]" : ""}`}>
            <button type="button" onClick={() => seek(m.t_start)} className="mono w-10 shrink-0 text-left text-[12px] text-accent hover:underline">{timecode(m.t_start)}</button>
            <p className="min-w-0 leading-relaxed">{(m.words ?? []).map((w, i) => (
              <button key={i} type="button" onClick={() => seek(w.start)} title={tv`${w.start.toFixed(1)} giây`} className={`mr-1 rounded hover:bg-raised ${w.p < 0.35 ? "text-cue underline decoration-dotted" : t >= w.start && t < w.end ? "text-accent" : ""}`}>{w.text}</button>))}</p>
          </li>
        ))}
      </ol>
    </div>
  );
}

/* ═════════════════════════ the vault: footage, drafts, cuts, published videos and resources, in three columns ═════════════════════════ */

type Status = "draft" | "review" | "approved" | "published" | "returned";
type Kind = "video" | "image" | "audio" | "draft" | "render";
type Item = {
  key: string; kind: Kind; title: string; thumb: string | null; src: string | null; duration: number | null; width: number | null; height: number | null;
  format: string | null; size: number | null; at: number | null; status: Status | null; projects: { project_id: string; title: string }[]; platforms: string[];
  rating: number; collections: string[]; asset?: Asset; render?: RenderItem; project?: Project; version?: number; pubs: Publication[]; captions: string | null; ai: boolean; code: string | null;
};
type Note = { note_id: string; subject: string; t: number | null; t_end?: number | null; text: string; kind: "note" | "issue"; resolved: boolean; at: number };

const STATUS: Record<Status, [string, string]> = {
  draft: [tr("Bản nháp"), "text-mute border-edge"], review: [tr("Chờ duyệt"), "text-cue border-cue/50"], approved: [tr("Đã duyệt"), "text-proof border-proof/50"],
  published: [tr("Đã đăng"), "text-accent border-accent/50"], returned: [tr("Cần sửa"), "text-tally border-tally/50"],
};
const MODES: [string, string, string[]][] = [["all", tr("Mọi thứ"), []], ["scene", tr("Cảnh"), ["segment", "scene", "event", "frame"]], ["speech", tr("Lời thoại"), ["speech"]],
  ["text", tr("Chữ trên hình"), ["text"]], ["sound", tr("Âm thanh"), ["sound"]], ["note", tr("Ghi chú"), ["note"]]];
const DAYS: [number, string][] = [[0, tr("Mọi lúc")], [1, tr("Hôm nay")], [7, tr("7 ngày")], [30, tr("30 ngày")]];
const FORMAT: Record<string, string> = { landscape: "16:9", portrait: "9:16", square: "1:1" };

const res = (w: number | null, h: number | null) => (!w || !h ? null : Math.min(w, h) >= 2160 ? "4K" : `${Math.min(w, h)}p`);
const day = (t: number | null) => (t ? new Date(t * 1000).toLocaleDateString(locale, { day: "2-digit", month: "2-digit", year: "numeric" }) : "");
const playable = (i: Item) => !!i.src && (i.kind === "video" || i.kind === "draft" || i.kind === "render" || i.kind === "audio");

type Entry = { code: string; subject: string; kind: string; title: string | null };
/** The house code of a video: KIND-YYMMDD-NNN, given once by the catalogue and never changed. */
const CODE = /^(FT|AN|AM|BN|BD)-\d{6}-\d{3,}$/i;
function gather(assets: Asset[], projects: Project[], pub: Publishing | null, book: Map<string, Entry>): Item[] {
  const out = gatherRaw(assets, projects, pub);
  for (const i of out) { const e = book.get(i.key); if (e) { i.code = e.code; if (e.title) i.title = e.title; } }
  return out;
}
function gatherRaw(assets: Asset[], projects: Project[], pub: Publishing | null): Item[] {
  const out: Item[] = assets.map((a) => ({
    key: a.asset_id, kind: (a.kind === "audio" ? "audio" : a.still || a.kind === "image" ? "image" : "video") as Kind, title: a.title || a.name, thumb: a.thumbnail_url,
    src: a.proxy_url, duration: a.still ? null : a.duration, width: a.width, height: a.height, format: null, size: a.size, at: a.ingest?.created_at ?? null, status: null,
    projects: a.used_in, platforms: [], rating: a.rating, collections: a.collections, asset: a, pubs: [], captions: null, ai: a.understand?.status === "succeeded", code: null,
  }));
  for (const p of projects) {
    const cuts = [...p.renders].sort((a, b) => a.created_at - b.created_at);
    const newest = cuts.at(-1)?.render_id;
    cuts.forEach((r, k) => {
      const pubs = (pub?.publications ?? []).filter((x) => x.render_id === r.render_id);
      const status: Status = pubs.some((x) => x.status === "published") ? "published" : r.review?.approved ? "approved" : r.review ? "returned"
        : p.render?.status === "waiting_review" && r.render_id === newest ? "review" : "draft";
      out.push({ key: r.render_id, kind: "render", title: p.title, thumb: r.package ? `/api/v1/renders/${r.render_id}/package/${r.package.thumbnail}` : null, src: r.url,
        duration: r.qc.duration ?? null, width: null, height: null, format: r.qc.format ?? p.format, size: null, at: r.created_at, status, projects: [{ project_id: p.project_id, title: p.title }],
        platforms: [...new Set(pubs.map((x) => x.target))], rating: 0, collections: [], render: r, project: p, version: k + 1, pubs,
        captions: r.package?.captions_vtt ? `/api/v1/renders/${r.render_id}/package/${r.package.captions_vtt}` : null, ai: !!r.qc.viewer, code: null });
    });
    for (const v of p.previews) out.push({ key: v.render_id, kind: "draft", title: p.title, thumb: null, src: v.url, duration: v.duration, width: null, height: null, format: p.format, size: null,
      at: v.created_at, status: "draft", projects: [{ project_id: p.project_id, title: p.title }], platforms: [], rating: 0, collections: [], project: p, pubs: [], captions: null, ai: false, code: null });
  }
  return out;
}

/** A video's own frame as its thumbnail, loaded only when the card scrolls into view. */
function Frame({ item, className = "", scrub = false }: { item: Item; className?: string; scrub?: boolean }) {
  const box = useRef<HTMLSpanElement>(null), clip = useRef<HTMLVideoElement>(null);
  const [near, setNear] = useState(false), [at, setAt] = useState<number | null>(null);
  // Moving the pointer across a card runs through the clip, as on a contact sheet.
  const can = scrub && !!item.src && !!item.duration && (item.kind === "video" || item.kind === "render" || item.kind === "draft");
  const move = (e: React.MouseEvent) => { if (!can) return; const r = e.currentTarget.getBoundingClientRect(); const f = Math.max(0, Math.min(0.999, (e.clientX - r.left) / r.width)); setAt(f); const v = clip.current; if (v && v.readyState >= 1) v.currentTime = f * item.duration!; };
  useEffect(() => { const el = box.current; if (!el || item.thumb) return; const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { setNear(true); io.disconnect(); } }, { rootMargin: "200px" }); io.observe(el); return () => io.disconnect(); }, [item.thumb]);
  return (
    <span ref={box} onMouseMove={move} onMouseLeave={() => setAt(null)} className={`relative block overflow-hidden bg-black ${className}`}>
      {item.thumb ? <img src={item.thumb} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" />
        : item.src && near && item.kind !== "audio" ? <video src={`${item.src}#t=1`} muted preload="metadata" className="h-full w-full object-cover" />
        : <span className="grid h-full w-full place-items-center text-faint"><Icon name={item.kind === "audio" ? "music" : item.kind === "image" ? "image" : "film"} size={26} /></span>}
      {can && at !== null && <>
        <video ref={clip} src={item.src!} muted playsInline preload="auto" onLoadedMetadata={(e) => { e.currentTarget.currentTime = (at ?? 0) * item.duration!; }} className="absolute inset-0 h-full w-full object-cover" />
        <span className="mono absolute left-2 top-2 rounded bg-black/70 px-1.5 text-[11px] leading-[18px] text-white">{timecode(at * item.duration!)}</span>
        <span className="absolute inset-x-0 bottom-0 h-[3px] bg-black/50"><span className="block h-full bg-accent" style={{ width: `${at * 100}%` }} /></span>
      </>}
    </span>
  );
}

const Badge = ({ s }: { s: Status }) => <span className={`inline-flex h-[20px] items-center rounded-full border bg-canvas/80 px-2 text-[11px] font-medium backdrop-blur ${STATUS[s][1]}`}>{STATUS[s][0]}</span>;

type Act = [string, string, () => void, boolean?];
/** A small menu behind ⋯: the few things one does to a single item. */
function More({ acts }: { acts: Act[] }) {
  const [on, setOn] = useState(false);
  if (!acts.length) return null;
  return (
    <span className="relative">
      <button type="button" onClick={(e) => { e.stopPropagation(); setOn(!on); }} aria-label={tr("Thêm thao tác")} aria-expanded={on} className="grid h-7 w-7 place-items-center rounded-md text-faint hover:bg-white/[0.06] hover:text-ink"><span className="text-[15px] leading-none tracking-[1px]">···</span></button>
      {on && <><span className="fixed inset-0 z-30" onClick={(e) => { e.stopPropagation(); setOn(false); }} />
        <span role="menu" className="absolute bottom-full right-0 z-40 mb-1 grid w-48 gap-0.5 rounded-lg border border-edge bg-overlay p-1 shadow-xl">
          {acts.map(([label, icon, fn, danger]) => <button key={label} type="button" role="menuitem" onClick={(e) => { e.stopPropagation(); setOn(false); fn(); }} className={`flex h-8 items-center gap-2.5 rounded-md px-2.5 text-left text-[13px] hover:bg-white/[0.06] ${danger ? "text-tally" : "text-ink"}`}><Icon name={icon} size={14} className={danger ? "" : "text-mute"} />{label}</button>)}
        </span></>}
    </span>
  );
}

function Card({ item, on, chosen, choosing, pick, choose, acts }: { item: Item; on: boolean; chosen: boolean; choosing: boolean; pick: () => void; choose: () => void; acts: Act[] }) {
  const meta = [item.code, item.kind === "render" || item.kind === "draft" ? (item.version ? `v${item.version}` : tr("Xem trước")) : null, day(item.at)];
  return (
    <li className="group relative">
      <div className={`overflow-hidden rounded-xl border bg-raised/30 transition-[border-color,box-shadow] ${on || chosen ? "border-accent shadow-[0_0_0_1px_var(--color-accent)]" : "border-line hover:border-edge"}`}>
        <button type="button" onClick={choosing ? choose : pick} aria-pressed={choosing ? chosen : on} className="block w-full text-left">
          <span className="relative block">
            <Frame item={item} className="aspect-video" scrub />
            {item.duration ? <TimeChip className="absolute bottom-2 right-2">{timecode(item.duration)}</TimeChip> : null}
            {item.status && item.status !== "draft" && <span className="absolute right-2 top-2"><Badge s={item.status} /></span>}
            {item.rating >= 4 && <span className="absolute bottom-2 left-2 text-cue drop-shadow"><svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor"><path d="M10 2.5l2.3 4.7 5.2.8-3.8 3.7.9 5.2L10 14.4l-4.6 2.5.9-5.2L2.5 8l5.2-.8z" /></svg></span>}
            {item.asset?.rejected && <span className="absolute inset-0 grid place-items-center bg-canvas/70 text-[12.5px] font-medium text-mute">{tr("Đã gạt ra")}</span>}
            {item.asset && !item.asset.online && <span className="absolute inset-x-0 top-0 bg-cue/95 px-2 py-0.5 text-[11.5px] font-medium text-canvas">{tr("Không tìm thấy file gốc")}</span>}
          </span>
        </button>
        <div className="flex items-start gap-1 px-3 pb-2.5 pt-2">
          <button type="button" onClick={choosing ? choose : pick} className="min-w-0 flex-1 text-left">
            <span className="block truncate text-[14px] font-medium leading-snug">{item.title}</span>
            <span className="mono mt-0.5 block truncate text-[12px] text-faint">{meta.filter(Boolean).join(" · ")}</span>
          </button>
          <span className="-mr-1 mt-0.5 opacity-60 group-hover:opacity-100"><More acts={acts} /></span>
        </div>
      </div>
      <span className={`absolute left-2 top-2 transition-opacity ${choosing || chosen ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}>
        <button type="button" onClick={choose} aria-label={chosen ? tr("Bỏ chọn") : tr("Chọn")} className={`grid h-5 w-5 place-items-center rounded-[5px] border ${chosen ? "border-accent bg-accent text-canvas" : "border-white/60 bg-black/40 text-transparent hover:text-white/70"}`}><Icon name="check" size={13} /></button>
      </span>
    </li>
  );
}

function Row({ item, on, chosen, choosing, pick, choose }: { item: Item; on: boolean; chosen: boolean; choosing: boolean; pick: () => void; choose: () => void }) {
  return (
    <li>
      <button type="button" onClick={choosing ? choose : pick} className={`flex w-full items-center gap-3 rounded-lg px-2 py-1.5 text-left ${on || chosen ? "bg-accent/10" : "hover:bg-raised/60"}`}>
        {choosing && <span className={`grid h-4 w-4 shrink-0 place-items-center rounded border ${chosen ? "border-accent bg-accent text-canvas" : "border-edge"}`}>{chosen && <Icon name="check" size={11} />}</span>}
        <Frame item={item} className="aspect-video w-20 shrink-0 rounded" />
        <span className="min-w-0 flex-1"><span className="block truncate text-[13px]">{item.title}{item.version ? <span className="mono ml-1.5 text-[11px] text-faint">v{item.version}</span> : null}</span>
          <span className="mono block truncate text-[11px] text-faint">{[item.duration ? timecode(item.duration) : null, res(item.width, item.height) ?? (item.format ? FORMAT[item.format] : null), item.size ? megabytes(item.size) : null].filter(Boolean).join(" · ")}</span></span>
        {item.status && <Badge s={item.status} />}
      </button>
    </li>
  );
}

/* ───────────────────────── the player: one, or two side by side to compare ───────────────────────── */

type Mark = { t: number; end?: number | null; tone: string; label: string };
function Scrub({ t, dur, marks, cuts, seek }: { t: number; dur: number; marks: Mark[]; cuts: number[]; seek: (s: number) => void }) {
  const bar = useRef<HTMLDivElement>(null);
  const at = (x: number) => { const r = bar.current!.getBoundingClientRect(); return Math.max(0, Math.min(1, (x - r.left) / r.width)) * dur; };
  const down = (e: React.PointerEvent) => { if (!dur) return; seek(at(e.clientX)); const move = (ev: PointerEvent) => seek(at(ev.clientX)); const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); }; window.addEventListener("pointermove", move); window.addEventListener("pointerup", up); };
  const pct = (s: number) => `${dur ? Math.min(100, (s / dur) * 100) : 0}%`;
  return (
    <div ref={bar} onPointerDown={down} role="slider" aria-label={tr("Tua")} aria-valuemin={0} aria-valuemax={Math.round(dur)} aria-valuenow={Math.round(t)} tabIndex={-1} className="group/s relative h-5 cursor-pointer" style={{ touchAction: "none" }}>
      <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-white/15 transition-[height] group-hover/s:h-1.5">
        <div className="h-full rounded-full bg-accent" style={{ width: pct(t) }} />
      </div>
      {cuts.map((c, k) => <span key={k} className="absolute top-1/2 h-2.5 w-px -translate-y-1/2 bg-white/35" style={{ left: pct(c) }} />)}
      {marks.map((m, k) => m.end ? <span key={`r${k}`} className={`pointer-events-none absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full opacity-70 ${m.tone}`} style={{ left: pct(m.t), width: `calc(${pct(m.end)} - ${pct(m.t)})` }} /> : null)}
      {marks.map((m, k) => (
        <span key={k} onPointerDown={(e) => { e.stopPropagation(); seek(m.t); }} className={`group/m absolute -top-1.5 h-3.5 w-3.5 -translate-x-1/2 cursor-pointer rounded-full border-2 border-black ${m.tone}`} style={{ left: pct(m.t) }}>
          <span className="pointer-events-none absolute bottom-full left-1/2 mb-1.5 hidden w-max max-w-[240px] -translate-x-1/2 rounded-md bg-black/90 px-2 py-1 text-[12px] leading-snug text-white shadow-lg group-hover/m:block"><span className="mono mr-1.5 text-cue">{timecode(m.t)}{m.end ? `–${timecode(m.end)}` : ""}</span>{m.label.length > 90 ? m.label.slice(0, 89) + "…" : m.label}</span>
        </span>))}
      <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white shadow opacity-0 group-hover/s:opacity-100" style={{ left: pct(t) }} />
    </div>
  );
}

/** Whether this browser plays a file's own codec: HEVC (10-bit too) and H.264 on a Mac; ProRes and the rest go to the proxy. */
function canDecode(codec?: string | null, pixel?: string | null): boolean {
  const v = document.createElement("video");
  if (codec === "hevc") return v.canPlayType(`video/mp4; codecs="${pixel?.includes("10") ? "hvc1.2.4.L153.B0" : "hvc1.1.6.L153.B0"}"`) !== "";
  if (codec === "h264") return v.canPlayType('video/mp4; codecs="avc1.640033"') !== "" && !pixel?.includes("10");
  return false;
}

type Feed = { src: string; poster: string | null; captions: string | null; label?: string; audio?: boolean };
// The picture's box keeps its shape: when the height limit binds, the width shrinks with it and the box is
// centred on black (as YouTube's theatre does) — a full-width box under a height cap would cut off the top and bottom.
const frame = (ratio: number, vh: number, left = false) => ({ aspectRatio: String(ratio), maxHeight: `${vh}vh`, width: `min(100%, ${(vh * ratio).toFixed(2)}vh)`, marginInline: left ? 0 : "auto" });
// The theatre's left column: as wide as the 16:9 picture at its height limit, leaving the tabs at least 380px.
const THEATRE_WIDTH = "min(calc(100% - 380px), 138.67vh)";

function Screen({ feeds, start, marks, cuts, onTime, jump, small = false, tall = false, onTheater }: { feeds: Feed[]; start?: number; marks: Mark[]; cuts: number[]; onTime: (t: number) => void; jump: { t: number; n: number } | null; small?: boolean; tall?: boolean; onTheater?: () => void }) {
  const vids = useRef<(HTMLVideoElement | null)[]>([]);
  const box = useRef<HTMLDivElement>(null);
  const [t, setT] = useState(0), [dur, setDur] = useState(0), [playing, setPlaying] = useState(false), [muted, setMuted] = useState(false), [cc, setCc] = useState(true), [rate, setRate] = useState(1);
  const all = () => vids.current.filter((v): v is HTMLVideoElement => !!v);
  const seek = (s: number) => { for (const v of all()) v.currentTime = s; setT(s); onTime(s); };
  const toggle = () => { const v = all(); if (!v.length) return; if (v[0].paused) v.forEach((x) => x.play().catch(() => {})); else v.forEach((x) => x.pause()); };
  useEffect(() => { const go = () => toggle(); window.addEventListener("nx-play", go); return () => window.removeEventListener("nx-play", go); }, []);
  useEffect(() => { if (jump) { seek(jump.t); all().forEach((x) => x.play().catch(() => {})); } }, [jump]);
  useEffect(() => { const v = all()[0]; if (!v) return; const go = () => { if (start) seek(start); }; if (v.readyState >= 1) go(); else v.addEventListener("loadedmetadata", go, { once: true }); }, [feeds.map((f) => f.src).join("|"), start]);
  useEffect(() => { for (const v of all()) { v.muted = muted; v.playbackRate = rate; for (const tr_ of Array.from(v.textTracks)) tr_.mode = cc ? "showing" : "hidden"; } }, [muted, rate, cc, feeds]);
  const key = (e: React.KeyboardEvent) => { if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
    if (e.key === " " || e.key === "k") { e.preventDefault(); toggle(); } else if (e.key === "ArrowLeft" || e.key === "j") seek(Math.max(0, t - 5)); else if (e.key === "ArrowRight" || e.key === "l") seek(Math.min(dur, t + 5)); else if (e.key === "f") full(); };
  const full = () => { if (document.fullscreenElement) document.exitFullscreen().catch(() => {}); else box.current?.requestFullscreen().catch(() => {}); };
  const hasCc = feeds.some((f) => f.captions);
  const [whole, setWhole] = useState(false);
  useEffect(() => { const on = () => setWhole(document.fullscreenElement === box.current); document.addEventListener("fullscreenchange", on); return () => document.removeEventListener("fullscreenchange", on); }, []);
  return (
    <div ref={box} tabIndex={0} onKeyDown={key} data-player="" className={`flex flex-col bg-black outline-none ${whole ? "h-full" : ""}`}>
      <div className={`grid w-full min-h-0 ${feeds.length > 1 ? "grid-cols-2 gap-1" : ""} ${whole ? "flex-1" : ""}`} style={whole ? undefined : frame(feeds.length > 1 ? 32 / 9 : 16 / 9, tall ? 78 : 56, tall)} onClick={toggle}>
        {feeds.map((f, k) => (
          <div key={f.src + k} className="relative grid h-full min-h-0 w-full place-items-center overflow-hidden">
            {f.audio ? <div className="grid place-items-center gap-3 text-white/60"><Icon name="music" size={44} /><audio ref={(el) => { vids.current[k] = el as unknown as HTMLVideoElement; }} src={f.src} onTimeUpdate={(e) => { if (k === 0) { setT(e.currentTarget.currentTime); onTime(e.currentTarget.currentTime); } }} onLoadedMetadata={(e) => k === 0 && setDur(e.currentTarget.duration)} onPlay={() => k === 0 && setPlaying(true)} onPause={() => k === 0 && setPlaying(false)} /></div>
              : <video ref={(el) => { vids.current[k] = el; }} src={f.src} poster={f.poster ?? undefined} playsInline preload="metadata" crossOrigin="anonymous" className="h-full w-full object-contain"
                  onTimeUpdate={(e) => { if (k === 0) { setT(e.currentTarget.currentTime); onTime(e.currentTarget.currentTime); } }} onLoadedMetadata={(e) => k === 0 && setDur(e.currentTarget.duration)}
                  onPlay={() => k === 0 && setPlaying(true)} onPause={() => k === 0 && setPlaying(false)} onEnded={() => k === 0 && setPlaying(false)}>
                  {f.captions && <track kind="subtitles" src={f.captions} srcLang="vi" label={tr("Phụ đề")} default />}
                </video>}
            {f.label && <span className="pointer-events-none absolute left-2 top-2 rounded bg-black/70 px-2 py-0.5 text-[11.5px] font-medium text-white/90">{f.label}</span>}
          </div>))}
      </div>
      <div className="shrink-0 bg-gradient-to-t from-black to-black/60 px-3 pb-2 pt-1 text-white/90" onClick={(e) => e.stopPropagation()}>
        <Scrub t={t} dur={dur} marks={marks} cuts={cuts} seek={seek} />
        <div className="flex items-center gap-2">
          <button type="button" onClick={toggle} aria-label={playing ? tr("Tạm dừng") : tr("Phát")} className="grid h-10 w-10 place-items-center rounded-md hover:bg-white/10"><Icon name={playing ? "pause" : "play"} size={22} /></button>
          {!small && <><button type="button" onClick={() => seek(Math.max(0, t - 5))} aria-label={tr("Lùi 5 giây")} className="grid h-10 w-10 place-items-center rounded-md hover:bg-white/10"><Icon name="skipback" size={20} /></button>
          <button type="button" onClick={() => seek(Math.min(dur, t + 5))} aria-label={tr("Tới 5 giây")} className="grid h-10 w-10 place-items-center rounded-md hover:bg-white/10"><Icon name="skipfwd" size={20} /></button></>}
          <button type="button" onClick={() => setMuted(!muted)} aria-label={muted ? tr("Bật tiếng") : tr("Tắt tiếng")} className="grid h-10 w-10 place-items-center rounded-md hover:bg-white/10"><Icon name={muted ? "mute" : "volume"} size={20} /></button>
          <span className="mono ml-1 whitespace-nowrap text-[14px]">{timecode(t)} <span className="text-white/50">/ {timecode(dur)}</span></span>
          <span className="ml-auto" />
          {!small && <select value={rate} onChange={(e) => setRate(Number(e.target.value))} aria-label={tr("Tốc độ phát")} className="mono h-9 rounded-md border-0 bg-white/10 px-2 text-[13.5px] text-white">{[0.5, 1, 1.5, 2].map((r) => <option key={r} value={r}>{r}×</option>)}</select>}
          {hasCc && <button type="button" onClick={() => setCc(!cc)} aria-pressed={cc} title={tr("Phụ đề")} className={`grid h-10 w-10 place-items-center rounded-md hover:bg-white/10 ${cc ? "text-accent" : ""}`}><Icon name="captions" size={20} /></button>}
          {onTheater && !whole && <button type="button" onClick={onTheater} aria-pressed={tall} title={tall ? tr("Thu về khung nhỏ (t)") : tr("Chế độ rạp (t)")} aria-label={tall ? tr("Thu về khung nhỏ (t)") : tr("Chế độ rạp (t)")}
            className={`grid h-10 w-10 place-items-center rounded-md hover:bg-white/10 ${tall ? "text-accent" : ""}`}><Icon name={tall ? "collapse" : "screen"} size={20} /></button>}
          <button type="button" onClick={full} title={whole ? tr("Thoát toàn màn hình (f)") : tr("Toàn màn hình (f)")} aria-label={tr("Toàn màn hình")} className="grid h-10 w-10 place-items-center rounded-md hover:bg-white/10"><Icon name="expand" size={20} /></button>
        </div>
      </div>
    </div>
  );
}

/** Captions for a recording made from what was heard in it, sentence by sentence. */
function useSpeechCaptions(asset?: Asset): { url: string | null; segments: Moment[]; speech: Moment[] } {
  const [data, setData] = useState<{ segments: Moment[]; speech: Moment[] } | null>(null);
  useEffect(() => { setData(null); if (!asset || asset.kind !== "video") return; let on = true; call<{ segments: Moment[]; speech: Moment[] }>(`/api/v1/assets/${asset.asset_id}/moments`).then((d) => on && setData(d)).catch(() => {}); return () => { on = false; }; }, [asset?.asset_id]);
  const url = useMemo(() => {
    if (!data?.speech.length) return null;
    const ts = (s: number) => new Date(s * 1000).toISOString().slice(11, 23);
    return URL.createObjectURL(new Blob(["WEBVTT\n\n" + data.speech.map((m) => `${ts(m.t_start)} --> ${ts(m.t_end)}\n${m.text}\n`).join("\n")], { type: "text/vtt" }));
  }, [data]);
  useEffect(() => () => { if (url) URL.revokeObjectURL(url); }, [url]);
  return { url, segments: data?.segments ?? [], speech: data?.speech ?? [] };
}

/** The recording as a contact sheet: one frame per scene, the one playing lit; the scene's description under the sheet. */
function Sheet({ asset, t, seek, similar }: { asset: Asset; t: number; seek: (s: number) => void; similar: (m: Moment) => void }) {
  const { data } = usePoll<{ video: Moment | null; segments: Moment[] }>(`/api/v1/assets/${asset.asset_id}/moments`, 8000);
  const [list, setList] = useState(false);
  if (list) return <div><button type="button" className="link mb-3 text-[12.5px]" onClick={() => setList(false)}>{tr("← Xem dạng lưới khung hình")}</button><Moments asset={asset} t={t} seek={seek} similar={similar} /></div>;
  if (!data) return null;
  if (!data.segments.length) return <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-[13px] text-mute">{asset.understand && asset.understand.status !== "succeeded" ? tr("Hệ thống đang xem video này. Các cảnh sẽ hiện ra khi xong.") : tr("Video này chưa được chia cảnh.")}</p>;
  const now = data.segments.find((m) => t >= m.t_start && t < m.t_end) ?? data.segments[0];
  return (
    <div className="grid gap-3">
      <div className="flex items-center gap-2 text-[12.5px] text-faint"><span>{tv`${data.segments.length} cảnh`}</span><button type="button" className="link ml-auto" onClick={() => setList(true)}>{tr("Xem mô tả từng cảnh")}</button></div>
      <ol className="grid gap-2" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(118px, 1fr))" }}>
        {data.segments.map((m, k) => { const on = m === now; return (
          <li key={m.moment_id}><button type="button" onClick={() => seek(m.t_start)} title={m.title ? `${m.title}\n${m.text}` : m.text} className={`group block w-full overflow-hidden rounded-lg border text-left transition-colors ${on ? "border-accent shadow-[0_0_0_1px_var(--color-accent)]" : "border-line hover:border-edge"}`}>
            <span className="relative block bg-black">{m.frame_url ?? asset.thumbnail_url ? <img src={(m.frame_url ?? asset.thumbnail_url)!} alt="" loading="lazy" className="aspect-video w-full object-cover" /> : <span className="grid aspect-video place-items-center text-faint"><Icon name="film" size={16} /></span>}
              <TimeChip className="absolute bottom-1 left-1 !h-[17px] !px-1 !text-[10.5px]">{timecode(m.t_start)}</TimeChip><span className="mono absolute right-1 top-1 rounded bg-black/60 px-1 text-[10.5px] text-white/80">{k + 1}</span></span>
            <span className={`block truncate px-2 py-1 text-[12px] ${on ? "text-accent" : "text-mute"}`}>{m.title || m.text}</span>
          </button></li>); })}
      </ol>
      <div className="rounded-xl border border-line bg-raised/30 p-3 text-[13px]">
        <p className="flex items-center gap-2 text-[12.5px] text-faint"><span className="mono text-cue">{timecode(now.t_start)} – {timecode(now.t_end)}</span>{now.title && <span className="truncate font-medium text-ink">{now.title}</span>}
          <button type="button" className="ml-auto flex shrink-0 items-center gap-1 text-ai hover:underline" onClick={() => similar(now)}><Icon name="sparkles" size={12} />{tr("Tìm cảnh giống")}</button></p>
        <p className="mt-1.5 leading-relaxed text-mute">{now.text}</p>
      </div>
      {data.video && <p className="text-[12.5px] leading-relaxed text-faint"><span className="text-ai">{tr("Tóm tắt")}:</span> {data.video.text}</p>}
    </div>
  );
}

/* ───────────────────────── notes pinned to a moment ───────────────────────── */

function Notes({ subject, t, seek, notes, ready, reload, fix }: { subject: string; t: number; seek: (s: number) => void; notes: Note[]; ready: boolean; reload: () => void; fix: React.ReactNode }) {
  const [text, setText] = useState(""), [kind, setKind] = useState<"note" | "issue">("note"), [pin, setPin] = useState(true), [only, setOnly] = useState<"all" | "open">("all"), [from, setFrom] = useState<number | null>(null);
  const add = async () => { if (!text.trim()) return; const stretch = pin && from != null && t > from; try { await post("/api/v1/notes", { subject, t: pin ? (stretch ? from : t) : null, t_end: stretch ? t : null, text, kind }); setText(""); setFrom(null); reload(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } };
  useEffect(() => { const go = (e: Event) => { const k = (e as CustomEvent).detail; if (k === "issue") setKind("issue"); document.getElementById("note-input")?.focus(); }; window.addEventListener("nx-note", go); return () => window.removeEventListener("nx-note", go); }, []);
  if (!ready) return <div className="p-4"><p className="rounded-lg border border-cue/30 bg-cue/5 px-3 py-2.5 text-[13px] text-cue">{tr("Ghi chú theo thời điểm cần khởi động lại máy chủ NEXORA một lần để bật.")}</p></div>;
  const list = notes.filter((n) => only === "all" || !n.resolved);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-2 px-4 pb-1 pt-3">
        <select value={only} onChange={(e) => setOnly(e.target.value as "all" | "open")} aria-label={tr("Lọc ghi chú")} className="bare h-7 pr-1 text-[13.5px] font-medium"><option value="all">{tr("Mọi ghi chú")}</option><option value="open">{tr("Chưa xử lý")}</option></select>
        <span className="ml-auto text-[12px] text-faint">{tv`${notes.length} ghi chú`}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-2">
        {fix && <div className="mb-3">{fix}</div>}
        {list.length === 0 ? <p className="py-8 text-center text-[13px] text-faint">{tr("Chưa có ghi chú nào. Dừng ở chỗ cần nói rồi gõ bên dưới.")}</p> : (
          <ol className="grid gap-2">{list.map((n) => (
            <li key={n.note_id} className={`rounded-xl border px-3.5 py-3 ${n.kind === "issue" && !n.resolved ? "border-tally/35 bg-tally/[0.04]" : "border-line bg-raised/30"} ${n.resolved ? "opacity-55" : ""}`}>
              <p className="flex items-center gap-2 text-[12.5px] text-faint">{n.kind === "issue" ? <span className="font-medium text-tally">{tr("Lỗi")}</span> : <span className="font-medium text-ink">{tr("Bạn")}</span>}<span>{day(n.at)}</span>{n.resolved && <span className="text-proof">· {tr("đã xử lý")}</span>}</p>
              <p className="mt-1 text-[14px] leading-relaxed">{n.t != null && <button type="button" onClick={() => seek(n.t!)} className="mono mr-2 rounded bg-cue/15 px-1.5 py-px text-[12.5px] text-cue hover:bg-cue/25">{timecode(n.t)}{n.t_end ? ` – ${timecode(n.t_end)}` : ""}</button>}<span className={n.resolved ? "line-through" : ""}>{n.text}</span></p>
              <p className="mt-2 flex items-center gap-4 text-[12.5px] text-faint">
                <button type="button" className="hover:text-ink" onClick={() => post(`/api/v1/notes/${n.note_id}`, { resolved: !n.resolved }, "PATCH").then(reload)}>{n.resolved ? tr("Mở lại") : n.kind === "issue" ? tr("Đã sửa") : tr("Xong")}</button>
                <button type="button" className="hover:text-ink" onClick={() => post(`/api/v1/notes/${n.note_id}`, { kind: n.kind === "issue" ? "note" : "issue" }, "PATCH").then(reload)}>{n.kind === "issue" ? tr("Bỏ đánh dấu lỗi") : tr("Đánh dấu lỗi")}</button>
                <button type="button" className="ml-auto hover:text-tally" onClick={() => call(`/api/v1/notes/${n.note_id}`, { method: "DELETE" }).then(reload)}>{tr("Xoá")}</button>
              </p>
            </li>))}</ol>)}
      </div>
      <form className="shrink-0 border-t border-line bg-raised/30 p-3" onSubmit={(e) => { e.preventDefault(); add(); }}>
        <div className="flex items-start gap-2">
          <button type="button" onClick={() => setPin(!pin)} aria-pressed={pin} title={tr("Gắn với thời điểm đang xem")} className={`mono mt-1 shrink-0 rounded px-1.5 text-[12.5px] leading-6 ${pin ? "bg-cue/15 text-cue" : "bg-white/5 text-faint line-through"}`}>{pin && from != null && t > from ? `${timecode(from)} – ${timecode(t)}` : timecode(t)}</button>
          <textarea id="note-input" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); add(); } }} rows={2} placeholder={kind === "issue" ? tr("Mô tả lỗi ở chỗ này, ví dụ: màu lệch, câu bị cắt ngang…") : tr("Để lại ghi chú…")} aria-label={tr("Ghi chú")} className="bare min-w-0 flex-1 resize-none py-1 text-[14px]" />
        </div>
        <div className="mt-1.5 flex items-center gap-2">
          <div className="seg !h-7" role="radiogroup" aria-label={tr("Loại ghi chú")}>
            <button type="button" role="radio" aria-checked={kind === "note"} onClick={() => setKind("note")}>{tr("Ghi chú")}</button>
            <button type="button" role="radio" aria-checked={kind === "issue"} onClick={() => setKind("issue")}><span className="text-tally">●</span> {tr("Lỗi")}</button>
          </div>
          <button type="button" onClick={() => setFrom(from == null ? t : null)} aria-pressed={from != null} title={tr("Đánh dấu điểm đầu, tua tới điểm cuối rồi gửi: ghi chú sẽ phủ cả đoạn")} className={`h-7 rounded-md border px-2 text-[12px] ${from != null ? "border-cue/50 bg-cue/10 text-cue" : "border-line text-mute hover:text-ink"}`}>{from != null ? tv`Đoạn từ ${timecode(from)}` : tr("Ghi cho một đoạn")}</button>
          <span className="ml-auto text-[12px] text-faint">{tr("Enter để gửi")}</span>
          <Button size="sm" kind="primary" type="submit" disabled={!text.trim()}>{tr("Gửi")}</Button>
        </div>
      </form>
    </div>
  );
}

/** Ask the system to put a cut's open faults right: they are read as edits to the script, shown, then applied. */
function FixCut({ item, issues, busy, reject }: { item: Item; issues: Note[]; busy: boolean; reject: (why: string) => void }) {
  const [ops, setOps] = useState<Op[] | null>(null), [state, setState] = useState<string | null>(null);
  const text = issues.map((n) => `${n.t != null ? timecode(n.t) + ": " : ""}${n.text}`).join("; ");
  if (!item.project || !issues.length) return null;
  const plan = async () => { setState(tr("Agent đang đọc các lỗi…")); try { const r = await post<{ ops: Op[] }>(`/api/v1/projects/${item.project!.project_id}/command`, { text }); setOps(r.ops); setState(r.ops.length ? null : tr("Agent chưa đổi được các lỗi này thành thao tác sửa. Hãy ghi rõ hơn, hoặc từ chối để dựng lại.")); } catch (e) { setState((e as Error).message); } };
  const apply = async () => { try { const r = await post<{ done: string[] }>(`/api/v1/projects/${item.project!.project_id}/command/apply`, { ops }); setOps(null); setState(tv`Đã sửa ${r.done.length} chỗ. Dựng lại để có bản mới.`); } catch (e) { setState((e as Error).message); } };
  return (
    <div className="rounded-xl border border-ai/30 bg-ai/[0.05] p-3 text-[13px]">
      <p className="flex flex-wrap items-center gap-2"><Icon name="sparkles" size={14} className="text-ai" /><span className="min-w-0 flex-1">{tv`${issues.length} lỗi chưa sửa`}</span>
        <Button size="sm" kind="ai" onClick={plan}>{tr("Nhờ agent sửa")}</Button>
        {item.status === "review" && <Button size="sm" disabled={busy} onClick={() => reject(text)}>{tr("Từ chối kèm các lỗi này")}</Button>}</p>
      {state && <p className="mt-2 text-[12.5px] text-mute">{state}</p>}
      {ops && ops.length > 0 && <div className="mt-2 border-t border-line pt-2">
        <ul className="grid gap-1">{ops.map((o, i) => <li key={i} className="flex gap-2"><Icon name="check" size={13} className="mt-0.5 shrink-0 text-ai" />{o.describe}</li>)}</ul>
        <div className="mt-2 flex gap-2"><Button size="sm" kind="primary" onClick={apply}>{tv`Áp dụng ${ops.length} thao tác`}</Button><Button size="sm" onClick={() => setOps(null)}>{tr("Thôi")}</Button></div></div>}
    </div>
  );
}

/* ───────────────────────── what is known about an item ───────────────────────── */

type Audit = { entries: { audit_id: number; at: number; method: string; path: string; status: number }[] };
const DID: [RegExp, string][] = [[/render\/decision/, tr("Duyệt hoặc trả lại bản dựng")], [/\/render$/, tr("Yêu cầu dựng")], [/command\/apply/, tr("Sửa theo yêu cầu")], [/\/script$/, tr("Sửa kịch bản")],
  [/match\/approve/, tr("Duyệt clip")], [/\/match$/, tr("Tìm clip")], [/\/publish$/, tr("Đăng")], [/\/package$/, tr("Đóng gói")], [/enhance/, tr("Nâng chất lượng")], [/understand/, tr("Cho AI xem lại")],
  [/transcribe/, tr("Nghe lại lời nói")], [/^\/api\/v1\/assets\/[^/]+$/, tr("Sửa thông tin")], [/trash/, tr("Thùng rác")]];
function History({ ids }: { ids: string[] }) {
  const { data } = usePoll<Audit>("/api/v1/audit?limit=500", 30000);
  const rows = (data?.entries ?? []).filter((e) => ids.some((id) => id && e.path.includes(id))).slice(0, 12);
  if (!rows.length) return <p className="text-[12.5px] text-faint">{tr("Chưa có thay đổi nào được ghi lại.")}</p>;
  return <ol className="grid gap-1 text-[12.5px]">{rows.map((e) => <li key={e.audit_id} className="flex gap-3"><span className="mono w-24 shrink-0 text-faint">{day(e.at)}</span><span className="min-w-0 flex-1 truncate">{DID.find(([re]) => re.test(e.path))?.[1] ?? e.path.replace("/api/v1/", "")}</span>{e.status >= 400 && <span className="text-tally">{tr("lỗi")}</span>}</li>)}</ol>;
}

const Facts = ({ rows }: { rows: [string, React.ReactNode][] }) => (
  <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-3">
    {rows.map(([k, v]) => <div key={k} className="bg-surface px-3 py-2"><dt className="text-[11.5px] text-faint">{k}</dt><dd className="mono mt-0.5 truncate text-[13px]">{v}</dd></div>)}
  </dl>
);
const Block = ({ title, children }: { title: string; children: React.ReactNode }) => <section><h3 className="mb-2 text-[12.5px] font-semibold text-mute">{title}</h3>{children}</section>;

function FootageInfo({ asset, reload, others }: { asset: Asset; reload: () => void; others: Asset[] }) {
  const [tags, setTags] = useState(""), [memo, setMemo] = useState<string | null>(null), [other, setOther] = useState(""), [sync, setSync] = useState<string | null>(null);
  const partners = others.filter((o) => o.asset_id !== asset.asset_id && o.kind === "video" && o.has_audio);
  const patch = (body: Record<string, unknown>, done?: string) => post(`/api/v1/assets/${asset.asset_id}`, body, "PATCH").then(() => { reload(); if (done) toast(done); }).catch((e) => toast((e as Error).message, { tone: "tally" }));
  const addTag = () => { const t = tags.trim(); if (!t || asset.collections.includes(t)) return; patch({ collections: [...asset.collections, t] }); setTags(""); };
  return (
    <div className="grid gap-5 text-[13px]">
      <Facts rows={[[tr("Loại"), asset.kind === "audio" ? tr("Âm thanh") : asset.still ? tr("Ảnh") : tr("Video")], ...(asset.width ? [[tr("Độ phân giải"), `${asset.width}×${asset.height}`] as [string, string]] : []),
        ...(asset.frame_rate ? [[tr("Tốc độ"), `${Math.round(asset.frame_rate * 100) / 100} fps`] as [string, string]] : []), ...(asset.duration && !asset.still ? [[tr("Thời lượng"), timecode(asset.duration)] as [string, string]] : []),
        [tr("Dung lượng"), megabytes(asset.size)], ...(asset.kind !== "image" && !asset.still ? [[tr("Âm thanh"), asset.has_audio ? (asset.mean_db != null ? tv`có, ${asset.mean_db.toFixed(0)} dB` : tr("có")) : tr("không")] as [string, string]] : []),
        ...(asset.ingest ? [[tr("Ngày nhập"), day(asset.ingest.created_at)] as [string, string]] : [])]} />
      <Block title={tr("Gắn thẻ và đánh giá")}>
        <div className="flex flex-wrap items-center gap-1.5">
          {asset.collections.map((c) => <span key={c} className="inline-flex h-7 items-center gap-1 rounded-full border border-line bg-raised/60 pl-2.5 pr-1 text-[12.5px]">{c}<button type="button" aria-label={tv`Bỏ thẻ ${c}`} onClick={() => patch({ collections: asset.collections.filter((x) => x !== c) })} className="grid h-5 w-5 place-items-center rounded-full text-faint hover:bg-white/10 hover:text-ink"><Icon name="x" size={11} /></button></span>)}
          <form className="flex items-center" onSubmit={(e) => { e.preventDefault(); addTag(); }}><input value={tags} onChange={(e) => setTags(e.target.value)} placeholder={tr("+ thẻ hoặc bộ sưu tập")} aria-label={tr("Thêm thẻ")} className="h-7 w-44 rounded-full px-3 text-[12.5px]" /></form>
        </div>
        <div className="mt-3 flex items-center gap-1" role="radiogroup" aria-label={tr("Bạn chấm")}>
          {[1, 2, 3, 4, 5].map((n) => <button key={n} type="button" role="radio" aria-checked={asset.rating === n} aria-label={tv`${n} sao`} onClick={() => patch({ rating: asset.rating === n ? 0 : n })}
            className={`grid h-7 w-7 place-items-center rounded-md transition-colors ${n <= asset.rating ? "text-cue" : "text-faint hover:text-mute"}`}><svg width="16" height="16" viewBox="0 0 20 20" fill={n <= asset.rating ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"><path d="M10 2.5l2.3 4.7 5.2.8-3.8 3.7.9 5.2L10 14.4l-4.6 2.5.9-5.2L2.5 8l5.2-.8z" /></svg></button>)}
          <span className="ml-2 text-[12px] text-faint">{asset.rating >= 4 ? tr("trong Yêu thích") : tr("từ 4 sao là Yêu thích")}</span>
        </div>
      </Block>
      <Block title={tr("Thông tin")}>
        <form className="grid gap-2 sm:grid-cols-2" key={`${asset.asset_id}-${asset.title}-${asset.session_set}`} onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); patch({ session: String(f.get("session") ?? "") }, tr("Đã lưu.")); }}>
          <label className="grid gap-1"><span className="text-[12px] text-faint">{tr("Buổi quay")}</span><input name="session" defaultValue={asset.session_set ?? ""} placeholder={asset.session || tr("không rõ")} className="h-8 px-2.5" /></label>
          <span className="sm:col-span-2"><Button size="sm" type="submit">{tr("Lưu")}</Button></span>
        </form>
        <label className="mt-3 grid gap-1"><span className="text-[12px] text-faint">{tr("Ghi chú chung (tìm được bằng ô tìm kiếm)")}</span>
          <textarea rows={2} value={memo ?? asset.note ?? ""} onChange={(e) => setMemo(e.target.value)} placeholder={tr("Ví dụ: quay sáng thứ bảy ở chợ Hội An, máy cầm tay")} className="w-full p-2.5 text-[13px]" /></label>
        {memo !== null && <div className="mt-1.5 flex gap-2"><Button size="sm" kind="primary" onClick={() => patch({ note: memo }).then(() => setMemo(null))}>{tr("Lưu ghi chú")}</Button><Button size="sm" onClick={() => setMemo(null)}>{tr("Bỏ")}</Button></div>}
      </Block>
      <Block title={tr("Quyền sử dụng")}>
        <div className="grid gap-2">
          <label className="flex items-start gap-2.5"><input type="checkbox" className="mt-0.5" checked={asset.rejected} onChange={(e) => patch({ rejected: e.target.checked })} /><span>{tr("Không dùng nguyên liệu này")}<span className="block text-[12px] text-faint">{tr("Không được đề xuất cho kịch bản nào và không hiện khi tìm kiếm.")}</span></span></label>
          {asset.kind === "video" && <label className="flex items-start gap-2.5"><input type="checkbox" className="mt-0.5" checked={!!asset.reference_only} onChange={(e) => patch({ reference_only: e.target.checked })} /><span>{tr("Chỉ để tham khảo phong cách")}<span className="block text-[12px] text-faint">{tr("Không bao giờ cắt hình hay tiếng của nó vào video.")}</span></span></label>}
          {asset.kind === "video" && <label className="flex items-start gap-2.5"><input type="checkbox" className="mt-0.5" checked={asset.consent === "given" || asset.consent === "not_needed"} onChange={(e) => patch({ consent: e.target.checked ? "given" : "" })} /><span>{tr("Người xuất hiện đã đồng ý")}<span className="block text-[12px] text-faint">{tr("Video dùng footage có mặt người chỉ được đăng khi bạn xác nhận điều này.")}</span></span></label>}
        </div>
      </Block>
      <Block title={tr("Nguồn gốc")}>
        <div className="grid gap-1.5 text-[12.5px]">
          <p className="mono break-all rounded-lg bg-canvas px-3 py-2 text-[11.5px] text-faint">{asset.path}</p>
          <p className="text-mute">{asset.online ? tr("File gốc đang kết nối, không bị sao chép hay sửa.") : <span className="text-cue">{tr("Không tìm thấy file gốc. Hãy cắm lại ổ chứa nó.")}</span>}{asset.duplicate_of ? ` ${tr("Trùng nội dung với một video đã có.")}` : ""}</p>
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1"><span className="text-faint">{tr("Đã dùng trong")}</span>{asset.used_in.length ? asset.used_in.map((u) => <button key={u.project_id} type="button" onClick={() => goTo(`/du-an/${u.project_id}`)} className="link">{u.title}</button>) : <span className="text-faint">{tr("chưa dự án nào")}</span>}</p>
        </div>
      </Block>
      {asset.kind === "video" && !asset.still && <Block title={tr("Nâng chất lượng")}>
        <p className="mb-2 text-[12px] text-faint">{asset.enhanced ? tr("Đã có bản nâng cấp; bản dựng cuối sẽ lấy từ bản này.") : tr("Phóng to là lấy mẫu lại cẩn thận rồi làm nét nhẹ, không thêm chi tiết mới.")}</p>
        <div className="flex flex-wrap gap-2"><Button size="sm" onClick={() => post(`/api/v1/assets/${asset.asset_id}/enhance`, { upscale: 2 }).then(() => toast(tr("Đã xếp việc nâng chất lượng."))).catch(() => {})}>{tr("Phóng to 2 lần")}</Button>
          <Button size="sm" onClick={() => post(`/api/v1/assets/${asset.asset_id}/enhance`, { smooth_fps: 60 }).then(() => toast(tr("Đã xếp việc nâng chất lượng."))).catch(() => {})}>{tr("Làm mượt lên 60 khung/giây")}</Button></div>
      </Block>}
      {asset.kind === "video" && asset.has_audio && partners.length > 0 && <Block title={tr("Quay cùng lúc với clip khác")}>
        {asset.angles.map((a) => <p key={a.asset_id} className="mb-1 text-[12.5px]">{others.find((o) => o.asset_id === a.asset_id)?.name}: <span className="mono text-mute">{a.offset >= 0 ? tr("sớm hơn") : tr("muộn hơn")} {Math.abs(a.offset).toFixed(2)}s</span></p>)}
        <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (!other) return; setSync(tr("Đang so âm thanh của hai clip…")); try { const r = await post<{ offset: number }>("/api/v1/assets/sync", { a: asset.asset_id, b: other }); setSync(tv`Đã đồng bộ, lệch ${Math.abs(r.offset).toFixed(2)} giây.`); reload(); } catch (err) { setSync((err as Error).message); } }}>
          <select value={other} onChange={(e) => setOther(e.target.value)} aria-label={tr("Clip quay cùng lúc")} className="h-8 min-w-0 flex-1 pl-2.5"><option value="">{tr("Chọn clip quay cùng lúc")}</option>{partners.map((o) => <option key={o.asset_id} value={o.asset_id}>{o.name}</option>)}</select>
          <Button size="sm" type="submit" disabled={!other}><Icon name="wave" size={13} />{tr("Đồng bộ theo tiếng")}</Button>
        </form>{sync && <p className="mt-1.5 text-[12.5px] text-mute">{sync}</p>}
      </Block>}
      <Block title={tr("Lịch sử chỉnh sửa")}><History ids={[asset.asset_id]} /></Block>
    </div>
  );
}

type Trace = { script: { version: number }; shots: { line: number; text: string; source: { name: string; origin: string; t_in: number | null; rights?: { licence?: string; source?: string } | null } | null; generated: { kind: string; prompt: string; provider: string }[] | null }[] };
const ORIGIN: Record<string, string> = { own: tr("footage của bạn"), stock: tr("kho ảnh bên ngoài"), generated: tr("AI tạo"), library: tr("thư viện") };
function CutInfo({ item }: { item: Item }) {
  const r = item.render, [trace, setTrace] = useState<Trace | null>(null), [rights, setRights] = useState<Rights | null>(null);
  useEffect(() => { setTrace(null); setRights(null); if (!r) return; call<Trace>(`/api/v1/renders/${r.render_id}/lineage`).then(setTrace).catch(() => {}); call<Rights>(`/api/v1/renders/${r.render_id}/rights`).then(setRights).catch(() => {}); }, [r?.render_id]);
  return (
    <div className="grid gap-5 text-[13px]">
      <Facts rows={[[tr("Phiên bản"), item.version ? `v${item.version}` : tr("xem trước")], [tr("Trạng thái"), item.status ? STATUS[item.status][0] : "–"], [tr("Thời lượng"), item.duration ? timecode(item.duration) : "–"],
        [tr("Khung hình"), item.format ? FORMAT[item.format] ?? item.format : "–"], [tr("Ngày dựng"), day(item.at)], ...(r ? [[tr("Kiểm tra"), r.qc.passed ? tr("đạt") : tv`${r.qc.gaps} chỗ thiếu hình`] as [string, string]] : [])]} />
      {r?.review && <Block title={tr("Kết luận duyệt")}><p className={r.review.approved ? "text-proof" : "text-tally"}>{r.review.approved ? tr("Đã duyệt") : tr("Đã trả lại")}{r.review.comment ? `: ${r.review.comment}` : ""} <span className="text-faint">· {day(r.review.at)}</span></p></Block>}
      {item.pubs.length > 0 && <Block title={tr("Đã đăng ở")}>
        <ul className="grid gap-1">{item.pubs.map((p) => <li key={p.publication_id} className="flex items-center gap-2"><Icon name="globe" size={13} className="text-faint" /><span className="min-w-0 flex-1 truncate">{p.target} · {p.title}</span><span className={p.status === "published" ? "text-proof" : p.error ? "text-tally" : "text-faint"}>{p.status}</span>{p.url && <a href={p.url} target="_blank" rel="noreferrer" className="link">{tr("Mở")}</a>}</li>)}</ul></Block>}
      <Block title={tr("Giấy phép sử dụng")}>
        {!rights ? <p className="text-faint">…</p> : <>
          <p className={rights.clear ? "text-proof" : "text-cue"}>{rights.clear ? tr("Mọi nguồn trong bản dựng đều được phép dùng.") : tr("Có nguồn cần xem lại trước khi đăng.")}</p>
          {rights.blockers.map((b) => <p key={b} className="mt-1 text-[12.5px] text-tally">• {b}</p>)}
          {rights.disclosures.map((b) => <p key={b} className="mt-1 text-[12.5px] text-mute">• {b}</p>)}
          <ul className="mt-2 grid gap-1 text-[12.5px]">{rights.items.map((x, k) => <li key={k} className="flex gap-2"><Icon name={x.ok ? "check" : "alert"} size={13} className={`mt-0.5 shrink-0 ${x.ok ? "text-proof" : "text-cue"}`} /><span className="min-w-0 flex-1"><span>{x.name}</span> <span className="text-faint">· {ORIGIN[x.origin] ?? x.origin}{x.note ? ` · ${x.note}` : ""}</span></span></li>)}</ul>
        </>}
      </Block>
      <Block title={tr("Nguồn gốc từng cảnh")}>
        {!trace ? <p className="text-faint">…</p> : <ol className="grid gap-1.5 text-[12.5px]"><li className="text-faint">{tv`Kịch bản phiên bản ${trace.script.version}`}</li>
          {trace.shots.map((s) => <li key={s.line}><span className="mono mr-2 text-faint">{String(s.line).padStart(2, "0")}</span>{s.text}
            <span className="block pl-7 text-faint">{s.source ? `${s.source.name}${s.source.t_in != null ? ` @ ${timecode(s.source.t_in)}` : ""} · ${ORIGIN[s.source.origin] ?? s.source.origin}${s.source.rights?.licence ? ` · ${s.source.rights.licence}` : ""}` : s.generated?.length ? tv`AI tạo bằng ${s.generated[0].provider}` : <span className="text-cue">{tr("không có hình")}</span>}</span></li>)}</ol>}
      </Block>
      {item.project && <Block title={tr("Lịch sử chỉnh sửa")}><History ids={[item.project.project_id, item.key]} /></Block>}
    </div>
  );
}

type Found = { entry: Entry; projects: { project_id: string; title: string }[]; publications: { publication_id: string; target: string; status: string; url: string | null }[]; notes: Note[]; related_codes: string[]; summary?: string | null };
/** Everything the catalogue knows under one code: where it was used, what came of it, and the other codes it is tied to. */
function Lookup({ code, items, pick }: { code: string; items: Item[]; pick: (key: string) => void }) {
  const [f, setF] = useState<Found | null>(null);
  useEffect(() => { setF(null); call<Found>(`/api/v1/catalog/${code}`).then(setF).catch(() => {}); }, [code]);
  if (!f) return null;
  const byCode = (c: string) => items.find((i) => i.code === c);
  return (
    <section className="rounded-xl border border-line bg-raised/30 p-3 text-[13px]">
      <p className="flex items-center gap-2"><span className="mono rounded bg-accent/10 px-1.5 text-[12.5px] text-accent">{code}</span><span className="text-faint">{tr("tra cứu theo mã")}</span></p>
      {f.summary && <p className="mt-2 leading-relaxed text-mute">{f.summary}</p>}
      <dl className="mt-2 grid gap-1.5">
        <div className="flex gap-2"><dt className="w-24 shrink-0 text-faint">{tr("Dự án")}</dt><dd className="min-w-0">{f.projects.length ? f.projects.map((p) => <button key={p.project_id} type="button" onClick={() => goTo(`/du-an/${p.project_id}`)} className="link mr-2">{p.title}</button>) : <span className="text-faint">{tr("chưa dùng")}</span>}</dd></div>
        <div className="flex gap-2"><dt className="w-24 shrink-0 text-faint">{tr("Đã đăng")}</dt><dd className="min-w-0">{f.publications.length ? f.publications.map((p) => p.url ? <a key={p.publication_id} href={p.url} target="_blank" rel="noreferrer" className="link mr-2">{p.target}</a> : <span key={p.publication_id} className="mr-2">{p.target} · {p.status}</span>) : <span className="text-faint">{tr("chưa đăng")}</span>}</dd></div>
        <div className="flex gap-2"><dt className="w-24 shrink-0 text-faint">{tr("Ghi chú")}</dt><dd>{f.notes.length ? tv`${f.notes.length} ghi chú, ${f.notes.filter((n) => n.kind === "issue" && !n.resolved).length} lỗi chưa sửa` : <span className="text-faint">{tr("chưa có")}</span>}</dd></div>
        {f.related_codes.length > 0 && <div className="flex gap-2"><dt className="w-24 shrink-0 text-faint">{tr("Mã liên quan")}</dt><dd className="flex min-w-0 flex-wrap gap-1">{f.related_codes.map((c) => { const it = byCode(c); return <button key={c} type="button" disabled={!it} onClick={() => it && pick(it.key)} title={it?.title} className="mono rounded border border-line px-1.5 text-[12px] leading-5 hover:border-accent/50 hover:text-accent disabled:opacity-50">{c}</button>; })}</dd></div>}
      </dl>
    </section>
  );
}

/** The name a video is shown by, changed in place, with its code beside it to copy. */
function Name({ item, reload }: { item: Item; reload: () => void }) {
  const [draft, setDraft] = useState<string | null>(null);
  useEffect(() => setDraft(null), [item.key]);
  const save = async () => { const t = (draft ?? "").trim(); if (!t || !item.code || t === item.title) { setDraft(null); return; } try { await post(`/api/v1/catalog/${item.code}`, { title: t }, "PATCH"); toast(tr("Đã đổi tên video.")); reload(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } setDraft(null); };
  if (draft !== null) return <form className="min-w-0 flex-1" onSubmit={(e) => { e.preventDefault(); save(); }}><input autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={save} onKeyDown={(e) => { if (e.key === "Escape") setDraft(null); }} aria-label={tr("Tên video")} className="h-7 w-full px-2 text-[14px] font-medium" /></form>;
  return (
    <span className="flex min-w-0 items-center gap-2">
      <button type="button" onClick={() => item.code && setDraft(item.title)} disabled={!item.code} title={item.code ? tr("Bấm để đổi tên") : undefined} className="min-w-0 truncate text-left text-[14px] font-medium hover:underline decoration-dotted underline-offset-4 disabled:no-underline">{item.title}</button>
      {item.code && <button type="button" onClick={() => navigator.clipboard?.writeText(item.code!).then(() => toast(tv`Đã chép mã ${item.code!}.`)).catch(() => {})} title={tr("Chép mã")} className="mono shrink-0 rounded border border-line px-1.5 text-[11.5px] leading-5 text-mute hover:border-edge hover:text-ink">{item.code}</button>}
    </span>
  );
}

/** What one wants to know at a glance, beside the picture when it is small. */
function Glance({ item, reload, wide = false }: { item: Item; reload: () => void; wide?: boolean }) {
  const a = item.asset, r = res(item.width, item.height);
  const rows: [string, string][] = [
    ...(item.code ? [[tr("Mã video"), item.code] as [string, string]] : []),
    ...(item.duration ? [[tr("Thời lượng"), timecode(item.duration)] as [string, string]] : []),
    ...(a?.width ? [[tr("Độ phân giải"), `${a.width}×${a.height}${r ? ` · ${r}` : ""}`] as [string, string]] : item.format ? [[tr("Khung hình"), FORMAT[item.format] ?? item.format] as [string, string]] : []),
    ...(a?.frame_rate ? [[tr("Tốc độ"), `${Math.round(a.frame_rate * 100) / 100} fps`] as [string, string]] : []),
    ...(item.size ? [[tr("Dung lượng"), megabytes(item.size)] as [string, string]] : []),
    ...(item.version ? [[tr("Phiên bản"), `v${item.version}`] as [string, string]] : []),
    ...(item.at ? [[item.asset ? tr("Ngày nhập") : tr("Ngày dựng"), day(item.at)] as [string, string]] : []),
  ];
  return (
    <div className="min-w-0 flex-1 overflow-y-auto p-3 text-[13px]">
      <dl className={`grid gap-x-3 gap-y-2 ${wide ? "grid-cols-4" : "grid-cols-2"}`}>{rows.map(([k, v]) => <div key={k} className="min-w-0"><dt className="text-[11.5px] text-faint">{k}</dt><dd className="mono truncate">{v}</dd></div>)}</dl>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {item.status && <Badge s={item.status} />}
        {item.ai && <span className="inline-flex h-[20px] items-center gap-1 rounded-full border border-ai/40 px-2 text-[11px] text-ai"><Icon name="sparkles" size={10} />{tr("AI đã hiểu")}</span>}
        {item.collections.slice(0, 3).map((c) => <span key={c} className="inline-flex h-[20px] max-w-full items-center truncate rounded-full border border-line px-2 text-[11px] text-mute">{c}</span>)}
        {item.platforms.map((p) => <span key={p} className="inline-flex h-[20px] items-center rounded-full border border-accent/40 px-2 text-[11px] text-accent">{p}</span>)}
      </div>
      {a && <div className="mt-2.5 flex items-center gap-0.5" role="radiogroup" aria-label={tr("Bạn chấm")}>{[1, 2, 3, 4, 5].map((n) => <button key={n} type="button" role="radio" aria-checked={a.rating === n} aria-label={tv`${n} sao`} onClick={() => post(`/api/v1/assets/${a.asset_id}`, { rating: a.rating === n ? 0 : n }, "PATCH").then(reload).catch(() => {})}
        className={`grid h-6 w-6 place-items-center ${n <= a.rating ? "text-cue" : "text-faint hover:text-mute"}`}><svg width="14" height="14" viewBox="0 0 20 20" fill={n <= a.rating ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round"><path d="M10 2.5l2.3 4.7 5.2.8-3.8 3.7.9 5.2L10 14.4l-4.6 2.5.9-5.2L2.5 8l5.2-.8z" /></svg></button>)}</div>}
      {item.projects.length > 0 && <p className="mt-2 truncate text-[12px] text-faint">{tr("Dự án")}: {item.projects.map((p) => p.title).join(", ")}</p>}
    </div>
  );
}

/* ───────────────────────── the viewer: the right half ───────────────────────── */

// This browser's last look in the library: what was open and where it was left.
const LAST = "nx.lib.last";

function Viewer({ item, items, start, assets, close, reload, similar, pick, compare, setCompare, theater = false, setTheater }: { item: Item; items: Item[]; start?: number; assets: Asset[]; close: () => void; reload: () => void;
  theater?: boolean; setTheater?: (on: boolean) => void;
  similar: (m: Moment) => void; pick: (key: string) => void; compare: string | null; setCompare: (k: string | null) => void }) {
  const asset = item.asset;
  const versions = item.project ? items.filter((i) => i.kind === "render" && i.project?.project_id === item.project!.project_id).sort((a, b) => (a.version ?? 0) - (b.version ?? 0)) : [];
  const other = compare ? items.find((i) => i.key === compare) ?? null : null;
  const [t, setT] = useState(start ?? 0), [jump, setJump] = useState<{ t: number; n: number } | null>(null);
  // Remembered for the next visit to the library (see LAST): the item and the point it was left at, in 2s steps.
  const left = Math.floor(t / 2) * 2;
  useEffect(() => { try { localStorage.setItem(LAST, JSON.stringify({ key: item.key, t: left })); } catch { /* fine */ } }, [item.key, left]);
  const seek = (s: number) => setJump({ t: s, n: Date.now() });
  const speech = useSpeechCaptions(asset);
  const [notes, setNotes] = useState<Note[]>([]), [ready, setReady] = useState(true);
  const loadNotes = () => call<{ notes: Note[] }>(`/api/v1/notes?subject=${encodeURIComponent(item.key)}`).then((r) => { setNotes(r.notes); setReady(true); }).catch(() => setReady(false));
  useEffect(() => { setNotes([]); loadNotes(); setT(start ?? 0); }, [item.key]);
  const shots = item.render?.qc.shots ?? [];
  const shotAt = shots.reduce<number[]>((acc, s, k) => { acc.push(k ? acc[k - 1] + shots[k - 1].duration : 0); return acc; }, []);
  type Tab = "board" | "speech" | "notes" | "info" | "analysis";
  const tabs: { key: Tab; label: string; icon: string; count?: number }[] = [
    ...(item.kind === "video" || shots.length ? [{ key: "board" as const, label: tr("Storyboard"), icon: "layers" }] : []),
    ...((item.kind === "video" && asset?.has_audio) || shots.length ? [{ key: "speech" as const, label: tr("Lời thoại"), icon: "captions" }] : []),
    ...(item.kind === "video" && asset && !asset.still && !asset.duplicate_of ? [{ key: "analysis" as const, label: tr("Phân tích"), icon: "sparkles" }] : []),
    { key: "info", label: tr("Thông tin"), icon: "info" },
    { key: "notes", label: tr("Ghi chú"), icon: "comment", count: notes.filter((n) => !n.resolved).length || undefined },
  ];
  const [tab, setTab] = useState<Tab>("board");
  useEffect(() => { const go = (e: Event) => setTab((e as CustomEvent).detail as Tab); window.addEventListener("nx-tab", go); return () => window.removeEventListener("nx-tab", go); }, []);
  // Three sizes, as YouTube has them: small beside the details (the default), theatre (the picture across the whole library,
  // `t`), and the player's own full screen (`f`).
  const grow = () => setTheater?.(!theater);
  const small = !theater && !compare;
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "t") { e.preventDefault(); setTheater?.(!theater); }
    };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, [theater, setTheater]);
  const shown = tabs.some((x) => x.key === tab) ? tab : tabs[0].key;
  const marks: Mark[] = notes.filter((n) => n.t != null).map((n) => ({ t: n.t!, end: n.t_end, label: n.text, tone: n.resolved ? "bg-white/40" : n.kind === "issue" ? "bg-tally" : "bg-cue" }));
  const cuts = item.kind === "video" ? speech.segments.map((m) => m.t_start).filter((x) => x > 0) : shotAt.filter((x) => x > 0);
  // The camera's own file is played when its drive is here and this browser decodes it (HEVC 10-bit and H.264 on a Mac): the
  // proxy is a stand-in compressed for speed, not for looking at. One switch goes back to the proxy.
  const [play, setPlay] = useState<"original" | "proxy">("original");
  const originalOk = !!asset && item.kind === "video" && !!asset.online && !!asset.original_url && canDecode(asset.codec, asset.pixel_format);
  const playing = originalOk ? play : "proxy";
  // The original shows its own first frame: the thumbnail (360 high) as a poster, stretched across a large player, looked blurred.
  const fromOriginal = (i: Item) => i.key === item.key && playing === "original" && !!asset?.original_url;
  const feed = (i: Item, label?: string): Feed => ({ src: fromOriginal(i) ? asset!.original_url! : i.src!, poster: fromOriginal(i) ? null : i.thumb,
    captions: i.key === item.key && asset ? speech.url : i.captions, label, audio: i.kind === "audio" });
  // The original and its enhanced copy (Visual Quality's approved recipe, or a larger or smoother copy): one, the other, or both.
  const better = asset?.enhanced_url ?? null;
  const [look, setLook] = useState<"original" | "enhanced" | "both">("original");
  const sight = better ? look : "original";
  const betterFeed: Feed | null = better && item.kind === "video" ? { src: better, poster: item.thumb, captions: null, label: asset?.enhanced_stale ? tr("Enhanced (cũ)") : tr("Enhanced") } : null;
  const feeds = item.src ? (other?.src ? [feed(item, item.version ? `v${item.version}` : "A"), feed(other, other.version ? `v${other.version}` : "B")]
    : betterFeed && sight === "enhanced" ? [{ ...feed(item), src: betterFeed.src, label: betterFeed.label }]
    : betterFeed && sight === "both" ? [feed(item, tr("Gốc")), betterFeed] : [feed(item)]) : [];
  const [busy, setBusy] = useState(false), [why, setWhy] = useState<string | null>(null);
  const decide = async (approve: boolean, comment?: string) => { if (!item.project) return; setBusy(true); try { await post(`/api/v1/projects/${item.project.project_id}/render/decision`, approve ? { approve: true } : { approve: false, comment: comment || null }); toast(approve ? tr("Đã duyệt bản dựng.") : tr("Đã trả lại để dựng lại.")); setWhy(null); reload(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } setBusy(false); };
  const issues = notes.filter((n) => n.kind === "issue" && !n.resolved);
  const compareTo = items.filter((i) => i.key !== item.key && playable(i) && (i.kind === item.kind || (item.project && i.project?.project_id === item.project.project_id)));
  return (
    <section className="flex h-full min-h-0 flex-col" aria-label={tr("Xem")}>
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-3">
        <span className="hidden shrink-0 text-[13.5px] text-faint xl:inline">{({ video: tr("Footage"), image: tr("Ảnh"), audio: tr("Âm thanh"), draft: tr("Bản nháp"), render: tr("Bản dựng") } as Record<Kind, string>)[item.kind]}</span>
        <span className="hidden shrink-0 text-faint xl:inline">/</span>
        <Name item={item} reload={reload} />
        {versions.length > 1 && item.kind === "render" ? <select value={item.key} onChange={(e) => pick(e.target.value)} aria-label={tr("Phiên bản")} className="mono h-7 shrink-0 pl-2 text-[12px]">{versions.map((v) => <option key={v.key} value={v.key}>v{v.version}{v.status ? ` · ${STATUS[v.status][0]}` : ""}</option>)}</select>
          : item.version ? <span className="mono shrink-0 text-[12px] text-faint">v{item.version}</span> : null}
        {item.status && <Badge s={item.status} />}
        {originalOk && item.src && <span className="shrink-0" title={tr("Gốc: file của máy quay, đúng độ phân giải và chất lượng. Proxy: bản nhẹ để dự phòng.")}>
          <Seg label={tr("Phát")} value={play} onChange={setPlay} items={[["original", tr("Gốc")], ["proxy", tr("Proxy")]] as const} /></span>}
        {better && !other && <span className="flex shrink-0 items-center gap-1.5">
          <Seg label={tr("Bản xem")} value={look} onChange={setLook} items={[["original", tr("Gốc")], ["enhanced", tr("Enhanced")], ["both", tr("Cả hai")]] as const} />
          {asset?.enhanced_stale && <span title={tr("Bản enhanced này làm từ một công thức chất lượng hình cũ; bản dựng dùng bản gốc với công thức đang duyệt.")} className="rounded bg-cue/12 px-1.5 text-[11px] text-cue">{tr("cũ")}</span>}
        </span>}
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {playable(item) && compareTo.length > 0 && (other
            ? <Button size="sm" onClick={() => setCompare(null)}><Icon name="x" size={13} />{tr("Thôi so sánh")}</Button>
            : <select value="" onChange={(e) => e.target.value && setCompare(e.target.value)} aria-label={tr("So sánh với")} className="h-7 w-[132px] pl-2 text-[12.5px]"><option value="">{tr("So sánh với…")}</option>
                {compareTo.slice(0, 40).map((i) => <option key={i.key} value={i.key}>{i.version ? `v${i.version} · ` : ""}{i.title.slice(0, 40)}</option>)}</select>)}
          {item.status === "review" && !why && <><Button size="sm" disabled={busy} onClick={() => setWhy(issues.map((n) => `${n.t != null ? timecode(n.t) + ": " : ""}${n.text}`).join("; "))}>{tr("Từ chối")}</Button><Button size="sm" kind="primary" busy={busy} onClick={() => decide(true)}><Icon name="check" size={13} />{tr("Duyệt")}</Button></>}
          {!feeds.length && <button type="button" onClick={grow} title={theater ? tr("Thu về khung nhỏ (t)") : tr("Chế độ rạp (t); toàn màn hình: f")} aria-label={theater ? tr("Thu về khung nhỏ (t)") : tr("Chế độ rạp (t); toàn màn hình: f")} aria-pressed={theater} className="grid h-7 w-7 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink"><Icon name={theater ? "collapse" : "expand"} size={14} /></button>}
          {item.project && <button type="button" onClick={() => goTo(`/du-an/${item.project!.project_id}`)} title={tr("Mở dự án")} aria-label={tr("Mở dự án")} className="grid h-7 w-7 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink"><Icon name="external" size={14} /></button>}
          <button type="button" onClick={close} aria-label={tr("Đóng")} className="grid h-7 w-7 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink"><Icon name="x" size={15} /></button>
        </span>
      </header>
      {why !== null && <form className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line bg-tally/[0.05] px-3 py-2" onSubmit={(e) => { e.preventDefault(); decide(false, why); }}>
        <input value={why} onChange={(e) => setWhy(e.target.value)} autoFocus placeholder={tr("Cần sửa gì? Agent sẽ dựng lại theo lời này")} aria-label={tr("Lý do trả lại")} className="h-8 min-w-0 flex-1 px-2.5 text-[13px]" />
        <Button size="sm" type="submit" kind="danger" busy={busy}>{tr("Trả lại để dựng lại")}</Button><Button size="sm" kind="quiet" onClick={() => setWhy(null)}>{tr("Thôi")}</Button></form>}
      {/* Theatre: the picture against the left edge with its facts below; the tabs fill the column on the right.
          Elsewhere the wrappers are display: contents and the layout is the stacked one. */}
      <div className={theater ? "flex min-h-0 flex-1" : "contents"}>
      <div className={theater ? "flex min-h-0 shrink-0 flex-col overflow-y-auto border-r border-line" : "contents"} style={theater ? { width: THEATRE_WIDTH } : undefined}>
      <div className={`shrink-0 ${small ? "flex border-b border-line" : ""}`}>
        <div className={small ? "w-[60%] shrink-0" : ""}>
        {feeds.length ? <Screen feeds={feeds} start={start} marks={marks} cuts={cuts} onTime={setT} jump={jump} small={small} tall={theater} onTheater={grow} />
          : item.kind === "image" && item.thumb ? (better && sight === "both"
            ? <div className={`grid aspect-video w-full grid-cols-2 gap-1 bg-black ${theater ? "max-h-[78vh]" : "max-h-[56vh]"}`}>{[[item.thumb, tr("Gốc")], [better, asset?.enhanced_stale ? tr("Enhanced (cũ)") : tr("Enhanced")]].map(([src, label]) =>
                <div key={label} className="relative grid min-h-0 place-items-center"><img src={src!} alt="" className="max-h-full max-w-full object-contain" /><span className="chip absolute left-2 top-2">{label}</span></div>)}</div>
            : <div className={`grid aspect-video w-full place-items-center bg-black ${theater ? "max-h-[78vh]" : "max-h-[56vh]"}`}><img src={better && sight === "enhanced" ? better : item.thumb} alt="" className="max-h-full max-w-full object-contain" /></div>)
          : <div className="grid aspect-video max-h-[56vh] w-full place-items-center bg-black text-[13px] text-white/60">{tr("Bản xem chưa sẵn sàng")}</div>}
        </div>
        {small && <Glance item={item} reload={reload} />}
      </div>
      {theater && <Glance item={item} reload={reload} wide />}
      </div>
      <div className={theater ? "flex min-h-0 min-w-0 flex-1 flex-col" : "contents"}>
      <div className="shrink-0 border-b border-line px-3 pt-1"><Tabs value={shown} onChange={setTab} items={tabs} /></div>
      <div className={`min-h-0 flex-1 ${shown === "notes" ? "" : "overflow-y-auto p-4"}`}>
        {shown === "board" && asset && <Sheet asset={asset} t={t} seek={seek} similar={similar} />}
        {shown === "board" && !asset && <ol className="grid gap-2 sm:grid-cols-2">{shots.map((s, k) => { const src = assets.find((a) => a.asset_id === s.asset_id); const now = t >= shotAt[k] && t < shotAt[k] + s.duration; return (
          <li key={k}><button type="button" onClick={() => seek(shotAt[k])} className={`flex w-full gap-2.5 rounded-lg border p-2 text-left ${now ? "border-accent/60 bg-accent/[0.06]" : "border-line hover:border-edge"}`}>
            <span className="relative w-24 shrink-0 overflow-hidden rounded bg-black">{src?.thumbnail_url ? <img src={src.thumbnail_url} alt="" loading="lazy" className="aspect-video w-full object-cover" /> : <span className="grid aspect-video place-items-center text-faint"><Icon name={s.gap ? "alert" : "film"} size={16} /></span>}
              <TimeChip className="absolute bottom-0.5 left-0.5 !h-[16px] !px-1 !text-[10px]">{timecode(shotAt[k])}</TimeChip></span>
            <span className="min-w-0 flex-1 text-[12.5px]"><span className="mono text-[11px] text-faint">{tv`Cảnh ${k + 1}`} · {s.duration.toFixed(1)}s</span><span className="line-clamp-3 block leading-snug">{s.text}</span>{s.gap && <span className="text-[11.5px] text-cue">{tr("thiếu hình")}</span>}</span>
          </button></li>); })}</ol>}
        {shown === "speech" && asset && <Speech asset={asset} t={t} seek={seek} />}
        {shown === "speech" && !asset && <ol className="grid gap-1">{shots.map((s, k) => (
          <li key={k} className={`flex gap-3 rounded-lg px-2.5 py-1.5 text-[13px] ${t >= shotAt[k] && t < shotAt[k] + s.duration ? "bg-accent/[0.08]" : ""}`}>
            <button type="button" onClick={() => seek(shotAt[k])} className="mono w-11 shrink-0 text-left text-[12px] text-accent hover:underline">{timecode(shotAt[k])}</button><span className="leading-relaxed">{s.text}</span></li>))}</ol>}
        {shown === "notes" && <Notes subject={item.key} t={t} seek={seek} notes={notes} ready={ready} reload={loadNotes}
          fix={item.kind === "render" ? <FixCut item={item} issues={issues} busy={busy} reject={(text) => setWhy(text)} />
            : asset && issues.length > 0 && asset.kind === "video" ? <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ai/30 bg-ai/[0.05] p-3 text-[13px]"><Icon name="sparkles" size={14} className="text-ai" /><span className="min-w-0 flex-1">{tv`${issues.length} lỗi chưa sửa. Cho AI xem lại đoạn này kèm ghi chú chung để mô tả đúng hơn.`}</span>
                <Button size="sm" kind="ai" onClick={() => post(`/api/v1/assets/${asset.asset_id}`, { note: [asset.note, ...issues.map((n) => `${n.t != null ? timecode(n.t) + " " : ""}${n.text}`)].filter(Boolean).join("\n") }, "PATCH").then(() => post(`/api/v1/assets/${asset.asset_id}/understand`)).then(() => toast(tr("Đã nhờ AI xem lại."))).catch((e) => toast((e as Error).message, { tone: "tally" }))}>{tr("Nhờ AI xem lại")}</Button></div> : null} />}
        {shown === "info" && item.code && <div className="mb-5"><Lookup code={item.code} items={items} pick={pick} /></div>}
        {shown === "info" && asset && <FootageInfo asset={asset} reload={reload} others={assets} />}
        {shown === "info" && !asset && <CutInfo item={item} />}
        {shown === "analysis" && asset && <div className="grid gap-4"><RangeStrip asset={asset} tall playhead={t} onSeek={seek} /><StructureStrip asset={asset} t={t} seek={seek} /><AssetProfile assetId={asset.asset_id} /><AssetDossier assetId={asset.asset_id} seek={seek} /><AssetStory assetId={asset.asset_id} seek={seek} /></div>}
      </div>
      </div>
      </div>
    </section>
  );
}

/* ───────────────────────── the page ───────────────────────── */

type Sort = "new" | "name" | "long" | "rating";
type Shelf = "" | "footage" | "video" | "image" | "audio" | "made" | "draft" | "render" | "published";
const ON_SHELF: Record<Shelf, (i: Item) => boolean> = {
  "": () => true, footage: (i) => i.kind === "video" || i.kind === "image" || i.kind === "audio", video: (i) => i.kind === "video", image: (i) => i.kind === "image", audio: (i) => i.kind === "audio",
  made: (i) => i.kind === "draft" || i.kind === "render", draft: (i) => i.kind === "draft", render: (i) => i.kind === "render", published: (i) => i.status === "published",
};

/** One line of the tree on the left: a place to look, with its children folded under it. */
function Node({ depth = 0, on, icon, label, click, open, fold, n, tone, more }: { depth?: number; on: boolean; icon: string; label: string; click: () => void; open?: boolean; fold?: () => void; n?: number; tone?: string; more?: React.ReactNode }) {
  return (
    <div className={`group/n flex h-9 items-center rounded-lg pr-2 text-[13.5px] transition-colors ${on ? "bg-white/[0.07] text-ink" : "text-mute hover:bg-white/[0.04] hover:text-ink"}`} style={{ paddingLeft: 4 + depth * 18 }}>
      {fold ? <button type="button" onClick={fold} aria-label={open ? tr("Thu gọn") : tr("Mở ra")} className="grid h-6 w-5 shrink-0 place-items-center text-faint hover:text-ink"><Icon name="next" size={11} className={`transition-transform ${open ? "rotate-90" : ""}`} /></button> : <span className="w-5 shrink-0" />}
      <button type="button" onClick={click} aria-pressed={on} className="flex min-w-0 flex-1 items-center gap-2.5 text-left"><Icon name={icon} size={16} className={on ? "text-accent" : tone ?? "text-faint"} /><span className="truncate">{label}</span></button>
      {n !== undefined && n > 0 && <span className={`mono text-[11.5px] text-faint opacity-0 group-hover/n:opacity-100 ${more ? "group-hover/n:hidden" : ""}`}>{n}</span>}
      {more && <span className="hidden group-hover/n:block">{more}</span>}
    </div>
  );
}
const Head = ({ title, add }: { title: string; add?: () => void }) => (
  <div className="flex h-8 items-center px-2 text-[13px] font-semibold text-ink"><span className="flex-1">{title}</span>{add && <button type="button" onClick={add} aria-label={tv`Thêm vào ${title}`} className="grid h-7 w-7 place-items-center rounded-md text-faint hover:bg-white/[0.06] hover:text-ink"><Icon name="plus" size={15} /></button>}</div>
);
const Tool = ({ icon, label, on, click, dot }: { icon: string; label: string; on?: boolean; click: () => void; dot?: boolean }) => (
  <button type="button" onClick={click} aria-label={label} title={label} aria-pressed={on} className={`relative grid h-8 w-8 place-items-center rounded-lg transition-colors ${on ? "bg-white/[0.08] text-ink" : "text-mute hover:bg-white/[0.05] hover:text-ink"}`}><Icon name={icon} size={17} />{dot && <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-accent" />}</button>
);

export default function Library() {
  const { data, error, reload } = usePoll<{ assets: Asset[] }>("/api/v1/library");
  const { data: projects, reload: reloadProjects } = usePoll<Project[]>("/api/v1/projects", 10000);
  const { data: pub } = usePoll<Publishing>("/api/v1/publishing", 30000);
  const { data: radar } = usePoll<Radar>("/api/v1/radar", 60000);
  const { data: bin } = usePoll<TrashView>("/api/v1/trash", 15000);
  const assets = useMemo(() => data?.assets ?? [], [data]);
  const { data: catalog, reload: reloadCatalog } = usePoll<{ items: Entry[] }>("/api/v1/catalog", 20000);
  const book = useMemo(() => new Map((catalog?.items ?? []).map((e) => [e.subject, e])), [catalog]);
  const items = useMemo(() => gather(assets, projects ?? [], pub ?? null, book), [assets, projects, pub, book]);
  const params = new URLSearchParams(window.location.search);
  const [adding, setAdding] = useState(params.get("them") === "1");
  const [shelf, setShelf] = useState<Shelf>(({ video: "video", image: "image", audio: "audio" } as Record<string, Shelf>)[params.get("loai") ?? ""] ?? ""), [project, setProject] = useState(""), [status, setStatus] = useState<Status | "">("");
  const [group, setGroup] = useState(params.get("bo") ?? ""), [platform, setPlatform] = useState(""), [days, setDays] = useState(0), [session, setSession] = useState(""), [use, setUse] = useState<"" | "unused" | "used" | "rejected">("");
  const [sort, setSort] = useState<Sort>("new"), [view, setView] = useState<"grid" | "list">(params.get("xem") === "list" ? "list" : "grid");
  const [open, setOpen] = useState<Record<string, boolean>>({ footage: true, made: true }), fold = (k: string) => setOpen((o) => ({ ...o, [k]: !o[k] }));
  const [panel, setPanel] = useState<"" | "filter" | "sort" | "keys">(""), [finding, setFinding] = useState(!!params.get("q"));
  const [q, setQ] = useState(""), [mode, setMode] = useState("all"), [hits, setHits] = useState<Hit[] | null>(null), [searching, setSearching] = useState(false), [similarOf, setSimilarOf] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null), [start, setStart] = useState<number | undefined>(), [compare, setCompare] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set()), [newGroup, setNewGroup] = useState<string | null>(null);
  const runSearch = async (text: string) => { setSimilarOf(null); if (!text.trim()) { setHits(null); return; } setSearching(true); try { const r = await call<{ hits: Hit[] }>(`/api/v1/library/search?q=${encodeURIComponent(text.trim())}&limit=60`); setHits(r.hits); } catch (e) { toast((e as Error).message, { tone: "tally" }); } setSearching(false); };
  const asked = params.get("q");
  useEffect(() => { if (asked) { setQ(asked); setFinding(true); if (!CODE.test(asked.trim())) runSearch(asked); window.history.replaceState({}, "", "/thu-vien"); } }, [asked]);
  // A code typed or pasted opens its item straight away.
  useEffect(() => { const c = q.trim().toUpperCase(); if (!CODE.test(c)) return; const hit = items.find((i) => i.code === c); if (hit && picked !== hit.key) { setPicked(hit.key); setStart(undefined); } }, [q, items]);
  // The viewer is not left empty on arrival: it reopens what was last looked at, where it was left (unless that was
  // its end), or else the newest item. Once per visit, and never over a search the page was opened with.
  const arrived = useRef(false);
  useEffect(() => {
    if (arrived.current || !data || !projects || !items.length) return;
    arrived.current = true;
    if (picked || asked) return;
    let last: { key?: string; t?: number } = {};
    try { last = JSON.parse(localStorage.getItem(LAST) ?? "{}"); } catch { /* fine */ }
    const back = items.find((i) => i.key === last.key);
    const go = back ?? [...items].filter((i) => i.thumb || i.src).sort((x, y) => (y.at ?? 0) - (x.at ?? 0))[0];
    if (!go) return;
    const at = back && last.t && !(go.duration && last.t > go.duration - 3) ? last.t : undefined;
    setPicked(go.key); setStart(at);
  }, [data, projects, items]);
  const reloadAll = () => { reload(); reloadProjects(); reloadCatalog(); };
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const since = days === 0 ? 0 : days === 1 ? today.getTime() / 1000 : Date.now() / 1000 - days * 86400;
  const keep = (i: Item) => ON_SHELF[shelf](i) && (!project || i.projects.some((p) => p.project_id === project))
    && (!status || i.status === status) && (!group || (group === "__fav" ? i.rating >= 4 : i.collections.includes(group))) && (!platform || i.platforms.includes(platform))
    && (!since || (i.at ?? 0) >= since) && (!session || i.asset?.session === session)
    && (use === "" ? !i.asset?.rejected : !!i.asset && (use === "rejected" ? i.asset.rejected : !i.asset.rejected && (use === "unused" ? i.projects.length === 0 : i.projects.length > 0)));
  const named = q.trim() && !hits ? q.trim().toLowerCase() : "";
  const shown = items.filter((i) => keep(i) && (!named || i.title.toLowerCase().includes(named) || (i.code ?? "").toLowerCase().includes(named) || (i.asset?.file_name ?? "").toLowerCase().includes(named)))
    .sort((a, b) => (sort === "new" ? (b.at ?? 0) - (a.at ?? 0) : sort === "long" ? (b.duration ?? 0) - (a.duration ?? 0) : sort === "rating" ? b.rating - a.rating : a.title.localeCompare(b.title)));
  const bytes = shown.reduce((s, i) => s + (i.size ?? 0), 0);
  const levels = MODES.find(([k]) => k === mode)?.[2] ?? [];
  const found = (hits ?? []).filter((h) => !levels.length || levels.includes(h.level ?? "segment"));
  const current = items.find((i) => i.key === picked) ?? null;
  const show = (key: string, t?: number) => { setPicked(key); setStart(t); setCompare(null); };
  const choose = (key: string) => setChosen((c) => { const n = new Set(c); if (n.has(key)) n.delete(key); else n.add(key); return n; });
  const picks = items.filter((i) => chosen.has(i.key));
  const chosenAssets = picks.filter((i) => i.asset).map((i) => i.asset!);
  const rate = (list: Asset[], on: boolean) => Promise.all(list.map((a) => post(`/api/v1/assets/${a.asset_id}`, { rating: on ? 5 : 0 }, "PATCH").catch(() => {}))).then(reload);
  const tagAll = async (list: Asset[], name: string) => { const t = name.trim(); if (!t || !list.length) return; for (const a of list) if (!a.collections.includes(t)) await post(`/api/v1/assets/${a.asset_id}`, { collections: [...a.collections, t] }, "PATCH").catch(() => {}); setNewGroup(null); reload(); toast(tv`Đã đưa ${list.length} mục vào “${t}”.`); };
  const trash = async (list: Asset[]) => {
    const ids = list.map((a) => a.asset_id); if (!ids.length) return;
    const using = list.filter((a) => a.used_in.length).length;
    if (!(await ask(tv`Chuyển ${ids.length} nguyên liệu vào thùng rác?`, { body: (using ? tv`${using} trong số đó đang được dùng trong dự án. ` : "") + tr("Có thể khôi phục trong Thùng rác trong 30 ngày. File gốc không bị đụng tới."), confirm: tr("Chuyển vào thùng rác"), danger: true }))) return;
    await post("/api/v1/trash", { assets: ids }); if (picked && ids.includes(picked)) setPicked(null); setChosen(new Set()); reload();
    toast(tv`Đã chuyển ${ids.length} nguyên liệu vào thùng rác.`, { undo: () => { post("/api/v1/trash/restore", { assets: ids }).then(reload).catch(() => {}); } });
  };
  const actsOf = (i: Item): Act[] => [
    ...(playable(i) && current && current.key !== i.key && playable(current) ? [[tr("So sánh với mục đang xem"), "layers", () => setCompare(i.key)] as Act] : []),
    [chosen.has(i.key) ? tr("Bỏ chọn") : tr("Chọn"), "check", () => choose(i.key)],
    ...(i.asset ? [[i.rating >= 4 ? tr("Bỏ yêu thích") : tr("Yêu thích"), "star", () => rate([i.asset!], i.rating < 4)] as Act] : []),
    ...(i.project ? [[tr("Mở dự án"), "external", () => goTo(`/du-an/${i.project!.project_id}`)] as Act] : []),
    ...(i.src ? [[tr("Tải xuống"), "download", () => { const a = document.createElement("a"); a.href = i.src!; a.download = ""; a.click(); }] as Act] : []),
    ...(i.asset ? [[tr("Chuyển vào thùng rác"), "trash", () => trash([i.asset!]), true] as Act] : []),
  ];
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const el = e.target instanceof HTMLElement ? e.target : null;
      if (e.metaKey || e.ctrlKey || e.altKey || (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable || el.closest("[data-player]")))) return;
      const list = shown, k = list.findIndex((i) => i.key === picked);
      if (e.key === "ArrowRight" || e.key === "ArrowDown") { e.preventDefault(); const n = list[Math.min(list.length - 1, k + 1)]; if (n) show(n.key); }
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp") { e.preventDefault(); const n = list[Math.max(0, k - 1)]; if (n) show(n.key); }
      else if (e.key === " ") { if (picked) { e.preventDefault(); window.dispatchEvent(new Event("nx-play")); } }
      else if (e.key === "f" && current?.asset) rate([current.asset], current.rating < 4);
      else if ((e.key === "n" || e.key === "x") && picked) { e.preventDefault(); window.dispatchEvent(new CustomEvent("nx-tab", { detail: "notes" })); setTimeout(() => window.dispatchEvent(new CustomEvent("nx-note", { detail: e.key === "x" ? "issue" : "note" })), 60); }
      else if (e.key === "/") { e.preventDefault(); setFinding(true); setTimeout(() => (document.querySelector('input[aria-label="' + tr("Tìm trong thư viện") + '"]') as HTMLInputElement | null)?.focus(), 30); }
      else if (e.key === "Escape" && picked) { setPicked(null); setCompare(null); }
      else if (e.key === "?") setPanel(panel === "keys" ? "" : "keys");
    };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  });
  const [renaming, setRenaming] = useState<string | null>(null), [nameDraft, setNameDraft] = useState("");
  // Renaming or removing a collection rewrites it on every asset that carries it; the assets themselves stay.
  const regroup = async (from: string, to: string) => {
    setRenaming(null); const name = to.trim(); if (name === from) return;
    const holders = assets.filter((a) => a.collections.includes(from));
    if (!name && !(await ask(tv`Xoá bộ sưu tập “${from}”?`, { body: tv`${holders.length} mục sẽ rời bộ sưu tập này; bản thân các mục vẫn còn trong thư viện.`, confirm: tr("Xoá bộ sưu tập"), danger: true }))) return;
    for (const a of holders) await post(`/api/v1/assets/${a.asset_id}`, { collections: [...new Set(a.collections.map((c) => (c === from ? name : c)).filter(Boolean))] }, "PATCH").catch(() => {});
    if (group === from) setGroup(name); reload(); toast(name ? tv`Đã đổi tên thành “${name}”.` : tv`Đã xoá bộ sưu tập “${from}”.`);
  };
  const comparePair = () => { const [a, b] = picks.filter(playable); if (!a || !b) return; setPicked(a.key); setStart(undefined); setCompare(b.key); setChosen(new Set()); };
  const count = (test: (i: Item) => boolean) => items.filter(test).length;
  const groups = [...new Set(assets.flatMap((a) => a.collections))].sort();
  const sessions = [...new Set(assets.filter((a) => a.kind !== "audio" && a.session).map((a) => a.session))].sort().reverse();
  const platforms = [...new Set(items.flatMap((i) => i.platforms))].sort();
  const extra = !!(platform || days || session || use);
  const reset = () => { setShelf(""); setProject(""); setStatus(""); setGroup(""); setPlatform(""); setDays(0); setSession(""); setUse(""); };
  const place = (s: Shelf, st: Status | "" = "") => { setShelf(s); setStatus(st); setProject(""); setGroup(""); };
  const here = shelf === "" && !status && !project && !group;
  const where = project ? (projects ?? []).find((p) => p.project_id === project)?.title : group === "__fav" ? tr("Yêu thích") : group || (status ? STATUS[status][0] : { "": tr("Tất cả"), footage: tr("Footage"), video: tr("Video"), image: tr("Ảnh"), audio: tr("Âm thanh"), made: tr("Sản phẩm"), draft: tr("Bản nháp"), render: tr("Bản dựng"), published: tr("Đã đăng") }[shelf]);

  const side = (
    <nav className="flex h-full min-h-0 flex-col" aria-label={tr("Kho")}>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        <Head title={tr("Kho")} add={() => setAdding(!adding)} />
        <Node on={here} icon="layers" label={tr("Tất cả")} n={items.length} click={() => place("")} />
        <Node on={shelf === "footage" && !status} icon="folder" label={tr("Footage")} n={count(ON_SHELF.footage)} click={() => place("footage")} open={open.footage} fold={() => fold("footage")} />
        {open.footage && <>
          <Node depth={1} on={shelf === "video"} icon="film" label={tr("Video")} n={count(ON_SHELF.video)} click={() => place("video")} />
          <Node depth={1} on={shelf === "image"} icon="image" label={tr("Ảnh")} n={count(ON_SHELF.image)} click={() => place("image")} />
          <Node depth={1} on={shelf === "audio"} icon="music" label={tr("Âm thanh")} n={count(ON_SHELF.audio)} click={() => place("audio")} />
        </>}
        <Node on={shelf === "made" && !status} icon="folder" label={tr("Sản phẩm")} n={count(ON_SHELF.made)} click={() => place("made")} open={open.made} fold={() => fold("made")} />
        {open.made && <>
          <Node depth={1} on={shelf === "draft"} icon="edit" label={tr("Bản nháp")} n={count(ON_SHELF.draft)} click={() => place("draft")} />
          <Node depth={1} on={shelf === "render" && !status} icon="scissors" label={tr("Bản dựng")} n={count(ON_SHELF.render)} click={() => place("render")} open={open.render} fold={() => fold("render")} />
          {open.render && (["review", "returned", "approved"] as Status[]).map((s) => <Node key={s} depth={2} on={status === s} icon={s === "approved" ? "check" : s === "review" ? "eye" : "alert"} label={STATUS[s][0]} n={count((i) => i.status === s)} click={() => place("render", s)} />)}
          <Node depth={1} on={shelf === "published"} icon="globe" label={tr("Đã đăng")} n={count(ON_SHELF.published)} click={() => place("published")} />
        </>}
        <div className="mt-4"><Head title={tr("Bộ sưu tập")} add={() => setNewGroup(newGroup === null ? "" : null)} /></div>
        {newGroup !== null && <form className="mb-1 px-1" onSubmit={(e) => { e.preventDefault(); tagAll(chosenAssets, newGroup); }}>
          <input autoFocus value={newGroup} onChange={(e) => setNewGroup(e.target.value)} placeholder={chosenAssets.length ? tv`Tên bộ sưu tập cho ${chosenAssets.length} mục đã chọn` : tr("Chọn mục ở giữa trước, rồi đặt tên")} aria-label={tr("Bộ sưu tập mới")} className="h-8 w-full px-2.5 text-[13px]" />
        </form>}
        <Node on={group === "__fav"} icon="star" tone="text-cue" label={tr("Yêu thích")} n={count((i) => i.rating >= 4)} click={() => { place(""); setGroup("__fav"); }} />
        {groups.map((g) => renaming === g
          ? <form key={g} className="px-1 py-0.5" onSubmit={(e) => { e.preventDefault(); regroup(g, nameDraft); }}><input autoFocus value={nameDraft} onChange={(e) => setNameDraft(e.target.value)} onBlur={() => setRenaming(null)} onKeyDown={(e) => { if (e.key === "Escape") setRenaming(null); }} aria-label={tr("Tên bộ sưu tập")} className="h-8 w-full px-2.5 text-[13px]" /></form>
          : <Node key={g} on={group === g} icon="board" label={g} n={count((i) => i.collections.includes(g))} click={() => { place(""); setGroup(g); }}
              more={<More acts={[[tr("Đổi tên"), "edit", () => { setRenaming(g); setNameDraft(g); }], [tr("Xoá bộ sưu tập"), "trash", () => regroup(g, ""), true]]} />} />)}
        <div className="mt-4"><Head title={tr("Dự án")} /></div>
        {(projects ?? []).slice(0, 30).map((p) => <Node key={p.project_id} on={project === p.project_id} icon="clapper" label={p.title} n={count((i) => i.projects.some((x) => x.project_id === p.project_id))} click={() => { place(""); setProject(p.project_id); }} />)}
      </div>
      <div className="shrink-0 border-t border-line px-2 py-2">
        <Node on={false} icon="trash" label={bin?.assets.length ? tv`Thùng rác (${bin.assets.length})` : tr("Thùng rác")} click={() => goTo("/thung-rac")} />
      </div>
    </nav>
  );

  const filters = (
    <div className="absolute right-2 top-[calc(100%+4px)] z-40 grid w-80 max-w-[calc(100%-16px)] gap-4 rounded-xl border border-edge bg-overlay p-4 text-[13px] shadow-2xl" onClick={(e) => e.stopPropagation()}>
      <div><p className="mb-1.5 text-[12px] text-faint">{tr("Ngày tạo")}</p><div className="seg w-full" role="radiogroup" aria-label={tr("Ngày tạo")}>{DAYS.map(([d, label]) => <button key={d} type="button" role="radio" aria-checked={days === d} onClick={() => setDays(d)} className="flex-1 !px-1.5">{label}</button>)}</div></div>
      <div><p className="mb-1.5 text-[12px] text-faint">{tr("Footage")}</p><div className="flex flex-wrap gap-1.5">{([["", tr("Đang dùng được")], ["unused", tr("Chưa dùng")], ["used", tr("Đã dùng")], ["rejected", tr("Đã gạt ra")]] as const).map(([k, label]) =>
        <button key={k} type="button" onClick={() => setUse(k)} aria-pressed={use === k} className={`h-7 rounded-full border px-3 ${use === k ? "border-accent/60 bg-accent/10 text-accent" : "border-line text-mute hover:text-ink"}`}>{label}</button>)}</div></div>
      {platforms.length > 0 && <div><p className="mb-1.5 text-[12px] text-faint">{tr("Nền tảng")}</p><div className="flex flex-wrap gap-1.5">{platforms.map((p) => <button key={p} type="button" onClick={() => setPlatform(platform === p ? "" : p)} aria-pressed={platform === p} className={`h-7 rounded-full border px-3 ${platform === p ? "border-accent/60 bg-accent/10 text-accent" : "border-line text-mute hover:text-ink"}`}>{p}</button>)}</div></div>}
      {sessions.length > 1 && <label className="grid gap-1.5"><span className="text-[12px] text-faint">{tr("Buổi quay")}</span><select value={session} onChange={(e) => setSession(e.target.value)} className="h-8 pl-2.5"><option value="">{tr("Mọi buổi quay")}</option>{sessions.map((s) => <option key={s} value={s}>{s}</option>)}</select></label>}
      {(radar?.subjects.length ?? 0) > 0 && <div><p className="mb-1.5 text-[12px] text-faint">{tr("Tìm theo chủ đề")}</p><div className="flex flex-wrap gap-1.5">{[...radar!.subjects].sort((a, b) => b.seconds - a.seconds).slice(0, 8).map((s) =>
        <button key={s.subject} type="button" onClick={() => { setQ(s.subject); setFinding(true); setPanel(""); runSearch(s.subject); }} className="h-7 max-w-full truncate rounded-full border border-line px-3 text-mute hover:text-ink">{s.subject}</button>)}</div></div>}
      <div className="flex justify-between border-t border-line pt-3"><button type="button" className="link" onClick={() => { setPlatform(""); setDays(0); setSession(""); setUse(""); }}>{tr("Bỏ lọc")}</button><Button size="sm" onClick={() => setPanel("")}>{tr("Xong")}</Button></div>
    </div>
  );

  const browser = (
    <section className="flex h-full min-h-0 flex-col" aria-label={tr("Danh sách")}>
      <div className="relative flex h-12 shrink-0 items-center gap-1 border-b border-line px-2">
        <Tool icon={view === "grid" ? "grid" : "list"} label={view === "grid" ? tr("Xem dạng danh sách") : tr("Xem dạng lưới")} click={() => setView(view === "grid" ? "list" : "grid")} />
        <Tool icon="sliders" label={tr("Lọc")} on={panel === "filter"} dot={extra} click={() => setPanel(panel === "filter" ? "" : "filter")} />
        <span className="relative"><Tool icon="list" label={tr("Sắp xếp")} on={panel === "sort"} click={() => setPanel(panel === "sort" ? "" : "sort")} />
          {panel === "sort" && <span role="menu" className="absolute left-0 top-[calc(100%+4px)] z-40 grid w-40 gap-0.5 rounded-lg border border-edge bg-overlay p-1 shadow-xl">{([["new", tr("Mới nhất")], ["name", tr("Tên")], ["long", tr("Dài nhất")], ["rating", tr("Đánh giá")]] as const).map(([k, label]) =>
            <button key={k} type="button" role="menuitemradio" aria-checked={sort === k} onClick={() => { setSort(k); setPanel(""); }} className={`flex h-8 items-center gap-2 rounded-md px-2.5 text-left text-[13px] hover:bg-white/[0.06] ${sort === k ? "text-accent" : ""}`}>{label}{sort === k && <Icon name="check" size={13} className="ml-auto" />}</button>)}</span>}</span>
        <span className="ml-auto" />
        <span className="relative"><Tool icon="command" label={tr("Phím tắt")} on={panel === "keys"} click={() => setPanel(panel === "keys" ? "" : "keys")} />
          {panel === "keys" && <><span className="fixed inset-0 z-30" onClick={() => setPanel("")} /><span className="absolute right-0 top-[calc(100%+4px)] z-40 grid w-64 gap-1.5 rounded-xl border border-edge bg-overlay p-3 text-[12.5px] shadow-2xl">
            {([["← →", tr("Mục trước / mục sau")], ["Space", tr("Phát / tạm dừng")], ["F", tr("Yêu thích")], ["N", tr("Viết ghi chú ở thời điểm đang xem")], ["X", tr("Đánh dấu lỗi")], ["/", tr("Tìm")], ["Esc", tr("Đóng khung xem")], ["J K L", tr("Tua khi đang ở khung xem")]] as const).map(([k, v]) =>
              <span key={k} className="flex items-center gap-3"><kbd className="mono min-w-[44px] rounded border border-line bg-canvas px-1.5 text-center text-[11.5px] leading-5">{k}</kbd><span className="text-mute">{v}</span></span>)}</span></>}</span>
        <Tool icon="plus" label={tr("Thêm footage")} on={adding} click={() => setAdding(!adding)} />
        <Tool icon="search" label={tr("Tìm")} on={finding} click={() => { setFinding(!finding); if (finding) { setQ(""); setHits(null); setSimilarOf(null); } }} />
        {panel === "filter" && <><span className="fixed inset-0 z-30" onClick={() => setPanel("")} />{filters}</>}
        {panel === "sort" && <span className="fixed inset-0 z-30" onClick={() => setPanel("")} />}
      </div>
      {finding && <form className="shrink-0 border-b border-line p-2.5" onSubmit={(e) => { e.preventDefault(); runSearch(q); }}>
        <div className="relative">
          <Icon name="search" size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <input autoFocus value={q} onChange={(e) => { setQ(e.target.value); if (!e.target.value) { setHits(null); setSimilarOf(null); } }} placeholder={tr("Mã video, tên, cảnh, lời thoại, chữ trên hình…")} aria-label={tr("Tìm trong thư viện")} className="h-9 w-full pl-9 pr-24 text-[13.5px]" />
          <span className="absolute right-1 top-1/2 -translate-y-1/2"><Button size="sm" kind="primary" type="submit" disabled={!q.trim() || searching}>{searching ? <Spinner size={12} /> : tr("Tìm cảnh")}</Button></span>
        </div>
        {hits && <div className="scroll-x mt-2 flex gap-1">{MODES.map(([k, label, lv]) => { const n = (hits ?? []).filter((h) => !lv.length || lv.includes(h.level ?? "segment")).length; return (
          <button key={k} type="button" onClick={() => setMode(k)} aria-pressed={mode === k} className={`h-7 shrink-0 rounded-full border px-3 text-[12.5px] ${mode === k ? "border-accent/50 bg-accent/10 text-accent" : "border-line text-mute hover:text-ink"}`}>{label} <span className="mono opacity-70">{n}</span></button>); })}</div>}
      </form>}
      {adding && <div className="shrink-0 border-b border-line bg-raised/30 p-3"><p className="mb-2 text-[13px] text-mute">{tr("Thêm video, ảnh, nhạc hoặc cả thư mục. Hệ thống chỉ ghi lại vị trí file, rồi tự xem và mô tả.")}</p><AddFootage onDone={() => { reload(); setAdding(false); }} /></div>}
      <div className="flex h-10 shrink-0 items-center gap-2 px-4 text-[13px]">
        {hits ? <><span className="min-w-0 flex-1 truncate text-mute">{similarOf ? tr("Cảnh giống với cảnh đã chọn") : <>{tv`${found.length} cảnh khớp`} “{q}”</>}</span><button type="button" className="link shrink-0" onClick={() => { setHits(null); setQ(""); setSimilarOf(null); }}>{tr("Bỏ tìm")}</button></>
          : <><Icon name="down" size={12} className="text-faint" /><span className="font-medium">{where}</span><span className="text-faint">{tv`${shown.length} mục`}{bytes ? ` · ${megabytes(bytes)}` : ""}</span>
            {(!here || extra) && <button type="button" className="link ml-auto shrink-0 text-[12.5px]" onClick={reset}>{tr("Bỏ lọc")}</button>}</>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        {error && <p className="mb-3 text-tally">{tv`Không tải được thư viện: ${error}`}</p>}
        {!data && <SkeletonCards count={6} className="grid grid-cols-2 gap-3" />}
        {hits ? (found.length === 0 ? <p className="py-8 text-center text-[13px] text-mute">{tr("Không có cảnh nào khớp. Thử từ khác hoặc chế độ tìm khác.")}</p> : (
          <div className="grid gap-4">{[...found.reduce((m, h) => { const g = m.get(h.asset_id) ?? []; g.push(h); m.set(h.asset_id, g); return m; }, new Map<string, Hit[]>()).values()].map((group) => { const it = items.find((i) => i.key === group[0].asset_id); return (
          <section key={group[0].asset_id}>
            <button type="button" onClick={() => show(group[0].asset_id, group[0].t_start)} className="mb-1 flex w-full items-center gap-2 px-1.5 text-left text-[13px] hover:text-accent"><Icon name="film" size={13} className="text-faint" /><span className="min-w-0 truncate font-medium">{it?.title ?? group[0].asset.name}</span>{it?.code && <span className="mono text-[11.5px] text-faint">{it.code}</span>}<span className="ml-auto shrink-0 text-[12px] text-faint">{tv`${group.length} cảnh`}</span></button>
          <ul className="grid gap-1">{group.map((h) => (
            <li key={h.moment_id}><button type="button" onClick={() => show(h.asset_id, h.t_start)} className={`flex w-full gap-3 rounded-lg p-1.5 text-left transition-colors ${picked === h.asset_id ? "bg-accent/[0.08]" : "hover:bg-white/[0.04]"}`}>
              <span className="relative w-32 shrink-0 overflow-hidden rounded-md bg-black">{h.frame_url ?? h.asset.thumbnail_url ? <img src={(h.frame_url ?? h.asset.thumbnail_url)!} alt="" loading="lazy" className="aspect-video w-full object-cover" /> : <span className="block aspect-video" />}
                <TimeChip className="absolute bottom-1 left-1 !h-[17px] !px-1 !text-[10.5px]">{h.asset.still ? tr("ẢNH") : timecode(h.t_start)}</TimeChip></span>
              <span className="min-w-0 flex-1"><span className="text-[11.5px] text-faint">{LEVEL[h.level ?? "segment"] ?? h.level}</span>
                <span className="mt-0.5 line-clamp-2 text-[13px] leading-snug">{h.text}</span></span>
            </button>
            {q.trim() && !similarOf && (h.level ?? "segment") === "segment" && <button type="button" className="link ml-[140px] text-[11.5px]" title={tr("Giữ cặp này làm đáp án đúng do chính bạn chọn, để đo hệ thống tìm kiếm")}
              onClick={async (e) => { const b = e.currentTarget; await post("/api/v1/evaluation/cases", { line: q.trim(), moment_id: h.moment_id }).catch(() => {}); b.textContent = tr("Đã lưu làm mẫu chuẩn"); b.disabled = true; }}>{tr("Đây là cảnh đúng")}</button>}</li>))}</ul>
          </section>); })}</div>))
          : searching ? <p className="flex items-center justify-center gap-2 py-10 text-[13px] text-mute"><Spinner size={13} />{tr("Đang tìm theo nội dung…")}</p>
          : data && shown.length === 0 ? <div className="py-10 text-center text-[13px] text-mute">{items.length ? <>{tr("Không có mục nào khớp bộ lọc.")} <button type="button" className="link" onClick={reset}>{tr("Bỏ lọc")}</button></> : tr("Thư viện còn trống. Bấm + để thêm footage.")}</div>
          : view === "grid" ? <ul className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))" }}>{shown.map((i) => <Card key={i.key} item={i} on={picked === i.key} chosen={chosen.has(i.key)} choosing={chosen.size > 0} pick={() => show(i.key)} choose={() => choose(i.key)} acts={actsOf(i)} />)}</ul>
          : <ul className="grid gap-0.5">{shown.map((i) => <Row key={i.key} item={i} on={picked === i.key} chosen={chosen.has(i.key)} choosing={chosen.size > 0} pick={() => show(i.key)} choose={() => choose(i.key)} />)}</ul>}
      </div>
      {chosen.size > 0 && (
        <div className="flex h-12 shrink-0 items-center gap-2 border-t border-line px-3 text-[13px]">
          <button type="button" onClick={() => setChosen(new Set())} aria-label={tr("Bỏ chọn")} className="grid h-7 w-7 place-items-center rounded-md text-mute hover:bg-white/[0.06] hover:text-ink"><Icon name="x" size={15} /></button>
          <span className="min-w-0 flex-1 truncate">{tv`${chosen.size} đã chọn`}{picks.some((i) => i.size) ? <span className="text-faint"> · {megabytes(picks.reduce((s, i) => s + (i.size ?? 0), 0))}</span> : null}</span>
          {picks.filter(playable).length === 2 && <Tool icon="layers" label={tr("So sánh")} click={comparePair} />}
          {chosenAssets.length > 0 && <Tool icon="star" label={tr("Yêu thích")} click={() => rate(chosenAssets, chosenAssets.some((a) => a.rating < 4))} />}
          {chosenAssets.length > 0 && <Tool icon="board" label={tr("Thêm vào bộ sưu tập")} click={() => setNewGroup("")} />}
          {chosenAssets.length > 0 && <Tool icon="trash" label={tr("Chuyển vào thùng rác")} click={() => trash(chosenAssets)} />}
        </div>)}
    </section>
  );

  // Theatre: the viewer across the whole library, the folders and the grid set aside, as YouTube's theatre mode;
  // asked for with its button each time — every item opens in the small frame, and closing returns to it.
  const [theater, setTheater] = useState(false);
  useEffect(() => { if (!picked) setTheater(false); }, [picked]);
  const wide = theater && !!current;

  const viewer = current ? (
    <Viewer item={current} items={items} start={start} assets={assets} close={() => { setPicked(null); setCompare(null); }} reload={reloadAll} pick={(k) => show(k)} compare={compare} setCompare={setCompare}
      theater={theater} setTheater={setTheater}
      similar={async (m) => { try { const r = await call<{ hits: Hit[] }>(`/api/v1/moments/${m.moment_id}/similar`); setQ(m.text.slice(0, 60)); setFinding(true); setMode("all"); setHits(r.hits); setSimilarOf(m.moment_id); } catch (e) { toast((e as Error).message, { tone: "tally" }); } }} />
  ) : (
    <div className="grid h-full place-items-center p-8 text-center">
      <div className="max-w-sm"><span className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-2xl bg-raised text-faint"><Icon name="play" size={22} /></span>
        <p className="text-[15px] font-medium">{tr("Chọn một mục để xem")}</p>
        <p className="mt-1 text-[13.5px] text-mute">{tr("Phát, tua, xem phụ đề và lời thoại, ghi chú theo thời điểm, so sánh phiên bản và duyệt bản dựng ngay tại đây.")}</p></div>
    </div>
  );

  return (
    <Page full flush title={tr("Thư viện")}>
      <div className={`grid h-full min-h-0 gap-2 overflow-y-auto bg-canvas p-2 lg:overflow-hidden ${wide ? "lg:grid-cols-1" : "lg:grid-cols-[minmax(210px,18fr)_minmax(340px,37fr)_minmax(0,45fr)]"}`}>
        <div className={`hidden min-h-0 overflow-hidden rounded-xl border border-line bg-surface ${wide ? "" : "lg:block"}`}>{side}</div>
        <details className="rounded-xl border border-line bg-surface lg:hidden"><summary className="flex h-11 cursor-pointer list-none items-center gap-2 px-3 text-[13.5px] font-medium"><Icon name="folder" size={15} />{where}</summary><div className="max-h-[60vh] overflow-y-auto border-t border-line">{side}</div></details>
        <div className={`min-h-[60vh] overflow-hidden rounded-xl border border-line bg-surface lg:min-h-0 ${wide ? "lg:hidden" : ""}`}>{browser}</div>
        <div className={`overflow-hidden border-line bg-surface lg:static lg:z-auto lg:min-h-0 lg:rounded-xl lg:border ${current ? "fixed inset-0 z-40" : "hidden lg:block"}`}>{viewer}</div>
      </div>
    </Page>
  );
}
