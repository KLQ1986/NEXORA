import { t as tr, tv, locale } from "./i18n";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { call, post, projectNext, projectState, scriptText, stageName, timecode, usePoll, type Idea, type Source, type AgentTask, type Asset, type Settings, type Candidate, type Project, type RenderItem, type Shot, type BibleEntry, type GapPlan, type Op, type Rights, type Publishing, type Channel, type Variant, type Illustration, type Quote, type Production, type ProductionMission, type Template } from "./api";
import Board from "./Board";
import { ask, Button, Empty, Filmstrip, goTo, Icon, Meter, Page, Section, Seg, SideFrame, SideGroup, SideLink, SkeletonCards, Spinner, StageRail, Steps, Tabs, Tag, TimeChip, toast, Readout } from "./parts";
import Timeline from "./Timeline";
import EditStep from "./EditStep";
import Storyboard from "./Storyboard";

const VERDICT: Record<string, [string, "proof" | "tally" | "cue"]> = { supported: [tr("Nguồn xác nhận"), "proof"], contradicted: [tr("Trái với nguồn"), "tally"], not_found: [tr("Chưa có căn cứ"), "cue"] };

function Clip({ url, tIn, tOut, poster }: { url: string | null; tIn: number; tOut: number; poster: string | null }) {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => { const v = ref.current; if (!v) return; const tick = () => { if (v.currentTime >= tOut) v.currentTime = tIn; }; v.addEventListener("timeupdate", tick); return () => v.removeEventListener("timeupdate", tick); }, [tIn, tOut, url]);
  if (!url) return poster ? <img src={poster} alt="" className="aspect-video w-full rounded-lg bg-black object-cover" /> : <div className="aspect-video w-full rounded-lg bg-raised" />;
  return <video ref={ref} key={`${url}${tIn}`} src={`${url}#t=${tIn},${tOut}`} poster={poster ?? undefined} muted playsInline controls preload="metadata" className="aspect-video w-full rounded-lg bg-black" />;
}

const FORMATS: Record<string, string> = { landscape: tr("Ngang 16:9"), portrait: tr("Dọc 9:16"), square: tr("Vuông 1:1") };

function PackagePanel({ render, reload }: { render: RenderItem; reload: () => void }) {
  const pkg = render.package;
  const [note, setNote] = useState<string | null>(null);
  const [why, setWhy] = useState("");
  const [blocked, setBlocked] = useState(false);
  const base = `/api/v1/renders/${render.render_id}/package`;
  if (!pkg) return (
    <div className="panel grid gap-3 p-4">
      <RightsList renderId={render.render_id} />
      <div><Button kind="primary" onClick={async () => { setNote(null); try { await post(base, why.trim() ? { override_reason: why.trim() } : {}); } catch (e) { setNote((e as Error).message); setBlocked(true); } reload(); }}><Icon name="layers" />{tr("Chuẩn bị gói xuất bản")}</Button>
        <p className="mt-2 text-[13px] text-mute">{tr("Tạo file video, phụ đề rời và ảnh đại diện trong một thư mục để bạn đăng tay.")}</p></div>
      {note && <p className="text-[13px] text-cue">{note}</p>}
      {blocked && <label className="grid gap-1 text-[13px]"><span className="text-mute">{tr("Lý do vẫn đăng (được lưu cùng gói)")}</span><input value={why} onChange={(e) => setWhy(e.target.value)} placeholder={tr("Ví dụ: nhạc do tôi tự sáng tác")} className="h-9 px-3" /></label>}
    </div>
  );
  return (
    <div className="panel p-4">
      <h3 className="mb-1 flex items-center gap-2 font-semibold"><Icon name="layers" size={16} className="text-accent" />{tr("Gói xuất bản")}</h3>
      <p className="mb-3 text-[13px] text-mute">{tr("Chọn ảnh đại diện. Mọi file nằm trong thư mục")} <span className="mono break-all text-ink">{pkg.folder}</span></p>
      <div className="mb-3 grid grid-cols-3 gap-2">
        {pkg.thumbnails.map((name) => (
          <button key={name} type="button" aria-pressed={pkg.thumbnail === name} onClick={async () => { await post(base, { thumbnail: name }); reload(); }}
                  className={`overflow-hidden rounded-md ring-2 transition ${pkg.thumbnail === name ? "ring-accent" : "opacity-60 ring-transparent hover:opacity-100"}`}>
            <img src={`${base}/${name}`} alt={tr("Ảnh đại diện ứng viên")} className="aspect-video w-full object-cover" />
          </button>
        ))}
      </div>
      {pkg.rights && (pkg.rights.override_reason || pkg.rights.disclosures.length > 0) && (
        <div className="mb-3 rounded-lg border border-line bg-raised/40 px-3 py-2 text-[12.5px] text-mute">
          {pkg.rights.override_reason && <p className="text-cue">{tv`Đóng gói dù còn điểm chưa xử lý. Lý do: ${pkg.rights.override_reason}`}</p>}
          {pkg.rights.disclosures.map((d) => <p key={d}>{d}</p>)}
        </div>)}
      {pkg.checks && Object.values(pkg.checks).some((ok) => !ok) && <p className="mb-3 text-[12.5px] text-tally">{tv`Gói còn thiếu: ${Object.entries(pkg.checks).filter(([, ok]) => !ok).map(([k]) => k.toLowerCase()).join(", ")}.`}</p>}
      <p className="font-medium">{pkg.title}</p>
      <p className="mb-3 line-clamp-3 text-[13px] text-mute">{pkg.description}</p>
      <div className="flex flex-wrap gap-2">
        <a className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${pkg.video}`} download><Icon name="download" size={14} />{tr("Video")}</a>
        <a className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${pkg.captions}`} download><Icon name="captions" size={14} />{tr("Phụ đề (SRT)")}</a>
        <a className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${pkg.thumbnail}`} download><Icon name="image" size={14} />{tr("Ảnh đại diện")}</a>
        {Object.entries(pkg.translations ?? {}).map(([lang, name]) => <a key={lang} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-line bg-raised px-3 text-[12.5px] hover:border-edge" href={`${base}/${name}`} download><Icon name="globe" size={14} />{tv`Phụ đề ${LANGS[lang] ?? lang}`}</a>)}
      </div>
      <PackageText render={render} reload={reload} />
      <Publish render={render} />
      <form className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3 text-[13px]" onSubmit={async (e) => { e.preventDefault(); const lang = String(new FormData(e.currentTarget).get("lang")); setNote(tr("Đang dịch…")); try { await post(`/api/v1/renders/${render.render_id}/captions/translate`, { language: lang }); setNote(null); } catch (err) { setNote((err as Error).message); } reload(); }}>
        <label htmlFor={`lang-${render.render_id}`} className="text-mute">{tr("Dịch phụ đề sang")}</label>
        <select id={`lang-${render.render_id}`} name="lang" className="h-8 pl-2">{Object.entries(LANGS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <Button size="sm" type="submit">{tr("Dịch")}</Button>{note && <span className="text-mute">{note}</span>}
      </form>
    </div>
  );
}

const PUB_STATE: Record<string, [string, "proof" | "cue" | "tally" | "mute"]> = { published: [tr("Đã đăng"), "proof"], unknown: [tr("Chưa rõ đã tới nơi chưa"), "cue"], failed: [tr("Chưa đăng được"), "tally"], publishing: [tr("Đang gửi"), "mute"], pending: [tr("Chưa gửi"), "mute"] };

/** Title candidates with what can be measured about each, and a thumbnail with words on it. */
function PackageText({ render, reload }: { render: RenderItem; reload: () => void }) {
  const pkg = render.package!;
  const [titles, setTitles] = useState<{ title: string; why: string; chars: number; notes: string[] }[] | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const edit = (body: Record<string, unknown>) => post(`/api/v1/renders/${render.render_id}/package`, body, "PATCH").then(reload, (e) => setNote((e as Error).message));
  return (
    <details className="mt-3 border-t border-line pt-3 text-[13px]">
      <summary className="cursor-pointer list-none text-accent">{tr("Tiêu đề và ảnh đại diện có chữ")}</summary>
      <div className="mt-2 grid gap-3">
        <div><Button size="sm" kind="ai" onClick={async () => { setNote(tr("Đang nghĩ tiêu đề…")); try { setTitles((await post<{ titles: { title: string; why: string; chars: number; notes: string[] }[] }>(`/api/v1/renders/${render.render_id}/titles`)).titles); setNote(null); } catch (e) { setNote((e as Error).message); } }}>{tr("Gợi ý tiêu đề")}</Button>
          {note && <span className="ml-2 text-mute">{note}</span>}</div>
        {titles && titles.length === 0 && <p className="text-mute">{tr("Mô hình không đưa ra tiêu đề nào.")}</p>}
        {titles && titles.length > 0 && <ul className="rows">{titles.map((t) => (
          <li key={t.title} className="flex gap-2 py-1.5"><span className="min-w-0 flex-1">{t.title}<span className="mono ml-2 text-[11.5px] text-faint">{tv`${t.chars} ký tự`}</span>{t.notes.map((n) => <span key={n} className="ml-2 text-[12px] text-cue">{n}</span>)}{t.why && <span className="block text-[12.5px] text-mute">{t.why}</span>}</span>
            <button type="button" className="link shrink-0" onClick={() => edit({ title: t.title })}>{tr("Dùng")}</button></li>))}</ul>}
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; const text = String(new FormData(f).get("words") ?? "").trim(); if (text) edit({ poster_text: text, base: pkg.thumbnails.includes(pkg.thumbnail) && !pkg.thumbnail.startsWith("poster_") ? pkg.thumbnail : pkg.thumbnails[0] }).then(() => f.reset()); }}>
          <input name="words" aria-label={tr("Chữ trên ảnh đại diện")} placeholder={tr("Vài chữ lớn đặt lên ảnh đại diện đang chọn")} className="h-8 min-w-0 flex-1 px-2.5" /><Button size="sm" type="submit">{tr("Tạo ảnh có chữ")}</Button>
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
      <p className="mb-2 flex items-center gap-2 font-semibold"><Icon name="external" size={15} className="text-accent" />{tr("Đăng")}</p>
      <ul className="rows empty:hidden">
        {mine.map((p) => (
          <li key={p.publication_id} className="py-2">
            <p className="flex flex-wrap items-center gap-2"><span className="font-medium">{name(p.target)}</span><Tag tone={PUB_STATE[p.status]?.[1] ?? "mute"}>{PUB_STATE[p.status]?.[0] ?? p.status}</Tag>
              {p.url && (/^https?:/i.test(p.url) ? <a href={p.url} target="_blank" rel="noreferrer" className="truncate underline decoration-edge underline-offset-2">{p.url}</a> : <span className="mono truncate text-[12px] text-mute">{decodeURI(p.url.replace("file://", ""))}</span>)}
              {p.status === "unknown" && <button type="button" className="link" onClick={async () => { await post(`/api/v1/publications/${p.publication_id}/reconcile`).catch(() => {}); reload(); }}>{tr("Hỏi lại nơi đăng")}</button>}</p>
            {p.error && p.status !== "published" && <p className="mt-0.5 text-[12.5px] text-cue">{p.error}</p>}
            {p.status === "published" && <p className="mt-0.5 text-[12.5px] text-mute">{p.snapshots.length ? tv`Lần ghi gần nhất: ${Math.round(p.snapshots[p.snapshots.length - 1].figures.views ?? 0)} lượt xem sau ${p.snapshots[p.snapshots.length - 1].hours.toFixed(0)} giờ.` : tr("Chưa ghi số liệu.")} <a href="/ke-hoach?xem=ket-qua" className="link">{tr("Ghi số liệu")}</a></p>}
          </li>))}
      </ul>
      <div className="mt-2 flex flex-wrap gap-2">
        {data.targets.filter((t) => !t.manual && !mine.some((p) => p.target === t.target && p.status === "published")).map((t) => <Button key={t.target} size="sm" kind="primary" onClick={() => send({ target: t.target })}><Icon name="folder" size={14} />{tv`Đưa vào ${t.label.toLowerCase()}`}</Button>)}
      </div>
      <form className="mt-2 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const url = String(f.get("url") ?? "").trim(); if (url) { send({ target: f.get("target"), url }); e.currentTarget.reset(); } }}>
        <select name="target" aria-label={tr("Nền tảng đã đăng")} className="h-8 pl-2">{data.targets.filter((t) => t.manual).map((t) => <option key={t.target} value={t.target}>{t.label}</option>)}</select>
        <input name="url" type="url" aria-label={tr("Địa chỉ video đã đăng")} placeholder={tr("Bạn đã đăng tay? Dán địa chỉ video vào đây")} className="h-8 min-w-0 flex-1 px-2.5" /><Button size="sm" type="submit">{tr("Ghi nhận")}</Button>
      </form>
      {note && <p className="mt-2 text-cue">{note}</p>}
      <p className="mt-2 text-[12px] text-faint">{tr("Hệ thống chưa nối tài khoản nền tảng nào nên chưa tự đăng lên YouTube, TikTok hay Facebook. Cùng một bản dựng không bao giờ được gửi hai lần tới cùng một nơi.")}</p>
    </div>
  );
}

const ORIGIN: Record<string, string> = { self_shot: tr("Footage của bạn"), licensed: tr("Clip có giấy phép"), generated: tr("Sinh bằng AI"), music: tr("Nhạc nền") };
/** Where every picture and sound of the cut came from, and what stands in the way of publishing it. */
function RightsList({ renderId }: { renderId: string }) {
  const { data } = usePoll<Rights>(`/api/v1/renders/${renderId}/rights`, 10000);
  if (!data) return null;
  return (
    <div className="text-[13px]">
      <p className="flex items-center gap-2 font-semibold"><Icon name="shield" size={15} className={data.clear ? "text-proof" : "text-cue"} />{tr("Nguồn gốc và quyền sử dụng")}<Tag tone={data.clear ? "proof" : "cue"}>{data.clear ? tr("Đủ điều kiện đăng") : tv`${data.blockers.length} điểm cần xử lý`}</Tag></p>
      <ul className="rows mt-2">
        {data.items.map((i) => <li key={i.name} className="flex gap-2 py-1.5"><Icon name={i.ok ? "check" : "alert"} size={14} className={`mt-0.5 shrink-0 ${i.ok ? "text-proof" : "text-cue"}`} /><span className="min-w-0"><span className="font-medium">{i.name}</span><span className="ml-1.5 text-faint">{ORIGIN[i.origin] ?? i.origin}</span><span className="block break-words text-[12.5px] text-mute">{i.note}</span></span></li>)}
      </ul>
      {data.blockers.length > 0 && <ul className="mt-2 grid gap-1 text-[12.5px] text-cue">{data.blockers.map((b) => <li key={b}>{b}</li>)}</ul>}
    </div>
  );
}

const LANGS: Record<string, string> = { en: tr("tiếng Anh"), zh: tr("tiếng Trung"), ja: tr("tiếng Nhật"), ko: tr("tiếng Hàn"), fr: tr("tiếng Pháp"), es: tr("tiếng Tây Ban Nha"), th: tr("tiếng Thái") };

/** Tracks from the library that would sit under this cut, with why each is where it is. */
/* Neighbouring shots from different sources (another camera, a phone, stock): each pair the cut puts side by side, the side
   that changes, to what, and the gap now. Matching proposes a step in Visual Quality, previewed and approved there. */
type ColourPair = { after: number; reference: { asset_id: string; t: number; source: string }; change: { asset_id: string; t: number; source: string };
  mode: "look" | "scene"; place: string | null; ready: boolean; state: "none" | "proposed" | "approved"; gap: number | null };
function ColourPairs({ id }: { id: string }) {
  const { data, reload } = usePoll<{ pairs: ColourPair[] }>(`/api/v1/projects/${id}/colour`, 60000);
  const [busy, setBusy] = useState<number | null>(null);
  const pairs = data?.pairs ?? [];
  if (!pairs.length) return null;
  const match = async (p: ColourPair) => {
    setBusy(p.after);
    try { await post(`/api/v1/projects/${id}/colour/match`, { after: p.after }); toast(tr("Đã đề xuất khớp màu; xem trước rồi duyệt ở VQ.")); reload(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); }
    setBusy(null);
  };
  return (
    <div className="grid gap-2 rounded-xl border border-line p-3">
      <p className="text-[13px] text-ink">{tr("Khớp màu giữa các nguồn")}</p>
      <p className="text-[12px] text-faint">{tr("Các cảnh kề nhau đến từ nguồn khác nhau. Nguồn dùng nhiều nhất trong bản dựng được giữ làm chuẩn; nguồn kia được chỉnh theo.")}</p>
      <ul className="grid gap-1.5">{pairs.map((p) => (
        <li key={p.after} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12.5px]">
          <span className="mono text-faint">{tv`Cảnh ${p.after + 1}–${p.after + 2}`}</span>
          <span className="min-w-0 flex-1">{tv`${p.change.source} theo ${p.reference.source}`}
            <span className="text-faint">{` · ${p.mode === "scene" ? tv`cùng nơi (${p.place ?? ""})` : tr("tông máy quay")}${p.gap != null ? tv` · lệch ${p.gap.toFixed(1)}` : ""}`}</span></span>
          {p.state === "approved" ? <Tag tone="proof">{tr("đã khớp")}</Tag>
            : p.state === "proposed" ? <button type="button" className="link" onClick={() => goTo(`/thu-vien?mo=${p.change.asset_id}&tab=vq`)}>{tr("Xem trước & duyệt")}</button>
            : !p.ready ? <span className="text-faint">{tr("chưa phân tích VQ")}</span>
            : <Button size="sm" busy={busy === p.after} onClick={() => match(p)}>{tr("Khớp màu")}</Button>}
        </li>))}</ul>
    </div>
  );
}

function MusicIdeas({ id, choose }: { id: string; choose: (path: string) => void }) {
  const [energy, setEnergy] = useState("");
  const [data, setData] = useState<{ seconds: number; tracks: { asset_id: string; name: string; path: string; why: string }[] } | null>(null);
  const ask = async (e: string) => { setEnergy(e); setData(await call(`/api/v1/projects/${id}/music/suggest${e ? `?energy=${encodeURIComponent(e)}` : ""}`)); };
  return (
    <details className="mt-2 text-[12.5px]" onToggle={(e) => { if ((e.target as HTMLDetailsElement).open && !data) ask(""); }}>
      <summary className="cursor-pointer list-none text-accent">{tr("Gợi ý nhạc từ thư viện")}</summary>
      <div className="mt-2 flex flex-wrap gap-1.5">{[["", tr("Mọi nhịp")], [tr("êm"), tr("Êm")], [tr("vừa"), tr("Vừa")], [tr("sôi động"), tr("Sôi động")]].map(([k, name]) => <button key={k} type="button" aria-pressed={energy === k} onClick={() => ask(k)} className={`rounded-md border px-2 py-1 ${energy === k ? "border-accent/60 bg-accent/[0.08]" : "border-line"}`}>{name}</button>)}</div>
      {data && data.tracks.length === 0 && <p className="mt-2 text-mute">{tr("Thư viện chưa có bản nhạc nào đã được đo. Thêm file nhạc ở mục Thư viện.")}</p>}
      <ul className="rows mt-1">{(data?.tracks ?? []).map((t) => <li key={t.asset_id} className="flex gap-2 py-1.5"><span className="min-w-0 flex-1"><span className="font-medium">{t.name}</span><span className="block text-faint">{t.why}</span></span><button type="button" className="link shrink-0" onClick={() => choose(t.path)}>{tr("Dùng")}</button></li>)}</ul>
    </details>
  );
}

type Trace = { script: { version: number }; shots: { line: number; text: string; source: { name: string; origin: string; checksum: string; t_in: number | null; derived: { role: string }[] } | null; generated: { kind: string; prompt: string; seed: number; provider: string }[] | null }[] };
/** Everything a cut was made from, traced back. */
function Lineage({ renderId }: { renderId: string }) {
  const [data, setData] = useState<Trace | null>(null);
  return (
    <details className="panel group px-4 py-3 text-[13px]" onToggle={async (e) => { if ((e.target as HTMLDetailsElement).open && !data) setData(await call(`/api/v1/renders/${renderId}/lineage`)); }}>
      <summary className="flex cursor-pointer list-none items-center justify-between text-mute hover:text-ink">{tr("Bản dựng này làm từ những gì")}<Icon name="down" size={14} className="transition-transform group-open:rotate-180" /></summary>
      {data && <ol className="rows mt-2">
        <li className="py-1.5 text-mute">{tv`Kịch bản phiên bản ${data.script.version}`}</li>
        {data.shots.map((s) => (
          <li key={s.line} className="py-1.5"><p><span className="mono mr-2 text-faint">{String(s.line).padStart(2, "0")}</span>{s.text}</p>
            {s.source ? <p className="mt-0.5 break-words text-[12.5px] text-mute">{s.source.name}{s.source.t_in != null ? tv`, từ giây ${s.source.t_in.toFixed(1)}` : ""}, {ORIGIN[s.source.origin] ?? s.source.origin}. <span className="mono text-faint" title={s.source.checksum}>{(s.source.checksum ?? "").slice(0, 12)}</span></p>
              : <p className="mt-0.5 text-[12.5px] text-cue">{tr("Không có hình.")}</p>}
            {s.generated?.map((g, i) => <p key={i} className="mt-0.5 break-words text-[12.5px] text-faint">{tv`${g.kind === "keyframe" ? tr("Ảnh") : "Clip"} từ ${g.provider}, seed ${g.seed}: ${g.prompt}`}</p>)}
          </li>))}
      </ol>}
    </details>
  );
}

/** Say what to change; see it as a list of operations; apply it or not. */
function Command({ id, busy, reload }: { id: string; busy: boolean; reload: () => void }) {
  const [text, setText] = useState("");
  const [ops, setOps] = useState<Op[] | null>(null);
  const [state, setState] = useState<string | null>(null);
  const ask = async () => { setState(tr("Đang đọc yêu cầu…")); setOps(null); try { const r = await post<{ ops: Op[] }>(`/api/v1/projects/${id}/command`, { text }); setOps(r.ops); setState(r.ops.length ? null : tr("Không hiểu yêu cầu này thành thao tác nào. Hãy nói rõ câu số mấy và muốn đổi gì.")); } catch (e) { setState((e as Error).message); } };
  const apply = async () => { try { const r = await post<{ done: string[] }>(`/api/v1/projects/${id}/command/apply`, { ops }); setState(tv`Đã làm ${r.done.length} thao tác. Dựng lại để thấy kết quả.`); setOps(null); setText(""); } catch (e) { setState((e as Error).message); } reload(); };
  return (
    <div className="mb-4 rounded-xl border border-line bg-ai/[0.04] px-4 py-3">
      <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim()) ask(); }}>
        <Icon name="sparkles" size={15} className="text-ai" /><label htmlFor="command" className="sr-only">{tr("Sửa bằng lời")}</label>
        <input id="command" value={text} onChange={(e) => setText(e.target.value)} placeholder={tr("Sửa bằng lời, ví dụ: rút câu 2 còn 2 giây, bỏ câu 4, đưa câu 3 lên đầu")} className="bare h-8 min-w-0 flex-1 px-1" />
        <Button size="sm" kind="ai" type="submit" disabled={busy || !text.trim()}>{tr("Xem sẽ đổi gì")}</Button>
      </form>
      {state && <p className="mt-2 text-[12.5px] text-mute">{state}</p>}
      {ops && ops.length > 0 && (
        <div className="mt-2 border-t border-line pt-2 text-[13px]">
          <ul className="grid gap-1">{ops.map((o, i) => <li key={i} className="flex items-start gap-2"><Icon name="check" size={14} className="mt-0.5 shrink-0 text-ai" /><span className="min-w-0 flex-1">{o.describe}</span><button type="button" className="link shrink-0" onClick={() => setOps(ops.filter((_, k) => k !== i))}>{tr("Bỏ")}</button></li>)}</ul>
          <div className="mt-2 flex gap-2"><Button size="sm" kind="primary" onClick={apply}>{tv`Áp dụng ${ops.length} thao tác`}</Button><Button size="sm" onClick={() => setOps(null)}>{tr("Thôi")}</Button></div>
        </div>
      )}
    </div>
  );
}

/** Ways on from a cut: finish it by hand elsewhere and bring it back, or make the same video in another shape. */
function Finishing({ id, render, format, run }: { id: string; render: RenderItem; format: string; run: (fn: () => Promise<unknown>) => void }) {
  const [hand, setHand] = useState<{ folder: string; files: string[] } | null>(null);
  const [path, setPath] = useState("");
  const shapes: [string, string][] = [["landscape", tr("Ngang 16:9")], ["portrait", tr("Dọc 9:16")], ["square", tr("Vuông 1:1")]];
  return (
    <details className="panel group px-4 py-3 text-[13px]">
      <summary className="flex cursor-pointer list-none items-center justify-between text-mute hover:text-ink">{tr("Dựng tiếp ở nơi khác, hoặc làm khung hình khác")}<Icon name="down" size={14} className="transition-transform group-open:rotate-180" /></summary>
      <div className="mt-3 grid gap-4">
        <div>
          <p className="font-medium">{tr("Gói bàn giao để dựng tay (CapCut và phần mềm khác)")}</p>
          <p className="mt-0.5 text-[12.5px] text-mute">{tr("Mỗi cảnh thành một clip sạch không phụ đề, kèm phụ đề rời, nhạc và tờ hướng dẫn thứ tự.")}</p>
          {!render.qc.external && <div className="mt-2"><Button size="sm" onClick={() => run(async () => { setHand(await post(`/api/v1/renders/${render.render_id}/handoff`)); })}><Icon name="folder" size={14} />{tr("Tạo gói bàn giao")}</Button></div>}
          {hand && <p className="mt-2 text-[12.5px] text-mute">{hand.files.length} file trong <span className="mono break-all text-ink">{hand.folder}</span></p>}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); if (path.trim()) run(async () => { await post(`/api/v1/projects/${id}/renders/import`, { path: path.trim() }); setPath(""); }); }}>
          <label htmlFor="finished" className="font-medium">{tr("Nhập lại bản đã hoàn thiện")}</label>
          <p className="mt-0.5 text-[12.5px] text-mute">{tr("File được đo như mọi bản dựng và trở thành bản mới nhất của dự án, đã duyệt.")}</p>
          <div className="mt-2 flex gap-2"><input id="finished" value={path} onChange={(e) => setPath(e.target.value)} placeholder={tr("/Users/bạn/Movies/ban-cuoi.mp4")} className="mono h-8 min-w-0 flex-1 px-2.5 text-[12.5px]" /><Button size="sm" type="submit" disabled={!path.trim()}>{tr("Nhập")}</Button></div>
        </form>
        <div>
          <p className="font-medium">{tr("Làm bản khung hình khác")}</p>
          <p className="mt-0.5 text-[12.5px] text-mute">{tr("Tạo một dự án mới với cùng kịch bản và cùng các clip đã chọn, ở khung hình khác.")}</p>
          <div className="mt-2 flex flex-wrap gap-2">{shapes.filter(([k]) => k !== format).map(([k, name]) => <Button key={k} size="sm" onClick={() => run(async () => { const r = await post<Project>(`/api/v1/projects/${id}/repurpose`, { format: k }); window.history.pushState(null, "", `/du-an/${r.project_id}`); window.dispatchEvent(new PopStateEvent("popstate")); })}>{name}</Button>)}</div>
        </div>
      </div>
    </details>
  );
}

/** Put a project in NEXORA's Trash, with a way back at once. Nothing is lost until the Trash is emptied. */
async function trashProject(p: { project_id: string; title: string }, then?: () => void): Promise<boolean> {
  if (!(await ask(tr("Chuyển dự án này vào thùng rác?"), { body: tv`${p.title}. Có thể khôi phục trong Thùng rác trong 30 ngày. Footage trong thư viện không bị ảnh hưởng.`, confirm: tr("Chuyển vào thùng rác"), danger: true }))) return false;
  try { await call(`/api/v1/projects/${p.project_id}`, { method: "DELETE" }); } catch (e) { toast((e as Error).message, { tone: "tally" }); return false; }
  toast(tv`Đã chuyển “${p.title}” vào thùng rác.`, { undo: () => { post("/api/v1/trash/restore", { projects: [p.project_id] }).then(() => then?.()).catch(() => {}); } });
  then?.();
  return true;
}

const CRITERIA: Record<string, [string, boolean]> = { hop_khan_gia: [tr("Hợp người xem"), false], hop_kenh: [tr("Hợp kênh"), false], co_hinh: [tr("Có hình trong kho"), true],
  moi: [tr("Footage chưa dùng"), true], khac_biet: [tr("Khác video đã làm"), true] };      // [name, measured rather than the model's opinion]


/** The script against its template's structure: each part's estimated length against its range. */

/** Two or three other ways to open or to end the script; choosing one saves it as the next version, the rest stay. */
/* How each line's picture illustrates its words: shown it (direct), evokes it (associative), or runs against it (contrast).
   The writer chose; the operator changes it here. These are notes on a line, so changing them makes no new script version. */
const WAYS: [NonNullable<Illustration["mode"]>, string][] = [["direct", tr("Trực tiếp")], ["associative", tr("Liên tưởng")], ["contrast", tr("Tương phản")]];
const FEELS: [string, string, string[]][] = [
  ["chuyen_dong", tr("Chuyển động"), ["tĩnh", "chậm", "nhanh"]], ["anh_sang", tr("Ánh sáng"), ["sáng", "vừa", "tối"]], ["mau", tr("Màu"), ["ấm", "trung tính", "lạnh"]],
  ["khung", tr("Khung hình"), ["rộng", "trung", "cận"]], ["nguoi", tr("Người"), ["không người", "một người", "vài người", "đông người"]],
];
function Illustrations({ shots, busy, run }: { shots: Shot[]; busy: boolean; run: (fn: () => Promise<unknown>) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [brief, setBrief] = useState<Record<string, string>>({}), [evokes, setEvokes] = useState<Record<string, string>>({});
  const save = (s: Shot, change: { brief?: string; illustration?: Illustration }) => run(() => post(`/api/v1/shots/${s.shot_id}`, change, "PATCH"));
  const ill = (s: Shot): Illustration => s.illustration ?? {};
  const counts = WAYS.map(([m, label]) => [label, shots.filter((s) => (ill(s).mode ?? "direct") === m).length] as const);
  return (
    <details className="mt-3 rounded-xl border border-line bg-raised/30 px-4 py-3 text-[13px]">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2"><Icon name="image" size={15} className="text-accent" /><span className="font-medium">{tr("Minh hoạ từng câu")}</span>
        <span className="text-faint">{counts.filter(([, n]) => n).map(([l, n]) => `${n} ${l.toLowerCase()}`).join(" · ")}</span></summary>
      <p className="mt-2 text-[12.5px] text-faint">{tr("Câu trực tiếp tìm hình theo lời; câu liên tưởng và tương phản tìm theo hình cần thấy và điều nó gợi, rồi xếp theo cảm giác đo được của footage. Đổi ở đây không tạo phiên bản kịch bản mới; tìm clip lại để áp dụng.")}</p>
      <ol className="mt-2 grid gap-2">{shots.map((s, n) => { const i = ill(s), mode = i.mode ?? "direct"; return (
        <li key={s.shot_id} className="rounded-lg border border-line bg-surface/60 px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="mono w-6 shrink-0 text-faint">{n + 1}</span><span className="min-w-0 flex-1 truncate">{s.text}</span>
            <Seg items={WAYS} value={mode} onChange={(m) => save(s, { illustration: { ...i, mode: m } })} label={tr("Cách minh hoạ")} disabled={busy} />
            <button type="button" className="link text-[12px]" onClick={() => setOpen(open === s.shot_id ? null : s.shot_id)}>{open === s.shot_id ? tr("Thu gọn") : tr("Chi tiết")}</button>
          </div>
          {open !== s.shot_id && (s.brief || i.evokes) && <p className="mt-1 truncate pl-8 text-[12px] text-faint">{s.brief}{i.evokes ? ` · ${tr("gợi")}: ${i.evokes}` : ""}</p>}
          {open === s.shot_id && <div className="mt-2 grid gap-2 pl-8">
            <label className="grid gap-1"><span className="text-[12px] text-mute">{tr("Hình cần thấy")}</span>
              <input value={brief[s.shot_id] ?? s.brief ?? ""} onChange={(e) => setBrief({ ...brief, [s.shot_id]: e.target.value })} onBlur={() => brief[s.shot_id] !== undefined && brief[s.shot_id] !== (s.brief ?? "") && save(s, { brief: brief[s.shot_id] })} className="h-8 px-2.5 text-[13px]" /></label>
            {mode !== "direct" && <label className="grid gap-1"><span className="text-[12px] text-mute">{tr("Hình gợi điều gì")}</span>
              <input value={evokes[s.shot_id] ?? i.evokes ?? ""} onChange={(e) => setEvokes({ ...evokes, [s.shot_id]: e.target.value })} onBlur={() => evokes[s.shot_id] !== undefined && evokes[s.shot_id] !== (i.evokes ?? "") && save(s, { illustration: { ...i, evokes: evokes[s.shot_id] } })} placeholder={tr("ví dụ: chậm lại, bắt đầu lại")} className="h-8 px-2.5 text-[13px]" /></label>}
            <div className="grid gap-1.5"><span className="text-[12px] text-mute">{tr("Cảm giác của hình (so với số đo của footage)")}</span>
              {FEELS.map(([key, name, values]) => <div key={key} className="flex flex-wrap items-center gap-1.5"><span className="w-24 shrink-0 text-[12px] text-faint">{name}</span>
                {values.map((v) => { const on = i.feel?.[key] === v; return <button key={v} type="button" aria-pressed={on} disabled={busy}
                  onClick={() => { const feel = { ...(i.feel ?? {}) }; if (on) delete feel[key]; else feel[key] = v; save(s, { illustration: { ...i, mode, feel } }); }}
                  className={`h-6 rounded-full border px-2.5 text-[12px] ${on ? "border-accent/60 bg-accent/12 text-accent" : "border-line text-mute hover:text-ink"}`}>{v}</button>; })}</div>)}
            </div>
          </div>}
        </li>); })}</ol>
    </details>
  );
}

type SpeechHit = { moment_id: string; asset_id: string; t_start: number; t_end: number; text: string; score: number | null; asset: { name: string; proxy_url: string | null } };

/** What people say in the footage, to put into the script as a quote: searched by words (or all of it), each sentence heard
    where it is said, and inserted after the line the cursor is on as a "> " line that keeps its stretch of the recording. */
function QuotePicker({ insert, close }: { insert: (hit: SpeechHit) => void; close: () => void }) {
  const [q, setQ] = useState(""), [asked, setAsked] = useState("");
  const { data } = usePoll<{ hits: SpeechHit[] }>(`/api/v1/speech?q=${encodeURIComponent(asked)}`, 60000);
  const player = useRef<HTMLVideoElement>(null), [playing, setPlaying] = useState<string | null>(null);
  const hear = (h: SpeechHit) => {
    const v = player.current;
    if (!v || !h.asset.proxy_url) return;
    if (playing === h.moment_id) { v.pause(); setPlaying(null); return; }
    v.src = h.asset.proxy_url; v.currentTime = h.t_start; v.play().catch(() => {}); setPlaying(h.moment_id);
    v.ontimeupdate = () => { if (v.currentTime >= h.t_end) { v.pause(); setPlaying(null); } };
  };
  return (
    <div className="border-t border-line bg-raised/40 px-4 py-3 text-[13px]">
      <div className="mb-2 flex items-center gap-2"><Icon name="mic" size={15} className="text-accent" /><span className="font-medium">{tr("Trích lời từ footage")}</span>
        <span className="text-faint">{tr("câu người trong footage tự nói; khi dựng giữ nguyên tiếng của họ")}</span><span className="flex-1" />
        <button type="button" className="link text-[12px]" onClick={close}>{tr("Đóng")}</button></div>
      <form className="mb-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); setAsked(q.trim()); }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr("Tìm theo lời nói, để trống để xem tất cả")} aria-label={tr("Tìm trong lời nói")} className="h-8 min-w-0 flex-1 px-2.5" />
        <Button size="sm" type="submit"><Icon name="search" size={13} />{tr("Tìm")}</Button></form>
      <video ref={player} className="hidden" playsInline />
      {!data ? <Spinner /> : data.hits.length === 0 ? <p className="text-faint">{asked ? tr("Không có câu nào nói như vậy trong footage đã nghe.") : tr("Footage chưa được nghe lời nói. Vào Thư viện, tab Lời thoại, bấm Nghe lời nói.")}</p> : (
        <ul className="grid max-h-72 gap-1.5 overflow-y-auto">{data.hits.map((h) => (
          <li key={h.moment_id} className="flex items-start gap-2.5 rounded-lg border border-line bg-surface/60 px-3 py-2">
            <button type="button" onClick={() => hear(h)} disabled={!h.asset.proxy_url} aria-label={playing === h.moment_id ? tr("Dừng") : tr("Nghe")}
                    className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md border border-edge text-mute hover:text-ink disabled:opacity-40"><Icon name={playing === h.moment_id ? "pause" : "play"} size={12} /></button>
            <span className="min-w-0 flex-1"><span className="block">“{h.text}”</span>
              <span className="mono block truncate text-[11.5px] text-faint">{h.asset.name} · {timecode(h.t_start)}–{timecode(h.t_end)}</span></span>
            <Button size="sm" onClick={() => insert(h)}><Icon name="plus" size={13} />{tr("Chèn")}</Button>
          </li>))}</ul>)}
    </div>
  );
}

type Recording = { asset_id: string; name: string; sentences: number; seconds: number };

/** A script from what people say in the recordings chosen: the model picks sentences to quote, word for word, and writes the
    narration between them; the result goes into the editor like a draft. */
function SpeechDraft({ id, topic, done }: { id: string; topic: string; done: (lines: string[]) => void }) {
  const { data } = usePoll<{ recordings: Recording[] }>("/api/v1/speech/recordings", 60000);
  const [chosen, setChosen] = useState<string[]>([]), [goal, setGoal] = useState(topic), [n, setN] = useState(8), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const write = async () => {
    setBusy(true); setErr(null);
    try { const r = await post<{ lines: string[] }>(`/api/v1/projects/${id}/draft-from-speech`, { asset_ids: chosen, goal, lines: n }); done(r.lines); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  return (
    <div className="border-t border-line bg-ai/[0.04] px-4 py-3 text-[13px]">
      <p className="mb-2 flex items-center gap-2"><Icon name="mic" size={15} className="text-ai" /><span className="font-medium">{tr("Kịch bản từ lời nói")}</span>
        <span className="text-faint">{tr("máy chọn câu người trong footage nói (nguyên văn) và viết lời dẫn nối giữa các đoạn")}</span></p>
      {!data ? <Spinner /> : data.recordings.length === 0 ? <p className="text-faint">{tr("Chưa có bản ghi nào có câu nói đủ dài để trích. Vào Thư viện, tab Lời thoại, bấm Nghe lời nói.")}</p> : (
        <ul className="mb-2.5 grid max-h-48 gap-1 overflow-y-auto">{data.recordings.map((r) => (
          <li key={r.asset_id}><label className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-white/[0.03]">
            <input type="checkbox" checked={chosen.includes(r.asset_id)} onChange={(e) => setChosen(e.target.checked ? [...chosen, r.asset_id] : chosen.filter((x) => x !== r.asset_id))} />
            <span className="mono min-w-0 flex-1 truncate text-[12.5px]">{r.name}</span><span className="mono shrink-0 text-[12px] text-faint">{tv`${r.sentences} câu · ${timecode(r.seconds)}`}</span></label></li>))}</ul>)}
      <div className="flex flex-wrap items-center gap-2">
        <input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder={tr("Mục tiêu (không bắt buộc), ví dụ: chuyến đi chơi của hai vợ chồng")} aria-label={tr("Mục tiêu")} className="h-8 min-w-0 flex-1 px-2.5" />
        <label className="flex items-center gap-1.5 text-[12.5px] text-mute">{tr("Khoảng")}<input type="number" min={3} max={20} value={n} onChange={(e) => setN(Number(e.target.value))} className="mono h-8 w-16 px-2" />{tr("câu")}</label>
        <Button size="sm" kind="ai" busy={busy} disabled={busy || !chosen.length} onClick={write}>{busy ? <Spinner /> : <Icon name="sparkles" size={13} />}{busy ? tr("Đang soạn…") : tr("Viết kịch bản")}</Button>
      </div>
      {err && <p className="mt-2 text-tally">{err}</p>}
    </div>
  );
}

const WORDS_PER_SECOND = 2.6, MIN_LINE = 3;             // as the server and the storyboard time a line of narration
const fold = (x: string) => x.normalize("NFC").toLowerCase().trim();

/** Each line's estimated seconds (null for a heading or an empty line), the total, and the seconds of each named section and of
    lines before any heading. */
function timeScript(lines: string[], quoteSeconds: Record<string, number>) {
  const out: (number | null)[] = [], sections: Record<string, number> = {};
  let section: string | null = null, loose = 0, total = 0;
  for (const raw of lines) {
    const l = raw.trim();
    if (!l) { out.push(null); continue; }
    if (l.startsWith("#")) { section = fold(l.replace(/^#+\s*/, "")); sections[section] ??= 0; out.push(null); continue; }
    const quoted = l.startsWith(">"), words = l.replace(/^>\s*/, "");
    const secs = quoted && quoteSeconds[words] != null ? quoteSeconds[words] : Math.max(MIN_LINE, words.split(/\s+/).filter(Boolean).length / WORDS_PER_SECOND);
    out.push(secs); total += secs;
    if (section != null) sections[section] += secs; else loose += secs;
  }
  return { lines: out, total, sections, loose };
}

/** The template's parts against the script as it is being written, live: each part's estimated length against its range. */
function LiveStructure({ segments, sections, loose }: { segments: { label: string; min: number; max: number }[]; sections: Record<string, number>; loose: number }) {
  const rows = segments.map((seg) => { const secs = sections[fold(seg.label)]; return { ...seg, secs, state: secs == null ? "missing" : secs < seg.min ? "short" : secs > seg.max ? "long" : "ok" } as const; });
  const target = [segments.reduce((t, s) => t + s.min, 0), segments.reduce((t, s) => t + s.max, 0)];
  const tone = { ok: "proof", short: "cue", long: "cue", missing: "tally" } as const, said = { ok: tr("vừa"), short: tr("ngắn"), long: tr("dài"), missing: tr("chưa có") };
  return (
    <div className="mt-3 rounded-xl border border-line bg-raised/30 px-4 py-3 text-[13px]">
      <div className="mb-2 flex flex-wrap items-center gap-2"><Icon name="layers" size={15} className="text-mute" /><span className="font-medium">{tr("Cấu trúc theo mẫu")}</span>
        <span className="text-faint">{tv`mục tiêu ${Math.round(target[0])}–${Math.round(target[1])} giây`}</span>
        {loose > 0 && <span className="text-cue">{tv`${Math.round(loose)} giây chưa thuộc phần nào (thêm dòng # tên phần ở trên)`}</span>}</div>
      <ul className="grid gap-1.5 sm:grid-cols-3">{rows.map((r) => (
        <li key={r.label} className="grid gap-1">
          <span className="flex items-center gap-2"><Tag tone={tone[r.state]}>{said[r.state]}</Tag><span className="min-w-0 truncate">{r.label}</span>
            <span className="mono ml-auto shrink-0 text-faint">{r.secs == null ? "–" : `${Math.round(r.secs)}s`} / {r.min}–{r.max}s</span></span>
          <span className="relative h-1.5 overflow-hidden rounded-full bg-white/[0.06]">
            <span className="absolute inset-y-0 bg-white/[0.08]" style={{ left: `${(r.min / (r.max * 1.25)) * 100}%`, width: `${((r.max - r.min) / (r.max * 1.25)) * 100}%` }} />
            <span className={`absolute inset-y-0 left-0 rounded-full ${r.state === "ok" ? "bg-proof" : "bg-cue"}`} style={{ width: `${Math.min(100, ((r.secs ?? 0) / (r.max * 1.25)) * 100)}%` }} /></span>
        </li>))}</ul>
    </div>
  );
}

/** The script line by line: each row its number, its kind (narration or quote), its estimated seconds and its words, edited in
    place, dragged to another place or removed; a scene heading is a row of its own. The same text as the plain editor. */
function ScriptLines({ lines, seconds, focus, change }: { lines: string[]; seconds: (number | null)[]; focus: (k: number) => void; change: (next: string[]) => void }) {
  const [drag, setDrag] = useState<number | null>(null), [over, setOver] = useState<number | null>(null);
  const set = (k: number, v: string) => change(lines.map((l, i) => (i === k ? v : l)));
  const move = (from: number, to: number) => { const next = [...lines]; const [x] = next.splice(from, 1); next.splice(from < to ? to - 1 : to, 0, x); change(next); };
  let n = 0;
  return (
    <ol className="grid gap-px bg-line/40 py-1">
      {lines.map((raw, k) => {
        const l = raw.trim();
        const heading = l.startsWith("#"), quoted = l.startsWith(">");
        if (!heading && l) n += 1;
        return (
          <li key={k} draggable={!!l} onDragStart={(e) => { setDrag(k); e.dataTransfer.effectAllowed = "move"; }} onDragEnd={() => { setDrag(null); setOver(null); }}
              onDragOver={(e) => { if (drag != null && drag !== k) { e.preventDefault(); setOver(k); } }} onDrop={(e) => { e.preventDefault(); if (drag != null) move(drag, k); setDrag(null); setOver(null); }}
              className={`group flex items-center gap-2.5 bg-surface px-3 ${heading ? "pt-3" : ""} ${drag === k ? "opacity-40" : ""} ${over === k ? "shadow-[inset_0_2px_0_var(--color-accent)]" : ""}`}>
            <span className="cursor-grab text-faint opacity-40 group-hover:opacity-100" aria-hidden="true"><Icon name="list" size={13} /></span>
            {heading ? <>
              <input value={l.replace(/^#+\s*/, "")} onChange={(e) => set(k, `# ${e.target.value}`)} onFocus={() => focus(k)} aria-label={tr("Tên phần")}
                     className="bare h-8 min-w-0 flex-1 px-1 text-[12.5px] font-semibold uppercase tracking-wide text-mute" />
            </> : <>
              <span className="mono w-6 shrink-0 text-right text-[12px] text-faint">{l ? n : ""}</span>
              <span className={`shrink-0 rounded px-1.5 text-[10.5px] ${quoted ? "bg-accent/12 text-accent" : "bg-white/[0.05] text-faint"}`}>{quoted ? tr("Trích lời") : tr("Lời dẫn")}</span>
              <textarea value={quoted ? l.replace(/^>\s*/, "") : raw} readOnly={quoted} onChange={(e) => set(k, e.target.value.replace(/\n/g, " "))} onFocus={() => focus(k)} aria-label={tv`Câu ${n}`}
                        title={quoted ? tr("Lời người trong footage tự nói: giữ nguyên văn") : undefined} rows={Math.max(1, Math.ceil(raw.length / 72))}
                        className={`bare min-w-0 flex-1 resize-none px-1 py-2 text-[14.5px] leading-relaxed ${quoted ? "italic text-mute" : ""}`} />
              <span className="mono w-10 shrink-0 text-right text-[12px] text-faint">{seconds[k] != null ? `${Math.round(seconds[k]!)}s` : ""}</span>
            </>}
            <button type="button" onClick={() => change(lines.filter((_, i) => i !== k))} aria-label={tr("Bỏ dòng này")} className="grid h-7 w-7 shrink-0 place-items-center rounded text-faint opacity-0 hover:text-tally focus-visible:opacity-100 group-hover:opacity-100"><Icon name="x" size={13} /></button>
          </li>);
      })}
      <li className="flex gap-2 bg-surface px-3 py-2">
        <Button size="sm" kind="quiet" onClick={() => change([...lines, ""])}><Icon name="plus" size={13} />{tr("Thêm câu")}</Button>
        <Button size="sm" kind="quiet" onClick={() => change([...lines, `# ${tr("Phần mới")}`])}><Icon name="plus" size={13} />{tr("Thêm tên phần")}</Button>
      </li>
    </ol>
  );
}

/** The lines a selection in the editor covers (a cursor alone: its line), when they are lines of the script (not empty, not
    a scene heading); null otherwise. */
function span_of(el: HTMLTextAreaElement): { first: number; last: number } | null {
  const before = (n: number) => el.value.slice(0, n).split("\n").length - 1;
  const first = before(el.selectionStart);
  let last = before(el.selectionEnd);
  if (last > first && el.value[el.selectionEnd - 1] === "\n") last -= 1;            // a selection that ends at a line's start stops before it
  const lines = el.value.split("\n").slice(first, last + 1);
  return lines.length && lines.every((l) => l.trim() && !l.trim().startsWith("#") && !l.trim().startsWith(">")) ? { first, last } : null;     // a quote is not rewritten
}

type Proposal = { label: string; lines: string[]; flags: string[] };
const ASKS: [string, string, string, boolean][] = [["shorten", tr("Rút gọn"), "collapse", false], ["tone", tr("Đổi giọng…"), "mic", true], ["bridge", tr("Thêm câu nối"), "plus", false],
  ["split", tr("Tách câu"), "scissors", false], ["again", tr("3 cách khác"), "sparkles", false], ["ask", tr("Yêu cầu khác…"), "comment", true]];

/** Writing with the model on the lines the operator is on: proposals for just those lines, the script as context; one chosen
    takes their place in the editor, still to be saved, as if typed. */
function CoWrite({ id, lines, span, replace }: { id: string; lines: string[]; span: { first: number; last: number }; replace: (first: number, last: number, lines: string[]) => void }) {
  const [asking, setAsking] = useState<string | null>(null), [words, setWords] = useState(""), [busy, setBusy] = useState(false);
  const [got, setGot] = useState<{ first: number; last: number; was: string[]; proposals: Proposal[] } | null>(null), [err, setErr] = useState<string | null>(null);
  const spoken = lines.map((l, k) => [l, k] as const).filter(([l]) => l.trim() && !l.trim().startsWith("#")).map(([, k]) => k);
  const a = spoken.indexOf(span.first) + 1, b = spoken.indexOf(span.last) + 1;
  const go = async (action: string, instruction = "") => {
    setBusy(true); setErr(null); setGot(null);
    const was = lines.slice(span.first, span.last + 1);
    try { setGot({ ...(await post<{ first: number; last: number; proposals: Proposal[] }>(`/api/v1/projects/${id}/script/rewrite`, { lines, first: span.first, last: span.last, action, instruction })), was }); setAsking(null); setWords(""); }
    catch (e) { setErr((e as Error).message); }
    setBusy(false);
  };
  // Proposals are for the lines as they were asked about: another choice, or those lines edited since, makes them out of date.
  const stale = got && (got.first !== span.first || got.last !== span.last || lines.slice(got.first, got.last + 1).join("\n") !== got.was.join("\n"));
  return (
    <div className="border-t border-line bg-ai/[0.04] px-4 py-2.5 text-[13px]">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 flex items-center gap-1.5 text-ai"><Icon name="sparkles" size={14} />{a === b ? tv`Câu ${a}` : tv`Câu ${a}–${b}`}</span>
        {ASKS.map(([key, label, icon, needs]) => <Button key={key} size="sm" kind={asking === key ? "ai" : "quiet"} disabled={busy}
          onClick={() => (needs ? setAsking(asking === key ? null : key) : go(key))}><Icon name={icon} size={13} />{label}</Button>)}
        {busy && <span className="flex items-center gap-1.5 text-faint"><Spinner />{tr("Đang viết…")}</span>}
      </div>
      {asking && <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (words.trim()) go(asking, words); }}>
        <input autoFocus value={words} onChange={(e) => setWords(e.target.value)} placeholder={asking === "tone" ? tr("Giọng thế nào? ví dụ: ấm hơn, hài hước, như kể chuyện") : tr("Muốn viết lại thế nào?")}
               aria-label={tr("Yêu cầu cho mô hình")} className="h-8 min-w-0 flex-1 px-2.5" />
        <Button size="sm" kind="ai" type="submit" disabled={busy || !words.trim()}>{tr("Viết")}</Button></form>}
      {err && <p className="mt-2 text-tally">{err}</p>}
      {got && !stale && <ul className="mt-2.5 grid gap-2">{got.proposals.map((p, k) => (
        <li key={k} className="rounded-lg border border-line bg-surface/70 px-3 py-2.5">
          <div className="mb-1.5 flex items-center gap-2"><span className="text-[12px] font-medium text-ai">{p.label}</span><span className="flex-1" />
            <Button size="sm" kind="primary" onClick={() => { replace(got.first, got.last, p.lines); setGot(null); }}><Icon name="check" size={13} />{tr("Dùng cách này")}</Button></div>
          <ol className="grid gap-0.5 text-[13.5px] leading-relaxed">{p.lines.map((l, i) => <li key={i}>{l}</li>)}</ol>
          {p.flags.map((f) => <p key={f} className="mt-1 text-[12px] text-cue">{f}</p>)}
        </li>))}</ul>}
      {got && stale && <p className="mt-2 text-[12px] text-faint">{tr("Đoạn đã đổi từ lúc hỏi; các phương án trước là cho đoạn cũ.")} <button type="button" className="link" onClick={() => setGot(null)}>{tr("Ẩn")}</button></p>}
    </div>
  );
}

function Variants({ id, p, busy, run }: { id: string; p: Project; busy: boolean; run: (fn: () => Promise<unknown>) => void }) {
  const { data, reload } = usePoll<{ variants: Variant[] }>(`/api/v1/projects/${id}/variants`, 60000);
  const current = new Set(p.shots.map((s) => s.text));
  const mine = (data?.variants ?? []).filter((v) => v.script_id === p.script?.script_id && !v.chosen);
  const make = (part: "opening" | "ending") => run(async () => { const r = await post<{ made: number }>(`/api/v1/projects/${id}/variants`, { part }); if (!r.made) toast(tr("Mô hình không viết được phương án nào khác.")); reload(); });
  return (
    <div className="mt-3 rounded-xl border border-line bg-raised/30 px-4 py-3 text-[13px]">
      <div className="flex flex-wrap items-center gap-2"><Icon name="edit" size={15} className="text-ai" /><span className="font-medium">{tr("Phương án mở bài, kết bài")}</span>
        <span className="text-faint">{tr("viết lại riêng một phần, phần còn lại giữ nguyên")}</span>
        <span className="ml-auto flex gap-2"><Button size="sm" kind="ai" disabled={busy} onClick={() => make("opening")}>{tr("Phương án mở bài")}</Button><Button size="sm" kind="ai" disabled={busy} onClick={() => make("ending")}>{tr("Phương án kết")}</Button></span></div>
      {mine.length > 0 && <ul className="mt-3 grid gap-2 lg:grid-cols-3">{mine.map((v) => { const changed = v.lines.filter((l) => !l.startsWith("#") && !current.has(l)); return (
        <li key={v.variant_id} className="panel-raised flex flex-col gap-1.5 p-3"><div className="flex items-baseline gap-2"><span className="font-medium">{v.label}</span>{v.note && <span className="text-faint">{v.note}</span>}</div>
          {changed.length ? <ul className="grid gap-0.5">{changed.map((l, k) => <li key={k}>{l}</li>)}</ul> : <p className="text-mute">{tr("Như kịch bản hiện tại.")}</p>}
          {changed.length > 0 && <div className="mt-auto pt-1"><Button size="sm" disabled={busy} onClick={() => run(async () => { await post(`/api/v1/variants/${v.variant_id}/choose`); reload(); })}>{tr("Dùng phương án này")}</Button></div>}
        </li>); })}</ul>}
    </div>
  );
}

/** Ideas the library can carry: each group of footage measured, the model asked only for the angle; a risk blocks. */
function IdeasPanel({ format, close, go, onTask }: { format: string; close: () => void; go: (to: string) => void; onTask: () => void }) {
  const [fast, setFast] = useState(false);
  const { data, reload } = usePoll<{ ideas: Idea[]; clusters: number; running: boolean; error: string | null; started_at: number | null }>("/api/v1/ideas", fast ? 3000 : 30000);
  const { data: chan } = usePoll<{ channels: Channel[] }>("/api/v1/channels", 60000);
  const [channel, setChannel] = useState(""), [note, setNote] = useState<string | null>(null);
  const [why, setWhy] = useState<Record<string, string>>({}), [showDone, setShowDone] = useState(false);
  const thinking = !!data?.running;
  useEffect(() => { setFast(thinking); }, [thinking]);
  const propose = async () => { setNote(null); try { await post("/api/v1/ideas", { channel: channel || null }); setFast(true); } catch (e) { setNote((e as Error).message); } reload(); };
  const accept = async (it: Idea) => { try { const p = await post<Project>(`/api/v1/ideas/${it.idea_id}/accept`, { reason: why[it.idea_id] ?? "" }); go(`/du-an/${p.project_id}/storyboard`); } catch (e) { toast((e as Error).message, { tone: "tally" }); } };
  const drop = async (it: Idea) => { await post(`/api/v1/ideas/${it.idea_id}/drop`); reload(); toast(tv`Đã bỏ ý tưởng “${it.title}”.`); };
  const all = data?.ideas ?? [];
  const open = all.filter((i) => i.status === "new" || i.status === "blocked"), done = all.filter((i) => i.status === "accepted" || i.status === "dropped");
  return (
    <div className="panel rise mb-6 p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0"><h2 className="flex items-center gap-2 text-[15px] font-semibold"><Icon name="spark" size={16} className="text-ai" />{tr("Ý tưởng làm được từ kho footage")}</h2>
          <p className="max-w-3xl text-[13px] text-mute">{tv`Hệ thống gom footage theo chủ đề và buổi quay (${data?.clusters ?? 0} nhóm), rồi chỉ hỏi mô hình góc kể và các cảnh cần có. Mỗi cảnh được tìm thật trong kho; điểm có dấu ● là số đo, không phải ý mô hình. Ý tưởng có rủi ro bị chặn cho tới khi bạn ghi lý do.`}</p></div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-[12.5px] text-mute">{tr("Cho kênh")}<select value={channel} onChange={(e) => setChannel(e.target.value)} className="h-9 pl-2.5 text-ink"><option value="">{tr("Không chọn")}</option>{(chan?.channels ?? []).map((c) => <option key={c.name}>{c.name}</option>)}</select></label>
          <Button kind="ai" disabled={thinking} onClick={propose}>{thinking ? tr("Đang nghĩ…") : (open.length ? tr("Gợi ý lại") : tr("Gợi ý ý tưởng"))}</Button><Button kind="quiet" onClick={close} aria-label={tr("Đóng")}><Icon name="x" /></Button></div>
      </div>
      {(note || data?.error) && <p className="mb-2 text-tally">{note || data?.error}</p>}
      {thinking && <p className="mb-3 flex items-center gap-2 text-[13px] text-ai"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ai" />{tr("Mô hình đang nghĩ góc kể cho từng nhóm footage, mỗi nhóm khoảng hai phút. Có thể rời trang; ý tưởng hiện ra khi xong.")}</p>}
      {data && open.length === 0 && !thinking && <p className="text-mute">{data.clusters ? tr("Chưa có ý tưởng nào đang chờ. Bấm Gợi ý ý tưởng.") : tr("Chưa có ý tưởng nào. Kho cần có footage đã được mô tả.")}</p>}
      <ul className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">
        {open.map((it) => (
          <li key={it.idea_id} className={`panel-raised flex flex-col p-4 ${it.status === "blocked" ? "border-cue/40" : ""}`}>
            <div className="mb-1 flex items-start justify-between gap-3"><p className="font-medium">{it.title}</p><span className="mono shrink-0 rounded-md bg-accent/15 px-1.5 text-[12px] text-accent" title={tr("Tổng điểm")}>{it.total}</span></div>
            {it.angle && <p className="mb-2 text-[13px] text-mute">{it.angle}</p>}
            <p className="mb-3 flex flex-wrap gap-1.5 text-[11.5px]">
              <span className="chip">{it.material.kind}: {it.material.name}</span>
              <span className="chip mono">{tv`${Math.round(it.coverage * 100)}% cảnh có hình`}</span>
              <span className="chip mono">{tv`khoảng ${timecode(it.seconds)}`}</span>
              {it.template && <span className="chip">{it.template}</span>}
              {it.channel && <span className="chip">{it.channel}</span>}
            </p>
            <dl className="mb-3 grid grid-cols-2 gap-x-5 gap-y-1.5 text-[12.5px]">
              {Object.entries(CRITERIA).filter(([key]) => key in it.scores).map(([key, [name, measured]]) => (
                <div key={key} className="flex items-center justify-between gap-2"><dt className="text-mute">{measured && <span className="mr-1 text-proof" title={tr("Số đo từ kho")}>●</span>}{name}</dt>
                  <dd className="flex gap-0.5" aria-label={tv`${it.scores[key]} trên 5`}>{[1, 2, 3, 4, 5].map((n) => <span key={n} className={`h-1.5 w-3 rounded-full ${n <= (it.scores[key] ?? 0) ? "bg-gradient-to-r from-accent to-ai" : "bg-overlay"}`} />)}</dd></div>
              ))}
            </dl>
            <details className="mb-3 text-[12.5px]"><summary className="cursor-pointer list-none text-accent">{tv`${it.shots.length} cảnh cần có, ${it.gaps.length} còn thiếu`}</summary>
              <ul className="mt-1.5 grid gap-1">{it.shots.map((sh, k) => (
                <li key={k} className="flex items-start gap-2"><Icon name={sh.covered ? "check" : "alert"} size={13} className={`mt-0.5 shrink-0 ${sh.covered ? "text-proof" : "text-cue"}`} />
                  <span className="min-w-0"><span className={sh.covered ? "" : "text-cue"}>{sh.need}</span>{sh.covered && sh.text && <span className="block truncate text-faint">{sh.text}</span>}</span></li>))}</ul></details>
            {it.risk && <p className="mb-2 text-[12.5px] text-cue">{tv`Rủi ro: ${it.risk}`}</p>}
            {it.status === "blocked" && <input aria-label={tr("Lý do vẫn làm")} value={why[it.idea_id] ?? ""} onChange={(e) => setWhy({ ...why, [it.idea_id]: e.target.value })} placeholder={tr("Lý do vẫn làm (bắt buộc với ý tưởng có rủi ro)")} className="mb-2 h-8 px-2.5 text-[12.5px]" />}
            <div className="mt-auto flex flex-wrap gap-2">
              <Button size="sm" kind="primary" disabled={it.status === "blocked" && !(why[it.idea_id] ?? "").trim()} onClick={() => accept(it)}><Icon name="check" size={14} />{tr("Nhận, mở Storyboard")}</Button>
              <Button size="sm" kind="ai" disabled={it.status === "blocked"} onClick={async () => { const m = await post<{ mission_id: string }>("/api/v1/missions", { text: `Làm một video ${format === "portrait" ? "dọc" : format === "square" ? "vuông" : "ngang"}: ${it.title}. ${it.angle ?? ""}` }); onTask(); go(`/phong-may?tab=missions&nv=${m.mission_id}`); }}><Icon name="sparkles" size={14} />{tr("Giao việc")}</Button>
              <Button size="sm" kind="quiet" onClick={() => drop(it)}>{tr("Bỏ")}</Button>
            </div>
          </li>
        ))}
      </ul>
      {done.length > 0 && <div className="mt-4"><button type="button" className="link text-[12.5px]" onClick={() => setShowDone(!showDone)}>{showDone ? tr("Ẩn ý tưởng đã quyết") : tv`Xem ${done.length} ý tưởng đã quyết`}</button>
        {showDone && <ul className="panel rows mt-2">{done.map((it) => (
          <li key={it.idea_id} className="flex flex-wrap items-center gap-2 px-3 py-2 text-[13px]"><Tag tone={it.status === "accepted" ? "proof" : "mute"}>{it.status === "accepted" ? tr("Đã nhận") : tr("Đã bỏ")}</Tag><span>{it.title}</span>
            {it.reason && <span className="text-faint">{tv`lý do: ${it.reason}`}</span>}
            {it.project_id && <button type="button" className="link ml-auto" onClick={() => go(`/du-an/${it.project_id}`)}>{tr("Mở dự án")}</button>}</li>))}</ul>}</div>}
    </div>
  );
}
const TASK_STATES: Record<string, string> = { working: tr("Đang làm"), waiting_operator: tr("Chờ bạn"), done: "Xong", failed: tr("Dừng vì lỗi") };

/** What the producer agent did for this project, role by role, in the order it happened. */
function AgentLog({ projectId }: { projectId: string }) {
  const { data } = usePoll<{ tasks: AgentTask[] }>(`/api/v1/agent/tasks?project_id=${projectId}`, 3000);
  const task = data?.tasks[0];
  if (!task) return null;
  return (
    <details className="ai-card mb-6 px-4 py-3" open={task.status !== "done"}>
      <summary className="flex cursor-pointer list-none items-center gap-2.5 font-medium">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-ai/15 text-ai"><Icon name="sparkles" size={15} /></span>{tr("Trợ lý sản xuất")}
        <Tag tone={task.status === "waiting_operator" ? "cue" : task.status === "failed" ? "tally" : task.status === "done" ? "proof" : "ai"}>{TASK_STATES[task.status] ?? task.status}</Tag>
        <span className="ml-auto truncate text-[12.5px] font-normal text-mute">{task.goal}</span><Icon name="down" size={14} className="text-faint" />
      </summary>
      <ol className="mt-3 grid gap-1.5 border-t border-ai/15 pt-3">
        {task.log.map((e, i) => <li key={i} className="grid grid-cols-[4.5rem_7rem_minmax(0,1fr)] gap-2 text-[13px]"><span className="mono text-faint">{new Date(e.at * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })}</span><span className="truncate text-ai">{e.role}</span><span>{e.text}</span></li>)}
      </ol>
    </details>
  );
}

type View = "script" | "clips" | "cut" | "publish" | "timeline" | "board";

/** Moves to another address in place of this one, so going back does not land here again. */
function Replace({ to }: { to: string }) {
  useEffect(() => { window.history.replaceState({}, "", to); window.dispatchEvent(new PopStateEvent("popstate")); }, [to]);
  return null;
}
const VIEWS: View[] = ["script", "clips", "cut", "publish", "timeline", "board"];
const FLOW: [View, string, string][] = [["script", tr("Kịch bản"), "edit"], ["cut", tr("Dựng video"), "scissors"], ["publish", tr("Xuất bản"), "globe"]];

/** The steps of a video as the page's own navigation: each one is a screen. A step lights amber when it waits for the operator,
    green when it is behind, white where the work stands; the selected one carries the underline. Beside them, the two views of the whole. */
/** Where a step stands for this project. */
function stepState(k: View, step: number, reviewing: boolean, renderReview: boolean, packaged: boolean): "done" | "now" | "wait" | "later" {
  if (k === "script") return step > 0 ? "done" : "now";
  if (k === "cut") return renderReview ? "wait" : step >= 5 ? "done" : step >= 3 ? "now" : "later";
  return step >= 5 ? (packaged ? "done" : "now") : "later";
}

type Lamps = { step: number; reviewing: boolean; renderReview: boolean; packaged: boolean };
type Place = View | "storyboard";

/** The steps of the open project, hung beneath it in the side menu: a lamp for where each stands, the open one lit; the
    Storyboard after the script, then the two views of the whole. */
function StepTree({ id, place, lamps, onChange }: { id: string; place: Place; lamps: Lamps; onChange?: (v: View) => void }) {
  const dot = { done: "border-proof/40 bg-proof/15 text-proof", now: "border-accent/60 bg-accent/15 text-accent", wait: "border-cue/60 bg-cue/15 text-cue", later: "border-line text-faint" };
  const said = { done: tr("Đã xong"), now: tr("Đang ở bước này"), wait: tr("Chờ bạn"), later: tr("Chưa tới") };
  // On the project's page a step changes the view in place; from the storyboard it opens the project at that step.
  const open = (k: View) => (onChange ? onChange(k) : goTo(`/du-an/${id}?tab=${k}`));
  const lamp = (cls: string, icon: string, wait = false) => <span className={`relative grid h-5 w-5 shrink-0 place-items-center rounded-full border ${cls}`}><Icon name={icon} size={11} />{wait && <span className="ping absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-cue" />}</span>;
  return (
    <>
      {FLOW.map(([k, label, icon]) => { const st = stepState(k, lamps.step, lamps.reviewing, lamps.renderReview, lamps.packaged); return (<Fragment key={k}>
        <SideLink small label={label} on={place === k} onClick={() => open(k)} title={said[st]} lead={lamp(dot[st], st === "done" ? "check" : icon, st === "wait")} />
        {k === "script" && <SideLink small label={tr("Storyboard")} on={place === "storyboard"} onClick={() => goTo(`/du-an/${id}/storyboard`)}
                                     title={tr("Từ ý tưởng hoặc kịch bản này thành cảnh và shot có đặc tả, mặt bằng máy, liền mạch; sửa bằng hội thoại.")}
                                     lead={(() => { const st = lamps.reviewing ? "wait" : lamps.step >= 3 ? "done" : lamps.step >= 1 ? "now" : "later";
                                       return lamp(place === "storyboard" ? dot.now : dot[st], st === "done" && place !== "storyboard" ? "check" : "layers", st === "wait"); })()} />}
      </Fragment>); })}
      <span className="mx-2.5 my-1 h-px bg-line" aria-hidden="true" />
      <SideLink small label={tr("Dòng thời gian")} icon="timeline" on={place === "timeline"} onClick={() => open("timeline")} />
      <SideLink small label={tr("Bảng theo dõi")} icon="board" on={place === "board"} onClick={() => open("board")} />
    </>
  );
}

/* The list's filter outlives a visit to a project, so coming back from one finds the list as it was left. */
let listFilter: Filter = "all";
const bucket = (p: Project): Filter => { const st = projectState(p); return st.step === 5 ? "done" : st.tone === "cue" || st.tone === "tally" ? "waiting" : "active"; };

/** The projects section's side menu, the same on every screen of it: the list's filters, then every project by where it
    stands, the open one unfolding its steps (and its storyboard) beneath it, so the menu never changes shape under the hand. */
function ProjectSide({ current, place, lamps, onView, filter, production }: { current?: string; place?: Place; lamps?: Lamps; onView?: (v: View) => void;
  filter?: { value: Filter; set: (f: Filter) => void }; production?: string }) {
  const { data } = usePoll<Project[]>("/api/v1/projects", 15000);
  const { data: prods } = usePoll<{ productions: Production[] }>("/api/v1/productions", 15000);
  const all = data ?? [];
  const counts = { all: all.length, active: 0, waiting: 0, done: 0 } as Record<Filter, number>;
  all.forEach((p) => { counts[bucket(p)] += 1; });
  const pick = (k: Filter) => { listFilter = k; if (filter) filter.set(k); else goTo("/du-an"); };
  const here = production ?? all.find((p) => p.project_id === current)?.production_id ?? null;
  const video = (p: Project) => { const st = projectState(p); const open = p.project_id === current; return (
    <SideLink key={p.project_id} small label={p.title} title={`${p.title}: ${st.label}`} on={open && !place} onClick={() => goTo(`/du-an/${p.project_id}`)}
              lead={<span className={`h-1.5 w-1.5 shrink-0 rounded-full ${({ mute: "bg-faint", cue: "bg-cue", proof: "bg-proof", tally: "bg-tally" } as const)[st.tone]}`} />}>
      {open && <StepTree id={p.project_id} place={place ?? "script"} lamps={lamps ?? { step: st.step, reviewing: st.tone === "cue" && st.step < 3, renderReview: false, packaged: st.step === 5 }} onChange={onView} />}
    </SideLink>); };
  const lit = filter?.value ?? (current || production ? null : listFilter);
  return (
    <>
      <SideGroup label={tr("Video")}>
        {FILTERS.map(([k, name]) => <SideLink key={k} small label={name} icon={({ all: "layers", active: "pulse", waiting: "bell", done: "check" } as const)[k]} on={lit === k} onClick={() => pick(k)} count={counts[k]} tone={k === "waiting" ? "cue" : undefined} />)}
      </SideGroup>
      <SideGroup label={tr("Dự án")} end={<span className="mono">{prods?.productions.length ?? ""}</span>}>
        {(prods?.productions ?? []).map((d) => { const open = d.production_id === here; const vids = all.filter((p) => p.production_id === d.production_id); return (
          <SideLink key={d.production_id} small label={d.title} on={open && production === d.production_id && !current} onClick={() => goTo(`/du-an/${d.production_id}`)} count={vids.length}
                    lead={<Icon name={open ? "down" : "next"} size={13} className={open ? "text-ink" : "text-faint"} />}>
            {open && (vids.length ? vids.map(video) : <p className="px-2.5 py-1 text-[12px] text-faint">{tr("Chưa có video")}</p>)}
          </SideLink>); })}
      </SideGroup>
    </>
  );
}

function StepTabs({ id, view, step, reviewing, renderReview, packaged, onChange }: { id: string; view: View; step: number; reviewing: boolean; renderReview: boolean; packaged: boolean; onChange: (v: View) => void }) {
  const state = (k: View) => stepState(k, step, reviewing, renderReview, packaged);
  const dot = { done: "border-proof/40 bg-proof/15 text-proof", now: "border-accent/60 bg-accent/15 text-accent", wait: "border-cue/60 bg-cue/15 text-cue", later: "border-line text-faint" };
  const tab = (k: View, label: string, inner: React.ReactNode) => (
    <button key={k} type="button" role="tab" aria-selected={view === k} onClick={() => onChange(k)}
            className={`relative flex h-11 shrink-0 items-center gap-2 whitespace-nowrap px-2.5 text-[13.5px] transition-colors after:absolute after:inset-x-2 after:-bottom-px after:h-0.5 after:rounded-full after:transition-colors ${view === k ? "font-medium text-ink after:bg-accent" : "text-mute after:bg-transparent hover:text-ink"}`}>
      {inner}{label}
    </button>
  );
  return (
    <div className="scroll-x -mb-px flex items-center gap-0.5" role="tablist" aria-label={tr("Các bước làm video")}>
      {FLOW.map(([k, label, icon], i) => {
        const st = state(k);
        return (
          <span key={k} className="flex shrink-0 items-center">
            {i > 0 && <span className={`mx-0.5 hidden h-px w-5 sm:block ${state(FLOW[i - 1][0]) === "done" ? "bg-proof/40" : "bg-line"}`} aria-hidden="true" />}
            {tab(k, label, <span className={`relative grid h-6 w-6 place-items-center rounded-full border text-[11px] ${dot[st]}`} title={{ done: tr("Đã xong"), now: tr("Đang ở bước này"), wait: tr("Chờ bạn"), later: tr("Chưa tới") }[st]}>
              <Icon name={st === "done" ? "check" : icon} size={13} />{st === "wait" && <span className="ping absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-cue" />}</span>)}
            {k === "script" && <button type="button" onClick={() => goTo(`/du-an/${id}/storyboard`)} className="flex h-11 shrink-0 items-center gap-2 whitespace-nowrap px-2.5 text-[13.5px] text-mute hover:text-ink">
              <span className="grid h-6 w-6 place-items-center rounded-full border border-line"><Icon name="layers" size={13} /></span>{tr("Storyboard")}</button>}
          </span>
        );
      })}
      <span className="mx-2 h-5 w-px shrink-0 bg-line" aria-hidden="true" />
      {tab("timeline", tr("Dòng thời gian"), <Icon name="timeline" size={15} />)}
      {tab("board", tr("Bảng theo dõi"), <Icon name="board" size={15} />)}
    </div>
  );
}

/** A panel that slides in from the right over the page, for what is set once and rarely touched. */
function Drawer({ title, close, children }: { title: string; close: () => void; children: React.ReactNode }) {
  useEffect(() => { const key = (e: KeyboardEvent) => { if (e.key === "Escape") close(); }; window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key); }, [close]);
  return createPortal(                                                       // above the page, not inside its animated scroll area
    <div className="scrim fixed inset-0 z-40" onMouseDown={close}>
      <aside role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}
             className="drawer absolute inset-y-0 right-0 flex w-full max-w-[440px] flex-col border-l border-edge bg-surface shadow-[var(--shadow-float)]">
        <div className="flex h-14 shrink-0 items-center gap-2 border-b border-line px-5"><Icon name="sliders" size={16} className="text-mute" /><h2 className="flex-1 text-[15px] font-semibold">{title}</h2>
          <button type="button" onClick={close} className="grid h-8 w-8 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink" aria-label={tr("Đóng")}><Icon name="x" size={16} /></button></div>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </div>, document.body);
}

function Detail({ id, back }: { id: string; back: (to?: string) => void }) {
  const { data: p, reload } = usePoll<Project>(`/api/v1/projects/${id}`, 2500);
  const [text, setText] = useState<string | null>(null);
  const [topic, setTopic] = useState("");
  const editor = useRef<HTMLTextAreaElement>(null);
  const [span, setSpan] = useState<{ first: number; last: number } | null>(null);       // the lines the cursor or the selection is on
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});                      // quotes picked in this editor, by their words, until saved
  const [quoting, setQuoting] = useState(false), [fromSpeech, setFromSpeech] = useState(false);
  const [lineView, setLineView] = useState(() => { try { return localStorage.getItem("nx.script.view") === "lines"; } catch { return false; } });
  useEffect(() => { try { localStorage.setItem("nx.script.view", lineView ? "lines" : "text"); } catch { /* private window */ } }, [lineView]);
  // A "> " line the operator picked from what the footage says goes with its stretch of the recording; any other line as written.
  const toSave = () => (text ?? "").split("\n").map((l) => { const w = l.trim().replace(/^>\s*/, ""); return l.trim().startsWith(">") && quotes[w] ? { text: `> ${w}`, quote: quotes[w] } : l; });
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const asked = new URLSearchParams(window.location.search).get("tab") as View | null;
  const [chosen, setChosen] = useState<View | null>(asked && VIEWS.includes(asked) ? asked : null);          // until the operator picks a step, the page opens where the work stands
  const setView = (k: View) => { setChosen(k); window.history.replaceState({}, "", `/du-an/${id}?tab=${k}`); document.querySelector("main .overflow-y-auto")?.scrollTo(0, 0); };
  const [mode, setMode] = useState<"quick" | "list">("quick");
  const [settings, setSettings] = useState(false);
  const [takes, setTakes] = useState<string | null>(null);
  const [music, setMusic] = useState<string | null>(null);
  const [style, setStyle] = useState<string | null>(null);
  const [budget, setBudget] = useState<string | null>(null);
  const [why, setWhy] = useState("");
  const { data: lib } = usePoll<{ assets: Asset[] }>("/api/v1/library", 30000);
  const tracks = (lib?.assets ?? []).filter((a) => a.kind === "audio" && a.online);
  const { data: prefs } = usePoll<Settings>("/api/v1/settings", 30000);
  const { data: chan } = usePoll<{ channels: Channel[] }>("/api/v1/channels", 60000);
  const cut = useRef<HTMLVideoElement>(null);
  const stored = p ? scriptText(p.shots) : null;
  const last = useRef<string | null>(null);
  // The editor follows the stored script (after a reorder on the timeline, for example) unless the operator has typed something not yet saved.
  useEffect(() => { if (stored === null) return; if (text === null || text.trim() === (last.current ?? "").trim()) setText(stored); last.current = stored; }, [stored]);
  const unsaved = text !== null && stored !== null && text.trim() !== stored.trim();
  const saveRef = useRef<() => void>(() => {});
  useEffect(() => {
    // Space plays or pauses the cut; ⌘ Enter saves the script. Neither fires while the operator is typing somewhere else.
    const on = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
      if (e.key === " " && !typing && cut.current && t?.tagName !== "BUTTON" && t?.tagName !== "A") { e.preventDefault(); if (cut.current.paused) cut.current.play().catch(() => {}); else cut.current.pause(); }
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && t?.getAttribute("aria-label") === tr("Kịch bản")) { e.preventDefault(); saveRef.current(); }
    };
    window.addEventListener("keydown", on); return () => window.removeEventListener("keydown", on);
  }, []);
  useEffect(() => {
    if (!unsaved) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };       // the browser asks before the unsaved script is lost
    window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved]);
  if (!p) return <Page title={tr("Đang mở dự án…")} back={{ label: tr("Dự án"), onClick: () => back() }} side={<ProjectSide current={id} />}><div className="grid gap-4" aria-busy="true"><div className="panel h-16" /><div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]"><div className="panel h-72" /><div className="panel h-72" /></div></div></Page>;
  const run = async (fn: () => Promise<unknown>) => { setBusy(true); setNote(null); try { await fn(); } catch (e) { setNote((e as Error).message); } setBusy(false); reload(); };
  const saved = scriptText(p.shots);
  const dirty = text !== null && text.trim() !== saved.trim();
  // How long the script runs, as it is being written: a quote as long as its stretch, a line of narration by its words.
  const quoteSeconds: Record<string, number> = {};
  for (const sh of p.shots) if (sh.quote?.t_out != null && sh.quote.t_in != null) quoteSeconds[sh.text] = sh.quote.t_out - sh.quote.t_in;
  for (const [w, q] of Object.entries(quotes)) if (q.t_out != null && q.t_in != null) quoteSeconds[w] = q.t_out - q.t_in;
  const timing = timeScript((text ?? saved).split("\n"), quoteSeconds);
  saveRef.current = () => { if (dirty && (text ?? "").trim()) run(() => post(`/api/v1/projects/${id}/script`, { lines: toSave() }, "PUT")); };
  const matching = p.match && ["queued", "running"].includes(p.match.status);
  const reviewing = p.match?.status === "waiting_review";
  const approved = !!p.script?.match_approved;
  const rendering = p.render && ["queued", "running"].includes(p.render.status);
  const latest = p.renders.find(() => true);
  const renderReview = p.render?.status === "waiting_review";
  const step = !p.script ? 0 : !p.match ? 1 : matching ? 1 : reviewing ? 2 : !approved ? 1 : !p.render || rendering ? 3 : renderReview ? 4 : 5;
  const view: View = chosen ?? (step === 0 ? "script" : step <= 2 ? "clips" : step <= 4 ? "cut" : "publish");
  // Pictures are chosen on the storyboard now: the clip step's address, and a project standing at that step, open it there.
  if (view === "clips") return <Replace to={`/du-an/${id}/storyboard`} />;
  const gaps = p.shots.filter((s) => s.selection?.status === "gap").length;
  const st = projectState(p);
  const patch = (body: Record<string, unknown>) => run(() => post(`/api/v1/projects/${id}`, body, "PATCH"));
  const lines = (text ?? "").split("\n").filter((l) => l.trim() && !l.trim().startsWith("#")).length;
  // The one thing to do next, always in the same place.
  const next = dirty ? { label: tr("Lưu kịch bản"), icon: "check", go: () => run(() => post(`/api/v1/projects/${id}/script`, { lines: toSave() }, "PUT")) }
    : !p.script ? null
    : reviewing || (!approved && !rendering) ? { label: tr("Chọn hình trên Storyboard"), icon: "layers", go: () => goTo(`/du-an/${id}/storyboard`) }
    : renderReview ? { label: tr("Duyệt bản dựng"), icon: "check", go: () => run(() => post(`/api/v1/projects/${id}/render/decision`, { approve: true })) }
    : approved && !latest && !rendering && view !== "cut" ? { label: tr("Sang bước Dựng video"), icon: "scissors", go: () => setView("cut") }
    : null;
  const field = "field-label";
  const card = "panel grid gap-4 p-4";
  const channels = chan?.channels ?? [];
  const previewing = !!p?.preview && ["queued", "running"].includes(p.preview.status);
  const facts = (p?.shots ?? []).filter((s) => s.is_fact);
  return (
    <Page title={p.title} back={{ label: p.production?.title ?? tr("Dự án"), onClick: () => back(p.production ? `/du-an/${p.production.production_id}` : undefined) }} wide full={view === "cut"}
          note={<Slate state={<Tag tone={st.tone}>{st.label}</Tag>} items={[
            [String(p.shots.length), tr("câu")],
            [String(new Set(p.shots.map((s) => s.scene).filter(Boolean)).size || "–"), tr("cảnh")],
            [String(p.renders.length || "–"), tr("bản dựng")],
            [latest ? timecode(latest.qc.duration) : "–", tr("thời lượng")],
          ]} extra={<>{FORMATS[p.format] ?? p.format}{p.template ? <span className="ml-3">{p.template}</span> : null}</>} />}
          side={<ProjectSide current={id} place={view} lamps={{ step, reviewing: !!reviewing, renderReview: !!renderReview, packaged: !!latest?.package }} onView={setView} />}
          tabs={<div className="lg:hidden"><StepTabs id={id} view={view} step={step} reviewing={!!reviewing} renderReview={!!renderReview} packaged={!!latest?.package} onChange={setView} /></div>}
          actions={<><Button onClick={() => setSettings(true)} title={tr("Mẫu, khung hình, nhạc, lời dẫn, kênh, ngày đăng")}><Icon name="sliders" size={15} />{tr("Thiết lập")}</Button>{next && <Button kind="primary" busy={busy} disabled={next.label === tr("Lưu kịch bản") && !(text ?? "").trim()} onClick={next.go}>{!busy && <Icon name={next.icon} />}{next.label}</Button>}</>}>
      {p.trashed_at && <div className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border border-cue/40 bg-cue/10 px-4 py-3 text-cue"><Icon name="trash" />
        <span className="min-w-0 flex-1">{tr("Dự án này đang ở Thùng rác. Nó không hiện trong danh sách và trợ lý không làm tiếp cho tới khi bạn khôi phục.")}</span>
        <Button size="sm" disabled={busy} onClick={() => run(() => post("/api/v1/trash/restore", { projects: [id] }))}><Icon name="undo" size={14} />{tr("Khôi phục")}</Button></div>}
      {note && <p className="mb-5 flex items-center gap-2 rounded-xl border border-tally/40 bg-tally/10 px-4 py-3 text-tally"><Icon name="alert" />{note}</p>}
      <AgentLog projectId={id} />
      {view === "board" && <Board project={p} />}
      {view === "timeline" && <Timeline project={p} reload={reload} busy={busy} rerender={() => run(() => post(`/api/v1/projects/${id}/render`))} />}

      {view === "script" && (
        <div className="rise grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0">
              <div className="mb-3 flex flex-wrap items-center gap-3 rounded-xl border border-accent/30 bg-accent/[0.05] px-4 py-3">
                <Icon name="layers" size={18} className="text-accent" />
                <span className="min-w-0 flex-1 text-[13px]"><span className="font-medium text-ink">{tr("Storyboard & Director")}</span>
                  <span className="block text-mute">{tr("Từ ý tưởng hoặc kịch bản này thành cảnh và shot có đặc tả, mặt bằng máy, liền mạch; sửa bằng hội thoại.")}</span></span>
                <Button kind="primary" onClick={() => goTo(`/du-an/${id}/storyboard`)}>{tr("Mở Storyboard")}</Button>
              </div>
              <Section title={tr("Kịch bản")} icon="edit" note={tr("Mỗi dòng là một câu lời dẫn; hệ thống tìm một clip cho từng câu. Dòng bắt đầu bằng dấu # là tên một cảnh; dòng bắt đầu bằng > là câu trích lời, người trong footage tự nói, giữ nguyên tiếng.")}>
                <div className={`panel overflow-hidden ${dirty ? "glow" : ""}`}>
                  <div className="flex flex-wrap items-center gap-3 border-b border-line bg-raised/40 px-4 py-2 text-[12px] text-mute">
                    <span className="mono">{p.script ? `v${p.script.version}` : tr("bản nháp")}</span>{p.script?.label && <Tag tone="ai">{p.script.label}</Tag>}<span className="mono">{tv`${lines} câu`}</span>
                    <span className="mono" title={tr("Ước lượng: lời dẫn 2,6 chữ mỗi giây (ít nhất 3 giây một câu), trích lời theo độ dài đoạn ghi âm")}>~{timecode(timing.total)}</span>
                    <Seg items={[["text", tr("Soạn chữ")], ["lines", tr("Theo câu")]] as const} value={lineView ? "lines" : "text"} onChange={(v) => setLineView(v === "lines")} label={tr("Cách soạn")} />
                    {dirty && <span className="flex items-center gap-1.5 text-accent"><span className="h-1.5 w-1.5 rounded-full bg-accent" />{tr("Chưa lưu")}</span>}
                    <span className="ml-auto" />
                    <Button size="sm" kind={quoting ? "ai" : "quiet"} onClick={() => setQuoting(!quoting)} title={tr("Chèn một câu người trong footage tự nói, giữ nguyên tiếng")}><Icon name="mic" size={14} />{tr("Chèn trích lời")}</Button>
                    <Button size="sm" disabled={busy || !dirty || !(text ?? "").trim()} onClick={() => run(() => post(`/api/v1/projects/${id}/script`, { lines: toSave() }, "PUT"))}>{tr("Lưu kịch bản")}</Button>
                  </div>
                  {lineView ? <ScriptLines lines={(text ?? "").split("\n")} seconds={timing.lines} focus={(k) => setSpan({ first: k, last: k })} change={(next) => setText(next.join("\n"))} />
                  : <textarea ref={editor} value={text ?? ""} onChange={(e) => setText(e.target.value)} rows={Math.max(6, (text ?? "").split("\n").length + 1)} aria-label={tr("Kịch bản")}
                            onSelect={(e) => setSpan(span_of(e.currentTarget))}
                            className="bare block w-full !rounded-none px-5 py-4 text-[15px] leading-[1.95]" placeholder={tr("Chợ Hội An buổi sáng tấp nập người mua kẻ bán.")} />}
                  {quoting && <QuotePicker insert={(hit) => {
                    const all = (text ?? "").split("\n"), at = span ? span.last + 1 : all.length;
                    all.splice(at, 0, `> ${hit.text}`); setText(all.join("\n"));
                    setQuotes({ ...quotes, [hit.text]: { asset_id: hit.asset_id, moment_id: hit.moment_id, t_in: hit.t_start, t_out: hit.t_end } }); }} close={() => setQuoting(false)} />}
                  {span && <CoWrite id={id} lines={(text ?? "").split("\n")} span={span} replace={(first, last, lines) => {
                    const all = (text ?? "").split("\n"); all.splice(first, last - first + 1, ...lines); setText(all.join("\n")); setSpan(null); }} />}
                  <form className="flex flex-wrap items-center gap-2 border-t border-line bg-ai/[0.04] px-4 py-2.5" onSubmit={(e) => e.preventDefault()}>
                    <Icon name="sparkles" size={15} className="text-ai" />
                    <label htmlFor="topic" className="sr-only">{tr("Chủ đề để viết nháp")}</label>
                    <input id="topic" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder={tr("Viết nháp từ kho footage — nhập chủ đề, ví dụ: một buổi sáng ở chợ")} className="bare h-8 min-w-0 flex-1 px-1" />
                    <Button kind="ai" size="sm" disabled={busy || !topic.trim()} onClick={() => run(async () => { const r = await post<{ lines: string[] }>(`/api/v1/projects/${id}/draft`, { topic }); if (r.lines.length) setText(r.lines.join("\n")); else setNote(tr("Mô hình không viết được câu nào. Hãy thử chủ đề khác.")); })}>{tr("Viết nháp")}</Button>
                    <Button kind={fromSpeech ? "ai" : "quiet"} size="sm" onClick={() => setFromSpeech(!fromSpeech)} title={tr("Soạn kịch bản từ lời người nói trong các bản ghi")}><Icon name="mic" size={14} />{tr("Từ lời nói…")}</Button>
                  </form>
                  {fromSpeech && <SpeechDraft id={id} topic={topic} done={async (lines) => {
                    if (dirty && (text ?? "").trim() && !(await ask(tr("Thay kịch bản đang soạn?"), { body: tr("Ô soạn có thay đổi chưa lưu; kịch bản mới sẽ thay chỗ nó."), confirm: tr("Thay") }))) return;
                    setText(lines.join("\n")); setFromSpeech(false); }} />}
                </div>
                {dirty && p.script && <p className="mt-2 text-[12.5px] text-mute">{tr("Lưu sẽ tạo phiên bản kịch bản mới; các clip đã chọn cho phiên bản cũ không áp dụng nữa.")}</p>}
                {p.script && !dirty && (
                  <div className="mt-3 rounded-xl border border-line bg-raised/30 px-4 py-3 text-[13px]">
                    <div className="flex flex-wrap items-center gap-2"><Icon name="eye" size={15} className="text-ai" /><span className="font-medium">{tr("Phản biện kịch bản")}</span>
                      <span className="text-faint">{p.script.critique == null ? tr("Chưa xin nhận xét cho phiên bản này.") : p.script.critique.length ? tv`${p.script.critique.length} điểm nên sửa` : tr("Không có điểm nào cần sửa.")}</span>
                      <span className="ml-auto flex gap-2">
                        <Button size="sm" kind="ai" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/critique`))}>{p.script.critique == null ? tr("Xin nhận xét") : tr("Nhận xét lại")}</Button>
                        {!!p.script.critique?.length && <Button size="sm" disabled={busy || !!rendering} title={tr("Tạo phiên bản kịch bản mới; clip của những câu bị đổi phải tìm lại")} onClick={() => run(async () => { const r = await post<{ revised: boolean }>(`/api/v1/projects/${id}/revise`); if (!r.revised) setNote(tr("Bản viết lại không khác bản cũ nên kịch bản được giữ nguyên.")); setText(null); })}>{tr("Viết lại theo nhận xét")}</Button>}
                      </span></div>
                    {!!p.script.critique?.length && <ul className="mt-2 grid gap-1.5">{p.script.critique.map((c, i) => (
                      <li key={i} className="flex gap-2.5"><span className="mono w-14 shrink-0 text-faint">{c.line ? tv`Câu ${c.line}` : tr("Cả bài")}</span><span className="min-w-0">{c.issue}{c.fix && <span className="text-mute"> {c.fix}</span>}</span></li>))}</ul>}
                  </div>
                )}
                {p.structure && (text ?? "").trim() && <LiveStructure segments={p.structure.segments} sections={timing.sections} loose={timing.loose} />}
                {p.script && !dirty && <Variants id={id} p={p} busy={busy} run={run} />}
                {p.script && !dirty && p.shots.length > 0 && <Illustrations shots={p.shots} busy={busy} run={run} />}
              </Section>
          </div>
          <aside className="grid gap-4 xl:sticky xl:top-0" aria-label={tr("Nguồn tham khảo")}>
              <div className={card}>
                <div><h2 className="flex items-center gap-2 text-[14px] font-semibold"><Icon name="link" size={15} className="text-mute" />{tr("Nguồn tham khảo")}<span className="mono ml-auto text-[12px] font-normal text-faint">{p.research.length}</span></h2>
                  <p className="mt-1 text-[12px] text-faint">{tr("Câu nào nêu dữ kiện thì gắn với một nguồn ở đây. Dữ kiện chưa có nguồn sẽ bị nêu ra khi kiểm tra bản dựng.")}</p></div>
                <ul className="rows empty:hidden">
                  {p.research.map((src) => (
                    <li key={src.title} className="py-2 text-[13px]"><div className="flex justify-between gap-2"><span className="min-w-0 font-medium">{/^https?:\/\//i.test(src.url) ? <a href={src.url} target="_blank" rel="noreferrer" className="underline decoration-edge underline-offset-2">{src.title}</a> : src.title}</span>
                      <button type="button" className="link shrink-0" onClick={() => { const before = p.research; patch({ research: before.filter((x) => x.title !== src.title) }); toast(tv`Đã bỏ nguồn “${src.title}”.`, { undo: () => patch({ research: before }) }); }}>{tr("Bỏ")}</button></div>
                      <p className="text-mute">{[src.publisher, src.date].filter(Boolean).join(", ")}</p>{src.passage && <p className="mt-0.5 border-l-2 border-edge pl-2 text-mute">“{src.passage}”</p>}</li>
                  ))}
                </ul>
                <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; const url = String(new FormData(f).get("url") ?? "").trim(); if (url) run(async () => { await post(`/api/v1/projects/${id}/sources/read`, { url }); f.reset(); }); }}>
                  <input name="url" type="url" aria-label={tr("Địa chỉ trang web cần đọc")} placeholder={tr("Dán địa chỉ bài viết để hệ thống đọc")} className="min-w-0 flex-1 px-3" />
                  <Button type="submit" disabled={busy} title={tr("Chỉ địa chỉ này được gửi ra ngoài máy")}><Icon name="globe" size={14} />{tr("Đọc")}</Button>
                </form>
                <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-faint"><Button size="sm" disabled={busy} title={tr("Chỉ tên dự án được gửi đi làm từ khoá tìm kiếm")} onClick={() => run(async () => { const r = await post<{ found: number }>(`/api/v1/projects/${id}/sources/find`, {}); if (!r.found) setNote(tr("Không tìm thấy bài nào trên Wikipedia cho tên dự án này.")); })}><Icon name="search" size={14} />{tr("Tự tìm nguồn")}</Button>
                  <span>{tr("Tìm trên Wikipedia theo tên dự án rồi đọc tối đa 3 bài.")}</span></div>
                {p.script && <div className="flex flex-wrap gap-2 border-t border-line pt-3">
                  <Button size="sm" kind="ai" disabled={busy} onClick={() => run(async () => { const r = await post<{ found: number }>(`/api/v1/projects/${id}/facts/find`); if (!r.found) setNote(tr("Không thấy câu nào nêu dữ kiện cần kiểm chứng.")); })}>{tr("Tìm câu nêu dữ kiện")}</Button>
                  <Button size="sm" disabled={busy || !p.shots.some((s) => s.is_fact)} title={p.shots.some((s) => s.is_fact) ? tr("So từng câu nêu dữ kiện với các nguồn ở trên") : tr("Chưa có câu nào được đánh dấu là dữ kiện")} onClick={() => run(() => post(`/api/v1/projects/${id}/facts/check`))}>{tr("Đối chiếu với nguồn")}</Button>
                  {facts.length > 0 && <p className="w-full text-[12px] text-faint">{tv`${facts.length} câu nêu dữ kiện: ${facts.filter((s) => s.fact_check?.verdict === "supported").length} có nguồn xác nhận, ${facts.filter((s) => s.fact_check?.verdict === "contradicted").length} trái nguồn, ${facts.filter((s) => !s.fact_check || s.fact_check.verdict === "not_found").length} chưa có căn cứ.`}</p>}
                </div>}
                <details className="group">
                  <summary className="flex cursor-pointer list-none items-center gap-1.5 text-[13px] text-accent"><Icon name="plus" size={14} />{tr("Tự nhập một nguồn")}</summary>
                  <form className="mt-3 grid gap-2" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const src = Object.fromEntries(["title", "publisher", "date", "url", "passage"].map((k) => [k, String(f.get(k) ?? "")])); if (!src.title.trim()) return; patch({ research: [...p.research, src] }); e.currentTarget.reset(); }}>
                    <input name="title" aria-label={tr("Tên nguồn")} placeholder={tr("Tên nguồn, ví dụ: Niên giám thống kê 2025")} className="px-3" />
                    <div className="flex gap-2"><input name="publisher" aria-label={tr("Nơi xuất bản")} placeholder={tr("Nơi xuất bản")} className="min-w-0 flex-1 px-3" /><input name="date" aria-label={tr("Ngày")} placeholder={tr("Ngày")} className="w-24 px-3" /></div>
                    <input name="url" aria-label={tr("Đường dẫn")} placeholder={tr("Đường dẫn (nếu có)")} className="px-3" />
                    <textarea name="passage" aria-label={tr("Đoạn trích")} rows={2} placeholder={tr("Đoạn trích chứng minh dữ kiện")} className="p-2.5" />
                    <div><Button type="submit">{tr("Thêm nguồn")}</Button></div>
                  </form>
                </details>
              </div>
          </aside>
        </div>
      )}


      {view === "cut" && <div className="mb-8"><EditStep projectId={id} approved={approved || !!p.script} onChanged={reload} /></div>}
      {view === "cut" && (
        <details className="group" open={!!renderReview || !!rendering}>
        <summary className="mb-4 flex cursor-pointer list-none items-center gap-2 text-[13px] text-mute hover:text-ink"><Icon name="next" size={13} className="transition-transform group-open:rotate-90" />{tr("Bản render và duyệt")}</summary>
        <div className="rise grid min-w-0 gap-10">
          {!approved && <Empty icon="check" title={tr("Duyệt clip trước khi dựng")} action={<Button kind="primary" onClick={() => goTo(`/du-an/${id}/storyboard`)}>{tr("Chọn hình trên Storyboard")}</Button>}>{tr("Khi storyboard đã được duyệt, hệ thống mới đọc lời dẫn, vẽ phụ đề và ghép thành video.")}</Empty>}
          {approved && (
            <Section title={tr("Bản dựng")} icon="play"
                     note={rendering ? <span className="text-ai">{tr("Đang dựng…")}</span> : undefined}
                     actions={<>{rendering && p.render && <div className="w-48"><StageRail stages={p.render.stages} name={(k) => stageName(k, "edit.render")} /></div>}
                       <Button size="sm" disabled={busy || previewing} title={tr("Bản nhỏ, dựng nhanh, không đọc lời dẫn mới; chỉ để xem nhịp và hình")} onClick={() => run(() => post(`/api/v1/projects/${id}/preview`))}><Icon name="bolt" size={14} />{previewing ? tr("Đang dựng bản xem thử…") : tr("Xem thử nhanh")}</Button>
                       {latest && <Button size="sm" onClick={() => { window.history.pushState({}, "", `/phong-chieu?r=${latest.render_id}`); window.dispatchEvent(new PopStateEvent("popstate")); }}><Icon name="screen" size={14} />{tr("Mở trong Phòng chiếu")}</Button>}
                       <Button size="sm" disabled={busy || !!rendering} onClick={() => run(() => post(`/api/v1/projects/${id}/render`))}><Icon name="scissors" size={14} />{latest ? tr("Dựng lại") : tr("Dựng video")}</Button></>}>
              <Command id={id} busy={busy} reload={reload} />
              {p.previews[0] && !previewing && (
                <details className="panel group mb-4 px-4 py-3">
                  <summary className="flex cursor-pointer list-none items-center gap-2 text-[13px]"><Icon name="bolt" size={14} className="text-ai" />{tr("Bản xem thử nhanh")}<span className="mono text-faint">{timecode(p.previews[0].duration)}</span>{p.previews[0].gaps > 0 && <span className="text-cue">{tv`${p.previews[0].gaps} câu thiếu hình`}</span>}<Icon name="down" size={14} className="ml-auto transition-transform group-open:rotate-180" /></summary>
                  <video key={p.previews[0].url} src={p.previews[0].url} controls className="mx-auto mt-3 max-h-[50vh] rounded-lg bg-black" />
                  <p className="mt-2 text-[12px] text-faint">{tr("Bản này nhỏ và nén mạnh để dựng cho nhanh, câu nào chưa có lời dẫn thì im lặng. Nó không dùng để duyệt hay đăng.")}</p>
                </details>
              )}
              {p.render?.status === "failed" && <p className="mb-3 text-tally">{tv`Lần dựng vừa rồi thất bại ở bước ${p.render.stages.find((s) => s.status === "failed")?.stage_key}. Xem chi tiết ở mục Tiến trình, rồi bấm dựng lại.`}</p>}
              {p.render?.status === "blocked" && <p className="mb-3 text-cue">{tr("Việc dựng đang dừng và cần bạn xử lý. Xem ở mục Tiến trình.")}</p>}
              {!latest && !rendering && <Empty icon="scissors" title={tr("Sẵn sàng dựng")}>{tr("Các clip đã được duyệt. Bấm Dựng video để hệ thống đọc lời dẫn, vẽ phụ đề và ghép cảnh.")}</Empty>}
              {latest && (
                <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
                  <div className="panel overflow-hidden bg-black p-0 xl:sticky xl:top-0">
                    <video ref={cut} key={latest.url} src={latest.url} controls className={`w-full bg-black ${latest.qc.format === "portrait" ? "mx-auto aspect-[9/16] max-h-[70vh] w-auto" : latest.qc.format === "square" ? "mx-auto aspect-square max-h-[70vh] w-auto" : "aspect-video max-h-[62vh]"}`} />
                  </div>
                  <div className="grid min-w-0 content-start gap-4">
                    {latest.qc.external && <p className="panel px-4 py-3 text-[13px] text-mute">{tr("Bản này được hoàn thiện ở phần mềm khác rồi nhập vào. Kiểm tra bên dưới đo trên chính file đó.")}</p>}
                    {latest.qc.draft && <p className="cue-card px-4 py-3 text-[13px] text-cue">{tr("Bản nháp: một số cảnh được cắt từ bản xem vì không tìm thấy file gốc. Cắm lại ổ chứa footage rồi dựng lại để có bản cuối.")}</p>}
                    <div className="panel overflow-hidden">
                      <p className="eyebrow flex items-center justify-between border-b border-line px-4 py-2.5"><span>{tr("Kiểm tra chất lượng")}</span><Tag tone={latest.qc.passed ? "proof" : "tally"}>{latest.qc.passed ? tr("Đạt") : tr("Không đạt")}</Tag></p>
                      <div className="rows">
                        {Object.entries(latest.qc.checks).map(([name, ok]) => <p key={name} className="flex items-center justify-between gap-3 px-4 py-2 text-[13px]"><span>{name}</span><span className={`flex items-center gap-1 ${ok ? "text-proof" : "text-tally"}`}><Icon name={ok ? "check" : "x"} size={14} />{ok ? tr("Đạt") : tr("Không đạt")}</span></p>)}
                        {latest.qc.gaps > 0 && <p className="flex items-center justify-between gap-3 px-4 py-2 text-[13px]"><span>{tr("Câu dùng nền trơn vì thiếu hình")}</span><span className="mono text-cue">{latest.qc.gaps}</span></p>}
                      </div>
                    </div>
                    {(latest.qc.findings ?? []).length > 0 && (
                      <div className="ai-card overflow-hidden">
                        <p className="eyebrow flex items-center gap-2 border-b border-ai/15 px-4 py-2.5 !text-ai"><Icon name="sparkles" size={13} />{tr("Nên xem lại")}</p>
                        <ul className="rows">
                          {(latest.qc.findings ?? []).map((f, i) => (
                            <li key={i} className="px-4 py-2.5 text-[13px]"><p><span className={f.severity === "cao" ? "font-medium text-cue" : "font-medium"}>{tv`Câu ${f.shot}, ${f.check.toLowerCase()}:`}</span> {f.text}</p><p className="text-mute">{f.fix}</p></li>
                          ))}
                        </ul>
                      </div>
                    )}
                    {!latest.qc.external && (
                      <div className="panel px-4 py-3 text-[13px]">
                        <div className="flex flex-wrap items-center gap-2"><Icon name="eye" size={15} className="text-ai" /><span className="font-medium">{tr("Xem lại như người xem")}</span>
                          <span className="text-faint">{latest.qc.viewer ? tv`Đã xem ${latest.qc.viewer.judged} trên ${latest.qc.viewer.of} cảnh có hình` : tr("Mô hình nhìn từng cảnh của bản dựng và so với lời dẫn.")}</span>
                          <span className="ml-auto"><Button size="sm" kind="ai" disabled={busy} onClick={() => run(() => post(`/api/v1/renders/${latest.render_id}/watch`))}>{latest.qc.viewer ? tr("Xem lại") : tr("Xem")}</Button></span></div>
                        {latest.qc.viewer && (latest.qc.viewer.findings.length ? <ul className="mt-2 grid gap-1.5">{latest.qc.viewer.findings.map((f, i) => <li key={i}><span className={f.severity === "cao" ? "font-medium text-cue" : "font-medium"}>{tv`Câu ${f.shot}, ${f.check.toLowerCase()}:`}</span> {f.text} <span className="text-mute">{f.fix}</span></li>)}</ul>
                          : latest.qc.viewer.judged === 0 ? <p className="mt-2 text-cue">{tr("Mô hình không trả lời được cho cảnh nào, nên chưa có nhận xét.")}</p>
                          : <p className="mt-2 text-proof">{tr("Không thấy cảnh nào lệch với lời dẫn")}{latest.qc.viewer.judged < latest.qc.viewer.of ? tv`, trong ${latest.qc.viewer.judged} cảnh mô hình xem được` : ""}.</p>)}
                      </div>
                    )}
                    {renderReview && (
                      <div className="cue-card p-4">
                        <label htmlFor="why" className={field}>{tr("Ghi chú nếu chưa được")}</label>
                        <textarea id="why" value={why} onChange={(e) => setWhy(e.target.value)} rows={2} placeholder={tr("Ví dụ: 0:07 cảnh xay cà phê bị tối, đổi cảnh khác")} className="mb-3 w-full p-2.5" />
                        <div className="flex flex-wrap gap-2">
                          <Button onClick={() => setWhy(`${why}${why && !why.endsWith(" ") ? " " : ""}${timecode(cut.current?.currentTime ?? 0)} `)}><Icon name="clock" size={14} />{tr("Ghi mốc đang xem")}</Button>
                          <Button kind="primary" disabled={busy} onClick={() => run(() => post(`/api/v1/projects/${id}/render/decision`, { approve: true }))}><Icon name="check" size={14} />{tr("Duyệt bản dựng")}</Button>
                          <Button disabled={busy} onClick={() => run(async () => { await post(`/api/v1/projects/${id}/render/decision`, { approve: false, comment: why }); setWhy(""); })}>{tr("Chưa được, dựng lại")}</Button>
                        </div>
                      </div>
                    )}
                    {p.render?.status === "succeeded" && <div className="flex flex-wrap items-center gap-3 rounded-xl border border-proof/30 bg-proof/[0.06] px-4 py-3"><Icon name="check" className="text-proof" /><span className="flex-1 text-proof">{tr("Bạn đã duyệt bản dựng này.")}</span><Button size="sm" kind="primary" onClick={() => setView("publish")}>{tr("Sang bước Xuất bản")}<Icon name="next" size={14} /></Button></div>}
                    <Finishing id={id} render={latest} format={p.format} run={run} />
                    <p className="text-[13px]"><a className="inline-flex items-center gap-1.5 text-ink underline decoration-edge underline-offset-4 hover:decoration-mute" href={`/api/v1/renders/${latest.render_id}/edl`} download><Icon name="download" size={14} />{tr("Tải danh sách cắt (EDL)")}</a> <span className="text-mute">{tr("hoặc")}</span> <a className="text-ink underline decoration-edge underline-offset-4 hover:decoration-mute" href={`/api/v1/renders/${latest.render_id}/otio`} download>OpenTimelineIO</a> <span className="text-mute">{tr("để dựng tiếp trong DaVinci Resolve từ file gốc")}</span></p>
                    <Lineage renderId={latest.render_id} />
                    {p.renders.length > 1 && (
                      <details className="panel group px-4 py-3">
                        <summary className="flex cursor-pointer list-none items-center justify-between text-[13px] text-mute hover:text-ink">{tv`Các bản dựng trước (${p.renders.length - 1})`}<Icon name="down" size={14} className="transition-transform group-open:rotate-180" /></summary>
                        <ul className="rows mt-2">
                          {p.renders.slice(1).map((r) => (
                            <li key={r.render_id} className="flex items-start gap-3 py-2 text-[13px]"><span className="min-w-0 flex-1"><a className="mono link" href={r.url} target="_blank" rel="noreferrer">{new Date(r.created_at * 1000).toLocaleString(locale)}</a>
                              <span className="text-mute">{tv`, dài ${timecode(r.qc.duration)}${r.review ? (r.review.approved ? tr(", đã duyệt") : tr(", không duyệt")) : ""}`}</span>
                              {r.review?.comment && <p className="text-mute">{tv`Ghi chú: ${r.review.comment}`}</p>}</span>
                              <button type="button" className="link shrink-0" disabled={busy} onClick={async () => { if (await ask(tr("Xoá bản dựng này?"), { body: tr("File được chuyển vào Thùng rác của máy. Bản đã đăng thì không xoá được."), confirm: tr("Xoá bản dựng"), danger: true })) run(() => call(`/api/v1/renders/${r.render_id}`, { method: "DELETE" })); }}>{tr("Xoá")}</button></li>
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
        </details>
      )}

      {view === "publish" && (
        <div className="rise grid max-w-4xl gap-6">
          {latest && p.render?.status === "succeeded" ? <PackagePanel render={latest} reload={reload} />
            : <Empty icon="globe" title={tr("Duyệt bản dựng trước khi xuất bản")} action={latest ? <Button kind="primary" onClick={() => setView("cut")}>{tr("Xem bản dựng")}</Button> : undefined}>{tr("Gói xuất bản gồm video, phụ đề rời, ảnh đại diện và kiểm tra bản quyền; nó chỉ được tạo từ một bản dựng bạn đã duyệt.")}</Empty>}
        </div>
      )}

      {settings && (
        <Drawer title={tr("Thiết lập dự án")} close={() => setSettings(false)}>
            <div className="grid gap-5">
              <form onSubmit={(e) => { e.preventDefault(); const v = String(new FormData(e.currentTarget).get("name") ?? "").trim(); if (v && v !== p.title) patch({ title: v }); }}>
                <label htmlFor="project-name" className={field}>{tr("Tên dự án")}</label>
                <div className="mt-1.5 flex gap-2"><input id="project-name" name="name" defaultValue={p.title} key={p.title} className="h-9 min-w-0 flex-1 px-3"
                  onBlur={(e) => { const v = e.target.value.trim(); if (v && v !== p.title) patch({ title: v }); else e.target.value = p.title; }} />
                  <Button size="sm" type="submit" disabled={busy}>{tr("Lưu")}</Button></div>
              </form>
              <div>
                <label htmlFor="template" className={field}>{tr("Mẫu định dạng")}</label>
                <select id="template" value={p.template ?? ""} disabled={busy} onChange={(e) => e.target.value && run(() => post(`/api/v1/projects/${id}/template`, { name: e.target.value }))} className="w-full pl-2.5">
                  <option value="">{tr("Chưa dùng mẫu")}</option>{(prefs?.templates ?? []).map((t) => <option key={t.name}>{t.name}</option>)}
                </select>
                <p className="mt-1.5 text-[12px] text-faint">{tr("Mẫu đặt sẵn khung hình, giọng đọc, mức nhạc và cách duyệt. Sửa mẫu ở mục Hệ thống.")}</p>
              </div>
              <div>
                <p className={field} id="format-label">{tr("Khung hình")}</p>
                <div className="seg w-full" role="radiogroup" aria-labelledby="format-label">
                  {Object.entries(FORMATS).map(([key, label]) => (
                    <button key={key} type="button" role="radio" aria-checked={p.format === key} disabled={busy} onClick={() => patch({ format: key })} className="flex-1">{label}</button>
                  ))}
                </div>
              </div>
              <form onSubmit={(e) => { e.preventDefault(); patch({ music_path: (music ?? "").trim() || null }); }}>
                <label htmlFor="music" className={field}>{tr("Nhạc nền")}</label>
                <div className="flex gap-2">
                  <input id="music" list="tracks" value={music ?? p.music_path ?? ""} onChange={(e) => setMusic(e.target.value)} placeholder={tr("Chọn trong thư viện hoặc dán đường dẫn")} className="min-w-0 flex-1 px-3" />
                  <Button disabled={busy || music === null || (music ?? "") === (p.music_path ?? "")} onClick={() => patch({ music_path: (music ?? "").trim() || null })}>{tr("Lưu")}</Button>
                </div>
                <datalist id="tracks">{tracks.map((a) => <option key={a.asset_id} value={a.path}>{`${a.name}, ${timecode(a.duration)}`}</option>)}</datalist>
                <p className="mt-1.5 text-[12px] text-faint">{tr("Nhạc tự nhỏ lại khi có lời dẫn.")}</p>
                <MusicIdeas id={id} choose={(path) => patch({ music_path: path })} />
              </form>
              <form onSubmit={(e) => { e.preventDefault(); patch({ narration_dir: (takes ?? "").trim() || null }); }}>
                <label htmlFor="takes" className={field}>{tr("Lời dẫn bạn tự thu")}</label>
                <div className="flex gap-2">
                  <input id="takes" value={takes ?? p.narration_dir ?? ""} onChange={(e) => setTakes(e.target.value)} placeholder={tr("Thư mục chứa 1.wav, 2.m4a")} className="min-w-0 flex-1 px-3" />
                  <Button disabled={busy || takes === null || (takes ?? "") === (p.narration_dir ?? "")} onClick={() => patch({ narration_dir: (takes ?? "").trim() || null })}>{tr("Lưu")}</Button>
                </div>
                <p className="mt-1.5 text-[12px] text-faint">{!p.narration_dir ? tr("Đặt tên file theo số câu. Câu nào không có file thì dùng giọng máy.") : p.own_takes.length ? tv`Đã có bản thu cho câu ${p.own_takes.join(", ")}. Các câu còn lại dùng giọng máy.` : tr("Chưa thấy file thu âm nào trong thư mục này.")}</p>
              </form>
              <div className="grid gap-2">
                {p.music_path && <label className="flex items-start gap-2.5 text-[13px]"><input type="checkbox" className="mt-0.5" checked={!!p.options.music_cleared} disabled={busy} onChange={(e) => patch({ options: { music_cleared: e.target.checked } })} />
                  <span>{tr("Tôi có quyền dùng bản nhạc này")}<span className="block text-[12px] text-faint">{tr("Chưa xác nhận thì video không được đóng gói để đăng.")}</span></span></label>}
                {p.remote.length > 0 && <label className="flex items-start gap-2.5 text-[13px]"><input type="checkbox" className="mt-0.5" checked={!!p.options.footage_may_leave} disabled={busy} onChange={(e) => patch({ options: { footage_may_leave: e.target.checked } })} />
                  <span>{tr("Cho gửi footage của tôi lên RunPod")}<span className="block text-[12px] text-faint">{tr("Chỉ áp dụng cho các cảnh bạn bật khớp khẩu hình hoặc phóng to bằng mô hình ở dự án này. Tắt thì chỉ hình sinh bằng AI mới được gửi. Chế độ riêng tư luôn chặn.")}</span></span></label>}
                <label className="flex items-start gap-2.5 text-[13px]"><input type="checkbox" className="mt-0.5" checked={!!p.options.clean_audio} disabled={busy} onChange={(e) => patch({ options: { clean_audio: e.target.checked } })} />
                  <span>{tr("Làm sạch âm thanh")}<span className="block text-[12px] text-faint">{tr("Giảm tiếng ù và tiếng xì ở lời tự thu và âm thanh gốc.")}</span></span></label>
                <label className="flex items-start gap-2.5 text-[13px]"><input type="checkbox" className="mt-0.5" checked={!!p.options.match_colour} disabled={busy} onChange={(e) => patch({ options: { match_colour: e.target.checked } })} />
                  <span>{tr("Cân màu giữa các cảnh")}<span className="block text-[12px] text-faint">{tr("Kéo độ sáng và tương phản của từng cảnh về cùng một mức.")}</span></span></label>
              </div>
              <ColourPairs id={id} />
              {channels.length > 0 && <div><label htmlFor="channel" className={field}>{tr("Kênh")}</label>
                <select id="channel" value={p.channel ?? ""} disabled={busy} onChange={(e) => patch({ channel: e.target.value })} className="mt-1.5 h-9 w-full pl-2.5"><option value="">{tr("Chưa thuộc kênh nào")}</option>{channels.map((c) => <option key={c.name}>{c.name}</option>)}</select></div>}
              <div><label htmlFor="due" className={field}>{tr("Ngày dự định đăng")}</label>
                <input id="due" type="date" defaultValue={p.due_date ?? ""} key={p.due_date ?? "none"} onChange={(e) => patch({ due_date: e.target.value })} className="mono mt-1.5 h-9 w-full px-3" /></div>
              <label className="flex items-start gap-2.5 rounded-lg border border-line bg-raised/50 p-3"><input type="checkbox" className="mt-0.5" checked={p.auto_accept} disabled={busy} onChange={(e) => patch({ auto_accept: e.target.checked ? 1 : 0 })} />
                <span className="text-[13px]">{tr("Tự duyệt clip")}<span className="block text-[12px] text-faint">{tr("Chỉ khi mọi câu đều có clip và mô hình chấm chắc chắn.")}</span></span></label>
              <div className="grid gap-2 rounded-lg border border-line bg-raised/50 p-3">
                <div className="flex flex-wrap items-center gap-3">
                  <p className="min-w-0 flex-1 text-[12.5px] text-mute">{tr("Nhân bản: một dự án mới cùng kịch bản, cùng các clip đã chọn và cùng khung hình.")}</p>
                  <Button size="sm" disabled={busy} onClick={() => run(async () => { const r = await post<Project>(`/api/v1/projects/${id}/duplicate`); setSettings(false); toast(tv`Đã tạo “${r.title}”.`); window.history.pushState(null, "", `/du-an/${r.project_id}`); window.dispatchEvent(new PopStateEvent("popstate")); })}><Icon name="copy" size={14} />{tr("Nhân bản")}</Button>
                </div>
                <div className="flex flex-wrap items-center gap-3 border-t border-line pt-2">
                  <p className="min-w-0 flex-1 text-[12.5px] text-mute">{tr("Chuyển vào thùng rác: dự án biến khỏi mọi danh sách nhưng khôi phục được trong 30 ngày. Footage trong thư viện không bị ảnh hưởng.")}</p>
                  <Button size="sm" disabled={busy} onClick={async () => { if (await trashProject(p)) { setSettings(false); back(p.production ? `/du-an/${p.production.production_id}` : undefined); } }}><Icon name="trash" size={14} />{tr("Chuyển vào thùng rác")}</Button>
                </div>
              </div>
            </div>
        </Drawer>
      )}
    </Page>
  );
}

const SIZES: [string, string][] = [["wide shot", tr("Toàn cảnh")], ["medium shot", tr("Trung cảnh")], ["close-up", tr("Cận cảnh")], ["extreme close-up", tr("Đặc tả")]];
const MOVES: [string, string][] = [["slow push in", tr("Đẩy vào chậm")], ["slow pull out", tr("Kéo ra chậm")], ["pan left", tr("Lia trái")], ["pan right", tr("Lia phải")], ["static", tr("Đứng yên")]];

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
            {g ? <><span>{g.provider}</span><span className="mono">seed {g.seed}</span></> : <span>{tr("Chưa sinh ảnh")}</span>}
            {q && <span className={q.score >= 6 ? "text-proof" : "text-cue"} title={q.issues.join(", ") || tr("Không thấy lỗi")}>{q.score}/10{q.tries > 1 ? tv`, chọn từ ${q.tries} lần` : ""}</span>}
            {shot.gen.attempt ? <span className="text-ai">{tr("đã yêu cầu ảnh khác")}</span> : null}
          </p>
        </div>
      </div>
      <details className="mt-1.5 text-[12px]">
        <summary className="cursor-pointer list-none text-accent">{tr("Sửa ảnh này")}</summary>
        <div className="mt-2 grid gap-2">
          <input defaultValue={shot.gen.subject ?? ""} onBlur={(e) => e.target.value !== (shot.gen.subject ?? "") && set({ subject: e.target.value })} aria-label={tv`Hình cần sinh cho câu ${n}`} placeholder={tr("Hình cần sinh (để trống thì dùng lời dẫn)")} className="h-8 px-2.5" />
          <div className="grid grid-cols-2 gap-2">
            <select aria-label={tr("Cỡ cảnh")} value={shot.gen.shot_size ?? "medium shot"} onChange={(e) => set({ shot_size: e.target.value })} className="h-8 pl-2">{SIZES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            <select aria-label={tr("Chuyển động máy")} value={shot.gen.camera ?? "slow push in"} onChange={(e) => set({ camera: e.target.value })} className="h-8 pl-2">{MOVES.map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
            {providers.image_providers.length > 1 && <select aria-label={tr("Nơi sinh ảnh")} value={shot.gen.provider_image ?? ""} onChange={(e) => set({ provider_image: e.target.value })} className="h-8 pl-2"><option value="">{tr("Ảnh: theo thứ tự chung")}</option>{providers.image_providers.map((x) => <option key={x.name} value={x.name}>{tv`Ảnh: ${x.label}`}</option>)}</select>}
            {providers.video_providers.length > 1 && <select aria-label={tr("Nơi sinh video")} value={shot.gen.provider_video ?? ""} onChange={(e) => set({ provider_video: e.target.value })} className="h-8 pl-2"><option value="">{tr("Video: theo thứ tự chung")}</option>{providers.video_providers.map((x) => <option key={x.name} value={x.name}>Video: {x.label}</option>)}</select>}
          </div>
          {g && <div className="flex items-center gap-2"><Button size="sm" onClick={() => post(`/api/v1/shots/${shot.shot_id}/variation`).then(changed)}>{tr("Xin ảnh khác")}</Button><span className="text-faint">{tr("Bấm “Sinh lại” ở trên để áp dụng. Ảnh của các câu khác được giữ nguyên.")}</span></div>}
          {g && <p className="mono break-words rounded bg-overlay p-2 text-[11px] leading-relaxed text-mute">{g.prompt}</p>}
        </div>
      </details>
    </li>
  );
}

const KIND: Record<string, string> = { character: tr("Nhân vật"), setting: tr("Bối cảnh"), prop: tr("Đồ vật"), style: tr("Phong cách") };
/** How the project's characters, places and look are described, so that every shot shows them the same way. */
function Bible({ entries, save, images = [], train }: { entries: BibleEntry[]; save: (b: BibleEntry[]) => void; images?: Asset[]; train?: (name: string, assets: string[]) => void }) {
  const sets = [...new Set(images.flatMap((a) => a.collections))].sort();
  return (
    <div className="border-t border-line pt-3">
      <h3 className="flex items-center gap-2 text-[13px] font-semibold"><Icon name="user" size={14} className="text-mute" />{tr("Nhân vật và bối cảnh")}<span className="mono ml-auto text-[12px] font-normal text-faint">{entries.length}</span></h3>
      <p className="mt-1 text-[12px] text-faint">{tr("Câu nào nhắc tới tên ở đây thì ảnh của câu đó được tả đúng như mô tả này. Mục “Phong cách” áp dụng cho mọi ảnh.")}</p>
      <ul className="rows mt-2 empty:hidden">
        {entries.map((e) => (
          <li key={e.name} className="flex gap-2 py-1.5 text-[12.5px]"><span className="min-w-0 flex-1"><span className="font-medium">{e.name}</span><span className="ml-1.5 text-faint">{KIND[e.kind]}{e.voice ? tv`, giọng ${e.voice}` : ""}</span><span className="block text-mute">{e.description}</span></span>
            <span className="flex shrink-0 flex-col items-end gap-1">
              <button type="button" className="link" onClick={() => { save(entries.filter((x) => x.name !== e.name)); toast(tv`Đã bỏ “${e.name}” khỏi hồ sơ.`, { undo: () => save(entries) }); }}>{tr("Bỏ")}</button>
              {e.kind === "character" && (e.model ? <span className="text-[11.5px] text-proof">{tr("đã có mô hình riêng")}</span> : e.training?.status === "queued" ? <span className="text-[11.5px] text-ai">{tr("đang huấn luyện")}</span>
                : train && sets.length > 0 && <select aria-label={tv`Huấn luyện mô hình cho ${e.name} từ bộ sưu tập`} value="" onChange={(ev) => ev.target.value && train(e.name, images.filter((a) => a.collections.includes(ev.target.value)).map((a) => a.asset_id))} className="h-7 max-w-[150px] pl-1.5 text-[11.5px]">
                    <option value="">{tr("Huấn luyện từ…")}</option>{sets.map((g) => <option key={g} value={g}>{tv`${g} (${images.filter((a) => a.collections.includes(g)).length} ảnh)`}</option>)}</select>)}
            </span></li>))}
      </ul>
      <form className="mt-2 grid gap-2" onSubmit={(ev) => { ev.preventDefault(); const f = new FormData(ev.currentTarget); const name = String(f.get("name") ?? "").trim(); if (!name) return;
        save([...entries.filter((x) => x.name !== name), { name, kind: String(f.get("kind")) as BibleEntry["kind"], description: String(f.get("description") ?? ""), voice: String(f.get("voice") ?? "").trim() || null, asset_id: null }]); ev.currentTarget.reset(); }}>
        <div className="flex gap-2"><input name="name" aria-label={tr("Tên")} placeholder={tr("Tên, ví dụ: Mít")} className="h-8 min-w-0 flex-1 px-2.5" />
          <select name="kind" aria-label={tr("Loại")} className="h-8 pl-2">{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
        <input name="description" aria-label={tr("Mô tả")} placeholder={tr("Mô tả bằng tiếng Anh cho mô hình: an orange tabby cat with a white chest")} className="h-8 px-2.5" />
        <input name="voice" aria-label={tr("Giọng đọc của nhân vật")} placeholder={tr("Giọng đọc riêng (tuỳ chọn). Câu viết “Tên: lời thoại” sẽ dùng giọng này")} className="h-8 px-2.5" />
        <div><Button size="sm" type="submit">{tr("Thêm")}</Button></div>
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
      <div className="flex flex-wrap items-center gap-2"><Icon name="image" size={15} className="text-cue" /><span className="font-semibold">{tv`${data.gaps.length} câu chưa có hình`}</span>
        <a href={`/api/v1/projects/${id}/shotlist`} className="ml-auto flex items-center gap-1.5 rounded-lg border border-edge px-2.5 py-1.5 text-[12.5px] hover:border-accent hover:text-accent" download><Icon name="download" size={14} />{tr("Tải danh sách cần quay")}</a></div>
      <ul className="mt-3 grid gap-3">
        {data.gaps.map((g) => (
          <li key={g.shot_id} className="grid gap-1.5">
            <p><span className="mono mr-2 text-faint">{tv`Câu ${g.line}`}</span>{g.text}<span className="ml-2 text-faint">{tv`cần ${g.seconds.toFixed(0)} giây`}</span></p>
            {g.near && <p className="text-[12.5px] text-mute">{tv`Gần nhất trong kho (${Math.round(g.near.score * 100)}%): ${g.near.text.slice(0, 140)}`}</p>}
            <div className="flex flex-wrap gap-2">
              {g.ways.some((w) => w.way === "stock") && <Button size="sm" onClick={() => run(async () => { await post(`/api/v1/shots/${g.shot_id}/stock`, { query: g.brief || g.text }); })}>{tr("Tìm clip stock")}</Button>}
              {g.ways.filter((w) => w.way === "reword" || w.way === "shoot" || w.way === "generate").map((w) => <span key={w.way} className="rounded-md border border-line bg-raised/50 px-2 py-1 text-[12px] text-mute">{w.text}</span>)}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

type Filter = "all" | "active" | "waiting" | "done";
const FILTERS: [Filter, string][] = [["all", tr("Tất cả")], ["active", tr("Đang làm")], ["waiting", tr("Chờ bạn")], ["done", tr("Đã xong")]];

/** Videos as cards (or rows): each its frames, where it stands, what is next, a way to the Trash. */
function VideoCards({ list, view, go, working, reload }: { list: Project[]; view: "grid" | "list"; go: (to: string) => void; working: Map<string, AgentTask>; reload: () => void }) {
  const remove = async (p: Project) => { await trashProject(p); reload(); };
  const bin = (p: Project, cls: string) => <button type="button" onClick={() => remove(p)} aria-label={tv`Xoá video ${p.title}`} title={tr("Xoá video")}
    className={`grid h-8 w-8 place-items-center rounded-md border border-line bg-surface/80 text-mute backdrop-blur transition hover:border-tally/50 hover:text-tally ${cls}`}><Icon name="trash" size={15} /></button>;
  const shown = list;
  return (
    <>
      {view === "grid" ? (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {shown.map((p) => {
            const st = projectState(p); const task = working.get(p.project_id); const latest = p.renders[0]; const nx = projectNext(p);
            const to = nx ? `/du-an/${p.project_id}?tab=${nx.tab}` : `/du-an/${p.project_id}`;
            return (
              <li key={p.project_id} className="group/card relative"><a href={to} onClick={(e) => { e.preventDefault(); go(to); }}
                 className="panel group block overflow-hidden transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-edge">
                <div className="relative"><Filmstrip shots={p.shots} height={150} />
                  <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-surface via-surface/10 to-transparent" />
                  <span className="absolute left-2.5 top-2.5 rounded-full bg-black/55 backdrop-blur"><Tag tone={st.tone}>{st.label}</Tag></span>
                  {latest && <span className="chip mono absolute right-2.5 top-2.5"><Icon name="play" size={11} />{timecode(latest.qc.duration)}</span>}
                  {task && <span className="chip absolute bottom-2.5 left-2.5 !text-ai"><Icon name="sparkles" size={12} />{tr("Trợ lý đang làm")}</span>}
                </div>
                <div className="px-4 pb-4 pt-1.5">
                  <p className="display truncate text-[15.5px] leading-snug">{p.title}</p>
                  <p className="mt-0.5 flex gap-3 truncate text-[12.5px] text-mute"><span>{p.shots.length ? tv`${p.shots.length} câu` : tr("Chưa có kịch bản")}</span><span>{FORMATS[p.format] ?? p.format}</span></p>
                  {nx && !task && <p className={`mt-2 flex items-center gap-1.5 truncate text-[12.5px] ${nx.you ? "text-cue" : "text-faint"}`}><Icon name={nx.you ? "next" : "clock"} size={13} />{nx.text}</p>}
                  <div className="mt-3 flex items-center justify-between pr-10"><Steps step={st.step} tone={st.tone} /><span className="mono text-[11px] text-faint">{new Date(p.created_at * 1000).toLocaleDateString(locale)}</span></div>
                </div>
              </a>{bin(p, "absolute bottom-3 right-3")}</li>
            );
          })}
        </ul>
      ) : (
        <ul className="panel rows overflow-hidden">
          {shown.map((p) => {
            const st = projectState(p); const task = working.get(p.project_id); const latest = p.renders[0]; const nx = projectNext(p);
            const to = nx ? `/du-an/${p.project_id}?tab=${nx.tab}` : `/du-an/${p.project_id}`;
            return (
              <li key={p.project_id} className="group/card relative">
                <a href={to} onClick={(e) => { e.preventDefault(); go(to); }}
                   className="grid items-center gap-x-6 gap-y-3 p-3 transition-colors hover:bg-white/[0.02] sm:grid-cols-[220px_minmax(0,1fr)_auto]">
                  <Filmstrip shots={p.shots} height={56} className="rounded-md" />
                  <div className="min-w-0">
                    <p className="truncate text-[15px] font-medium">{p.title}</p>
                    <p className="truncate text-[13px] text-mute">{p.shots.length ? tv`${p.shots.length} câu` : tr("Chưa có kịch bản")}, {FORMATS[p.format] ?? p.format}{latest ? <span className="mono">, {timecode(latest.qc.duration)}</span> : ""}{task ? <span className="text-ai">{tr(", trợ lý đang làm")}</span> : ""}</p>
                    {nx && !task && <p className={`mt-0.5 flex items-center gap-1.5 truncate text-[12.5px] ${nx.you ? "text-cue" : "text-faint"}`}><Icon name={nx.you ? "next" : "clock"} size={13} />{nx.text}</p>}
                  </div>
                  <div className="flex items-center gap-4 sm:justify-end sm:pr-12"><Steps step={st.step} tone={st.tone} /><span className="sm:w-40 sm:text-right"><Tag tone={st.tone}>{st.label}</Tag></span></div>
                </a>{bin(p, "absolute right-3 top-3 sm:top-1/2 sm:-translate-y-1/2")}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}

const MISSION_STATUS: Record<string, [string, "mute" | "cue" | "accent" | "ai" | "proof" | "tally"]> = {
  draft: [tr("Nháp"), "mute"], planned: [tr("Chờ xác nhận"), "cue"], queued: [tr("Trong hàng đợi"), "accent"], running: [tr("Đang chạy"), "ai"],
  awaiting_approval: [tr("Chờ bạn duyệt"), "cue"], completed: [tr("Hoàn thành"), "proof"], blocked: [tr("Bị chặn"), "tally"], failed: [tr("Lỗi"), "tally"],
  cancelled: [tr("Đã huỷ"), "mute"], partially_completed: [tr("Xong một phần"), "cue"], paused: [tr("Tạm dừng"), "mute"],
};

/** The missions given for a production, newest first: what each is doing, opened in Mission Control. */
function GivenMissions({ list, production, go }: { list: ProductionMission[]; production: string; go: (to: string) => void }) {
  const open = list.filter((m) => !["completed", "partially_completed", "failed", "cancelled"].includes(m.status)).length;
  return (
    <Section title={tr("Nhiệm vụ đã giao")} icon="bolt" note={open ? tv`${open} đang mở · ${list.length} tất cả` : tv`${list.length} nhiệm vụ`}
             actions={<button type="button" className="link text-[12.5px]" onClick={() => go(`/phong-may?tab=missions&prd=${production}`)}>{tr("Xem trong Mission Control")}</button>}>
      <ul className="grid max-w-4xl gap-2">{list.slice(0, 6).map((m) => {
        const [label, tone] = MISSION_STATUS[m.status] ?? [m.status, "mute"];
        return (
          <li key={m.mission_id}><button type="button" onClick={() => go(`/phong-may?tab=missions&nv=${m.mission_id}`)} className="tile flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 text-left">
            <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px]">{m.title || m.text}</span>
              <span className="block truncate text-[12px] text-faint">{m.kind_name ?? tr("Chưa rõ loại việc")} · {new Date(m.created_at * 1000).toLocaleDateString(locale)}{m.count ? ` · ${tv`${m.done}/${m.count} xong`}` : ""}</span></span>
            {m.spent > 0 && <span className="mono text-[12px] text-faint">${m.spent.toFixed(2)}</span>}
            <Tag tone={tone}>{label}</Tag></button></li>);
      })}</ul>
    </Section>
  );
}

/** A production: its videos, what they share, a way to add a video or hand work to the machine; removed once empty. */
function ProductionPage({ id, go }: { id: string; go: (to: string) => void }) {
  const { data, reload } = usePoll<Production & { projects: Project[] }>(`/api/v1/productions/${id}`, 5000);
  const { data: chan } = usePoll<{ channels: Channel[] }>("/api/v1/channels", 60000);
  const { data: settings } = usePoll<{ templates: Template[]; voices: string[] }>("/api/v1/settings", 60000);
  const { data: agent } = usePoll<{ tasks: AgentTask[] }>("/api/v1/agent/tasks", 6000);
  const [mode, setMode] = useState<"none" | "new" | "mission" | "shared">("none"), [title, setTitle] = useState(""), [format, setFormat] = useState("landscape");
  const [ask_, setAsk] = useState(""), [busy, setBusy] = useState(false), [note, setNote] = useState<string | null>(null);
  const [view, setView] = useState<"grid" | "list">(() => { try { return (localStorage.getItem("nx.projects.view") as "grid" | "list") ?? "grid"; } catch { return "grid"; } });
  if (!data) return <Page title={tr("Đang mở dự án…")} side={<ProjectSide production={id} />}><SkeletonCards count={3} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" /></Page>;
  const working = new Map((agent?.tasks ?? []).filter((t) => t.status === "working" || t.status === "waiting_operator").map((t) => [t.project_id, t]));
  const act = async (fn: () => Promise<unknown>) => { setBusy(true); setNote(null); try { await fn(); } catch (e) { setNote((e as Error).message); } setBusy(false); reload(); };
  const change = (body: Partial<Production>) => act(() => post(`/api/v1/productions/${id}`, body, "PATCH"));
  const addVideo = () => act(async () => { const p = await post<Project>("/api/v1/projects", { title: title.trim(), format, production_id: id }); setTitle(""); setMode("none"); go(`/du-an/${p.project_id}`); });
  const mission = () => act(async () => { const m = await post<{ mission_id: string }>("/api/v1/missions", { text: ask_.trim(), production_id: id }); setAsk(""); go(`/phong-may?tab=missions&nv=${m.mission_id}`); });
  const states = data.projects.map(bucket);
  const toggle = (m: typeof mode) => setMode(mode === m ? "none" : m);
  return (
    <Page title={data.title} back={{ label: tr("Dự án"), onClick: () => go("/du-an") }} side={<ProjectSide production={id} />}
          note={<Slate state={<Tag tone="accent">{tv`${data.projects.length} video`}</Tag>} items={[[String(states.filter((x) => x === "active").length), tr("đang làm")], [String(states.filter((x) => x === "waiting").length), tr("chờ bạn")], [String(states.filter((x) => x === "done").length), tr("đã xong")]]}
                      extra={<>{data.channel && <span className="mr-3">{data.channel}</span>}{data.template && <span>{data.template}</span>}</>} />}
          actions={<><Button kind="quiet" onClick={() => toggle("shared")}><Icon name="sliders" />{tr("Dùng chung")}</Button><Button kind="ai" onClick={() => toggle("mission")}><Icon name="sparkles" />{tr("Giao việc")}</Button>
                     <Button kind="primary" onClick={() => toggle("new")}><Icon name="plus" />{tr("Thêm video")}</Button></>}>
      {note && <p className="mb-4 rounded-xl border border-tally/40 bg-tally/10 px-4 py-3 text-tally">{note}</p>}
      {mode === "new" && (
        <form className="panel glow rise mb-6 max-w-3xl p-5" onSubmit={(e) => { e.preventDefault(); if (title.trim()) addVideo(); }}>
          <p className="mb-3 font-semibold">{tv`Video mới trong “${data.title}”`}</p>
          <div className="flex flex-wrap gap-2"><input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder={tr("Tên video")} aria-label={tr("Tên video")} className="h-10 min-w-0 flex-1 px-3" />
            <Seg label={tr("Khung hình")} value={format} onChange={setFormat} items={Object.entries(FORMATS) as [string, string][]} />
            <Button kind="primary" busy={busy} disabled={!title.trim()} type="submit">{tr("Tạo video")}</Button></div>
          <p className="mt-2 text-[12.5px] text-faint">{tr("Video mới nhận kênh, mẫu, giọng đọc, nhạc, nhân vật và nguồn tham khảo của dự án; đổi riêng cho video sau cũng được.")}</p>
        </form>)}
      {mode === "mission" && (
        <form className="ai-card rise mb-6 max-w-3xl p-5" onSubmit={(e) => { e.preventDefault(); if (ask_.trim()) mission(); }}>
          <p className="mb-1 font-semibold">{tr("Giao việc cho dự án này")}</p>
          <p className="mb-3 text-[13px] text-mute">{tr("Nói việc cần làm bằng lời, ví dụ “làm 3 video dọc về buổi sáng ở chợ”. Máy lập kế hoạch, kiểm tra năng lực và ngân sách; bạn xem và xác nhận ở Mission Control. Video làm ra nằm trong dự án này.")}</p>
          <div className="flex flex-wrap gap-2"><textarea autoFocus rows={2} value={ask_} onChange={(e) => setAsk(e.target.value)} aria-label={tr("Việc cần làm")} className="min-w-0 flex-1 p-2.5" />
            <Button kind="ai" busy={busy} disabled={!ask_.trim()} type="submit"><Icon name="sparkles" size={14} />{tr("Lập kế hoạch")}</Button></div>
        </form>)}
      {mode === "shared" && (
        <div className="panel rise mb-6 grid max-w-3xl gap-3 p-5 text-[13px]">
          <p className="font-semibold">{tr("Dùng chung cho các video")}</p>
          <p className="-mt-2 text-[12.5px] text-faint">{tr("Đổi ở đây thì video nào còn theo giá trị của dự án sẽ đổi theo; video đã đặt riêng giữ nguyên.")}</p>
          <label className="grid gap-1"><span className="field-label">{tr("Tên dự án")}</span><input defaultValue={data.title} onBlur={(e) => e.target.value.trim() && e.target.value !== data.title && change({ title: e.target.value })} className="h-9 px-3" /></label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1"><span className="field-label">{tr("Kênh")}</span><select value={data.channel ?? ""} onChange={(e) => change({ channel: e.target.value || null })} className="h-9 pl-2.5">
              <option value="">{tr("Không chọn")}</option>{(chan?.channels ?? []).map((c) => <option key={c.name}>{c.name}</option>)}</select></label>
            <label className="grid gap-1"><span className="field-label">{tr("Mẫu video")}</span><select value={data.template ?? ""} onChange={(e) => change({ template: e.target.value || null })} className="h-9 pl-2.5">
              <option value="">{tr("Không chọn")}</option>{(settings?.templates ?? []).map((t) => <option key={t.name}>{t.name}</option>)}</select></label>
            <label className="grid gap-1"><span className="field-label">{tr("Giọng đọc")}</span><select value={data.voice ?? ""} onChange={(e) => change({ voice: e.target.value || null })} className="h-9 pl-2.5">
              <option value="">{tr("Theo mẫu")}</option>{(settings?.voices ?? []).map((v) => <option key={v}>{v}</option>)}</select></label>
            <label className="grid gap-1"><span className="field-label">{tr("Ngân sách tổng (USD)")}</span><input type="number" min={0} step={0.5} defaultValue={data.budget_cap ?? ""} placeholder={tr("không giới hạn")}
              onBlur={(e) => change({ budget_cap: e.target.value === "" ? null : Number(e.target.value) })} className="mono h-9 px-3" />
              <span className="text-[12px] text-faint">{tv`Đã tiêu ${data.spent.toFixed(2)} USD cho các video của dự án`}</span></label>
          </div>
          <label className="grid gap-1"><span className="field-label">{tr("Nhạc nền (đường dẫn file)")}</span><input defaultValue={data.music_path ?? ""} onBlur={(e) => e.target.value !== (data.music_path ?? "") && change({ music_path: e.target.value || null })} className="mono h-9 px-3 text-[12.5px]" /></label>
          <label className="grid gap-1"><span className="field-label">{tr("Ghi chú")}</span><textarea defaultValue={data.notes ?? ""} rows={2} onBlur={(e) => e.target.value !== (data.notes ?? "") && change({ notes: e.target.value })} className="p-2.5" /></label>
        </div>)}
      {data.projects.length === 0 ? <Empty icon="clapper" title={tr("Dự án chưa có video nào")} action={<div className="flex gap-2"><Button kind="primary" onClick={() => setMode("new")}><Icon name="plus" />{tr("Thêm video")}</Button>
          <Button kind="quiet" onClick={() => act(async () => { await post(`/api/v1/productions/${id}`, undefined, "DELETE"); go("/du-an"); })}><Icon name="trash" size={14} />{tr("Xoá dự án trống")}</Button></div>}>
          {tr("Thêm một video, hoặc giao việc để máy làm nhiều video cùng lúc.")}</Empty> : (<>
        <div className="mb-4 flex justify-end"><div className="seg" role="radiogroup" aria-label={tr("Cách xem")}>
          <button type="button" role="radio" aria-checked={view === "grid"} onClick={() => { setView("grid"); try { localStorage.setItem("nx.projects.view", "grid"); } catch { /* fine */ } }} aria-label={tr("Lưới")}><Icon name="grid" size={15} /></button>
          <button type="button" role="radio" aria-checked={view === "list"} onClick={() => { setView("list"); try { localStorage.setItem("nx.projects.view", "list"); } catch { /* fine */ } }} aria-label={tr("Danh sách")}><Icon name="list" size={15} /></button></div></div>
        <VideoCards list={data.projects} view={view} go={go} working={working} reload={reload} /></>)}
      {!!data.missions?.length && <div className="mt-8"><GivenMissions list={data.missions} production={id} go={go} /></div>}
    </Page>
  );
}

export default function Projects({ sub, go }: { sub: string | null; go: (to: string) => void }) {
  const { data, reload } = usePoll<Project[]>("/api/v1/projects", 5000);
  const { data: prods, reload: reloadProds } = usePoll<{ productions: Production[] }>("/api/v1/productions", 8000);
  const [title, setTitle] = useState("");
  const [format, setFormat] = useState("landscape");
  const [into, setInto] = useState("");
  const [mode, setMode] = useState<"none" | "new" | "production" | "ideas">(() => { const q = new URLSearchParams(window.location.search); return q.has("moi") ? "new" : q.has("y-tuong") ? "ideas" : "none"; });
  const [filter, setFilterState] = useState<Filter>(() => listFilter);
  const setFilter = (f: Filter) => { listFilter = f; setFilterState(f); };
  const [view, setView] = useState<"grid" | "list">(() => { try { return (localStorage.getItem("nx.projects.view") as "grid" | "list") ?? "grid"; } catch { return "grid"; } });
  const { data: agent, reload: reloadAgent } = usePoll<{ tasks: AgentTask[] }>("/api/v1/agent/tasks", 4000);
  useEffect(() => { if (!sub && new URLSearchParams(window.location.search).has("moi")) setMode("new"); }, [sub, window.location.search]);
  if (sub) {
    const [pid, part] = sub.split("/");
    if (pid.startsWith("prd_")) return <ProductionPage key={pid} id={pid} go={go} />;
    if (part === "storyboard") return <SideFrame side={<ProjectSide current={pid} place="storyboard" />}><Storyboard key={pid} projectId={pid} back={() => go(`/du-an/${pid}`)} /></SideFrame>;
    return <Detail key={pid} id={pid} back={(to) => go(to ?? "/du-an")} />;
  }
  const create = async () => { const p = await post<Project>("/api/v1/projects", { title: title.trim(), format, production_id: into || null }); setTitle(""); reload(); go(`/du-an/${p.project_id}`); };
  const makeProduction = async () => { const d = await post<Production>("/api/v1/productions", { title: title.trim() }); setTitle(""); reloadProds(); go(`/du-an/${d.production_id}`); };
  const working = new Map((agent?.tasks ?? []).filter((t) => t.status === "working" || t.status === "waiting_operator").map((t) => [t.project_id, t]));
  const setLook = (v: "grid" | "list") => { setView(v); try { localStorage.setItem("nx.projects.view", v); } catch { /* fine */ } };
  const all = data ?? [];
  const toggle = (m: typeof mode) => { setMode(mode === m ? "none" : m); if (window.location.search) window.history.replaceState({}, "", "/du-an"); };
  // With a filter on, the videos in that state, across productions; otherwise the productions themselves.
  const shown = all.filter((p) => bucket(p) === filter);
  const byProduction = (prods?.productions ?? []).map((d) => ({ d, vids: all.filter((p) => p.production_id === d.production_id) }));
  return (
    <Page eyebrow={tr("Sản xuất")} title={tr("Dự án")} note={tr("Mỗi dự án gồm một hay nhiều video; mỗi video có kịch bản, storyboard, bản dựng riêng.")}
          side={<ProjectSide filter={{ value: filter, set: setFilter }} />}
          actions={<><Button kind="quiet" onClick={() => toggle("ideas")}><Icon name="spark" />{tr("Gợi ý ý tưởng")}</Button><Button kind="quiet" onClick={() => toggle("production")}><Icon name="folder" />{tr("Dự án mới")}</Button>
                     <Button kind="primary" onClick={() => toggle("new")}><Icon name="plus" />{tr("Video mới")}</Button></>}>
      {mode === "new" && (
        <form className="panel glow rise mb-6 max-w-3xl p-5" onSubmit={(e) => { e.preventDefault(); if (title.trim()) create(); }}>
          <div className="mb-3 flex items-center gap-2.5"><span className="grid h-8 w-8 place-items-center rounded-lg bg-accent/15 text-accent"><Icon name="clapper" size={16} /></span><p className="font-semibold">{tr("Video mới")}</p>
            <button type="button" onClick={() => toggle("new")} className="ml-auto text-faint hover:text-ink" aria-label={tr("Đóng")}><Icon name="x" /></button></div>
          <label htmlFor="title" className="field-label">{tr("Tên video")}</label>
          <div className="flex flex-wrap gap-2">
            <input id="title" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder={tr("Ví dụ: Một buổi sáng ở chợ Hội An")} className="h-10 min-w-0 flex-1 px-3" />
            <select value={into} onChange={(e) => setInto(e.target.value)} aria-label={tr("Thuộc dự án")} className="h-10 max-w-[220px] pl-2.5">
              <option value="">{tr("Dự án mới cùng tên")}</option>{(prods?.productions ?? []).map((d) => <option key={d.production_id} value={d.production_id}>{d.title}</option>)}</select>
            <Seg label={tr("Khung hình")} value={format} onChange={setFormat} items={Object.entries(FORMATS) as [string, string][]} /><Button kind="primary" disabled={!title.trim()} onClick={create}>{tr("Tạo video")}</Button>
          </div>
        </form>
      )}
      {mode === "production" && (
        <form className="panel glow rise mb-6 max-w-3xl p-5" onSubmit={(e) => { e.preventDefault(); if (title.trim()) makeProduction(); }}>
          <p className="mb-1 font-semibold">{tr("Dự án mới")}</p>
          <p className="mb-3 text-[13px] text-mute">{tr("Một dự án gom nhiều video cùng chủ đề hay cùng chiến dịch, và giữ những gì chúng dùng chung: kênh, mẫu, giọng đọc, nhạc, nhân vật, nguồn, ngân sách tổng.")}</p>
          <div className="flex gap-2"><input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} placeholder={tr("Ví dụ: Series biển miền Trung")} aria-label={tr("Tên dự án")} className="h-10 min-w-0 flex-1 px-3" />
            <Button kind="primary" disabled={!title.trim()} type="submit">{tr("Tạo dự án")}</Button></div>
        </form>
      )}
      {mode === "ideas" && <IdeasPanel format={format} close={() => toggle("ideas")} go={go} onTask={() => { reloadAgent(); reload(); }} />}
      {data && prods && prods.productions.length === 0 && <Empty icon="clapper" title={tr("Chưa có dự án nào")} action={<Button kind="primary" onClick={() => setMode("new")}><Icon name="plus" />{tr("Video mới")}</Button>}>{tr("Tạo một video (nó có dự án riêng), hoặc tạo dự án rồi thêm nhiều video vào.")}</Empty>}
      {all.length > 0 && filter !== "all" && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <p className="min-w-0 flex-1 text-[13px] text-mute">{tv`Video ${FILTERS.find(([k]) => k === filter)?.[1].toLowerCase()} ở mọi dự án`}</p>
          <Button size="sm" kind="quiet" onClick={() => setFilter("all")}>{tr("Xem theo dự án")}</Button>
          <div className="seg" role="radiogroup" aria-label={tr("Cách xem")}>
            <button type="button" role="radio" aria-checked={view === "grid"} onClick={() => setLook("grid")} aria-label={tr("Lưới")}><Icon name="grid" size={15} /></button>
            <button type="button" role="radio" aria-checked={view === "list"} onClick={() => setLook("list")} aria-label={tr("Danh sách")}><Icon name="list" size={15} /></button>
          </div>
        </div>
      )}
      {!data && <SkeletonCards count={6} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4" />}
      {data && filter !== "all" && (shown.length ? <VideoCards list={shown} view={view} go={go} working={working} reload={reload} /> : <p className="panel px-5 py-6 text-mute">{tr("Không có video nào ở mục này.")}</p>)}
      {data && filter === "all" && (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
          {byProduction.map(({ d, vids }) => {
            const states = vids.map(bucket), waiting = states.filter((x) => x === "waiting").length, active = states.filter((x) => x === "active").length, done = states.filter((x) => x === "done").length;
            return (
              <li key={d.production_id}><a href={`/du-an/${d.production_id}`} onClick={(e) => { e.preventDefault(); go(`/du-an/${d.production_id}`); }}
                   className="panel group block overflow-hidden transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-edge">
                <div className="grid h-[150px] grid-cols-2 gap-0.5 bg-black">{vids.slice(0, 4).map((v, i) => <Filmstrip key={v.project_id} shots={v.shots} height={vids.length > 2 ? 74 : 150}
                    className={vids.length === 1 || (vids.length === 3 && i === 2) ? "col-span-2" : ""} />)}
                  {vids.length === 0 && <span className="col-span-2 grid place-items-center text-faint"><Icon name="folder" size={26} /></span>}</div>
                <div className="px-4 pb-4 pt-2.5">
                  <p className="display truncate text-[15.5px] leading-snug">{d.title}</p>
                  <p className="mt-0.5 truncate text-[12.5px] text-mute">{tv`${vids.length} video`}{d.channel ? ` · ${d.channel}` : ""}{d.template ? ` · ${d.template}` : ""}</p>
                  <p className="mt-2 flex flex-wrap gap-2 text-[12px]">
                    {waiting > 0 && <Tag tone="cue">{tv`${waiting} chờ bạn`}</Tag>}{active > 0 && <Tag tone="accent">{tv`${active} đang làm`}</Tag>}{done > 0 && <Tag tone="proof">{tv`${done} đã xong`}</Tag>}
                    {vids.length === 0 && <Tag tone="mute">{tr("trống")}</Tag>}</p>
                </div>
              </a></li>);
          })}
        </ul>
      )}
    </Page>
  );
}

/** The project's slate: its numbers set large in the reel face, each with a small plain label, the state lamp first. */
function Slate({ state, items, extra }: { state: React.ReactNode; items: [string, string][]; extra?: React.ReactNode }) {
  return (
    <span className="flex flex-wrap items-center gap-x-4 gap-y-2">
      {state}
      {items.map(([n, label]) => <span key={label} className="flex items-baseline gap-1.5"><span className="mono text-[14px] font-medium leading-none text-ink">{n}</span><span className="text-[12.5px] text-faint">{label}</span></span>)}
      {extra && <span className="text-[12.5px] text-faint">{extra}</span>}
    </span>
  );
}
