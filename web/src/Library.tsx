import { t as tr, tv } from "./i18n";
import { useEffect, useRef, useState } from "react";
import { call, megabytes, post, timecode, usePoll, type Asset, type Hit, type Moment, type Project, type RoughPlan } from "./api";

const LEVEL: Record<string, string> = { segment: tr("CẢNH"), speech: tr("LỜI NÓI"), note: tr("GHI CHÚ"), frame: tr("KHUNG HÌNH") };
import { ask, Button, Icon, Page, RangeStrip, SkeletonCards, StageRail, StatusText, Tabs, TimeChip, toast } from "./parts";
import { StructureStrip } from "./Structure";

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

function Player({ asset, start, others, close, similar }: { asset: Asset; start?: number; others: Asset[]; close: () => void; similar: (m: Moment) => void }) {
  const [memo, setMemo] = useState<string | null>(null);
  const [other, setOther] = useState("");
  const [sync, setSync] = useState<string | null>(null);
  const [tags, setTags] = useState<string | null>(null);
  const [tab, setTab] = useState<"scenes" | "speech" | "info">(asset.kind === "video" ? "scenes" : "info");
  const video = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  const seek = (s: number) => { if (video.current) { video.current.currentTime = s; video.current.play().catch(() => {}); } };
  useEffect(() => { setT(start ?? 0); const v = video.current; if (v && start != null) { const go = () => { v.currentTime = start; }; v.readyState >= 1 ? go() : v.addEventListener("loadedmetadata", go, { once: true }); } }, [asset.asset_id, start]);
  const unusable = asset.black_ranges.reduce((sum, [a, b]) => sum + (b - a), 0);
  const partners = others.filter((o) => o.asset_id !== asset.asset_id && o.kind === "video" && o.has_audio);
  const facts: [string, string][] = [
    [tr("Loại"), asset.kind === "audio" ? tr("Nhạc") : asset.still ? tr("Ảnh") : tr("Video")],
    ...(asset.width ? [[tr("Khung hình"), `${asset.width}×${asset.height}`] as [string, string]] : []),
    ...(asset.frame_rate ? [[tr("Tốc độ"), `${Math.round(asset.frame_rate * 100) / 100} fps`] as [string, string]] : []),
    ...(asset.duration && !asset.still ? [[tr("Độ dài"), timecode(asset.duration)] as [string, string]] : []),
    [tr("Dung lượng"), megabytes(asset.size)],
    ...(asset.kind !== "image" && !asset.still ? [[tr("Âm thanh"), asset.has_audio ? (asset.mean_db != null ? tv`có, ${asset.mean_db.toFixed(0)} dB` : tr("có")) : tr("không")] as [string, string]] : []),
  ];
  return (
    <aside className="rise flex w-full flex-col overflow-hidden border-t border-line bg-surface lg:w-[460px] lg:shrink-0 lg:border-l lg:border-t-0" aria-label={tr("Chi tiết nguyên liệu")}>
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <Icon name={asset.kind === "audio" ? "music" : asset.still ? "image" : "film"} size={15} className="text-mute" />
        <h2 className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{asset.name}</h2>
        <button type="button" onClick={close} className="grid h-7 w-7 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink" aria-label={tr("Đóng")}><Icon name="x" size={15} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="bg-black">
          {asset.proxy_url
            ? <video ref={video} key={asset.proxy_url} src={asset.proxy_url} controls className="aspect-video w-full bg-black" onTimeUpdate={(e) => setT(e.currentTarget.currentTime)} />
            : asset.still && asset.thumbnail_url ? <img src={asset.thumbnail_url} alt="" className="aspect-video w-full bg-black object-contain" />
            : <div className="grid aspect-video w-full place-items-center text-[13px] text-mute">{tr("Bản xem chưa sẵn sàng")}</div>}
        </div>
        {!asset.still && asset.kind === "video" && <div className="px-4 pt-3"><RangeStrip asset={asset} tall playhead={t} onSeek={seek} /></div>}
        {!asset.still && asset.kind === "video" && !asset.duplicate_of && <div className="px-4 pt-3"><StructureStrip asset={asset} t={t} seek={seek} /></div>}
        <div className="grid gap-2 px-4 pt-3">
          {unusable > 0 && <p className="flex items-center gap-2 text-[12.5px] text-mute"><span className="hatch inline-block h-3 w-5 rounded-sm" />{tr("Có")} <span className="mono text-ink">{timecode(unusable)}</span> {tr("khung đen — hệ thống sẽ không chọn clip từ phần này.")}</p>}
          {asset.duplicate_of && <p className="text-[12.5px] text-mute">{tr("File này trùng nội dung với một video đã có trong thư viện nên không được xử lý lại.")}</p>}
          {!asset.online && <p className="rounded-lg border border-cue/30 bg-cue/5 px-3 py-2 text-[12.5px] text-cue">{tr("Không tìm thấy file gốc. Hãy cắm lại ổ chứa nó để render bản cuối.")}</p>}
        </div>
        <div className="mt-2 px-4"><Tabs value={tab} onChange={setTab} items={[...(asset.kind === "video" ? [{ key: "scenes" as const, label: tr("Các cảnh"), icon: "layers" }] : []), ...(asset.kind === "video" && asset.has_audio ? [{ key: "speech" as const, label: tr("Lời nói"), icon: "mic", count: asset.speech?.sentences }] : []), { key: "info" as const, label: tr("Thông tin"), icon: "sliders" }]} /></div>
        <div className="border-t border-line p-4">
          {tab === "scenes" && <Moments asset={asset} t={t} seek={seek} similar={similar} />}
          {tab === "speech" && <Speech asset={asset} t={t} seek={seek} />}
          {tab === "info" && (
            <div className="grid gap-5">
              <div className="grid gap-2 text-[13px]">
                <form className="grid gap-2 rounded-lg border border-line bg-raised/50 p-3" key={`${asset.asset_id}-${asset.title}-${asset.session_set}`}
                      onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); post(`/api/v1/assets/${asset.asset_id}`, { title: String(f.get("title") ?? ""), session: String(f.get("session") ?? "") }, "PATCH").then(() => toast(tr("Đã lưu tên và buổi quay."))).catch(() => {}); }}>
                  <label className="grid gap-1"><span className="text-mute">{tr("Tên hiển thị")}</span><input name="title" defaultValue={asset.title ?? ""} placeholder={asset.file_name} className="h-8 px-2.5" /></label>
                  <label className="grid gap-1"><span className="text-mute">{tr("Buổi quay")}</span><input name="session" defaultValue={asset.session_set ?? ""} placeholder={asset.session || tr("không rõ")} className="h-8 px-2.5" /></label>
                  <div className="flex flex-wrap items-center gap-3"><Button size="sm" type="submit">{tr("Lưu")}</Button><span className="text-[12px] text-faint">{tv`Để trống thì dùng tên file (${asset.file_name}) và thư mục chứa nó.`}</span></div>
                </form>
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1"><Icon name="clapper" size={14} className="text-faint" /><span className="text-mute">{tr("Đã dùng trong")}</span>
                  {asset.used_in.length ? asset.used_in.map((u) => <a key={u.project_id} href={`/du-an/${u.project_id}`} className="underline decoration-edge underline-offset-2">{u.title}</a>) : <span className="text-faint">{tr("chưa dự án nào")}</span>}</p>
                {asset.kind === "video" && !asset.still && (
                  <div className="rounded-lg border border-line bg-raised/50 p-3">
                    <p className="flex items-center gap-2"><Icon name="bolt" size={14} className="text-faint" />{tr("Nâng chất lượng")}
                      {asset.enhanced && <span className="text-proof">{tr("đã có bản")} {asset.enhanced.upscale > 1 ? tr("phóng to 2 lần") : ""}{asset.enhanced.upscale > 1 && asset.enhanced.smooth_fps ? ", " : ""}{asset.enhanced.smooth_fps ? tv`${asset.enhanced.smooth_fps} khung/giây` : ""}</span>}
                      {asset.enhance && ["queued", "running"].includes(asset.enhance.status) && <span className="text-ai">{tr("đang làm…")}</span>}</p>
                    <p className="mt-1 text-[12px] text-faint">{tr("Phóng to là lấy mẫu lại cẩn thận rồi làm nét nhẹ, không thêm chi tiết mới. Làm mượt hợp với cảnh chậm, có thể nhoè ở cảnh chuyển động nhanh. Bản dựng cuối sẽ lấy từ bản này.")}</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button size="sm" onClick={() => post(`/api/v1/assets/${asset.asset_id}/enhance`, { upscale: 2 }).catch(() => {})}>{tr("Phóng to 2 lần")}</Button>
                      <Button size="sm" onClick={() => post(`/api/v1/assets/${asset.asset_id}/enhance`, { smooth_fps: 60 }).catch(() => {})}>{tr("Làm mượt lên 60 khung/giây")}</Button>
                    </div>
                  </div>
                )}
                <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-raised/50 p-3">
                  <p className="min-w-0 flex-1 text-[12.5px] text-mute">{tr("Chuyển vào thùng rác: nguyên liệu biến khỏi thư viện và tìm kiếm, các câu đang dùng nó tạm thiếu hình. Khôi phục được trong 30 ngày; file gốc không bị đụng tới.")}</p>
                  <Button size="sm" onClick={async () => {
                    if (!(await ask(tr("Chuyển nguyên liệu này vào thùng rác?"), { body: asset.used_in.length ? tv`${asset.name} đang được dùng trong ${asset.used_in.length} dự án. Các câu dùng nó sẽ thiếu hình cho tới khi bạn khôi phục.` : asset.name, confirm: tr("Chuyển vào thùng rác"), danger: true }))) return;
                    await call(`/api/v1/assets/${asset.asset_id}`, { method: "DELETE" }); close();
                    toast(tv`Đã chuyển “${asset.name}” vào thùng rác.`, { undo: () => { post("/api/v1/trash/restore", { assets: [asset.asset_id] }).catch(() => {}); } });
                  }}><Icon name="trash" size={14} />{tr("Chuyển vào thùng rác")}</Button>
                </div>
                <label className="flex items-start gap-2.5 rounded-lg border border-line bg-raised/50 p-3"><input type="checkbox" className="mt-0.5" checked={asset.rejected} onChange={(e) => post(`/api/v1/assets/${asset.asset_id}`, { rejected: e.target.checked }, "PATCH")} />
                  <span>{tr("Không dùng nguyên liệu này")}<span className="block text-[12px] text-faint">{tr("Nó vẫn nằm trong thư viện nhưng không được đề xuất cho kịch bản nào và không hiện khi tìm kiếm.")}</span></span></label>
              </div>
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line">
                {facts.map(([k, v]) => <div key={k} className="bg-surface px-3 py-2"><dt className="eyebrow !text-[10px]">{k}</dt><dd className="mono mt-0.5 text-[13px]">{v}</dd></div>)}
              </dl>
              <div>
                <p className="field-label" id="rate">{tr("Bạn chấm")}</p>
                <div className="flex gap-1" role="radiogroup" aria-labelledby="rate">
                  {[1, 2, 3, 4, 5].map((n) => <button key={n} type="button" role="radio" aria-checked={asset.rating === n} aria-label={`${n} sao`} onClick={() => post(`/api/v1/assets/${asset.asset_id}`, { rating: asset.rating === n ? 0 : n }, "PATCH")}
                    className={`grid h-8 w-8 place-items-center rounded-lg border transition-colors ${n <= asset.rating ? "border-cue/40 bg-cue/10 text-cue" : "border-line text-faint hover:border-edge hover:text-mute"}`}><svg width="15" height="15" viewBox="0 0 20 20" fill={n <= asset.rating ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true"><path d="m10 3.3 2 4.3 4.6.5-3.4 3.2.9 4.6L10 13.6l-4.1 2.3.9-4.6-3.4-3.2 4.6-.5 2-4.3Z" /></svg></button>)}
                </div>
              </div>
              <form onSubmit={(e) => { e.preventDefault(); post(`/api/v1/assets/${asset.asset_id}`, { collections: (tags ?? asset.collections.join(", ")).split(",") }, "PATCH").then(() => setTags(null)); }}>
                <label htmlFor="tags" className="field-label">{tr("Bộ sưu tập")}</label>
                <div className="flex gap-2">
                  <input id="tags" value={tags ?? asset.collections.join(", ")} onChange={(e) => setTags(e.target.value)} placeholder={tr("Cách nhau bằng dấu phẩy: Hội An, cà phê")} className="min-w-0 flex-1 px-3" />
                  <Button type="submit" disabled={tags === null}>{tr("Lưu")}</Button>
                </div>
              </form>
              <form onSubmit={(e) => { e.preventDefault(); post(`/api/v1/assets/${asset.asset_id}`, { note: memo ?? "" }, "PATCH").then(() => setMemo(null)); }}>
                <label htmlFor="memo" className="field-label">{tr("Ghi chú buổi quay")}</label>
                <textarea id="memo" rows={2} value={memo ?? asset.note ?? ""} onChange={(e) => setMemo(e.target.value)} placeholder={tr("Ví dụ: quay sáng thứ bảy ở chợ Hội An, máy cầm tay")} className="w-full p-2.5 text-[13px]" />
                {memo !== null && <div className="mt-1.5 flex gap-2"><Button size="sm" kind="primary" onClick={() => post(`/api/v1/assets/${asset.asset_id}`, { note: memo }, "PATCH").then(() => setMemo(null))}>{tr("Lưu ghi chú")}</Button><Button size="sm" onClick={() => setMemo(null)}>{tr("Bỏ")}</Button></div>}
                {memo === null && asset.note && asset.kind !== "audio" && <p className="mt-1.5 text-[12px] text-faint">{tr("Ghi chú này tìm được bằng ô tìm kiếm.")} <button type="button" className="link" title={tr("Mô hình xem lại footage và dùng ghi chú để gọi đúng tên người, nơi chốn")} onClick={() => post(`/api/v1/assets/${asset.asset_id}/understand`).catch(() => {})}>{tr("Mô tả lại theo ghi chú")}</button></p>}
              </form>
              {asset.kind === "video" && asset.has_audio && partners.length > 0 && (
                <div>
                  <p className="field-label">{tr("Quay cùng lúc với clip khác")}</p>
                  {asset.angles.map((a) => <p key={a.asset_id} className="mb-1 text-[12.5px]">{others.find((o) => o.asset_id === a.asset_id)?.name}: <span className="mono text-mute">{a.offset >= 0 ? tr("sớm hơn") : tr("muộn hơn")} {Math.abs(a.offset).toFixed(2)}s</span></p>)}
                  <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (!other) return; setSync(tr("Đang so âm thanh của hai clip…")); try { const r = await post<{ offset: number }>("/api/v1/assets/sync", { a: asset.asset_id, b: other }); setSync(tv`Đã đồng bộ, lệch ${Math.abs(r.offset).toFixed(2)} giây.`); } catch (err) { setSync((err as Error).message); } }}>
                    <label htmlFor="other" className="sr-only">{tr("Clip quay cùng lúc")}</label>
                    <select id="other" value={other} onChange={(e) => setOther(e.target.value)} className="min-w-0 flex-1 pl-2.5">
                      <option value="">{tr("Chọn clip quay cùng lúc")}</option>
                      {partners.map((o) => <option key={o.asset_id} value={o.asset_id}>{o.name}</option>)}
                    </select>
                    <Button type="submit" disabled={!other}><Icon name="wave" size={14} />{tr("Đồng bộ theo tiếng")}</Button>
                  </form>
                  {sync && <p className="mt-1.5 text-[12.5px] text-mute">{sync}</p>}
                </div>
              )}
              <p className="mono break-all rounded-lg bg-canvas px-3 py-2 text-[11px] text-faint">{asset.path}</p>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}

type Sort = "name" | "long" | "rating";
const KINDS = [["", tr("Tất cả"), "layers"], ["video", tr("Video"), "film"], ["image", tr("Ảnh"), "image"], ["audio", tr("Nhạc"), "music"]] as const;

export default function Library() {
  const { data, error, reload } = usePoll<{ assets: Asset[] }>("/api/v1/library");
  const [picked, setPicked] = useState<string | null>(null);
  const [start, setStart] = useState<number | undefined>();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const params = new URLSearchParams(window.location.search);
  const [adding, setAdding] = useState(params.get("them") === "1");
  const [searching, setSearching] = useState(false);
  const runSearch = async (text: string) => { if (!text.trim()) { setHits(null); return; } setSearching(true); try { const r = await call<{ hits: Hit[] }>(`/api/v1/library/search?q=${encodeURIComponent(text.trim())}`); setHits(r.hits); } finally { setSearching(false); } };
  const search = () => runSearch(q);
  // A search started from ⌘K arrives as ?q=…
  const asked = new URLSearchParams(window.location.search).get("q");
  useEffect(() => { if (asked) { setQ(asked); runSearch(asked); window.history.replaceState({}, "", "/thu-vien"); } }, [asked]);
  const assets = data?.assets ?? [];
  const current = assets.find((a) => a.asset_id === picked) ?? null;
  const [kind, setKindState] = useState(params.get("loai") ?? "");
  const [group, setGroupState] = useState(params.get("bo") ?? "");
  const remember = (key: string, value: string) => { const u = new URL(window.location.href); if (value) u.searchParams.set(key, value); else u.searchParams.delete(key); u.searchParams.delete("them"); window.history.replaceState({}, "", u.pathname + (u.search || "")); };
  const setKind = (v: string) => { setKindState(v); remember("loai", v); };
  const setGroup = (v: string) => { setGroupState(v); remember("bo", v); };
  const [least, setLeast] = useState(0);
  const [session, setSession] = useState("");
  const [use, setUse] = useState<"" | "unused" | "used" | "rejected">("");
  const [sort, setSort] = useState<Sort>("name");
  const [view, setViewState] = useState<"grid" | "list">(params.get("xem") === "list" ? "list" : "grid");
  const setView = (v: "grid" | "list") => { setViewState(v); remember("xem", v === "list" ? "list" : ""); };
  const groups = [...new Set(assets.flatMap((a) => a.collections))].sort();
  const sessions = [...new Set(assets.filter((a) => a.kind !== "audio" && a.session).map((a) => a.session))].sort().reverse();
  const shown = assets.filter((a) => (!kind || a.kind === kind) && (!group || a.collections.includes(group)) && a.rating >= least && (!session || a.session === session)
    && (use === "rejected" ? a.rejected : !a.rejected || use === "") && (use !== "unused" || a.used_in.length === 0) && (use !== "used" || a.used_in.length > 0))
    .sort((a, b) => (sort === "long" ? (b.duration ?? 0) - (a.duration ?? 0) : sort === "rating" ? b.rating - a.rating : a.name.localeCompare(b.name)));
  const seconds = assets.reduce((sum, a) => sum + (a.kind === "video" ? a.duration ?? 0 : 0), 0);
  const described = assets.filter((a) => a.understand?.status === "succeeded").length;
  const [chosen, setChosen] = useState<Set<string> | null>(null);       // null: not choosing; otherwise the assets ticked
  const choose = (id: string) => setChosen((c) => { const n = new Set(c ?? []); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const pick = (a: Asset, t?: number) => { if (chosen) { choose(a.asset_id); return; } setPicked(a.asset_id); setStart(t); };
  const trashChosen = async () => {
    const ids = [...(chosen ?? [])]; if (!ids.length) return;
    const using = assets.filter((a) => ids.includes(a.asset_id) && a.used_in.length).length;
    if (!(await ask(tv`Chuyển ${ids.length} nguyên liệu vào thùng rác?`, { body: (using ? tv`${using} trong số đó đang được dùng trong dự án; các câu dùng chúng sẽ thiếu hình cho tới khi bạn khôi phục. ` : "") + tr("Có thể khôi phục trong Thùng rác trong 30 ngày. File gốc không bị đụng tới."), confirm: tr("Chuyển vào thùng rác"), danger: true }))) return;
    await post("/api/v1/trash", { assets: ids });
    if (picked && ids.includes(picked)) setPicked(null);
    setChosen(null); reload();
    toast(tv`Đã chuyển ${ids.length} nguyên liệu vào thùng rác.`, { undo: () => { post("/api/v1/trash/restore", { assets: ids }).then(reload).catch(() => {}); } });
  };
  const facet = (on: boolean) => `flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] transition-colors ${on ? "bg-accent/10 font-medium text-accent" : "text-mute hover:bg-raised/50 hover:text-ink"}`;
  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <Page eyebrow={tr("Sản xuất")} title={tr("Thư viện")} wide
            side={assets.length > 0 ? (
            <nav className="grid gap-5" aria-label={tr("Lọc thư viện")}>
              <div>
                <p className="eyebrow mb-1.5 px-2.5">{tr("Loại")}</p>
                {KINDS.map(([k, name, icon]) => <button key={k} type="button" onClick={() => setKind(k)} aria-pressed={kind === k} className={facet(kind === k)}><Icon name={icon} size={15} /><span className="flex-1">{name}</span><span className="mono text-[11px] text-faint">{k ? assets.filter((a) => a.kind === k).length : assets.length}</span></button>)}
              </div>
              {groups.length > 0 && (
                <div>
                  <p className="eyebrow mb-1.5 px-2.5">{tr("Bộ sưu tập")}</p>
                  <button type="button" onClick={() => setGroup("")} aria-pressed={!group} className={facet(!group)}><Icon name="folder" size={15} /><span className="flex-1">{tr("Mọi bộ sưu tập")}</span></button>
                  {groups.map((g) => <button key={g} type="button" onClick={() => setGroup(g)} aria-pressed={group === g} className={facet(group === g)}><Icon name="folder" size={15} className="text-accent" /><span className="flex-1 truncate">{g}</span><span className="mono text-[11px] text-faint">{assets.filter((a) => a.collections.includes(g)).length}</span></button>)}
                </div>
              )}
              {sessions.length > 1 && (
                <div>
                  <p className="eyebrow mb-1.5 px-2.5">{tr("Buổi quay")}</p>
                  <button type="button" onClick={() => setSession("")} aria-pressed={!session} className={facet(!session)}><Icon name="clock" size={15} /><span className="flex-1">{tr("Mọi buổi quay")}</span></button>
                  {sessions.slice(0, 12).map((s) => <button key={s} type="button" onClick={() => setSession(s)} aria-pressed={session === s} className={facet(session === s)}><Icon name="clock" size={15} /><span className="flex-1 truncate" title={s}>{s}</span><span className="mono text-[11px] text-faint">{assets.filter((a) => a.session === s).length}</span></button>)}
                </div>
              )}
              <div>
                <p className="eyebrow mb-1.5 px-2.5">{tr("Tình trạng dùng")}</p>
                {([["", tr("Tất cả")], ["unused", tr("Chưa dùng vào video nào")], ["used", tr("Đã dùng")], ["rejected", tr("Đã gạt ra")]] as const).map(([k, name]) => (
                  <button key={k} type="button" onClick={() => setUse(k)} aria-pressed={use === k} className={facet(use === k)}><Icon name={k === "rejected" ? "x" : k === "used" ? "check" : "layers"} size={15} /><span className="flex-1">{name}</span>
                    <span className="mono text-[11px] text-faint">{k === "" ? assets.length : k === "rejected" ? assets.filter((a) => a.rejected).length : k === "used" ? assets.filter((a) => a.used_in.length > 0).length : assets.filter((a) => !a.rejected && a.used_in.length === 0).length}</span></button>))}
              </div>
              <div>
                <p className="eyebrow mb-1.5 px-2.5">{tr("Đánh giá")}</p>
                <button type="button" onClick={() => setLeast(least ? 0 : 4)} aria-pressed={least > 0} className={facet(least > 0)}><Icon name="star" size={15} className={least ? "text-cue" : ""} /><span className="flex-1">{tr("Từ 4 sao")}</span></button>
              </div>
            </nav>
            ) : undefined}
            note={assets.length ? <span className="flex flex-wrap gap-x-3"><span>{tv`${assets.length} nguyên liệu`}</span><span className="mono">{timecode(seconds)} video</span><span className="text-ai">{tv`${described} đã được AI mô tả`}</span></span> : tr("Footage, ảnh và nhạc của bạn. File gốc không bị sao chép hay sửa.")}
            actions={<Button kind={adding ? "plain" : "primary"} onClick={() => setAdding(!adding)}><Icon name={adding ? "x" : "plus"} />{adding ? tr("Đóng") : tr("Thêm footage")}</Button>}>
        {(adding || (data && assets.length === 0)) && <div className="panel glow rise mb-5 p-5"><p className="mb-1 font-semibold">{tr("Thêm video, ảnh, nhạc hoặc cả thư mục")}</p><p className="mb-3 text-[13px] text-mute">{tr("Hệ thống chỉ ghi lại vị trí file, rồi tự xem và mô tả từng đoạn để bạn tìm bằng lời.")}</p><AddFootage onDone={reload} /></div>}

        <form className="mb-5" onSubmit={(e) => { e.preventDefault(); search(); }}>
          <div className="relative">
            <label htmlFor="q" className="sr-only">{tr("Tìm trong footage")}</label>
            <Icon name="sparkles" size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ai" />
            <input id="q" value={q} onChange={(e) => { setQ(e.target.value); if (!e.target.value) setHits(null); }} placeholder={tr("Mô tả cảnh bạn cần, ví dụ: bàn tay rót cà phê ra tách")}
                   className="h-12 w-full pl-11 pr-32 text-[15px] md:pr-60" />
            <span className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-3"><span className="hidden items-center gap-1.5 text-[12px] text-faint md:flex" title={tr("Tìm cảnh bằng lời")}><span className="h-1.5 w-1.5 rounded-full bg-proof" />{tv`${described} video đã hiểu`}</span><Button kind="primary" size="sm" type="submit" disabled={!q.trim() || searching}>{searching ? tr("Đang tìm…") : tr("Tìm cảnh")}</Button></span>
          </div>
        </form>

        {hits && (
          <div className="mb-8">
            <div className="mb-3 flex items-baseline justify-between gap-4"><h2 className="text-[15px] font-semibold">{hits.length ? <>{tv`${hits.length} cảnh khớp với`} <span className="text-ai">“{q}”</span></> : tv`Không có cảnh nào khớp với “${q}”`}</h2>
              <button type="button" className="link text-[12.5px]" onClick={() => { setHits(null); setQ(""); }}>{tr("Bỏ tìm kiếm")}</button></div>
            {!hits.length && <p className="text-mute">{tr("Thử từ khác, hoặc kiểm tra xem video đã được hệ thống xem xong chưa ở mục Tiến trình.")}</p>}
            <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {hits.map((h, i) => (
                <li key={h.moment_id}>
                  <button type="button" className="panel group block w-full overflow-hidden text-left transition-colors hover:border-ai/50" onClick={() => { setPicked(h.asset_id); setStart(h.t_start); }}>
                    <span className="relative block bg-black">{h.frame_url ?? h.asset.thumbnail_url ? <img src={(h.frame_url ?? h.asset.thumbnail_url)!} alt="" loading="lazy" className="aspect-video w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" /> : <span className="block aspect-video" />}
                      {h.level && h.level !== "segment" && <span className="chip absolute left-2 top-2">{LEVEL[h.level] ?? h.level}</span>}
                      <TimeChip className="absolute bottom-2 left-2">{h.asset.still ? tr("ẢNH") : `${timecode(h.t_start)} – ${timecode(h.t_end)}`}</TimeChip>
                      <span className="mono absolute right-2 top-2 grid h-6 w-6 place-items-center rounded-md bg-ai/90 text-[11px] font-semibold text-canvas">{i + 1}</span></span>
                    <span className="block px-3 py-2.5"><span className="block truncate text-[12px] text-faint">{h.asset.name}</span>
                      <span className="mt-0.5 line-clamp-2 text-[13px]">{h.text}</span></span>
                  </button>
                  {q.trim() && (h.level ?? "segment") === "segment" && <button type="button" className="link mt-1 px-1 text-[12px]" title={tr("Giữ cặp này làm đáp án đúng do chính bạn chọn, để đo hệ thống tìm kiếm")}
                    onClick={async (e) => { const b = e.currentTarget; await post("/api/v1/evaluation/cases", { line: q.trim(), moment_id: h.moment_id }).catch(() => {}); b.textContent = tr("Đã lưu làm mẫu chuẩn"); b.disabled = true; }}>{tv`Đây là cảnh đúng cho “${q.trim().slice(0, 24)}”`}</button>}
                </li>
              ))}
            </ul>
          </div>
        )}
        {error && <p className="mb-4 text-tally">{tv`Không tải được thư viện: ${error}`}</p>}

        {assets.length > 0 && (
          <div>
            <div className="min-w-0">
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <span className="mono text-[12px] text-faint">{shown.length} / {assets.length}</span>
                <span className="ml-auto" />
                <Button size="sm" kind={chosen ? "primary" : "plain"} aria-pressed={!!chosen} onClick={() => setChosen(chosen ? null : new Set())}><Icon name={chosen ? "x" : "check"} size={14} />{chosen ? tr("Thôi chọn") : tr("Chọn nhiều")}</Button>
                <label className="flex items-center gap-2 text-[12.5px] text-mute">{tr("Sắp xếp")}<select value={sort} onChange={(e) => setSort(e.target.value as Sort)} className="h-8 pl-2.5 text-[12.5px]"><option value="name">{tr("Tên")}</option><option value="long">{tr("Dài nhất")}</option><option value="rating">{tr("Đánh giá")}</option></select></label>
                <div className="seg" role="radiogroup" aria-label={tr("Cách xem")}>
                  <button type="button" role="radio" aria-checked={view === "grid"} onClick={() => setView("grid")} aria-label={tr("Lưới")}><Icon name="grid" size={15} /></button>
                  <button type="button" role="radio" aria-checked={view === "list"} onClick={() => setView("list")} aria-label={tr("Danh sách")}><Icon name="list" size={15} /></button>
                </div>
              </div>
              {!data && <SkeletonCards count={6} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4" />}
              {data && view === "grid" ? (
                <ul className={`grid gap-4 ${current ? "sm:grid-cols-2 2xl:grid-cols-3" : "sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"}`}>
                  {shown.map((a) => {
                    const working = a.ingest && a.ingest.status !== "succeeded";
                    const seen = a.understand?.status === "succeeded";
                    return (
                      <li key={a.asset_id}>
                        <button type="button" onClick={() => pick(a)} aria-pressed={chosen ? chosen.has(a.asset_id) : picked === a.asset_id}
                                className={`panel group block w-full overflow-hidden text-left transition-[border-color,box-shadow] ${picked === a.asset_id ? "!border-accent shadow-[0_0_0_1px_var(--color-accent),0_8px_30px_-12px_var(--color-accent)]" : "hover:border-edge"}`}>
                          <span className="relative block bg-black">
                            {a.thumbnail_url ? <img src={a.thumbnail_url} alt="" loading="lazy" className="aspect-video w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" />
                              : <span className="grid aspect-video place-items-center bg-raised text-faint"><Icon name={a.kind === "audio" ? "music" : "film"} size={30} /></span>}
                            <TimeChip className="absolute bottom-2 right-2">{a.still ? tr("ẢNH") : a.duration ? timecode(a.duration) : "…"}</TimeChip>
                            {a.rating > 0 && <span className="chip absolute left-2 top-2 !text-cue"><Icon name="star" size={11} />{a.rating}</span>}
                            {seen && <span className="chip absolute right-2 top-2 !text-ai" title={tr("Đã được AI mô tả")}><Icon name="sparkles" size={11} />AI</span>}
                            {a.rejected && <span className="absolute inset-0 grid place-items-center bg-canvas/70 text-[12px] font-medium text-mute">{tr("Đã gạt ra")}</span>}
                            {!a.online && <span className="absolute inset-x-0 top-0 bg-cue/95 px-2 py-0.5 text-[11px] font-medium text-canvas">{tr("Không tìm thấy file gốc")}</span>}
                            {chosen && <span className={`absolute inset-0 grid place-items-start p-2 ${chosen.has(a.asset_id) ? "bg-accent/20 ring-2 ring-inset ring-accent" : "bg-canvas/30"}`}>
                              <span className={`grid h-6 w-6 place-items-center rounded-md border ${chosen.has(a.asset_id) ? "border-accent bg-accent text-canvas" : "border-edge bg-surface/80"}`}>{chosen.has(a.asset_id) && <Icon name="check" size={14} />}</span></span>}
                          </span>
                          <span className="block px-3 pb-3 pt-2.5">
                            <span className="block truncate text-[13.5px] font-medium">{a.name}</span>
                            <span className="mt-1 flex flex-wrap items-center gap-x-2 text-[11.5px] text-faint">
                              {working ? <StatusText status={a.ingest!.status} /> : <>
                                <span className="mono">{a.kind === "audio" ? tr("Nhạc") : `${a.width ?? "?"}×${a.height ?? "?"}`}</span>
                                {a.frame_rate ? <span className="mono">{Math.round(a.frame_rate)}fps</span> : null}
                                <span className="mono">{megabytes(a.size)}</span>
                                {a.kind === "video" && !seen && a.understand && <span className="text-ai">{tr("đang mô tả")}</span>}
                              </>}
                              {a.used_in.length > 0 && <span className="text-proof" title={a.used_in.map((u) => u.title).join(", ")}>{tv`dùng trong ${a.used_in.length} dự án`}</span>}
                              {a.speech && a.speech.words > 0 && <span title={tr("Có lời nói đã được ghi lại")}><Icon name="mic" size={11} className="inline" /></span>}
                              {a.collections.length > 0 && <span className="truncate text-accent">{a.collections.join(", ")}</span>}
                            </span>
                            <span className="mt-2.5 block">{working ? <StageRail stages={a.ingest!.stages} /> : a.kind === "video" ? <RangeStrip asset={a} /> : <span className="block h-1.5" />}</span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <div className="panel overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-[13px]">
                    <thead className="eyebrow"><tr className="[&>th]:px-3 [&>th]:py-2.5">{chosen && <th className="w-8"><span className="sr-only">{tr("Chọn")}</span></th>}<th>{tr("Tên")}</th><th>{tr("Độ dài")}</th><th>{tr("Khung hình")}</th><th>{tr("Dung lượng")}</th><th>{tr("Đánh giá")}</th><th>{tr("Trạng thái")}</th></tr></thead>
                    <tbody className="divide-y divide-line border-t border-line">
                      {shown.map((a) => (
                        <tr key={a.asset_id} onClick={() => pick(a)} className={`cursor-pointer [&>td]:px-3 [&>td]:py-2 ${(chosen ? chosen.has(a.asset_id) : picked === a.asset_id) ? "bg-accent/[0.07]" : "hover:bg-white/[0.02]"}`}>
                          {chosen && <td><input type="checkbox" checked={chosen.has(a.asset_id)} onChange={() => choose(a.asset_id)} onClick={(e) => e.stopPropagation()} aria-label={tv`Chọn ${a.name}`} /></td>}
                          <td><span className="flex items-center gap-3">{a.thumbnail_url ? <img src={a.thumbnail_url} alt="" className="h-9 w-16 rounded object-cover" /> : <span className="grid h-9 w-16 place-items-center rounded bg-raised text-faint"><Icon name={a.kind === "audio" ? "music" : "film"} size={15} /></span>}<span className="truncate font-medium">{a.name}</span></span></td>
                          <td className="mono text-mute">{a.still ? tr("ảnh") : timecode(a.duration)}</td>
                          <td className="mono text-mute">{a.width ? `${a.width}×${a.height}` : "—"}</td>
                          <td className="mono text-mute">{megabytes(a.size)}</td>
                          <td className="text-cue">{"★".repeat(a.rating)}<span className="text-faint">{"★".repeat(5 - a.rating)}</span></td>
                          <td>{a.ingest && a.ingest.status !== "succeeded" ? <StatusText status={a.ingest.status} /> : !a.online ? <span className="text-cue">{tr("Mất file gốc")}</span> : a.understand?.status === "succeeded" ? <span className="text-ai">{tr("Đã mô tả")}</span> : <span className="text-mute">{tr("Sẵn sàng")}</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
        {chosen && (
          <div className="sticky bottom-4 z-20 mt-6 flex flex-wrap items-center gap-3 rounded-xl border border-edge bg-surface/95 px-4 py-3 shadow-xl backdrop-blur">
            <span className="text-[13px]">{chosen.size ? tv`Đã chọn ${chosen.size}` : tr("Bấm vào nguyên liệu để chọn")}</span>
            <button type="button" className="link text-[12.5px]" onClick={() => setChosen(new Set(shown.map((a) => a.asset_id)))}>{tv`Chọn cả ${shown.length} đang hiện`}</button>
            {chosen.size > 0 && <button type="button" className="link text-[12.5px]" onClick={() => setChosen(new Set())}>{tr("Bỏ chọn")}</button>}
            <span className="ml-auto" />
            <Button size="sm" disabled={!chosen.size} onClick={trashChosen}><Icon name="trash" size={14} />{tv`Chuyển vào thùng rác (${chosen.size})`}</Button>
          </div>
        )}
      </Page>
      {current && <Player key={current.asset_id} asset={current} start={start} others={assets} close={() => setPicked(null)}
                           similar={async (m) => { const r = await call<{ hits: Hit[] }>(`/api/v1/moments/${m.moment_id}/similar`); setQ(m.text.slice(0, 60)); setHits(r.hits); }} />}
    </div>
  );
}
