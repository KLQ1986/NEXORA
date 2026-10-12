import { useEffect, useRef, useState } from "react";
import { post, projectState, scriptText, stageName, timecode, usePoll, type Idea, type Source, type AgentTask, type Asset, type Settings, type Candidate, type Project, type RenderItem, type Shot, type BibleEntry, type GapPlan, type Op, type Rights, type Publishing } from "./api";
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

function ShotRow({ shot, n, locked, changed, heading, sources = [], effects = [], remote = [] }: { shot: Shot; n: number; locked: boolean; changed: () => void; heading?: string | null; effects?: Asset[]; remote?: string[]; sources?: Source[] }) {
  const note = async (body: Record<string, unknown>) => { await post(`/api/v1/shots/${shot.shot_id}`, body, "PATCH").catch(() => {}); changed(); };
  const sel = shot.selection;
  const [brief, setBrief] = useState<string | null>(null);
  const [screen, setScreen] = useState<string | null>(null);
  const saveNotes = async () => { await post(`/api/v1/shots/${shot.shot_id}`, { brief: brief ?? shot.brief ?? "", screen_text: screen ?? shot.screen_text ?? "" }, "PATCH").catch(() => {}); setBrief(null); setScreen(null); changed(); };
  const [query, setQuery] = useState("");
  const [stock, setStock] = useState<string | null>(null);
  const findStock = async () => { setStock("Đang tìm trên các kho miễn phí…"); try { const r = await post<{ found: boolean }>(`/api/v1/shots/${shot.shot_id}/stock`, { query }); setStock(r.found ? null : "Không tìm thấy clip nào. Thử từ khoá tiếng Anh khác."); } catch (e) { setStock((e as Error).message); } changed(); };
  const act = async (path: string, body?: unknown) => { await post(`/api/v1/shots/${shot.shot_id}/${path}`, body).catch(() => {}); changed(); };
  const [saved, setSaved] = useState(false);
  const treat = async (body: Record<string, unknown>) => { await post(`/api/v1/shots/${shot.shot_id}/treatment`, body, "PATCH").catch(() => {}); changed(); };
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
            {sel && !gap && !locked && sel.asset && !sel.asset.still && (
              <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px] text-mute">
                <label className="flex items-center gap-1.5">Tốc độ<select aria-label={`Tốc độ hình của câu ${n}`} value={sel.speed} onChange={(e) => treat({ speed: Number(e.target.value) })} className="h-7 pl-1.5 text-[12px]">{[0.5, 0.75, 1, 1.5, 2].map((v) => <option key={v} value={v}>{v}×</option>)}</select></label>
                <label className="flex items-center gap-1.5"><input type="checkbox" checked={sel.stabilise} onChange={(e) => treat({ stabilise: e.target.checked })} />Chống rung</label>
                <label className="flex items-center gap-1.5" title="Giữ âm thanh của chính clip thay cho lời dẫn; độ dài cảnh bằng đúng đoạn đã chọn"><input type="checkbox" checked={sel.live_sound} onChange={(e) => treat({ live_sound: e.target.checked })} />Dùng âm thanh gốc</label>
                {remote.includes("lipsync") && <label className="flex items-center gap-1.5" title="Gửi clip của cảnh này và lời dẫn tới mô hình khớp khẩu hình trên RunPod"><input type="checkbox" checked={sel.lipsync} onChange={(e) => treat({ lipsync: e.target.checked })} />Khớp khẩu hình</label>}
                {remote.includes("upscale") && <label className="flex items-center gap-1.5" title="Gửi clip của cảnh này tới mô hình phóng to trên RunPod"><input type="checkbox" checked={sel.upscale_ml} onChange={(e) => treat({ upscale_ml: e.target.checked })} />Phóng to bằng mô hình</label>}
                {effects.length > 0 && <label className="flex items-center gap-1.5">Tiếng động<select aria-label={`Tiếng động của câu ${n}`} value={sel.sfx ?? ""} onChange={(e) => treat({ sfx: e.target.value || null })} className="h-7 max-w-[160px] pl-1.5 text-[12px]"><option value="">Không</option>{effects.map((a) => <option key={a.asset_id} value={a.asset_id}>{a.name}</option>)}</select></label>}
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px]">
              {sel && !gap && !locked && <button type="button" className="link" onClick={() => act("gap")}>Không clip nào hợp</button>}
              {sel && !gap && sel.status === "accepted" && <button type="button" className="link" title="Giữ cặp câu và clip này làm đáp án đúng, để đo xem hệ thống có tìm kém đi sau khi đổi mô hình hay cài đặt" onClick={async () => { await post("/api/v1/evaluation/cases", { shot_id: shot.shot_id }).catch(() => {}); setSaved(true); }}>{saved ? "Đã lưu làm mẫu chuẩn" : "Lưu làm mẫu chuẩn"}</button>}
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
  const [note, setNote] = useState<string | null>(null);
  const [why, setWhy] = useState("");
  const [blocked, setBlocked] = useState(false);
  const base = `/api/v1/renders/${render.render_id}/package`;
  if (!pkg) return (
    <div className="panel grid gap-3 p-4">
      <RightsList renderId={render.render_id} />
      <div><Button kind="primary" onClick={async () => { setNote(null); try { await post(base, why.trim() ? { override_reason: why.trim() } : {}); } catch (e) { setNote((e as Error).message); setBlocked(true); } reload(); }}><Icon name="layers" />Chuẩn bị gói xuất bản</Button>
        <p className="mt-2 text-[13px] text-mute">Tạo file video, phụ đề rời và ảnh đại diện trong một thư mục để bạn đăng tay.</p></div>
      {note && <p className="text-[13px] text-cue">{note}</p>}
      {blocked && <label className="grid gap-1 text-[13px]"><span className="text-mute">Lý do vẫn đăng (được lưu cùng gói)</span><input value={why} onChange={(e) => setWhy(e.target.value)} placeholder="Ví dụ: nhạc do tôi tự sáng tác" className="h-9 px-3" /></label>}
    </div>
  );
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
      {pkg.rights && (pkg.rights.override_reason || pkg.rights.disclosures.length > 0) && (
        <div className="mb-3 rounded-lg border border-line bg-raised/40 px-3 py-2 text-[12.5px] text-mute">
          {pkg.rights.override_reason && <p className="text-cue">Đóng gói dù còn điểm chưa xử lý. Lý do: {pkg.rights.override_reason}</p>}
          {pkg.rights.disclosures.map((d) => <p key={d}>{d}</p>)}
        </div>)}
      {pkg.checks && Object.values(pkg.checks).some((ok) => !ok) && <p className="mb-3 text-[12.5px] text-tally">Gói còn thiếu: {Object.entries(pkg.checks).filter(([, ok]) => !ok).map(([k]) => k.toLowerCase()).join(", ")}.</p>}
      <p className="font-medium">{pkg.title}</p>
      <p className="mb-3 line-clamp-3 text-[13px] text-mute">{pkg.description}</p>
      <div className="flex flex-wrap gap-2">
        <a className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${pkg.video}`} download><Icon name="download" size={14} />Video</a>
        <a className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${pkg.captions}`} download><Icon name="captions" size={14} />Phụ đề (SRT)</a>
        <a className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${pkg.thumbnail}`} download><Icon name="image" size={14} />Ảnh đại diện</a>
        {Object.entries(pkg.translations ?? {}).map(([lang, name]) => <a key={lang} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${name}`} download><Icon name="globe" size={14} />Phụ đề {LANGS[lang] ?? lang}</a>)}
      </div>
      <PackageText render={render} reload={reload} />
      <Publish render={render} />
      <form className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3 text-[13px]" onSubmit={async (e) => { e.preventDefault(); const lang = String(new FormData(e.currentTarget).get("lang")); setNote("Đang dịch…"); try { await post(`/api/v1/renders/${render.render_id}/captions/translate`, { language: lang }); setNote(null); } catch (err) { setNote((err as Error).message); } reload(); }}>
        <label htmlFor={`lang-${render.render_id}`} className="text-mute">Dịch phụ đề sang</label>
        <select id={`lang-${render.render_id}`} name="lang" className="h-8 pl-2">{Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <Button size="sm" type="submit">Dịch</Button>{note && <span className="text-mute">{note}</span>}
      </form>
    </div>
  );
}

const PUB_STATE: Record<string, [string, "proof" | "cue" | "tally" | "mute"]> = { published: ["Đã đăng", "proof"], unknown: ["Chưa rõ đã tới nơi chưa", "cue"], failed: ["Chưa đăng được", "tally"], publishing: ["Đang gửi", "mute"], pending: ["Chưa gửi", "mute"] };

/** Title candidates with what can be measured about each, and a thumbnail with words on it. */
function PackageText({ render, reload }: { render: RenderItem; reload: () => void }) {
  const pkg = render.package!;
  const [titles, setTitles] = useState<{ title: string; why: string; chars: number; notes: string[] }[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const edit = (body: Record<string, unknown>) => post(`/api/v1/renders/${render.render_id}/package`, body, "PATCH").then(reload, (e) => setNote((e as Error).message));
  return (
    <details className="mt-3 border-t border-line pt-3 text-[13px]">
      <summary className="cursor-pointer list-none text-accent">Tiêu đề và ảnh đại diện có chữ</summary>
      <div className="mt-2 grid gap-3">
        <div><Button size="sm" kind="ai" onClick={async () => { setNote("Đang nghĩ tiêu đề…"); try { setTitles((await post<{ titles: { title: string; why: string; chars: number; notes: string[] }[] }>(`/api/v1/renders/${render.render_id}/titles`)).titles); setNote(null); } catch (e) { setNote((e as Error).message); } }}>Gợi ý tiêu đề</Button>
          {note && <span className="ml-2 text-mute">{note}</span>}</div>
        {titles && titles.length === 0 && <p className="text-mute">Mô hình không đưa ra tiêu đề nào.</p>}
        {titles && titles.length > 0 && <ul className="rows">{titles.map((t) => (
          <li key={t.title} className="flex gap-2 py-1.5"><span className="min-w-0 flex-1">{t.title}<span className="mono ml-2 text-[11.5px] text-faint">{t.chars} ký tự</span>{t.notes.map((n) => <span key={n} className="ml-2 text-[12px] text-cue">{n}</span>)}{t.why && <span className="block text-[12.5px] text-mute">{t.why}</span>}</span>
            <button type="button" className="link shrink-0" onClick={() => edit({ title: t.title })}>Dùng</button></li>))}</ul>}
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; const text = String(new FormData(f).get("words") ?? "").trim(); if (text) edit({ poster_text: text, base: pkg.thumbnails.includes(pkg.thumbnail) && !pkg.thumbnail.startsWith("poster_") ? pkg.thumbnail : pkg.thumbnails[0] }).then(() => f.reset()); }}>
          <input name="words" aria-label="Chữ trên ảnh đại diện" placeholder="Vài chữ lớn đặt lên ảnh đại diện đang chọn" className="h-8 min-w-0 flex-1 px-2.5" /><Button size="sm" type="submit">Tạo ảnh có chữ</Button>
        </form>
      </div>
    </details>
  );
}

/** Send the package to a destination, or record where it was uploaded by hand; then take its figures at each mark. */
function Publish({ render }: { render: RenderItem }) {
  const { data, reload } = usePoll<Publishing>("/api/v1/publishing", 20000);
  const [note, setNote] = useState<string | null>(null);
  const mine = (data?.publications ?? []).filter((p) => p.render_id === render.render_id);
  const send = async (body: Record<string, unknown>) => { setNote(null); try { await post(`/api/v1/renders/${render.render_id}/publish`, body); } catch (e) { setNote((e as Error).message); } reload(); };
  if (!data) return null;
  const name = (t: string) => data.targets.find((x) => x.target === t)?.label ?? t;
  return (
    <div className="mt-3 border-t border-line pt-3 text-[13px]">
      <p className="mb-2 flex items-center gap-2 font-semibold"><Icon name="external" size={15} className="text-accent" />Đăng</p>
      <ul className="rows empty:hidden">
        {mine.map((p) => (
          <li key={p.publication_id} className="py-2">
            <p className="flex flex-wrap items-center gap-2"><span className="font-medium">{name(p.target)}</span><Tag tone={PUB_STATE[p.status]?.[1] ?? "mute"}>{PUB_STATE[p.status]?.[0] ?? p.status}</Tag>
              {p.url && (/^https?:/i.test(p.url) ? <a href={p.url} target="_blank" rel="noreferrer" className="truncate underline decoration-edge underline-offset-2">{p.url}</a> : <span className="mono truncate text-[12px] text-mute">{decodeURI(p.url.replace("file://", ""))}</span>)}
              {p.status === "unknown" && <button type="button" className="link" onClick={async () => { await post(`/api/v1/publications/${p.publication_id}/reconcile`).catch(() => {}); reload(); }}>Hỏi lại nơi đăng</button>}</p>
            {p.error && p.status !== "published" && <p className="mt-0.5 text-[12.5px] text-cue">{p.error}</p>}
            {p.status === "published" && <p className="mt-0.5 text-[12.5px] text-mute">{p.snapshots.length ? `Lần ghi gần nhất: ${Math.round(p.snapshots[p.snapshots.length - 1].figures.views ?? 0)} lượt xem sau ${p.snapshots[p.snapshots.length - 1].hours.toFixed(0)} giờ.` : "Chưa ghi số liệu."} <a href="/ke-hoach?xem=ket-qua" className="link">Ghi số liệu</a></p>}
          </li>))}
      </ul>
      <div className="mt-2 flex flex-wrap gap-2">
        {data.targets.filter((t) => !t.manual && !mine.some((p) => p.target === t.target && p.status === "published")).map((t) => <Button key={t.target} size="sm" kind="primary" onClick={() => send({ target: t.target })}><Icon name="folder" size={14} />Đưa vào {t.label.toLowerCase()}</Button>)}
      </div>
      <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const url = String(f.get("url") ?? "").trim(); if (url) { send({ target: f.get("target"), url }); e.currentTarget.reset(); } }}>
        <select name="target" aria-label="Nền tảng đã đăng" className="h-8 pl-2">{data.targets.filter((t) => t.manual).map((t) => <option key={t.target} value={t.target}>{t.label}</option>)}</select>
        <input name="url" type="url" aria-label="Địa chỉ video đã đăng" placeholder="Bạn đã đăng tay? Dán địa chỉ video vào đây" className="h-8 min-w-0 flex-1 px-2.5" /><Button size="sm" type="submit">Ghi nhận</Button>
      </form>
      {note && <p className="mt-2 text-cue">{note}</p>}
      <p className="mt-2 text-[12px] text-faint">Hệ thống chưa nối tài khoản nền tảng nào nên chưa tự đăng lên YouTube, TikTok hay Facebook. Cùng một bản dựng không bao giờ được gửi hai lần tới cùng một nơi.</p>
    </div>
  );
}

const ORIGIN: Record<string, string> = { self_shot: "Footage của bạn", licensed: "Clip có giấy phép", generated: "Sinh bằng AI", music: "Nhạc nền" };
/** Where every picture and sound of the cut came from, and what stands in the way of publishing it. */
function RightsList({ renderId }: { renderId: string }) {
  const { data } = usePoll<Rights>(`/api/v1/renders/${renderId}/rights`, 10000);
  if (!data) return null;
  return (
    <div className="text-[13px]">
      <p className="flex items-center gap-2 font-semibold"><Icon name="shield" size={15} className={data.clear ? "text-proof" : "text-cue"} />Nguồn gốc và quyền sử dụng<Tag tone={data.clear ? "proof" : "cue"}>{data.clear ? "Đủ điều kiện đăng" : `${data.blockers.length} điểm cần xử lý`}</Tag></p>
      <ul className="rows mt-2">
        {data.items.map((i) => <li key={i.name} className="flex gap-2 py-1.5"><Icon name={i.ok ? "check" : "alert"} size={14} className={`mt-0.5 shrink-0 ${i.ok ? "text-proof" : "text-cue"}`} /><span className="min-w-0"><span className="font-medium">{i.name}</span><span className="ml-1.5 text-faint">{ORIGIN[i.origin] ?? i.origin}</span><span className="block break-words text-[12.5px] text-mute">{i.note}</span></span></li>)}
      </ul>
      {data.blockers.length > 0 && <ul className="mt-2 grid gap-1 text-[12.5px] text-cue">{data.blockers.map((b) => <li key={b}>{b}</li>)}</ul>}
    </div>
  );
}

const LANGS: Record<string, string> = { en: "tiếng Anh", zh: "tiếng Trung", ja: "tiếng Nhật", ko: "tiếng Hàn", fr: "tiếng Pháp", es: "tiếng Tây Ban Nha", th: "tiếng Thái" };

/** Say what to change; see it as a list of operations; apply it or not. */
function Command({ id, busy, reload }: { id: string; busy: boolean; reload: () => void }) {
  const [text, setText] = useState("");
  const [ops, setOps] = useState<Op[] | null>(null);
  const [state, setState] = useState<string | null>(null);
  const ask = async () => { setState("Đang đọc yêu cầu…"); setOps(null); try { const r = await post<{ ops: Op[] }>(`/api/v1/projects/${id}/command`, { text }); setOps(r.ops); setState(r.ops.length ? null : "Không hiểu yêu cầu này thành thao tác nào. Hãy nói rõ câu số mấy và muốn đổi gì."); } catch (e) { setState((e as Error).message); } };
  const apply = async () => { try { const r = await post<{ done: string[] }>(`/api/v1/projects/${id}/command/apply`, { ops }); setState(`Đã làm ${r.done.length} thao tác. Dựng lại để thấy kết quả.`); setOps(null); setText(""); } catch (e) { setState((e as Error).message); } reload(); };
  return (
    <div className="mb-4 rounded-xl border border-line bg-ai/[0.04] px-4 py-3">
      <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) ask(); }}>
        <Icon name="sparkles" size={15} className="text-ai" /><label htmlFor="command" className="sr-only">Sửa bằng lời</label>
        <input id="command" value={text} onChange={(e) => setText(e.target.value)} placeholder="Sửa bằng lời, ví dụ: rút câu 2 còn 2 giây, bỏ câu 4, đưa câu 3 lên đầu" className="bare h-8 min-w-0 flex-1 px-1" />
        <Button size="sm" kind="ai" type="submit" disabled={busy || !text.trim()}>Xem sẽ đổi gì</Button>
      </form>
      {state && <p className="mt-2 text-[12.5px] text-mute">{state}</p>}
      {ops && ops.length > 0 && (
        <div className="mt-2 border-t border-line pt-2 text-[13px]">
          <ul className="grid gap-1">{ops.map((o, i) => <li key={i} className="flex items-start gap-2"><Icon name="check" size={14} className="mt-0.5 shrink-0 text-ai" /><span className="min-w-0 flex-1">{o.describe}</span><button type="button" className="link shrink-0" onClick={() => setOps(ops.filter((_, k) => k !== i))}>Bỏ</button></li>)}</ul>
          <div className="mt-2 flex gap-2"><Button size="sm" kind="primary" onClick={apply}>Áp dụng {ops.length} thao tác</Button><Button size="sm" onClick={() => setOps(null)}>Thôi</Button></div>
        </div>
      )}
    </div>
  );
}

/** Ways on from a cut: finish it by hand elsewhere and bring it back, or make the same video in another shape. */
function Finishing({ id, render, format, run }: { id: string; render: RenderItem; format: string; run: (fn: () => Promise<unknown>) => void }) {
  const [hand, setHand] = useState<{ folder: string; files: string[] } | null>(null);
  const [path, setPath] = useState("");
  const shapes: [string, string][] = [["landscape", "Ngang 16:9"], ["portrait", "Dọc 9:16"], ["square", "Vuông 1:1"]];
  return (
    <details className="panel group px-4 py-3 text-[13px]">
      <summary className="flex cursor-pointer list-none items-center justify-between text-mute hover:text-ink">Dựng tiếp ở nơi khác, hoặc làm khung hình khác<Icon name="down" size={14} className="transition-transform group-open:rotate-180" /></summary>
      <div className="mt-3 grid gap-4">
        <div>
          <p className="font-medium">Gói bàn giao để dựng tay (CapCut và phần mềm khác)</p>
          <p className="mt-0.5 text-[12.5px] text-mute">Mỗi cảnh thành một clip sạch không phụ đề, kèm phụ đề rời, nhạc và tờ hướng dẫn thứ tự.</p>
          {!render.qc.external && <div className="mt-2"><Button size="sm" onClick={() => run(async () => { setHand(await post(`/api/v1/renders/${render.render_id}/handoff`)); })}><Icon name="folder" size={14} />Tạo gói bàn giao</Button></div>}
          {hand && <p className="mt-2 text-[12.5px] text-mute">{hand.files.length} file trong <span className="mono break-all text-ink">{hand.folder}</span></p>}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); if (path.trim()) run(async () => { await post(`/api/v1/projects/${id}/renders/import`, { path: path.trim() }); setPath(""); }); }}>
          <label htmlFor="finished" className="font-medium">Nhập lại bản đã hoàn thiện</label>
          <p className="mt-0.5 text-[12.5px] text-mute">File được đo như mọi bản dựng và trở thành bản mới nhất của dự án, đã duyệt.</p>
          <div className="mt-2 flex gap-2"><input id="finished" value={path} onChange={(e) => setPath(e.target.value)} placeholder="/Users/bạn/Movies/ban-cuoi.mp4" className="mono h-8 min-w-0 flex-1 px-2.5 text-[12.5px]" /><Button size="sm" type="submit" disabled={!path.trim()}>Nhập</Button></div>
        </form>
        <div>
          <p className="font-medium">Làm bản khung hình khác</p>
          <p className="mt-0.5 text-[12.5px] text-mute">Tạo một dự án mới với cùng kịch bản và cùng các clip đã chọn, ở khung hình khác.</p>
          <div className="mt-2 flex flex-wrap gap-2">{shapes.filter(([k]) => k !== format).map(([k, name]) => <Button key={k} size="sm" onClick={() => run(async () => { const r = await post<Project>(`/api/v1/projects/${id}/repurpose`, { format: k }); window.history.pushState(null, "", `/du-an/${r.project_id}`); window.dispatchEvent(new PopStateEvent("popstate")); })}>{name}</Button>)}</div>
        </div>
      </div>
    </details>
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
  const previewing = !!p?.preview && ["queued", "running"].includes(p.preview.status);
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
              <Gaps id={id} shots={p.shots} run={run} />
              {p.shots.some((s) => s.selection) && <div className="mb-4"><TimelineStrip shots={p.shots} /></div>}
              <ol className="grid gap-3">
                {p.shots.map((s, i) => <ShotRow key={s.shot_id} shot={s} n={i + 1} locked={!!rendering} changed={reload} heading={s.scene && s.scene !== p.shots[i - 1]?.scene ? s.scene : null} sources={p.research} effects={(lib?.assets ?? []).filter((a) => a.kind === "audio")} remote={p.remote} />)}
              </ol>
            </Section>
          )}

          {approved && (
            <Section title="Bản dựng" icon="play"
                     note={rendering ? <span className="text-ai">Đang dựng…</span> : undefined}
                     actions={<>{rendering && p.render && <div className="w-48"><StageRail stages={p.render.stages} name={(k) => stageName(k, "edit.render")} /></div>}
                       <Button size="sm" disabled={busy || previewing} title="Bản nhỏ, dựng nhanh, không đọc lời dẫn mới; chỉ để xem nhịp và hình" onClick={() => run(() => post(`/api/v1/projects/${id}/preview`))}><Icon name="bolt" size={14} />{previewing ? "Đang dựng bản xem thử…" : "Xem thử nhanh"}</Button>
                       <Button size="sm" disabled={busy || !!rendering} onClick={() => run(() => post(`/api/v1/projects/${id}/render`))}><Icon name="scissors" size={14} />{latest ? "Dựng lại" : "Dựng video"}</Button></>}>
              <Command id={id} busy={busy} reload={reload} />
              {p.previews[0] && !previewing && (
                <details className="panel group mb-4 px-4 py-3">
                  <summary className="flex cursor-pointer list-none items-center gap-2 text-[13px]"><Icon name="bolt" size={14} className="text-ai" />Bản xem thử nhanh<span className="mono text-faint">{timecode(p.previews[0].duration)}</span>{p.previews[0].gaps > 0 && <span className="text-cue">{p.previews[0].gaps} câu thiếu hình</span>}<Icon name="down" size={14} className="ml-auto transition-transform group-open:rotate-180" /></summary>
                  <video key={p.previews[0].url} src={p.previews[0].url} controls className="mx-auto mt-3 max-h-[50vh] rounded-lg bg-black" />
                  <p className="mt-2 text-[12px] text-faint">Bản này nhỏ và nén mạnh để dựng cho nhanh, câu nào chưa có lời dẫn thì im lặng. Nó không dùng để duyệt hay đăng.</p>
                </details>
              )}
              {p.render?.status === "failed" && <p className="mb-3 text-tally">Lần dựng vừa rồi thất bại ở bước {p.render.stages.find((s) => s.status === "failed")?.stage_key}. Xem chi tiết ở mục Tiến trình, rồi bấm dựng lại.</p>}
              {p.render?.status === "blocked" && <p className="mb-3 text-cue">Việc dựng đang dừng và cần bạn xử lý. Xem ở mục Tiến trình.</p>}
              {!latest && !rendering && <Empty icon="scissors" title="Sẵn sàng dựng">Các clip đã được duyệt. Bấm Dựng video để hệ thống đọc lời dẫn, vẽ phụ đề và ghép cảnh.</Empty>}
              {latest && (
                <div className="grid gap-6 2xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                  <div className="panel overflow-hidden bg-black p-0">
                    <video ref={cut} key={latest.url} src={latest.url} controls className={`w-full bg-black ${latest.qc.format === "portrait" ? "mx-auto aspect-[9/16] max-h-[70vh] w-auto" : latest.qc.format === "square" ? "mx-auto aspect-square max-h-[70vh] w-auto" : "aspect-video"}`} />
                  </div>
                  <div className="grid min-w-0 content-start gap-4">
                    {latest.qc.external && <p className="panel px-4 py-3 text-[13px] text-mute">Bản này được hoàn thiện ở phần mềm khác rồi nhập vào. Kiểm tra bên dưới đo trên chính file đó.</p>}
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
                    {!latest.qc.external && (
                      <div className="panel px-4 py-3 text-[13px]">
                        <div className="flex flex-wrap items-center gap-2"><Icon name="eye" size={15} className="text-ai" /><span className="font-medium">Xem lại như người xem</span>
                          <span className="text-faint">{latest.qc.viewer ? `Đã xem ${latest.qc.viewer.judged} trên ${latest.qc.viewer.of} cảnh có hình` : "Mô hình nhìn từng cảnh của bản dựng và so với lời dẫn."}</span>
                          <span className="ml-auto"><Button size="sm" kind="ai" disabled={busy} onClick={() => run(() => post(`/api/v1/renders/${latest.render_id}/watch`))}>{latest.qc.viewer ? "Xem lại" : "Xem"}</Button></span></div>
                        {latest.qc.viewer && (latest.qc.viewer.findings.length ? <ul className="mt-2 grid gap-1.5">{latest.qc.viewer.findings.map((f, i) => <li key={i}><span className={f.severity === "cao" ? "font-medium text-cue" : "font-medium"}>Câu {f.shot}, {f.check.toLowerCase()}:</span> {f.text} <span className="text-mute">{f.fix}</span></li>)}</ul>
                          : latest.qc.viewer.judged === 0 ? <p className="mt-2 text-cue">Mô hình không trả lời được cho cảnh nào, nên chưa có nhận xét.</p>
                          : <p className="mt-2 text-proof">Không thấy cảnh nào lệch với lời dẫn{latest.qc.viewer.judged < latest.qc.viewer.of ? `, trong ${latest.qc.viewer.judged} cảnh mô hình xem được` : ""}.</p>)}
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
                    <Finishing id={id} render={latest} format={p.format} run={run} />
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
            <div className="grid gap-2">
              {p.music_path && <label className="flex items-start gap-2.5 text-[13px]"><input type="checkbox" className="mt-0.5" checked={!!p.options.music_cleared} disabled={busy} onChange={(e) => patch({ options: { music_cleared: e.target.checked } })} />
                <span>Tôi có quyền dùng bản nhạc này<span className="block text-[12px] text-faint">Chưa xác nhận thì video không được đóng gói để đăng.</span></span></label>}
              {p.remote.length > 0 && <label className="flex items-start gap-2.5 text-[13px]"><input type="checkbox" className="mt-0.5" checked={!!p.options.footage_may_leave} disabled={busy} onChange={(e) => patch({ options: { footage_may_leave: e.target.checked } })} />
                <span>Cho gửi footage của tôi lên RunPod<span className="block text-[12px] text-faint">Chỉ áp dụng cho các cảnh bạn bật khớp khẩu hình hoặc phóng to bằng mô hình ở dự án này. Tắt thì chỉ hình sinh bằng AI mới được gửi. Chế độ riêng tư luôn chặn.</span></span></label>}
              <label className="flex items-start gap-2.5 text-[13px]"><input type="checkbox" className="mt-0.5" checked={!!p.options.clean_audio} disabled={busy} onChange={(e) => patch({ options: { clean_audio: e.target.checked } })} />
                <span>Làm sạch âm thanh<span className="block text-[12px] text-faint">Giảm tiếng ù và tiếng xì ở lời tự thu và âm thanh gốc.</span></span></label>
              <label className="flex items-start gap-2.5 text-[13px]"><input type="checkbox" className="mt-0.5" checked={!!p.options.match_colour} disabled={busy} onChange={(e) => patch({ options: { match_colour: e.target.checked } })} />
                <span>Cân màu giữa các cảnh<span className="block text-[12px] text-faint">Kéo độ sáng và tương phản của từng cảnh về cùng một mức.</span></span></label>
            </div>
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
            <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-faint"><Button size="sm" disabled={busy} title="Chỉ tên dự án được gửi đi làm từ khoá tìm kiếm" onClick={() => run(async () => { const r = await post<{ found: number }>(`/api/v1/projects/${id}/sources/find`, {}); if (!r.found) setNote("Không tìm thấy bài nào trên Wikipedia cho tên dự án này."); })}><Icon name="search" size={14} />Tự tìm nguồn</Button>
              <span>Tìm trên Wikipedia theo tên dự án rồi đọc tối đa 3 bài.</span></div>
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
                  <p className="text-[12px] text-faint">Ảnh: {p.generators.image_providers.map((x) => x.label).join(", ")}. Video: {p.generators.video_providers.map((x) => x.label === "motion" ? "chuyển động từ ảnh tĩnh (trên máy)" : x.label).join(", ")}.</p>
                  <ol className="grid gap-2">
                    {p.shots.map((s, i) => <GenRow key={s.shot_id} shot={s} n={i + 1} providers={p.generators} changed={reload} />)}
                  </ol>
                  <Bible entries={p.bible} save={(bible) => patch({ bible })} />
                </>
              )}
            </div>
          )}
        </aside>
      </div>
    </Page>
  );
}

const SIZES: [string, string][] = [["wide shot", "Toàn cảnh"], ["medium shot", "Trung cảnh"], ["close-up", "Cận cảnh"], ["extreme close-up", "Đặc tả"]];
const MOVES: [string, string][] = [["slow push in", "Đẩy vào chậm"], ["slow pull out", "Kéo ra chậm"], ["pan left", "Lia trái"], ["pan right", "Lia phải"], ["static", "Đứng yên"]];

/** One shot of a generated story: its still, what the model made of it, and the operator's choices for making it again. */
function GenRow({ shot, n, providers, changed }: { shot: Shot; n: number; providers: Project["generators"]; changed: () => void }) {
  const g = shot.generation, q = g?.quality;
  const set = (gen: Record<string, string>) => post(`/api/v1/shots/${shot.shot_id}`, { gen }, "PATCH").then(changed);
  return (
    <li className="rounded-lg border border-line bg-raised/40 p-2">
      <div className="flex gap-2.5">
        {shot.keyframe_url ? <img src={shot.keyframe_url} alt="" className="aspect-video w-24 shrink-0 rounded-md bg-black object-cover" /> : <div className="grid aspect-video w-24 shrink-0 place-items-center rounded-md bg-raised text-faint"><Icon name="image" /></div>}
        <div className="min-w-0 flex-1 text-[12.5px]">
          <p className="truncate"><span className="mono mr-1.5 text-faint">{String(n).padStart(2, "0")}</span>{shot.gen.subject || shot.brief || shot.text}</p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11.5px] text-faint">
            {g ? <><span>{g.provider}</span><span className="mono">seed {g.seed}</span></> : <span>Chưa sinh ảnh</span>}
            {q && <span className={q.score >= 6 ? "text-proof" : "text-cue"} title={q.issues.join(", ") || "Không thấy lỗi"}>{q.score}/10{q.tries > 1 ? `, chọn từ ${q.tries} lần` : ""}</span>}
            {shot.gen.attempt ? <span className="text-ai">đã yêu cầu ảnh khác</span> : null}
          </p>
        </div>
      </div>
      <details className="mt-1.5 text-[12px]">
        <summary className="cursor-pointer list-none text-accent">Sửa ảnh này</summary>
        <div className="mt-2 grid gap-2">
          <input defaultValue={shot.gen.subject ?? ""} onBlur={(e) => e.target.value !== (shot.gen.subject ?? "") && set({ subject: e.target.value })} aria-label={`Hình cần sinh cho câu ${n}`} placeholder="Hình cần sinh (để trống thì dùng lời dẫn)" className="h-8 px-2.5" />
          <div className="grid grid-cols-2 gap-2">
            <select aria-label="Cỡ cảnh" value={shot.gen.shot_size ?? "medium shot"} onChange={(e) => set({ shot_size: e.target.value })} className="h-8 pl-2">{SIZES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            <select aria-label="Chuyển động máy" value={shot.gen.camera ?? "slow push in"} onChange={(e) => set({ camera: e.target.value })} className="h-8 pl-2">{MOVES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            {providers.image_providers.length > 1 && <select aria-label="Nơi sinh ảnh" value={shot.gen.provider_image ?? ""} onChange={(e) => set({ provider_image: e.target.value })} className="h-8 pl-2"><option value="">Ảnh: theo thứ tự chung</option>{providers.image_providers.map((x) => <option key={x.name} value={x.name}>Ảnh: {x.label}</option>)}</select>}
            {providers.video_providers.length > 1 && <select aria-label="Nơi sinh video" value={shot.gen.provider_video ?? ""} onChange={(e) => set({ provider_video: e.target.value })} className="h-8 pl-2"><option value="">Video: theo thứ tự chung</option>{providers.video_providers.map((x) => <option key={x.name} value={x.name}>Video: {x.label}</option>)}</select>}
          </div>
          {g && <div className="flex items-center gap-2"><Button size="sm" onClick={() => post(`/api/v1/shots/${shot.shot_id}/variation`).then(changed)}>Xin ảnh khác</Button><span className="text-faint">Bấm “Sinh lại” ở trên để áp dụng. Ảnh của các câu khác được giữ nguyên.</span></div>}
          {g && <p className="mono break-words rounded bg-overlay p-2 text-[11px] leading-relaxed text-mute">{g.prompt}</p>}
        </div>
      </details>
    </li>
  );
}

const KIND: Record<string, string> = { character: "Nhân vật", setting: "Bối cảnh", prop: "Đồ vật", style: "Phong cách" };
/** How the project's characters, places and look are described, so that every shot shows them the same way. */
function Bible({ entries, save }: { entries: BibleEntry[]; save: (b: BibleEntry[]) => void }) {
  return (
    <div className="border-t border-line pt-3">
      <h3 className="flex items-center gap-2 text-[13px] font-semibold"><Icon name="user" size={14} className="text-mute" />Nhân vật và bối cảnh<span className="mono ml-auto text-[12px] font-normal text-faint">{entries.length}</span></h3>
      <p className="mt-1 text-[12px] text-faint">Câu nào nhắc tới tên ở đây thì ảnh của câu đó được tả đúng như mô tả này. Mục “Phong cách” áp dụng cho mọi ảnh.</p>
      <ul className="rows mt-2 empty:hidden">
        {entries.map((e) => (
          <li key={e.name} className="flex gap-2 py-1.5 text-[12.5px]"><span className="min-w-0 flex-1"><span className="font-medium">{e.name}</span><span className="ml-1.5 text-faint">{KIND[e.kind]}{e.voice ? `, giọng ${e.voice}` : ""}</span><span className="block text-mute">{e.description}</span></span>
            <button type="button" className="link shrink-0" onClick={() => save(entries.filter((x) => x.name !== e.name))}>Bỏ</button></li>))}
      </ul>
      <form className="mt-2 grid gap-2" onSubmit={(ev) => { ev.preventDefault(); const f = new FormData(ev.currentTarget); const name = String(f.get("name") ?? "").trim(); if (!name) return;
        save([...entries.filter((x) => x.name !== name), { name, kind: String(f.get("kind")) as BibleEntry["kind"], description: String(f.get("description") ?? ""), voice: String(f.get("voice") ?? "").trim() || null, asset_id: null }]); ev.currentTarget.reset(); }}>
        <div className="flex gap-2"><input name="name" aria-label="Tên" placeholder="Tên, ví dụ: Mít" className="h-8 min-w-0 flex-1 px-2.5" />
          <select name="kind" aria-label="Loại" className="h-8 pl-2">{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <input name="description" aria-label="Mô tả" placeholder="Mô tả bằng tiếng Anh cho mô hình: an orange tabby cat with a white chest" className="h-8 px-2.5" />
        <input name="voice" aria-label="Giọng đọc của nhân vật" placeholder="Giọng đọc riêng (tuỳ chọn). Câu viết “Tên: lời thoại” sẽ dùng giọng này" className="h-8 px-2.5" />
        <div><Button size="sm" type="submit">Thêm</Button></div>
      </form>
    </div>
  );
}

/** Lines that have no picture, with what the library holds nearest to each and the ways out this machine has. */
function Gaps({ id, shots, run }: { id: string; shots: Shot[]; run: (fn: () => Promise<unknown>) => void }) {
  const count = shots.filter((s) => s.selection?.status === "gap").length;
  const { data } = usePoll<{ gaps: GapPlan[] }>(`/api/v1/projects/${id}/gaps`, 8000);
  if (!count || !data?.gaps.length) return null;
  return (
    <div className="mb-4 rounded-xl border border-cue/30 bg-cue/[0.05] p-4 text-[13px]">
      <div className="flex flex-wrap items-center gap-2"><Icon name="image" size={15} className="text-cue" /><span className="font-semibold">{data.gaps.length} câu chưa có hình</span>
        <a href={`/api/v1/projects/${id}/shotlist`} className="ml-auto flex items-center gap-1.5 rounded-lg border border-edge px-2.5 py-1.5 text-[12.5px] hover:border-accent hover:text-accent" download><Icon name="download" size={14} />Tải danh sách cần quay</a></div>
      <ul className="mt-3 grid gap-3">
        {data.gaps.map((g) => (
          <li key={g.shot_id} className="grid gap-1.5">
            <p><span className="mono mr-2 text-faint">Câu {g.line}</span>{g.text}<span className="ml-2 text-faint">cần {g.seconds.toFixed(0)} giây</span></p>
            {g.near && <p className="text-[12.5px] text-mute">Gần nhất trong kho ({Math.round(g.near.score * 100)}%): {g.near.text.slice(0, 140)}</p>}
            <div className="flex flex-wrap gap-2">
              {g.ways.some((w) => w.way === "stock") && <Button size="sm" onClick={() => run(async () => { await post(`/api/v1/shots/${g.shot_id}/stock`, { query: g.brief || g.text }); })}>Tìm clip stock</Button>}
              {g.ways.filter((w) => w.way === "reword" || w.way === "shoot" || w.way === "generate").map((w) => <span key={w.way} className="rounded-md border border-line bg-raised/50 px-2 py-1 text-[12px] text-mute">{w.text}</span>)}
            </div>
          </li>
        ))}
      </ul>
    </div>
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
  const [seek, setSeek] = useState(false);
  useEffect(() => { if (!sub && new URLSearchParams(window.location.search).has("moi")) setMode("new"); }, [sub, window.location.search]);
  if (sub) return <Detail key={sub} id={sub} back={() => go("/du-an")} />;
  const create = async () => { const p = await post<Project>("/api/v1/projects", { title: title.trim(), format }); setTitle(""); reload(); go(`/du-an/${p.project_id}`); };
  const assign = async () => { setAgentNote(null); try { const t = await post<AgentTask>("/api/v1/agent/tasks", { goal: goal.trim(), format, find_sources: seek, urls: urls.split("\n").map((u) => u.trim()).filter(Boolean) }); setGoal(""); setUrls(""); reloadAgent(); reload(); go(`/du-an/${t.project_id}`); } catch (err) { setAgentNote((err as Error).message); } };
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
          <label className="mt-3 flex items-center gap-2 text-[13px]"><input type="checkbox" checked={seek} onChange={(e) => setSeek(e.target.checked)} />Để trợ lý tự tìm nguồn trên Wikipedia rồi đối chiếu dữ kiện</label>
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
