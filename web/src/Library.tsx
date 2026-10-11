import { useEffect, useRef, useState } from "react";
import { call, megabytes, post, timecode, usePoll, type Asset, type Hit, type Moment } from "./api";
import { Button, Icon, Page, RangeStrip, StageRail, StatusText } from "./parts";

function AddFootage({ onDone }: { onDone: () => void }) {
  const [path, setPath] = useState("");
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!path.trim()) return;
    setBusy(true);
    try {
      const r = await call<{ registered: unknown[] }>("/api/v1/assets/register", { method: "POST", body: JSON.stringify({ path: path.trim() }) });
      setNote({ ok: true, text: r.registered.length ? `Đã thêm ${r.registered.length} video. Hệ thống đang xử lý.` : "Thư mục này không có video nào." });
      setPath(""); onDone();
    } catch (e) { setNote({ ok: false, text: (e as Error).message }); }
    setBusy(false);
  };
  return (
    <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <label htmlFor="path" className="sr-only">Đường dẫn tới video hoặc thư mục</label>
      <input id="path" value={path} onChange={(e) => setPath(e.target.value)} placeholder="Đường dẫn tới video, ảnh, nhạc hoặc thư mục, ví dụ /Volumes/Footage/DaLat"
             className="min-w-0 flex-1 px-3" />
      <Button kind="primary" disabled={busy || !path.trim()} onClick={submit}>Thêm vào thư viện</Button>
      {note && <p className={`w-full text-sm ${note.ok ? "text-mute" : "text-tally"}`}>{note.text}</p>}
    </form>
  );
}

function Moments({ asset, t, seek, similar }: { asset: Asset; t: number; seek: (s: number) => void; similar: (m: Moment) => void }) {
  const { data, reload } = usePoll<{ video: Moment | null; segments: Moment[] }>(`/api/v1/assets/${asset.asset_id}/moments`, 6000);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  if (!data) return null;
  if (!data.segments.length) return <p className="text-mute">{asset.understand && asset.understand.status !== "succeeded" ? "Hệ thống đang xem video này. Mô tả sẽ hiện ra khi xong." : "Video này chưa được mô tả."}</p>;
  const save = async (id: string) => { await post(`/api/v1/moments/${id}`, { text: draft }, "PATCH"); setEditing(null); reload(); };
  return (
    <div>
      {data.video && <p className="mb-3">{data.video.text}</p>}
      <h3 className="mb-1 font-semibold">Từng đoạn</h3>
      <ol className="divide-y divide-line border-y border-line">
        {data.segments.map((m) => {
          const now = t >= m.t_start && t < m.t_end;
          return (
            <li key={m.moment_id} className={`grid grid-cols-[3.2rem_1fr] gap-2 py-2 ${now ? "bg-raised/60" : ""}`}>
              <button type="button" className="tc self-start text-left text-mute hover:text-ink" onClick={() => seek(m.t_start)}>{timecode(m.t_start)}</button>
              {editing === m.moment_id ? (
                <div><textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={3} className="w-full rounded border border-line bg-canvas p-2" aria-label="Sửa mô tả" />
                  <div className="mt-1 flex gap-2"><Button kind="primary" onClick={() => save(m.moment_id)}>Lưu mô tả</Button><Button onClick={() => setEditing(null)}>Bỏ</Button></div></div>
              ) : (
                <p>{m.text} <button type="button" className="text-mute underline decoration-line underline-offset-2 hover:text-ink" onClick={() => { setEditing(m.moment_id); setDraft(m.text); }}>Sửa</button>
                  <button type="button" className="ml-2 text-mute underline decoration-line underline-offset-2 hover:text-ink" onClick={() => similar(m)}>Tìm cảnh giống</button>
                  {m.source === "human" && <span className="ml-2 text-xs text-mute">Bạn đã sửa</span>}</p>
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
  const video = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  const seek = (s: number) => { if (video.current) { video.current.currentTime = s; video.current.play().catch(() => {}); } };
  useEffect(() => { setT(start ?? 0); const v = video.current; if (v && start != null) { const go = () => { v.currentTime = start; }; v.readyState >= 1 ? go() : v.addEventListener("loadedmetadata", go, { once: true }); } }, [asset.asset_id, start]);
  const unusable = asset.black_ranges.reduce((sum, [a, b]) => sum + (b - a), 0);
  return (
    <aside className="rise flex w-full flex-col gap-5 overflow-y-auto border-t border-line bg-surface p-5 lg:w-[460px] lg:shrink-0 lg:border-l lg:border-t-0" aria-label="Chi tiết nguyên liệu">
      <div className="-mb-2 flex justify-end"><button type="button" onClick={close} className="text-[13px] text-mute hover:text-ink">Đóng</button></div>
      {asset.proxy_url
        ? <video ref={video} key={asset.proxy_url} src={asset.proxy_url} controls className="aspect-video w-full rounded bg-black" onTimeUpdate={(e) => setT(e.currentTarget.currentTime)} />
        : asset.still && asset.thumbnail_url ? <img src={asset.thumbnail_url} alt="" className="aspect-video w-full rounded bg-black object-contain" />
        : <div className="grid aspect-video w-full place-items-center rounded bg-canvas text-mute">Bản xem chưa sẵn sàng</div>}
      {!asset.still && <RangeStrip asset={asset} tall playhead={t} onSeek={seek} />}
      <div>
        <h2 className="break-all text-base font-semibold">{asset.name}</h2>
        <p className="tc text-mute">{asset.width}×{asset.height}, {asset.frame_rate ? `${Math.round(asset.frame_rate)} khung/giây, ` : ""}{megabytes(asset.size)}, {asset.has_audio ? "có âm thanh" : "không có âm thanh"}</p>
      </div>
      {unusable > 0 && <p>Có <span className="tc">{timecode(unusable)}</span> khung đen. Hệ thống sẽ không chọn clip từ phần này.</p>}
      {asset.duplicate_of && <p className="text-mute">File này trùng nội dung với một video đã có trong thư viện nên không được xử lý lại.</p>}
      {!asset.online && <p className="text-cue">Không tìm thấy file gốc. Hãy cắm lại ổ chứa nó để render bản cuối.</p>}
      {asset.kind === "video" && asset.has_audio && others.filter((o) => o.asset_id !== asset.asset_id && o.kind === "video" && o.has_audio).length > 0 && (
        <div>
          <h3 className="mb-1 font-semibold">Quay cùng lúc với clip khác</h3>
          {asset.angles.map((a) => <p key={a.asset_id} className="tc text-sm">{others.find((o) => o.asset_id === a.asset_id)?.name}: {a.offset >= 0 ? "bắt đầu sớm hơn" : "bắt đầu muộn hơn"} {Math.abs(a.offset).toFixed(2)} giây</p>)}
          <form className="mt-1 flex gap-2" onSubmit={async (e) => { e.preventDefault(); if (!other) return; setSync("Đang so âm thanh của hai clip"); try { const r = await post<{ offset: number }>("/api/v1/assets/sync", { a: asset.asset_id, b: other }); setSync(`Đã đồng bộ, lệch ${Math.abs(r.offset).toFixed(2)} giây.`); } catch (err) { setSync((err as Error).message); } }}>
            <label htmlFor="other" className="sr-only">Clip quay cùng lúc</label>
            <select id="other" value={other} onChange={(e) => setOther(e.target.value)} className="min-w-0 flex-1 rounded border border-line bg-canvas px-2 py-1.5">
              <option value="">Chọn clip quay cùng lúc</option>
              {others.filter((o) => o.asset_id !== asset.asset_id && o.kind === "video" && o.has_audio).map((o) => <option key={o.asset_id} value={o.asset_id}>{o.name}</option>)}
            </select>
            <button type="submit" disabled={!other} className="rounded border border-line px-3 py-1.5 text-sm font-medium hover:border-mute disabled:opacity-40">Đồng bộ theo tiếng</button>
          </form>
          {sync && <p className="mt-1 text-sm text-mute">{sync}</p>}
        </div>
      )}
      <div className="grid gap-2">
        <div className="flex items-center gap-3"><span className="font-semibold" id="rate">Bạn chấm</span>
          <div className="flex gap-1" role="radiogroup" aria-labelledby="rate">
            {[1, 2, 3, 4, 5].map((n) => <button key={n} type="button" role="radio" aria-checked={asset.rating === n} aria-label={`${n} sao`} onClick={() => post(`/api/v1/assets/${asset.asset_id}`, { rating: asset.rating === n ? 0 : n }, "PATCH")}
              className={`h-6 w-6 rounded-sm border text-xs ${n <= asset.rating ? "border-ink bg-ink text-canvas" : "border-line text-mute hover:border-mute"}`}>{n}</button>)}
          </div>
        </div>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); post(`/api/v1/assets/${asset.asset_id}`, { collections: (tags ?? asset.collections.join(", ")).split(",") }, "PATCH").then(() => setTags(null)); }}>
          <label htmlFor="tags" className="sr-only">Bộ sưu tập</label>
          <input id="tags" value={tags ?? asset.collections.join(", ")} onChange={(e) => setTags(e.target.value)} placeholder="Bộ sưu tập, cách nhau bằng dấu phẩy: Hội An, cà phê" className="min-w-0 flex-1 rounded border border-line bg-canvas px-2 py-1.5 placeholder:text-mute/70" />
          <button type="submit" disabled={tags === null} className="rounded border border-line px-3 py-1.5 text-sm font-medium hover:border-mute disabled:opacity-40">Lưu</button>
        </form>
      </div>
      <form onSubmit={(e) => { e.preventDefault(); post(`/api/v1/assets/${asset.asset_id}`, { note: memo ?? "" }, "PATCH").then(() => setMemo(null)); }}>
        <label htmlFor="memo" className="mb-1 block font-semibold">Ghi chú buổi quay</label>
        <textarea id="memo" rows={2} value={memo ?? asset.note ?? ""} onChange={(e) => setMemo(e.target.value)} placeholder="Ví dụ: quay sáng thứ bảy ở chợ Hội An, máy cầm tay" className="w-full p-2.5" />
        {memo !== null && <div className="mt-1.5 flex gap-2"><Button size="sm" kind="primary" onClick={() => post(`/api/v1/assets/${asset.asset_id}`, { note: memo }, "PATCH").then(() => setMemo(null))}>Lưu ghi chú</Button><Button size="sm" onClick={() => setMemo(null)}>Bỏ</Button></div>}
      </form>
      <Moments asset={asset} t={t} seek={seek} similar={similar} />
      <p className="break-all text-xs text-mute">{asset.path}</p>
    </aside>
  );
}

export default function Library() {
  const { data, error, reload } = usePoll<{ assets: Asset[] }>("/api/v1/library");
  const [picked, setPicked] = useState<string | null>(null);
  const [start, setStart] = useState<number | undefined>();
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [adding, setAdding] = useState(false);
  const search = async () => { if (!q.trim()) { setHits(null); return; } const r = await call<{ hits: Hit[] }>(`/api/v1/library/search?q=${encodeURIComponent(q.trim())}`); setHits(r.hits); };
  const assets = data?.assets ?? [];
  const current = assets.find((a) => a.asset_id === picked) ?? null;
  const [kind, setKind] = useState("");
  const [group, setGroup] = useState("");
  const [least, setLeast] = useState(0);
  const groups = [...new Set(assets.flatMap((a) => a.collections))].sort();
  const shown = assets.filter((a) => (!kind || a.kind === kind) && (!group || a.collections.includes(group)) && a.rating >= least);
  const seconds = assets.reduce((sum, a) => sum + (a.kind === "video" ? a.duration ?? 0 : 0), 0);
  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <Page title="Thư viện" note={assets.length ? `${assets.length} nguyên liệu, ${timecode(seconds)} video. Hệ thống đã xem và mô tả từng đoạn để bạn tìm bằng lời.` : "Footage, ảnh và nhạc của bạn. File gốc không bị sao chép hay sửa."}
            actions={<Button kind={adding ? "plain" : "primary"} onClick={() => setAdding(!adding)}><Icon name="plus" />Thêm footage</Button>} wide>
        {(adding || (data && assets.length === 0)) && <div className="panel rise mb-6 p-5"><p className="mb-2 font-medium">Thêm video, ảnh, nhạc hoặc cả thư mục</p><AddFootage onDone={reload} /></div>}
        <form className="relative mb-4" onSubmit={(e) => { e.preventDefault(); search(); }}>
          <label htmlFor="q" className="sr-only">Tìm trong footage</label>
          <span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-faint"><Icon name="search" size={18} /></span>
          <input id="q" value={q} onChange={(e) => { setQ(e.target.value); if (!e.target.value) setHits(null); }} placeholder="Tìm một cảnh bằng lời, ví dụ: rót cà phê ra tách"
                 className="h-11 w-full pl-11 pr-28 text-[15px]" />
          <span className="absolute right-1.5 top-1/2 -translate-y-1/2"><Button size="sm" onClick={search} disabled={!q.trim()}>Tìm cảnh</Button></span>
        </form>
        {hits && (
          <div className="mb-8">
            <div className="mb-3 flex items-baseline justify-between gap-4"><h2 className="text-[15px] font-semibold">{hits.length ? `${hits.length} cảnh khớp với “${q}”` : `Không có cảnh nào khớp với “${q}”`}</h2>
              <button type="button" className="text-[13px] text-mute hover:text-ink" onClick={() => { setHits(null); setQ(""); }}>Bỏ tìm kiếm</button></div>
            {!hits.length && <p className="text-mute">Thử từ khác, hoặc kiểm tra xem video đã được hệ thống xem xong chưa ở mục Tiến trình.</p>}
            <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              {hits.map((h) => (
                <li key={h.moment_id}>
                  <button type="button" className="group w-full text-left" onClick={() => { setPicked(h.asset_id); setStart(h.t_start); }}>
                    <span className="relative block overflow-hidden rounded-md bg-black">{h.frame_url ? <img src={h.frame_url} alt="" loading="lazy" className="aspect-video w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" /> : <span className="block aspect-video" />}
                      <span className="tc absolute bottom-1.5 right-1.5 rounded bg-canvas/85 px-1.5 text-[11px] leading-5">{timecode(h.t_start)} đến {timecode(h.t_end)}</span></span>
                    <p className="mt-1.5 truncate text-[13px] text-mute">{h.asset.name}</p>
                    <p className="line-clamp-2 text-[13px]">{h.text}</p>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {error && <p className="mb-4 text-tally">Không tải được thư viện: {error}</p>}
        {assets.length > 0 && (
          <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-[13px]">
            <div className="flex rounded-md border border-line p-0.5" role="radiogroup" aria-label="Loại nguyên liệu">
              {([["", "Tất cả"], ["video", "Video"], ["image", "Ảnh"], ["audio", "Nhạc"]] as const).map(([k, name]) => <button key={k} type="button" role="radio" aria-checked={kind === k} onClick={() => setKind(k)} className={`h-7 rounded px-2.5 ${kind === k ? "bg-raised font-medium" : "text-mute hover:text-ink"}`}>{name}</button>)}
            </div>
            {groups.length > 0 && <><label htmlFor="group" className="sr-only">Bộ sưu tập</label><select id="group" value={group} onChange={(e) => setGroup(e.target.value)} className="h-8 px-2"><option value="">Mọi bộ sưu tập</option>{groups.map((g) => <option key={g}>{g}</option>)}</select></>}
            <label className="flex items-center gap-2 text-mute"><input type="checkbox" checked={least > 0} onChange={(e) => setLeast(e.target.checked ? 4 : 0)} />Chỉ footage bạn chấm từ 4 sao</label>
            <span className="tc ml-auto text-faint">{shown.length} trên {assets.length}</span>
          </div>
        )}
        <ul className={`grid gap-x-4 gap-y-6 ${current ? "sm:grid-cols-2 2xl:grid-cols-3" : "sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"}`}>
          {shown.map((a) => {
            const working = a.ingest && a.ingest.status !== "succeeded";
            const seen = a.understand?.status === "succeeded";
            return (
              <li key={a.asset_id}>
                <button type="button" onClick={() => { setPicked(a.asset_id); setStart(undefined); }} aria-pressed={picked === a.asset_id} className="group w-full text-left">
                  <span className={`relative block overflow-hidden rounded-md bg-black ring-2 ring-offset-2 ring-offset-canvas transition-shadow ${picked === a.asset_id ? "ring-ink" : "ring-transparent"}`}>
                    {a.thumbnail_url ? <img src={a.thumbnail_url} alt="" loading="lazy" className="aspect-video w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" />
                      : <span className="grid aspect-video place-items-center bg-surface text-faint"><Icon name={a.kind === "audio" ? "wave" : "film"} size={30} /></span>}
                    <span className="tc absolute bottom-1.5 right-1.5 rounded bg-canvas/85 px-1.5 text-[11px] leading-5">{a.still ? "Ảnh" : a.duration ? timecode(a.duration) : "Đang xử lý"}</span>
                    {a.rating > 0 && <span className="tc absolute left-1.5 top-1.5 rounded bg-canvas/85 px-1.5 text-[11px] leading-5">{a.rating} sao</span>}
                    {!a.online && <span className="absolute inset-x-0 top-0 bg-cue px-2 py-0.5 text-[11px] font-medium text-canvas">Không tìm thấy file gốc</span>}
                  </span>
                  <span className="mt-2 block">{working ? <StageRail stages={a.ingest!.stages} /> : a.kind === "video" ? <RangeStrip asset={a} /> : <span className="block h-2" />}</span>
                  <span className="mt-1.5 block truncate font-medium">{a.name}</span>
                  <span className="tc block truncate text-[13px] text-mute">
                    {working ? <StatusText status={a.ingest!.status} /> : a.kind === "audio" ? "Nhạc" : `${a.width ?? "?"}×${a.height ?? "?"}`}{a.kind !== "audio" && !working ? (seen ? ", đã mô tả" : a.understand ? ", đang mô tả" : "") : ""}{a.collections.length ? `, ${a.collections.join(", ")}` : ""}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </Page>
      {current && <Player key={current.asset_id} asset={current} start={start} others={assets} close={() => setPicked(null)}
                           similar={async (m) => { const r = await call<{ hits: Hit[] }>(`/api/v1/moments/${m.moment_id}/similar`); setQ(m.text.slice(0, 60)); setHits(r.hits); }} />}
    </div>
  );
}
