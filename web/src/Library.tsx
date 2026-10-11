import { useEffect, useRef, useState } from "react";
import { call, megabytes, post, timecode, usePoll, type Asset, type Hit, type Moment } from "./api";
import { Button, Icon, Page, RangeStrip, StageRail, StatusText, Tabs, TimeChip } from "./parts";

function AddFootage({ onDone }: { onDone: () => void }) {
  const [path, setPath] = useState("");
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!path.trim()) return;
    setBusy(true);
    try {
      const r = await call<{ registered: unknown[] }>("/api/v1/assets/register", { method: "POST", body: JSON.stringify({ path: path.trim() }) });
      setNote({ ok: true, text: r.registered.length ? `Đã thêm ${r.registered.length} file. Hệ thống đang xử lý.` : "Thư mục này không có file nào dùng được." });
      setPath(""); onDone();
    } catch (e) { setNote({ ok: false, text: (e as Error).message }); }
    setBusy(false);
  };
  return (
    <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <label htmlFor="path" className="sr-only">Đường dẫn tới video hoặc thư mục</label>
      <span className="relative min-w-0 flex-1"><Icon name="folder" size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
        <input id="path" value={path} onChange={(e) => setPath(e.target.value)} placeholder="Đường dẫn tới video, ảnh, nhạc hoặc thư mục, ví dụ /Volumes/Footage/DaLat" className="mono h-10 w-full pl-9 pr-3 text-[13px]" /></span>
      <Button kind="primary" disabled={busy || !path.trim()} onClick={submit}>Thêm vào thư viện</Button>
      {note && <p className={`w-full text-[13px] ${note.ok ? "text-proof" : "text-tally"}`}>{note.text}</p>}
    </form>
  );
}

function Moments({ asset, t, seek, similar }: { asset: Asset; t: number; seek: (s: number) => void; similar: (m: Moment) => void }) {
  const { data, reload } = usePoll<{ video: Moment | null; segments: Moment[] }>(`/api/v1/assets/${asset.asset_id}/moments`, 6000);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  if (!data) return null;
  if (!data.segments.length) return <p className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-[13px] text-mute">{asset.understand && asset.understand.status !== "succeeded" ? "Hệ thống đang xem video này. Mô tả sẽ hiện ra khi xong." : "Video này chưa được mô tả."}</p>;
  const save = async (id: string) => { await post(`/api/v1/moments/${id}`, { text: draft }, "PATCH"); setEditing(null); reload(); };
  return (
    <div className="grid gap-3">
      {data.video && <div className="ai-card p-3.5 text-[13px]"><p className="eyebrow mb-1.5 flex items-center gap-1.5 !text-ai"><Icon name="sparkles" size={12} />Tóm tắt video</p><p className="leading-relaxed">{data.video.text}</p></div>}
      <ol className="grid gap-2">
        {data.segments.map((m) => {
          const now = t >= m.t_start && t < m.t_end;
          return (
            <li key={m.moment_id} className={`rounded-xl border p-2.5 transition-colors ${now ? "border-accent/50 bg-accent/[0.06]" : "border-line bg-raised/40 hover:border-edge"}`}>
              <div className="flex gap-3">
                <button type="button" onClick={() => seek(m.t_start)} className="group relative w-28 shrink-0 overflow-hidden rounded-md bg-black" title="Tới đoạn này">
                  {m.frame_url ? <img src={m.frame_url} alt="" loading="lazy" className="aspect-video w-full object-cover transition-opacity group-hover:opacity-80" /> : <span className="grid aspect-video place-items-center text-faint"><Icon name="film" /></span>}
                  <TimeChip className="absolute bottom-1 left-1 !h-[18px] !px-1.5 !text-[10px]">{timecode(m.t_start)}</TimeChip>
                </button>
                <div className="min-w-0 flex-1">
                  {m.title && <p className={`mb-0.5 text-[13px] font-medium ${now ? "text-accent" : ""}`}>{m.title}</p>}
                  {editing === m.moment_id ? (
                    <div><textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} className="w-full p-2 text-[13px]" aria-label="Sửa mô tả" />
                      <div className="mt-1.5 flex gap-2"><Button size="sm" kind="primary" onClick={() => save(m.moment_id)}>Lưu mô tả</Button><Button size="sm" onClick={() => setEditing(null)}>Bỏ</Button></div></div>
                  ) : <p className="line-clamp-3 text-[12.5px] leading-relaxed text-mute">{m.text}</p>}
                </div>
              </div>
              {editing !== m.moment_id && (
                <div className="mt-2 flex items-center gap-3 pl-[124px] text-[11.5px]">
                  <span className="mono rounded bg-overlay px-1.5 text-faint">CẢNH</span>
                  {m.source === "human" && <span className="text-accent">Bạn đã sửa</span>}
                  <span className="ml-auto" />
                  <button type="button" className="link" onClick={() => { setEditing(m.moment_id); setDraft(m.text); }}>Sửa</button>
                  <button type="button" className="flex items-center gap-1 text-ai hover:underline" onClick={() => similar(m)}><Icon name="sparkles" size={12} />Tìm cảnh giống</button>
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Player({ asset, start, others, close, similar }: { asset: Asset; start?: number; others: Asset[]; close: () => void; similar: (m: Moment) => void }) {
  const [memo, setMemo] = useState<string | null>(null);
  const [other, setOther] = useState("");
  const [sync, setSync] = useState<string | null>(null);
  const [tags, setTags] = useState<string | null>(null);
  const [tab, setTab] = useState<"scenes" | "info">(asset.kind === "video" ? "scenes" : "info");
  const video = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  const seek = (s: number) => { if (video.current) { video.current.currentTime = s; video.current.play().catch(() => {}); } };
  useEffect(() => { setT(start ?? 0); const v = video.current; if (v && start != null) { const go = () => { v.currentTime = start; }; v.readyState >= 1 ? go() : v.addEventListener("loadedmetadata", go, { once: true }); } }, [asset.asset_id, start]);
  const unusable = asset.black_ranges.reduce((sum, [a, b]) => sum + (b - a), 0);
  const partners = others.filter((o) => o.asset_id !== asset.asset_id && o.kind === "video" && o.has_audio);
  const facts: [string, string][] = [
    ["Loại", asset.kind === "audio" ? "Nhạc" : asset.still ? "Ảnh" : "Video"],
    ...(asset.width ? [["Khung hình", `${asset.width}×${asset.height}`] as [string, string]] : []),
    ...(asset.frame_rate ? [["Tốc độ", `${Math.round(asset.frame_rate * 100) / 100} fps`] as [string, string]] : []),
    ...(asset.duration && !asset.still ? [["Độ dài", timecode(asset.duration)] as [string, string]] : []),
    ["Dung lượng", megabytes(asset.size)],
    ...(asset.kind !== "image" && !asset.still ? [["Âm thanh", asset.has_audio ? (asset.mean_db != null ? `có, ${asset.mean_db.toFixed(0)} dB` : "có") : "không"] as [string, string]] : []),
  ];
  return (
    <aside className="rise flex w-full flex-col overflow-hidden border-t border-line bg-surface lg:w-[460px] lg:shrink-0 lg:border-l lg:border-t-0" aria-label="Chi tiết nguyên liệu">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <Icon name={asset.kind === "audio" ? "music" : asset.still ? "image" : "film"} size={15} className="text-mute" />
        <h2 className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{asset.name}</h2>
        <button type="button" onClick={close} className="grid h-7 w-7 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink" aria-label="Đóng"><Icon name="x" size={15} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="bg-black">
          {asset.proxy_url
            ? <video ref={video} key={asset.proxy_url} src={asset.proxy_url} controls className="aspect-video w-full bg-black" onTimeUpdate={(e) => setT(e.currentTarget.currentTime)} />
            : asset.still && asset.thumbnail_url ? <img src={asset.thumbnail_url} alt="" className="aspect-video w-full bg-black object-contain" />
            : <div className="grid aspect-video w-full place-items-center text-[13px] text-mute">Bản xem chưa sẵn sàng</div>}
        </div>
        {!asset.still && asset.kind === "video" && <div className="px-4 pt-3"><RangeStrip asset={asset} tall playhead={t} onSeek={seek} /></div>}
        <div className="grid gap-2 px-4 pt-3">
          {unusable > 0 && <p className="flex items-center gap-2 text-[12.5px] text-mute"><span className="hatch inline-block h-3 w-5 rounded-sm" />Có <span className="mono text-ink">{timecode(unusable)}</span> khung đen — hệ thống sẽ không chọn clip từ phần này.</p>}
          {asset.duplicate_of && <p className="text-[12.5px] text-mute">File này trùng nội dung với một video đã có trong thư viện nên không được xử lý lại.</p>}
          {!asset.online && <p className="rounded-lg border border-cue/30 bg-cue/5 px-3 py-2 text-[12.5px] text-cue">Không tìm thấy file gốc. Hãy cắm lại ổ chứa nó để render bản cuối.</p>}
        </div>
        <div className="mt-2 px-4"><Tabs value={tab} onChange={setTab} items={[...(asset.kind === "video" ? [{ key: "scenes" as const, label: "Các cảnh", icon: "layers" }] : []), { key: "info" as const, label: "Thông tin", icon: "sliders" }]} /></div>
        <div className="border-t border-line p-4">
          {tab === "scenes" && <Moments asset={asset} t={t} seek={seek} similar={similar} />}
          {tab === "info" && (
            <div className="grid gap-5">
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line">
                {facts.map(([k, v]) => <div key={k} className="bg-surface px-3 py-2"><dt className="eyebrow !text-[10px]">{k}</dt><dd className="mono mt-0.5 text-[13px]">{v}</dd></div>)}
              </dl>
              <div>
                <p className="field-label" id="rate">Bạn chấm</p>
                <div className="flex gap-1" role="radiogroup" aria-labelledby="rate">
                  {[1, 2, 3, 4, 5].map((n) => <button key={n} type="button" role="radio" aria-checked={asset.rating === n} aria-label={`${n} sao`} onClick={() => post(`/api/v1/assets/${asset.asset_id}`, { rating: asset.rating === n ? 0 : n }, "PATCH")}
                    className={`grid h-8 w-8 place-items-center rounded-lg border transition-colors ${n <= asset.rating ? "border-cue/40 bg-cue/10 text-cue" : "border-line text-faint hover:border-edge hover:text-mute"}`}><svg width="15" height="15" viewBox="0 0 20 20" fill={n <= asset.rating ? "currentColor" : "none"} stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true"><path d="m10 3.3 2 4.3 4.6.5-3.4 3.2.9 4.6L10 13.6l-4.1 2.3.9-4.6-3.4-3.2 4.6-.5 2-4.3Z" /></svg></button>)}
                </div>
              </div>
              <form onSubmit={(e) => { e.preventDefault(); post(`/api/v1/assets/${asset.asset_id}`, { collections: (tags ?? asset.collections.join(", ")).split(",") }, "PATCH").then(() => setTags(null)); }}>
                <label htmlFor="tags" className="field-label">Bộ sưu tập</label>
                <div className="flex gap-2">
                  <input id="tags" value={tags ?? asset.collections.join(", ")} onChange={(e) => setTags(e.target.value)} placeholder="Cách nhau bằng dấu phẩy: Hội An, cà phê" className="min-w-0 flex-1 px-3" />
                  <Button type="submit" disabled={tags === null}>Lưu</Button>
                </div>
              </form>
              <form onSubmit={(e) => { e.preventDefault(); post(`/api/v1/assets/${asset.asset_id}`, { note: memo ?? "" }, "PATCH").then(() => setMemo(null)); }}>
                <label htmlFor="memo" className="field-label">Ghi chú buổi quay</label>
                <textarea id="memo" rows={2} value={memo ?? asset.note ?? ""} onChange={(e) => setMemo(e.target.value)} placeholder="Ví dụ: quay sáng thứ bảy ở chợ Hội An, máy cầm tay" className="w-full p-2.5 text-[13px]" />
                {memo !== null && <div className="mt-1.5 flex gap-2"><Button size="sm" kind="primary" onClick={() => post(`/api/v1/assets/${asset.asset_id}`, { note: memo }, "PATCH").then(() => setMemo(null))}>Lưu ghi chú</Button><Button size="sm" onClick={() => setMemo(null)}>Bỏ</Button></div>}
              </form>
              {asset.kind === "video" && asset.has_audio && partners.length > 0 && (
                <div>
                  <p className="field-label">Quay cùng lúc với clip khác</p>
                  {asset.angles.map((a) => <p key={a.asset_id} className="mb-1 text-[12.5px]">{others.find((o) => o.asset_id === a.asset_id)?.name}: <span className="mono text-mute">{a.offset >= 0 ? "sớm hơn" : "muộn hơn"} {Math.abs(a.offset).toFixed(2)}s</span></p>)}
                  <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (!other) return; setSync("Đang so âm thanh của hai clip…"); try { const r = await post<{ offset: number }>("/api/v1/assets/sync", { a: asset.asset_id, b: other }); setSync(`Đã đồng bộ, lệch ${Math.abs(r.offset).toFixed(2)} giây.`); } catch (err) { setSync((err as Error).message); } }}>
                    <label htmlFor="other" className="sr-only">Clip quay cùng lúc</label>
                    <select id="other" value={other} onChange={(e) => setOther(e.target.value)} className="min-w-0 flex-1 pl-2.5">
                      <option value="">Chọn clip quay cùng lúc</option>
                      {partners.map((o) => <option key={o.asset_id} value={o.asset_id}>{o.name}</option>)}
                    </select>
                    <Button type="submit" disabled={!other}><Icon name="wave" size={14} />Đồng bộ theo tiếng</Button>
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
const KINDS = [["", "Tất cả", "layers"], ["video", "Video", "film"], ["image", "Ảnh", "image"], ["audio", "Nhạc", "music"]] as const;

export default function Library() {
  const { data, error, reload } = usePoll<{ assets: Asset[] }>("/api/v1/library");
  const [picked, setPicked] = useState<string | null>(null);
  const [start, setStart] = useState<number | undefined>();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [searching, setSearching] = useState(false);
  const runSearch = async (text: string) => { if (!text.trim()) { setHits(null); return; } setSearching(true); try { const r = await call<{ hits: Hit[] }>(`/api/v1/library/search?q=${encodeURIComponent(text.trim())}`); setHits(r.hits); } finally { setSearching(false); } };
  const search = () => runSearch(q);
  // A search started from ⌘K arrives as ?q=…
  const asked = new URLSearchParams(window.location.search).get("q");
  useEffect(() => { if (asked) { setQ(asked); runSearch(asked); window.history.replaceState({}, "", "/thu-vien"); } }, [asked]);
  const assets = data?.assets ?? [];
  const current = assets.find((a) => a.asset_id === picked) ?? null;
  const [kind, setKind] = useState("");
  const [group, setGroup] = useState("");
  const [least, setLeast] = useState(0);
  const [sort, setSort] = useState<Sort>("name");
  const [view, setView] = useState<"grid" | "list">("grid");
  const groups = [...new Set(assets.flatMap((a) => a.collections))].sort();
  const shown = assets.filter((a) => (!kind || a.kind === kind) && (!group || a.collections.includes(group)) && a.rating >= least)
    .sort((a, b) => (sort === "long" ? (b.duration ?? 0) - (a.duration ?? 0) : sort === "rating" ? b.rating - a.rating : a.name.localeCompare(b.name)));
  const seconds = assets.reduce((sum, a) => sum + (a.kind === "video" ? a.duration ?? 0 : 0), 0);
  const described = assets.filter((a) => a.understand?.status === "succeeded").length;
  const pick = (a: Asset, t?: number) => { setPicked(a.asset_id); setStart(t); };
  const facet = (on: boolean) => `flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] transition-colors ${on ? "bg-raised font-medium text-ink" : "text-mute hover:bg-raised/50 hover:text-ink"}`;
  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <Page eyebrow="Sản xuất" title="Thư viện" wide
            note={assets.length ? <span className="flex flex-wrap gap-x-3"><span>{assets.length} nguyên liệu</span><span className="mono">{timecode(seconds)} video</span><span className="text-ai">{described} đã được AI mô tả</span></span> : "Footage, ảnh và nhạc của bạn. File gốc không bị sao chép hay sửa."}
            actions={<Button kind={adding ? "plain" : "primary"} onClick={() => setAdding(!adding)}><Icon name={adding ? "x" : "plus"} />{adding ? "Đóng" : "Thêm footage"}</Button>}>
        {(adding || (data && assets.length === 0)) && <div className="panel glow rise mb-5 p-5"><p className="mb-1 font-semibold">Thêm video, ảnh, nhạc hoặc cả thư mục</p><p className="mb-3 text-[13px] text-mute">Hệ thống chỉ ghi lại vị trí file, rồi tự xem và mô tả từng đoạn để bạn tìm bằng lời.</p><AddFootage onDone={reload} /></div>}

        <form className="ai-card mb-5 p-3" onSubmit={(e) => { e.preventDefault(); search(); }}>
          <div className="mb-2 flex items-center gap-2 px-1 text-[12.5px]"><Icon name="sparkles" size={14} className="text-ai" /><span className="font-medium">Tìm cảnh bằng lời</span>
            <span className="ml-auto flex items-center gap-1.5 text-mute"><span className="h-1.5 w-1.5 rounded-full bg-proof" />{described} video đã hiểu</span></div>
          <div className="relative">
            <label htmlFor="q" className="sr-only">Tìm trong footage</label>
            <Icon name="search" size={18} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-faint" />
            <input id="q" value={q} onChange={(e) => { setQ(e.target.value); if (!e.target.value) setHits(null); }} placeholder="Mô tả cảnh bạn cần, ví dụ: bàn tay rót cà phê ra tách"
                   className="h-12 w-full pl-11 pr-32 text-[15px]" />
            <span className="absolute right-2 top-1/2 -translate-y-1/2"><Button kind="primary" size="sm" type="submit" disabled={!q.trim() || searching}>{searching ? "Đang tìm…" : "Tìm cảnh"}</Button></span>
          </div>
        </form>

        {hits && (
          <div className="mb-8">
            <div className="mb-3 flex items-baseline justify-between gap-4"><h2 className="text-[15px] font-semibold">{hits.length ? <>{hits.length} cảnh khớp với <span className="text-ai">“{q}”</span></> : `Không có cảnh nào khớp với “${q}”`}</h2>
              <button type="button" className="link text-[12.5px]" onClick={() => { setHits(null); setQ(""); }}>Bỏ tìm kiếm</button></div>
            {!hits.length && <p className="text-mute">Thử từ khác, hoặc kiểm tra xem video đã được hệ thống xem xong chưa ở mục Tiến trình.</p>}
            <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
              {hits.map((h, i) => (
                <li key={h.moment_id}>
                  <button type="button" className="panel group block w-full overflow-hidden text-left transition-colors hover:border-ai/50" onClick={() => { setPicked(h.asset_id); setStart(h.t_start); }}>
                    <span className="relative block bg-black">{h.frame_url ? <img src={h.frame_url} alt="" loading="lazy" className="aspect-video w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" /> : <span className="block aspect-video" />}
                      <TimeChip className="absolute bottom-2 left-2">{h.asset.still ? "ẢNH" : `${timecode(h.t_start)} – ${timecode(h.t_end)}`}</TimeChip>
                      <span className="mono absolute right-2 top-2 grid h-6 w-6 place-items-center rounded-md bg-ai/90 text-[11px] font-semibold text-canvas">{i + 1}</span></span>
                    <span className="block px-3 py-2.5"><span className="block truncate text-[12px] text-faint">{h.asset.name}</span>
                      <span className="mt-0.5 line-clamp-2 text-[13px]">{h.text}</span></span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {error && <p className="mb-4 text-tally">Không tải được thư viện: {error}</p>}

        {assets.length > 0 && (
          <div className={`grid items-start gap-6 ${current ? "2xl:grid-cols-[200px_minmax(0,1fr)]" : "lg:grid-cols-[200px_minmax(0,1fr)]"}`}>
            <nav className={`gap-5 lg:sticky lg:top-0 ${current ? "hidden 2xl:grid" : "grid"}`} aria-label="Lọc thư viện">
              <div>
                <p className="eyebrow mb-1.5 px-2.5">Loại</p>
                {KINDS.map(([k, name, icon]) => <button key={k} type="button" onClick={() => setKind(k)} aria-pressed={kind === k} className={facet(kind === k)}><Icon name={icon} size={15} /><span className="flex-1">{name}</span><span className="mono text-[11px] text-faint">{k ? assets.filter((a) => a.kind === k).length : assets.length}</span></button>)}
              </div>
              {groups.length > 0 && (
                <div>
                  <p className="eyebrow mb-1.5 px-2.5">Bộ sưu tập</p>
                  <button type="button" onClick={() => setGroup("")} aria-pressed={!group} className={facet(!group)}><Icon name="folder" size={15} /><span className="flex-1">Mọi bộ sưu tập</span></button>
                  {groups.map((g) => <button key={g} type="button" onClick={() => setGroup(g)} aria-pressed={group === g} className={facet(group === g)}><Icon name="folder" size={15} className="text-accent" /><span className="flex-1 truncate">{g}</span><span className="mono text-[11px] text-faint">{assets.filter((a) => a.collections.includes(g)).length}</span></button>)}
                </div>
              )}
              <div>
                <p className="eyebrow mb-1.5 px-2.5">Đánh giá</p>
                <button type="button" onClick={() => setLeast(least ? 0 : 4)} aria-pressed={least > 0} className={facet(least > 0)}><Icon name="star" size={15} className={least ? "text-cue" : ""} /><span className="flex-1">Từ 4 sao</span></button>
              </div>
            </nav>
            <div className="min-w-0">
              <div className="mb-4 flex flex-wrap items-center gap-3">
                <span className="mono text-[12px] text-faint">{shown.length} / {assets.length}</span>
                <span className="ml-auto" />
                <label className="flex items-center gap-2 text-[12.5px] text-mute">Sắp xếp<select value={sort} onChange={(e) => setSort(e.target.value as Sort)} className="h-8 pl-2.5 text-[12.5px]"><option value="name">Tên</option><option value="long">Dài nhất</option><option value="rating">Đánh giá</option></select></label>
                <div className="seg" role="radiogroup" aria-label="Cách xem">
                  <button type="button" role="radio" aria-checked={view === "grid"} onClick={() => setView("grid")} aria-label="Lưới"><Icon name="grid" size={15} /></button>
                  <button type="button" role="radio" aria-checked={view === "list"} onClick={() => setView("list")} aria-label="Danh sách"><Icon name="list" size={15} /></button>
                </div>
              </div>
              {view === "grid" ? (
                <ul className={`grid gap-4 ${current ? "sm:grid-cols-2 2xl:grid-cols-3" : "sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"}`}>
                  {shown.map((a) => {
                    const working = a.ingest && a.ingest.status !== "succeeded";
                    const seen = a.understand?.status === "succeeded";
                    return (
                      <li key={a.asset_id}>
                        <button type="button" onClick={() => pick(a)} aria-pressed={picked === a.asset_id}
                                className={`panel group block w-full overflow-hidden text-left transition-[border-color,box-shadow] ${picked === a.asset_id ? "!border-accent shadow-[0_0_0_1px_var(--color-accent),0_8px_30px_-12px_var(--color-accent)]" : "hover:border-edge"}`}>
                          <span className="relative block bg-black">
                            {a.thumbnail_url ? <img src={a.thumbnail_url} alt="" loading="lazy" className="aspect-video w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" />
                              : <span className="grid aspect-video place-items-center bg-gradient-to-br from-raised to-surface text-faint"><Icon name={a.kind === "audio" ? "music" : "film"} size={30} /></span>}
                            <TimeChip className="absolute bottom-2 right-2">{a.still ? "ẢNH" : a.duration ? timecode(a.duration) : "…"}</TimeChip>
                            {a.rating > 0 && <span className="chip absolute left-2 top-2 !text-cue"><Icon name="star" size={11} />{a.rating}</span>}
                            {seen && <span className="chip absolute right-2 top-2 !text-ai" title="Đã được AI mô tả"><Icon name="sparkles" size={11} />AI</span>}
                            {!a.online && <span className="absolute inset-x-0 top-0 bg-cue/95 px-2 py-0.5 text-[11px] font-medium text-canvas">Không tìm thấy file gốc</span>}
                          </span>
                          <span className="block px-3 pb-3 pt-2.5">
                            <span className="block truncate text-[13.5px] font-medium">{a.name}</span>
                            <span className="mt-1 flex flex-wrap items-center gap-x-2 text-[11.5px] text-faint">
                              {working ? <StatusText status={a.ingest!.status} /> : <>
                                <span className="mono">{a.kind === "audio" ? "Nhạc" : `${a.width ?? "?"}×${a.height ?? "?"}`}</span>
                                {a.frame_rate ? <span className="mono">{Math.round(a.frame_rate)}fps</span> : null}
                                <span className="mono">{megabytes(a.size)}</span>
                                {a.kind === "video" && !seen && a.understand && <span className="text-ai">đang mô tả</span>}
                              </>}
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
                    <thead className="eyebrow"><tr className="[&>th]:px-3 [&>th]:py-2.5"><th>Tên</th><th>Độ dài</th><th>Khung hình</th><th>Dung lượng</th><th>Đánh giá</th><th>Trạng thái</th></tr></thead>
                    <tbody className="divide-y divide-line border-t border-line">
                      {shown.map((a) => (
                        <tr key={a.asset_id} onClick={() => pick(a)} className={`cursor-pointer [&>td]:px-3 [&>td]:py-2 ${picked === a.asset_id ? "bg-accent/[0.07]" : "hover:bg-white/[0.02]"}`}>
                          <td><span className="flex items-center gap-3">{a.thumbnail_url ? <img src={a.thumbnail_url} alt="" className="h-9 w-16 rounded object-cover" /> : <span className="grid h-9 w-16 place-items-center rounded bg-raised text-faint"><Icon name={a.kind === "audio" ? "music" : "film"} size={15} /></span>}<span className="truncate font-medium">{a.name}</span></span></td>
                          <td className="mono text-mute">{a.still ? "ảnh" : timecode(a.duration)}</td>
                          <td className="mono text-mute">{a.width ? `${a.width}×${a.height}` : "—"}</td>
                          <td className="mono text-mute">{megabytes(a.size)}</td>
                          <td className="text-cue">{"★".repeat(a.rating)}<span className="text-faint">{"★".repeat(5 - a.rating)}</span></td>
                          <td>{a.ingest && a.ingest.status !== "succeeded" ? <StatusText status={a.ingest.status} /> : !a.online ? <span className="text-cue">Mất file gốc</span> : a.understand?.status === "succeeded" ? <span className="text-ai">Đã mô tả</span> : <span className="text-mute">Sẵn sàng</span>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </Page>
      {current && <Player key={current.asset_id} asset={current} start={start} others={assets} close={() => setPicked(null)}
                           similar={async (m) => { const r = await call<{ hits: Hit[] }>(`/api/v1/moments/${m.moment_id}/similar`); setQ(m.text.slice(0, 60)); setHits(r.hits); }} />}
    </div>
  );
}
