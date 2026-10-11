import { useEffect, useRef, useState } from "react";
import { call, megabytes, timecode, usePoll, type Asset } from "./api";
import { Button, RangeStrip, StageRail, StatusText } from "./parts";

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
      <input id="path" value={path} onChange={(e) => setPath(e.target.value)} placeholder="Đường dẫn tới video hoặc thư mục, ví dụ /Volumes/Footage/DaLat"
             className="min-w-0 flex-1 rounded border border-line bg-canvas px-3 py-1.5 placeholder:text-mute/70" />
      <Button kind="primary" disabled={busy || !path.trim()} onClick={submit}>Thêm footage</Button>
      {note && <p className={`w-full text-sm ${note.ok ? "text-mute" : "text-tally"}`}>{note.text}</p>}
    </form>
  );
}

function Player({ asset }: { asset: Asset }) {
  const video = useRef<HTMLVideoElement>(null);
  const [t, setT] = useState(0);
  useEffect(() => setT(0), [asset.asset_id]);
  const unusable = asset.black_ranges.reduce((sum, [a, b]) => sum + (b - a), 0);
  return (
    <aside className="flex w-full flex-col gap-4 border-t border-line bg-surface p-5 lg:w-[440px] lg:shrink-0 lg:border-l lg:border-t-0">
      {asset.proxy_url
        ? <video ref={video} key={asset.proxy_url} src={asset.proxy_url} controls className="aspect-video w-full rounded bg-black" onTimeUpdate={(e) => setT(e.currentTarget.currentTime)} />
        : <div className="grid aspect-video w-full place-items-center rounded bg-canvas text-mute">Bản xem chưa sẵn sàng</div>}
      <RangeStrip asset={asset} tall playhead={t} onSeek={(s) => { if (video.current) video.current.currentTime = s; }} />
      <div>
        <h2 className="break-all text-base font-semibold">{asset.name}</h2>
        <p className="tc text-mute">{asset.width}×{asset.height}, {asset.frame_rate ? `${Math.round(asset.frame_rate)} khung/giây, ` : ""}{megabytes(asset.size)}, {asset.has_audio ? "có âm thanh" : "không có âm thanh"}</p>
      </div>
      {unusable > 0 && <p>Có <span className="tc">{timecode(unusable)}</span> khung đen. Hệ thống sẽ không chọn clip từ phần này.</p>}
      {asset.duplicate_of && <p className="text-mute">File này trùng nội dung với một video đã có trong thư viện nên không được xử lý lại.</p>}
      {!asset.online && <p className="text-cue">Không tìm thấy file gốc. Hãy cắm lại ổ chứa nó để render bản cuối.</p>}
      <p className="break-all text-xs text-mute">{asset.path}</p>
    </aside>
  );
}

export default function Library() {
  const { data, error, reload } = usePoll<{ assets: Asset[] }>("/api/v1/library");
  const [picked, setPicked] = useState<string | null>(null);
  const assets = data?.assets ?? [];
  const current = assets.find((a) => a.asset_id === picked) ?? null;
  return (
    <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
      <section className="min-w-0 flex-1 overflow-y-auto p-6">
        <h1 className="mb-4 text-2xl font-semibold tracking-tight">Thư viện</h1>
        <AddFootage onDone={reload} />
        {error && <p className="mt-4 text-tally">Không tải được thư viện: {error}</p>}
        {data && assets.length === 0 && (
          <p className="mt-10 max-w-md text-mute">Thư viện đang trống. Dán đường dẫn tới một video hoặc cả thư mục footage vào ô phía trên để hệ thống bắt đầu xem và ghi nhớ chúng.</p>
        )}
        <ul className="mt-5 divide-y divide-line border-y border-line">
          {assets.map((a) => (
            <li key={a.asset_id}>
              <button type="button" onClick={() => setPicked(a.asset_id)} aria-pressed={picked === a.asset_id}
                      className={`grid w-full grid-cols-[112px_1fr] items-center gap-4 px-2 py-3 text-left transition-colors sm:grid-cols-[112px_minmax(0,1fr)_minmax(140px,36%)] ${picked === a.asset_id ? "bg-surface" : "hover:bg-surface/60"}`}>
                {a.thumbnail_url
                  ? <img src={a.thumbnail_url} alt="" className="aspect-video w-28 rounded-sm bg-black object-cover" />
                  : <div className="aspect-video w-28 rounded-sm bg-raised" />}
                <div className="min-w-0">
                  <p className="truncate font-medium">{a.name}</p>
                  <p className="tc text-sm text-mute">
                    {a.duration ? timecode(a.duration) : "Đang xử lý"}{a.width ? `, ${a.width}×${a.height}` : ""}
                    {a.ingest && a.ingest.status !== "succeeded" && <>, <StatusText status={a.ingest.status} /></>}
                  </p>
                </div>
                <div className="col-span-2 sm:col-span-1">
                  {a.ingest && a.ingest.status !== "succeeded" ? <StageRail stages={a.ingest.stages} /> : <RangeStrip asset={a} />}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </section>
      {current && <Player asset={current} />}
    </div>
  );
}
