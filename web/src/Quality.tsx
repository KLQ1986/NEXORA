import { t as tr, tv } from "./i18n";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { call, post, timecode, usePoll, type Run } from "./api";
import { ask, Button, Empty, Icon, Meter, Seg, Spinner, StageRail, Tag, toast } from "./parts";
import { CONTENT, DEFECT, OP, TIER, VERDICT } from "./VisualQuality";

/* Visual Quality, its own workspace (design 2026-10-16): every source the engine can work on, library or not, down the left; the
   picture in the middle, before and after under a wipe, its shots along a strip coloured by how wrong each is; and on the right
   what the engine knows and has decided, with every step a switch, its numbers editable, and its evidence beside it. Nothing
   reaches a cut, an extract or a file until a recipe is approved here. */

type Defect = { t_start: number; t_end: number; kind: string; severity: number; value?: number; region?: number[][] };
type Checked = { niqe_without?: number; niqe_with?: number; niqe_classic?: number; niqe_ai?: number; judge?: Judge | null;
  dark_without?: number; dark_with?: number; clipped_without?: number; clipped_with?: number };
type Judge = { veto: boolean; ai_better_both: boolean; why: string };
type Step = { op: string; tier?: string; params: Record<string, unknown>; why?: string; off?: boolean; generative?: boolean; edited?: boolean;
  checked?: Checked; method_noise?: number; remote?: boolean };
type Shot = { t_start: number; t_end: number; steps: Step[]; defects: { kind: string; severity: number }[]; dropped?: { op: string; why: string; failed?: boolean; judge?: Judge }[];
  scores?: Record<string, number | number[]> };
type QA = { verdict: string; reasons: string[]; metrics: Record<string, [number | null, number | null]> };
type Preview = { preview_id: string; t: number; seconds: number; qa: QA; urls: Record<string, string>; at: number };
type Version = { recipe_id: string; version: number; status: string; decided_by: string | null; at: number; from?: string; edited?: boolean };
type Profile = { encoding: string | null; encoding_name: string | null; encoding_confidence: string; encoding_why?: string[]; content: string; content_why?: string[];
  warnings: string[]; technical: Record<string, unknown>; apparent_detail?: unknown };
type Info = { name: string; file_name?: string; in_library: boolean; path: string; still: boolean; duration: number | null; width: number | null; height: number | null;
  frame_rate: number | null; thumbnail_url: string | null; proxy_url: string | null };
type View = { subject: string; info: Info; profile: Profile | null; defects: Defect[]; state: string; run: Run | null;
  recipe: { recipe_id: string; version: number; status: string; decided_by: string | null; shots: Shot[]; notes: string[]; options?: Record<string, unknown> } | null;
  approved: string | null; previews: Preview[]; versions: Version[]; exports: { name: string; size: number; at: number; url: string }[] };
type Row = { subject: string; in_library: boolean; name: string; still: boolean | null; thumbnail_url: string | null; duration?: number | null; width?: number | null;
  height?: number | null; state: string; recipe: { recipe_id: string; version: number; status: string } | null; encoding_name: string | null; content: string | null;
  warnings: number; defects: number; worst: { kind: string; severity: number } | null; steps: number; generative: number; verdict: string | null; code?: string };
type Tool = { name: string; label: string; available: boolean; fix: string | null };

const STATE: Record<string, [string, "mute" | "cue" | "proof" | "tally" | "accent" | "ai"]> = {
  none: [tr("chưa phân tích"), "mute"], running: [tr("đang chạy"), "accent"], proposed: [tr("chờ duyệt"), "cue"], approved: [tr("đã duyệt"), "proof"],
  rejected: [tr("đã bỏ"), "mute"], failed: [tr("lỗi"), "tally"],
};
const PIPELINE: Record<string, string> = { "vq.analyse": tr("Phân tích"), "vq.preview": tr("Xem trước"), "vq.apply": tr("Áp công thức") };
const STAGE: Record<string, string> = { profile: tr("Hồ sơ nguồn"), assess: tr("Đánh giá"), plan: tr("Lập công thức"), preview: tr("Xem trước"), apply: tr("Áp") };
const METRIC: Record<string, string> = {
  flicker: tr("nhấp nháy"), colour_drift: tr("màu trôi"), crawl: tr("texture bò"), structure: tr("cấu trúc"), niqe: tr("NIQE (thấp là tự nhiên)"),
  exposure: tr("phơi sáng"), contrast: tr("tương phản"), saturation: tr("bão hoà"), clipped_high: tr("cháy sáng"), noise: tr("nhiễu"), sharpness: tr("độ nét"),
  psnr: "PSNR", warp_error: tr("lệch theo optical flow"), gain: tr("hệ số tương phản"),
};
// Lower is better for these; for the rest the change is shown without a judgement. A grade that raises contrast raises the
// temporal ones with it, so those are judged against the gain the checks themselves use.
const LOWER_BETTER = new Set(["flicker", "colour_drift", "crawl", "niqe", "clipped_high", "noise", "warp_error"]);
const SCALED = new Set(["flicker", "colour_drift", "crawl", "warp_error", "noise"]);
const VERDICT_NAME: Record<string, string> = { pass: tr("đạt"), warn: tr("cảnh báo"), fail: tr("hỏng") };

/* The numbers an operator may change on a step, with their range: everything else stays as the engine set it. */
const KNOBS: Record<string, { key: string; label: string; min: number; max: number; step: number }[]> = {
  denoise: [{ key: "strength", label: tr("cường độ"), min: 0, max: 2, step: 0.05 }],
  sharpen: [{ key: "strength", label: tr("cường độ"), min: 0, max: 1, step: 0.05 }],
  deband: [{ key: "threshold", label: tr("ngưỡng"), min: 0.005, max: 0.1, step: 0.005 }],
  levels: [{ key: "gamma", label: "gamma", min: 0.5, max: 2, step: 0.01 }, { key: "saturation", label: tr("bão hoà"), min: 0.5, max: 1.6, step: 0.01 }],
  relight: [{ key: "shadows", label: tr("nâng vùng tối"), min: 0, max: 1, step: 0.05 }, { key: "highlights", label: tr("giữ vùng sáng"), min: 0, max: 1, step: 0.05 }],
  faces: [{ key: "weight", label: tr("độ trung thành"), min: 0, max: 1, step: 0.05 }],
  stabilise: [{ key: "smoothing", label: tr("độ mượt"), min: 5, max: 60, step: 1 }],
  deflicker: [{ key: "size", label: tr("số khung"), min: 2, max: 30, step: 1 }],
};

const sevTone = (s: number) => (s >= 0.6 ? "tally" : s >= 0.25 ? "cue" : "proof") as "tally" | "cue" | "proof";
const sevColour = (s: number) => (s >= 0.6 ? "bg-tally" : s >= 0.25 ? "bg-cue" : s > 0 ? "bg-proof/70" : "bg-white/[0.08]");
const fmt = (v: number | null | undefined, d = 2) => (v == null ? "–" : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(d));

export default function Quality() {
  const params = new URLSearchParams(window.location.search);
  const [selected, setSelected] = useState<string | null>(params.get("s"));
  const select = (s: string) => { setSelected(s); window.history.replaceState({}, "", `/chat-luong-hinh?s=${encodeURIComponent(s)}`); };
  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <Sources selected={selected} onSelect={select} />
      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        {selected ? <Workspace key={selected} subject={selected} /> : (
          <div className="grid flex-1 place-items-center p-8">
            <Empty icon="sparkles" title={tr("Chọn một nguồn để xem chất lượng hình")}>
              {tr("Mỗi video hay ảnh được đo shot theo shot: profile màu, nhiễu, mờ, phơi sáng, rung… rồi được lập công thức sửa. Không có gì được áp cho đến khi bạn duyệt.")}
            </Empty>
          </div>
        )}
      </section>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------------------ the list of sources */
function Sources({ selected, onSelect }: { selected: string | null; onSelect: (s: string) => void }) {
  const { data, reload } = usePoll<{ subjects: Row[] }>("/api/v1/vq/subjects", 4000);
  // One name and one house code for each item, as the library shows them.
  const catalog = usePoll<{ items: { subject: string; code: string; title: string | null }[] }>("/api/v1/catalog", 60000).data;
  const book = useMemo(() => new Map((catalog?.items ?? []).map((e) => [e.subject, e])), [catalog]);
  const tools = usePoll<{ tools: Tool[] }>("/api/v1/vq/tools", 60000).data?.tools ?? [];
  const [scope, setScope] = useState<"library" | "files" | "all">("library");
  const [state, setState] = useState<string>("all");
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const rows = useMemo(() => (data?.subjects ?? []).map((r) => {
    const e = book.get(r.subject);
    return e ? { ...r, name: e.title || r.name, code: e.code } : r;
  }), [data, book]);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of rows) if (scope === "all" || (scope === "library") === r.in_library) c[r.state] = (c[r.state] ?? 0) + 1;
    return c;
  }, [rows, scope]);
  const shown = rows.filter((r) => (scope === "all" || (scope === "library") === r.in_library) && (state === "all" || r.state === state)
    && (!q.trim() || r.name.toLowerCase().includes(q.trim().toLowerCase())));
  const waiting = rows.filter((r) => r.in_library && r.state === "none");
  const analyseAll = async () => {
    setBusy(true);
    try { for (const r of waiting) await post(`/api/v1/vq/subjects/${r.subject}/plan`, {}); toast(tv`Đã xếp ${waiting.length} mục vào hàng phân tích.`); reload?.(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(false); }
  };
  const addFile = async () => {
    if (!path.trim()) return;
    setBusy(true);
    try { const r = await post<{ subject: string }>("/api/v1/vq/jobs", { path: path.trim() }); setPath(""); setAdding(false); setScope("files"); reload?.(); onSelect(r.subject); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(false); }
  };
  const missing = tools.filter((t) => !t.available);
  return (
    <aside aria-label={tr("Nguồn")} className="flex w-[330px] shrink-0 flex-col border-r border-line bg-surface/40 max-lg:hidden">
      <div className="grid gap-2.5 border-b border-line p-3">
        <div className="flex items-center gap-2">
          <p className="eyebrow flex-1">{tr("Chất lượng hình")}</p>
          <Button size="sm" kind="quiet" onClick={() => setAdding((v) => !v)} title={tr("Thêm file ngoài thư viện")}><Icon name="plus" size={14} />{tr("File")}</Button>
          {waiting.length > 0 && <Button size="sm" onClick={analyseAll} busy={busy}>{tv`Phân tích ${waiting.length}`}</Button>}
        </div>
        {adding && (
          <form className="flex gap-1.5" onSubmit={(e) => { e.preventDefault(); addFile(); }}>
            <input value={path} onChange={(e) => setPath(e.target.value)} placeholder={tr("Đường dẫn file trên máy, ví dụ ~/Movies/clip.mov")} autoFocus
                   className="h-8 min-w-0 flex-1 rounded-md border border-line bg-raised px-2 text-[12.5px] outline-none focus:border-accent" />
            <Button size="sm" kind="primary" type="submit" busy={busy}>{tr("Thêm")}</Button>
          </form>
        )}
        <Seg label={tr("Phạm vi")} value={scope} onChange={setScope} items={[["library", tr("Thư viện")], ["files", tr("File ngoài")], ["all", tr("Tất cả")]] as const} />
        <div className="flex flex-wrap gap-1">
          {(["all", "proposed", "approved", "running", "none", "failed"] as const).map((k) => {
            const n = k === "all" ? Object.values(counts).reduce((a, b) => a + b, 0) : counts[k] ?? 0;
            if (k !== "all" && !n) return null;
            return <button key={k} type="button" onClick={() => setState(k)} className={`h-6 rounded-full px-2.5 text-[11.5px] ${state === k ? "bg-accent/15 text-accent" : "bg-white/[0.04] text-mute hover:text-ink"}`}>
              {k === "all" ? tr("Tất cả") : STATE[k][0]} <span className="mono">{n}</span></button>;
          })}
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={tr("Tìm theo tên")} className="h-8 rounded-md border border-line bg-raised px-2.5 text-[12.5px] outline-none focus:border-accent" />
      </div>
      <ul className="min-h-0 flex-1 overflow-y-auto p-2">
        {!data && <li className="grid place-items-center p-6"><Spinner /></li>}
        {data && shown.length === 0 && <li className="p-4 text-center text-[12.5px] text-faint">{tr("Không có mục nào ở đây.")}</li>}
        {shown.map((r) => {
          const [label, tone] = STATE[r.state] ?? [r.state, "mute"];
          return (
            <li key={r.subject}>
              <button type="button" onClick={() => onSelect(r.subject)} aria-current={selected === r.subject ? "true" : undefined}
                      className={`flex w-full gap-2.5 rounded-lg p-2 text-left transition-colors ${selected === r.subject ? "bg-accent/10 shadow-[inset_0_0_0_1px_rgba(48,175,255,0.25)]" : "hover:bg-raised/60"}`}>
                <span className="relative h-[42px] w-[74px] shrink-0 overflow-hidden rounded-md bg-overlay">
                  {r.thumbnail_url && <img src={r.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-cover" />}
                  {r.duration ? <span className="mono absolute bottom-0.5 right-0.5 rounded bg-black/70 px-1 text-[10px]">{timecode(r.duration)}</span> : null}
                  {r.still && <span className="absolute bottom-0.5 right-0.5 rounded bg-black/70 px-1"><Icon name="image" size={11} /></span>}
                </span>
                <span className="grid min-w-0 flex-1 content-start gap-1">
                  <span className="truncate text-[13px] text-ink">{r.name}</span>
                  {r.code && <span className="mono -mt-0.5 text-[11px] text-faint">{r.code}</span>}
                  <span className="flex flex-wrap items-center gap-1">
                    <Tag tone={tone}>{label}</Tag>
                    {r.recipe && <span className="mono text-[11px] text-faint">v{r.recipe.version}</span>}
                    {r.generative > 0 && <Tag tone="ai" dot={false}>AI {r.generative}</Tag>}
                    {r.verdict && <span className={`text-[11px] ${r.verdict === "pass" ? "text-proof" : r.verdict === "warn" ? "text-cue" : "text-tally"}`}>{tv`QA ${VERDICT_NAME[r.verdict] ?? r.verdict}`}</span>}
                  </span>
                  {(r.encoding_name || r.worst) && <span className="truncate text-[11.5px] text-faint">
                    {[r.encoding_name, r.worst ? tv`${DEFECT[r.worst.kind] ?? r.worst.kind} ${Math.round(r.worst.severity * 100)}%` : null].filter(Boolean).join(" · ")}</span>}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="border-t border-line p-3">
        <details>
          <summary className="cursor-pointer list-none text-[12px] text-faint">
            {tv`Công cụ trên máy: ${tools.length - missing.length}/${tools.length}`}{missing.length > 0 && <span className="ml-1 text-cue">{tv`· thiếu ${missing.length}`}</span>}
          </summary>
          <ul className="mt-2 grid gap-1 text-[12px]">
            {tools.map((t) => <li key={t.name} className="flex items-start gap-1.5">
              <span className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${t.available ? "bg-proof" : "bg-cue"}`} />
              <span className="min-w-0"><span className={t.available ? "text-mute" : "text-ink"}>{t.label}</span>
                {!t.available && t.fix && <code className="mono block truncate text-[11px] text-faint">{t.fix}</code>}</span></li>)}
          </ul>
        </details>
      </div>
    </aside>
  );
}

/* --------------------------------------------------------------------------------------------------------- one source */
function Workspace({ subject }: { subject: string }) {
  const { data, reload } = usePoll<View>(`/api/v1/vq/subjects/${subject}`, 2500);
  // Only the library's own items are in the catalogue; a file job is named by its file.
  const entry = usePoll<{ entry: { code: string; title: string | null } }>(subject.startsWith("ast_") ? `/api/v1/catalog/${subject}` : "", 120000).data?.entry;
  const [shotIndex, setShotIndex] = useState(0);
  const [tab, setTab] = useState<"recipe" | "source" | "qa" | "defects" | "versions">("recipe");
  const [busy, setBusy] = useState<string | null>(null);
  const [options, setOptions] = useState(false);
  const act = async (key: string, url: string, body?: object, done?: string) => {
    setBusy(key);
    try { await post(url, body ?? {}); if (done) toast(done); reload?.(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(null); }
  };
  if (!data) return <div className="grid flex-1 place-items-center"><Spinner /></div>;
  const r = data.recipe, info = data.info, p = data.profile;
  const shots = r?.shots ?? [];
  const shot = shots[Math.min(shotIndex, Math.max(0, shots.length - 1))];
  const running = data.state === "running";
  const mid = shot ? (shot.t_start + shot.t_end) / 2 : 0;
  const base = `/api/v1/vq/subjects/${subject}`;
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-5 py-3">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <h2 className="display truncate text-[17px]">{entry?.title || info.name}</h2>
            {entry?.code && <span className="mono rounded border border-line px-1.5 text-[11px] text-faint">{entry.code}</span>}
            <Tag tone={(STATE[data.state] ?? ["", "mute"])[1]}>{(STATE[data.state] ?? [data.state])[0]}</Tag>
            {r && <span className="mono text-[12px] text-faint">{tv`công thức v${r.version}`}</span>}
            {!info.in_library && <Tag tone="mute" dot={false}>{tr("ngoài thư viện")}</Tag>}
          </div>
          <p className="mt-0.5 truncate text-[12.5px] text-faint">
            {[info.width && info.height ? `${info.width}×${info.height}` : null, p?.technical.bit_depth ? `${p.technical.bit_depth}-bit` : null,
              info.frame_rate ? `${Number(info.frame_rate).toFixed(2)} fps` : null, info.duration ? timecode(info.duration) : info.still ? tr("ảnh tĩnh") : null,
              p?.encoding_name, p ? CONTENT[p.content] ?? p.content : null].filter(Boolean).join(" · ")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => setOptions((v) => !v)} disabled={running}><Icon name="sliders" size={14} />{r ? tr("Phân tích lại") : tr("Phân tích")}</Button>
          {r && <Button size="sm" disabled={running} busy={busy === "preview"} onClick={() => act("preview", `${base}/preview`, { t: info.still ? 0 : mid, seconds: 3, recipe_id: r.recipe_id }, tr("Đã xếp việc xem trước shot này."))}>
            <Icon name="eye" size={14} />{tr("Xem trước shot")}</Button>}
          {r && r.status !== "approved" && <Button size="sm" kind="primary" busy={busy === "approve"} onClick={async () => {
            // A recipe whose newest preview (the list holds this version's, newest first) failed its checks is approved only on purpose.
            const failed = data.previews[0];
            if (failed?.qa.verdict === "fail" && !(await ask(tr("Bản xem trước gần nhất không qua kiểm tra"), {
              body: <p>{tv`Lý do: ${failed.qa.reasons.join("; ")}. Duyệt thì công thức này sẽ được dùng khi dựng và trích xuất.`}</p>, confirm: tr("Vẫn duyệt"), danger: true }))) return;
            act("approve", `/api/v1/vq/recipes/${r.recipe_id}/approve`, {}, tr("Đã duyệt công thức."));
          }}>
            <Icon name="check" size={14} />{tr("Duyệt")}</Button>}
          {r && r.status !== "rejected" && r.status !== "approved" && <Button size="sm" kind="quiet" busy={busy === "reject"} onClick={() => act("reject", `/api/v1/vq/recipes/${r.recipe_id}/reject`)}>{tr("Bỏ")}</Button>}
          {data.approved && <ExportButton base={base} still={info.still} disabled={running} onDone={reload} />}
          {running && <Button size="sm" kind="danger" busy={busy === "cancel"} onClick={() => act("cancel", `${base}/cancel`, {}, tr("Đã huỷ."))}>{tr("Huỷ")}</Button>}
        </div>
        {options && <AnalyseOptions recipeOptions={r?.options} onRun={(o) => { setOptions(false); act("plan", `${base}/plan`, o, tr("Đã xếp việc phân tích.")); }} onClose={() => setOptions(false)} />}
      </header>
      <RunBar run={data.run} state={data.state} />
      {!r && !running && (
        <div className="grid flex-1 place-items-center p-8">
          <Empty icon="sparkles" title={tr("Chưa phân tích")} action={<Button kind="primary" busy={busy === "plan"} onClick={() => act("plan", `${base}/plan`, {}, tr("Đã xếp việc phân tích."))}>{tr("Phân tích chất lượng hình")}</Button>}>
            {tr("Hệ thống sẽ nhận diện profile màu, đo từng shot và đề xuất công thức sửa. Chưa áp gì cho tới khi bạn duyệt.")}
          </Empty>
        </div>
      )}
      {r && shot && (
        <div className="flex min-h-0 flex-1 max-xl:flex-col">
          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto p-4">
            <Viewer subject={subject} view={data} shot={shot} shotIndex={shotIndex} onRemove={reload} />
            {shots.length > 1 && <ShotStrip shots={shots} index={shotIndex} onPick={setShotIndex} duration={info.duration ?? shots[shots.length - 1].t_end} />}
          </div>
          <aside className="flex min-h-0 w-[440px] shrink-0 flex-col border-l border-line max-xl:w-auto max-xl:border-l-0 max-xl:border-t">
            <div className="flex gap-1 border-b border-line px-3 pt-2">
              {([["recipe", tr("Công thức")], ["source", tr("Nguồn")], ["qa", tr("Kiểm tra")], ["defects", tr("Lỗi")], ["versions", tr("Phiên bản")]] as const).map(([k, l]) => (
                <button key={k} type="button" onClick={() => setTab(k)} className={`-mb-px border-b-2 px-2.5 pb-2 text-[13px] ${tab === k ? "border-accent text-ink" : "border-transparent text-mute hover:text-ink"}`}>{l}
                  {k === "defects" && shot.defects.length > 0 && <span className="mono ml-1 text-[11px] text-faint">{shot.defects.length}</span>}
                  {k === "versions" && <span className="mono ml-1 text-[11px] text-faint">{data.versions.length}</span>}
                </button>))}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {tab === "recipe" && <RecipeTab recipe={r} shot={shot} shotIndex={shotIndex} notes={r.notes} onChanged={reload} />}
              {tab === "source" && <SourceTab profile={p} info={info} />}
              {tab === "qa" && <QATab previews={data.previews} shot={shot} />}
              {tab === "defects" && <DefectsTab shot={shot} defects={data.defects} />}
              {tab === "versions" && <VersionsTab versions={data.versions} current={r.recipe_id} exports={data.exports} onChanged={reload} />}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}

function RunBar({ run, state }: { run: Run | null; state: string }) {
  if (!run || (state !== "running" && state !== "failed")) return null;
  const failedStage = run.stages.find((s) => s.status === "failed");
  return (
    <div className={`flex flex-wrap items-center gap-3 border-b border-line px-5 py-2 text-[12.5px] ${state === "failed" ? "bg-tally/[0.06]" : "bg-accent/[0.05]"}`}>
      {state === "running" ? <Spinner size={13} /> : <Icon name="alert" size={14} className="text-tally" />}
      <span className="text-ink">{PIPELINE[run.pipeline] ?? run.pipeline}</span>
      <div className="min-w-[160px] flex-1"><StageRail stages={run.stages} labels name={(k) => STAGE[k] ?? k} /></div>
      {state === "failed" && failedStage && <span className="text-tally">{tv`hỏng ở bước ${STAGE[failedStage.stage_key] ?? failedStage.stage_key}`}{failedStage.blocked_reason ? `: ${failedStage.blocked_reason}` : ""}</span>}
    </div>
  );
}

/* --------------------------------------------------------------------------------------------------- the picture itself */
function Viewer({ subject, view, shot, shotIndex, onRemove }: { subject: string; view: View; shot: Shot; shotIndex: number; onRemove?: () => void }) {
  const info = view.info;
  const preview = view.previews.find((p) => p.t >= shot.t_start - 0.01 && p.t <= Math.max(shot.t_end, shot.t_start) + 0.01) ?? (info.still ? view.previews[0] : undefined);
  const [mode, setMode] = useState<"wipe" | "side" | "video">("wipe");
  const [split, setSplit] = useState(50);
  const [marking, setMarking] = useState(false);
  const [box, setBox] = useState<[number, number, number, number] | null>(null);
  const [heat, setHeat] = useState<string | null>(null);
  const drag = useRef<{ x: number; y: number } | null>(null);
  const mid = info.still ? 0 : (shot.t_start + shot.t_end) / 2;
  const frame = `/api/v1/vq/subjects/${subject}/frame?t=${mid.toFixed(2)}&graded=1`;
  const before = preview?.urls.before_still ?? frame;
  const after = preview?.urls.after_still;
  const W = Number(view.profile?.technical.display_width ?? info.width) || 1, H = Number(view.profile?.technical.display_height ?? info.height) || 1;
  const toSource = (e: React.MouseEvent<HTMLDivElement>): [number, number] => {
    const r = e.currentTarget.getBoundingClientRect();
    return [Math.max(0, Math.min(W, ((e.clientX - r.left) / r.width) * W)), Math.max(0, Math.min(H, ((e.clientY - r.top) / r.height) * H))];
  };
  const region = heat ? view.defects.find((d) => d.kind === heat && d.t_start <= mid + 0.01 && mid <= d.t_end + 0.01)?.region : undefined;
  const removeIt = async () => {
    if (!box || !view.recipe) return;
    try {
      await post(`/api/v1/vq/recipes/${view.recipe.recipe_id}/shots/${shotIndex}/remove`, { regions: [box.map(Math.round)] });
      toast(tr("Đã thêm bước xoá vật vào phiên bản mới; xem trước rồi duyệt.")); setBox(null); setMarking(false); onRemove?.();
    } catch (e) { toast((e as Error).message, { tone: "tally" }); }
  };
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Seg label={tr("Cách so sánh")} value={mode} onChange={setMode}
             items={[["wipe", tr("Trượt")], ["side", tr("Cạnh nhau")], ...(preview?.urls.before_video ? [["video", tr("Video")] as const] : [])] as readonly (readonly ["wipe" | "side" | "video", string])[]} />
        <span className="text-[12px] text-faint">
          {preview ? tv`xem trước tại ${timecode(preview.t)} · ${preview.seconds}s` : tr("chưa xem trước shot này: đang hiện khung gốc đã chuyển màu")}</span>
        <span className="flex-1" />
        {shot.defects.some((d) => view.defects.some((x) => x.kind === d.kind && x.region)) && (
          <select value={heat ?? ""} onChange={(e) => setHeat(e.target.value || null)} className="h-7 rounded-md border border-line bg-raised px-2 text-[12px]">
            <option value="">{tr("Bản đồ lỗi: tắt")}</option>
            {shot.defects.map((d) => <option key={d.kind} value={d.kind}>{tv`Bản đồ: ${DEFECT[d.kind] ?? d.kind}`}</option>)}
          </select>)}
        {!info.still && <Button size="sm" kind={marking ? "primary" : "quiet"} onClick={() => { setMarking((v) => !v); setBox(null); }}><Icon name="scissors" size={14} />{marking ? tr("Đang chọn vùng xoá") : tr("Xoá vật")}</Button>}
      </div>
      {mode === "video" && preview?.urls.before_video ? (
        <SyncedVideos before={preview.urls.before_video} after={preview.urls.after_video} />
      ) : mode === "side" ? (
        <div className="grid grid-cols-2 gap-2">
          <Figure label={tr("trước")}><img src={before} alt="" className="w-full" /></Figure>
          <Figure label={tr("sau")}>{after ? <img src={after} alt="" className="w-full" /> : <NoAfter />}</Figure>
        </div>
      ) : (
        <div className="relative select-none overflow-hidden rounded-lg border border-line bg-black"
             onMouseDown={(e) => { if (!marking) return; const [x, y] = toSource(e); drag.current = { x, y }; setBox([x, y, 0, 0]); }}
             onMouseMove={(e) => { if (!marking || !drag.current) return; const [x, y] = toSource(e); const o = drag.current; setBox([Math.min(o.x, x), Math.min(o.y, y), Math.abs(x - o.x), Math.abs(y - o.y)]); }}
             onMouseUp={() => { drag.current = null; }}>
          <img src={before} alt="" draggable={false} className="block w-full" />
          {after && !marking && <img src={after} alt="" draggable={false} className="absolute inset-0 block h-full w-full" style={{ clipPath: `inset(0 0 0 ${split}%)` }} />}
          {after && !marking && <>
            <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white/80 shadow-[0_0_8px_rgba(0,0,0,0.6)]" style={{ left: `${split}%` }} />
            <input type="range" min={0} max={100} value={split} onChange={(e) => setSplit(Number(e.target.value))} aria-label={tr("Vị trí so sánh")}
                   className="absolute inset-0 h-full w-full cursor-ew-resize opacity-0" />
            <span className="chip absolute left-2 top-2">{tr("trước")}</span><span className="chip absolute right-2 top-2">{tr("sau")}</span>
          </>}
          {!after && !marking && <span className="chip absolute left-2 top-2">{preview ? tr("trước") : tr("khung gốc (đã chuyển màu)")}</span>}
          {region && <Heat grid={region} kind={heat!} />}
          {marking && <div className="absolute inset-0 cursor-crosshair bg-black/10" />}
          {box && box[2] > 0 && <div className="pointer-events-none absolute border-2 border-tally bg-tally/10" style={{ left: `${box[0] / W * 100}%`, top: `${box[1] / H * 100}%`, width: `${box[2] / W * 100}%`, height: `${box[3] / H * 100}%` }} />}
        </div>
      )}
      {marking && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-tally/30 bg-tally/[0.06] px-3 py-2 text-[12.5px]">
          <span className="flex-1 text-mute">{box && box[2] > 8 ? tv`Vùng ${Math.round(box[2])}×${Math.round(box[3])} px tại (${Math.round(box[0])}, ${Math.round(box[1])}), giữ cho cả shot. ProPainter lấp từ các khung lân cận.` : tr("Kéo một khung quanh vật cần xoá. Khung được giữ cho cả shot.")}</span>
          <Button size="sm" kind="primary" disabled={!box || box[2] < 8 || box[3] < 8} onClick={removeIt}>{tr("Thêm bước xoá vật")}</Button>
          <Button size="sm" kind="quiet" onClick={() => { setMarking(false); setBox(null); }}>{tr("Thôi")}</Button>
        </div>
      )}
    </div>
  );
}

function Figure({ label, children }: { label: string; children: React.ReactNode }) {
  return <figure className="relative overflow-hidden rounded-lg border border-line bg-black">{children}<figcaption className="chip absolute left-2 top-2">{label}</figcaption></figure>;
}
function NoAfter() {
  return <div className="grid aspect-video place-items-center text-[12.5px] text-faint">{tr("Bấm “Xem trước shot” để thấy bản sau")}</div>;
}

/* Where in the picture a defect is: its 4×4 measure, worst cells strongest. Darkness is worse where lower; the rest where higher. */
function Heat({ grid, kind }: { grid: number[][]; kind: string }) {
  const values = grid.flat();
  const lo = Math.min(...values), hi = Math.max(...values);
  const norm = (v: number) => (hi - lo < 1e-9 ? 0.5 : (v - lo) / (hi - lo));
  const worse = kind === "underexposed" ? (v: number) => 1 - norm(v) : norm;
  return (
    <div className="pointer-events-none absolute inset-0 grid" style={{ gridTemplateColumns: `repeat(${grid[0].length}, 1fr)`, gridTemplateRows: `repeat(${grid.length}, 1fr)` }}>
      {grid.flatMap((row, i) => row.map((v, j) => <div key={`${i}-${j}`} className="border border-white/10" style={{ background: `rgba(255, 92, 92, ${0.08 + 0.45 * worse(v)})` }} />))}
    </div>
  );
}

function SyncedVideos({ before, after }: { before: string; after?: string }) {
  const a = useRef<HTMLVideoElement>(null), b = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const toggle = () => {
    const x = a.current, y = b.current;
    if (!x) return;
    if (playing) { x.pause(); y?.pause(); setPlaying(false); return; }
    if (y) y.currentTime = x.currentTime;
    x.play(); y?.play(); setPlaying(true);
  };
  useEffect(() => {
    const x = a.current, y = b.current;
    if (!x || !y) return;
    const keep = () => { if (Math.abs(x.currentTime - y.currentTime) > 0.08) y.currentTime = x.currentTime; };
    x.addEventListener("seeked", keep); x.addEventListener("timeupdate", keep);
    return () => { x.removeEventListener("seeked", keep); x.removeEventListener("timeupdate", keep); };
  }, []);
  return (
    <div className="grid gap-2">
      <div className="grid grid-cols-2 gap-2">
        <Figure label={tr("trước")}><video ref={a} src={before} muted loop playsInline className="w-full" onEnded={() => setPlaying(false)} /></Figure>
        <Figure label={tr("sau")}>{after ? <video ref={b} src={after} muted loop playsInline className="w-full" /> : <NoAfter />}</Figure>
      </div>
      <div><Button size="sm" onClick={toggle}><Icon name={playing ? "pause" : "play"} size={14} />{playing ? tr("Dừng") : tr("Phát cả hai")}</Button></div>
    </div>
  );
}

function ShotStrip({ shots, index, onPick, duration }: { shots: Shot[]; index: number; onPick: (i: number) => void; duration: number }) {
  return (
    <div className="mt-3 grid gap-1.5">
      <p className="text-[12px] text-faint">{tv`${shots.length} shot · màu theo lỗi nặng nhất`}</p>
      <div className="flex h-9 w-full gap-px overflow-hidden rounded-md">
        {shots.map((s, i) => {
          const worst = Math.max(0, ...s.defects.map((d) => d.severity));
          const ai = s.steps.some((x) => x.generative && !x.off);
          return (
            <button key={i} type="button" onClick={() => onPick(i)} title={`${timecode(s.t_start)}–${timecode(s.t_end)} · ${s.defects.map((d) => DEFECT[d.kind] ?? d.kind).join(", ") || tr("không lỗi")}`}
                    className={`relative min-w-[6px] ${sevColour(worst)} ${i === index ? "ring-2 ring-inset ring-white" : "opacity-80 hover:opacity-100"}`}
                    style={{ flexGrow: Math.max(0.2, s.t_end - s.t_start) / Math.max(duration, 1) * 100 }}>
              {ai && <span className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-ai" />}
            </button>);
        })}
      </div>
      <div className="flex justify-between text-[11px] text-faint"><span className="mono">0:00</span><span className="mono">{timecode(duration)}</span></div>
    </div>
  );
}

/* ---------------------------------------------------------------------------------------------------------- the inspector */
function RecipeTab({ recipe, shot, shotIndex, notes, onChanged }: { recipe: NonNullable<View["recipe"]>; shot: Shot; shotIndex: number; notes: string[]; onChanged?: () => void }) {
  const edit = async (step: number, body: object) => {
    try { await call(`/api/v1/vq/recipes/${recipe.recipe_id}/shots/${shotIndex}/steps/${step}`, { method: "PATCH", body: JSON.stringify(body) }); toast(tr("Đã lưu thành phiên bản mới.")); onChanged?.(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); }
  };
  return (
    <div className="grid gap-3">
      <div className="flex items-center gap-2 text-[12.5px]">
        <span className="mono text-ink">{`${timecode(shot.t_start)}–${timecode(shot.t_end)}`}</span>
        <span className="text-faint">{tv`shot ${shotIndex + 1} · ${shot.steps.filter((s) => !s.off).length} bước đang bật`}</span>
      </div>
      {shot.defects.length > 0 && <div className="flex flex-wrap gap-1">{shot.defects.map((d) => <Tag key={d.kind} tone={sevTone(d.severity)}>{`${DEFECT[d.kind] ?? d.kind} ${Math.round(d.severity * 100)}%`}</Tag>)}</div>}
      {shot.steps.length === 0 && <p className="rounded-lg border border-line p-3 text-[12.5px] text-faint">{tr("Shot này không cần xử lý.")}</p>}
      <ol className="grid gap-2">{shot.steps.map((st, j) => <StepCard key={`${recipe.recipe_id}-${j}`} step={st} index={j} onEdit={(b) => edit(j, b)} />)}</ol>
      {(shot.dropped ?? []).length > 0 && (
        <div className="grid gap-1.5 rounded-lg border border-line p-3">
          <p className="eyebrow">{tr("Đã cân nhắc rồi bỏ")}</p>
          {(shot.dropped ?? []).map((d, k) => <p key={k} className="text-[12.5px]"><span className={d.failed ? "text-tally" : "text-ink"}>{OP[d.op] ?? d.op}</span>
            <span className="text-faint">{`: ${d.why}`}</span></p>)}
        </div>
      )}
      {notes.length > 0 && <div className="grid gap-1 rounded-lg border border-line p-3"><p className="eyebrow">{tr("Ghi chú")}</p>{notes.map((n) => <p key={n} className="text-[12.5px] text-mute">{n}</p>)}</div>}
    </div>
  );
}

function StepCard({ step, index, onEdit }: { step: Step; index: number; onEdit: (body: object) => void }) {
  const knobs = KNOBS[step.op] ?? [];
  const [draft, setDraft] = useState<Record<string, number>>({});
  const value = (k: string) => draft[k] ?? Number(step.params[k] ?? (k === "strength" ? 1 : 0));
  const dirty = Object.keys(draft).length > 0;
  const c = step.checked;
  return (
    <li className={`rounded-lg border p-3 ${step.off ? "border-line opacity-60" : step.generative ? "border-ai/30 bg-ai/[0.04]" : "border-line bg-raised/30"}`}>
      <div className="flex items-start gap-2.5">
        <label className="mt-0.5 inline-flex cursor-pointer items-center">
          <input type="checkbox" className="peer sr-only" checked={!step.off} onChange={(e) => onEdit({ off: !e.target.checked })} aria-label={tv`Bật hoặc tắt bước ${OP[step.op] ?? step.op}`} />
          <span className="h-4 w-7 rounded-full bg-white/[0.12] transition-colors after:ml-0.5 after:mt-0.5 after:block after:h-3 after:w-3 after:rounded-full after:bg-white after:transition-transform peer-checked:bg-accent peer-checked:after:translate-x-3" />
        </label>
        <div className="grid min-w-0 flex-1 gap-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="mono text-[11px] text-faint">{index + 1}</span>
            <span className={`text-[13.5px] ${step.off ? "line-through" : "text-ink"}`}>{OP[step.op] ?? step.op}</span>
            {step.tier && <span className="rounded bg-white/[0.05] px-1.5 text-[11px] text-mute">{TIER[step.tier] ?? step.tier}</span>}
            {step.generative && <Tag tone="ai" dot={false}>{tr("AI sinh chi tiết")}</Tag>}
            {step.remote && <Tag tone="cue" dot={false}>{tr("gửi lên GPU thuê")}</Tag>}
            {step.edited && <span className="text-[11px] text-faint">{tr("đã chỉnh tay")}</span>}
          </div>
          {step.why && <p className="text-[12.5px] text-mute">{step.why}</p>}
          {c && <Evidence checked={c} />}
          {step.method_noise != null && <p className="text-[12px] text-faint">{tv`lượng bỏ đi / nhiễu đo được: ${fmt(step.method_noise)} (tối đa 1,0)`}</p>}
          {knobs.length > 0 && !step.off && (
            <div className="mt-1 grid gap-1.5">
              {knobs.map((k) => (
                <label key={k.key} className="grid grid-cols-[96px_1fr_44px] items-center gap-2 text-[12px]">
                  <span className="text-faint">{k.label}</span>
                  <input type="range" min={k.min} max={k.max} step={k.step} value={value(k.key)} onChange={(e) => setDraft({ ...draft, [k.key]: Number(e.target.value) })} className="accent-[#30afff]" />
                  <span className="mono text-right text-mute">{fmt(value(k.key))}</span>
                </label>))}
              {dirty && <div className="flex gap-1.5"><Button size="sm" kind="primary" onClick={() => { onEdit({ params: draft }); setDraft({}); }}>{tr("Lưu thành phiên bản mới")}</Button>
                <Button size="sm" kind="quiet" onClick={() => setDraft({})}>{tr("Hoàn tác")}</Button></div>}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

function Evidence({ checked: c }: { checked: Checked }) {
  const lines: React.ReactNode[] = [];
  if (c.niqe_ai != null) lines.push(<span key="ai">{tv`NIQE cổ điển ${fmt(c.niqe_classic)} → AI ${fmt(c.niqe_ai)}`}</span>);
  if (c.niqe_with != null && c.dark_with == null) lines.push(<span key="n">{tv`NIQE không có bước ${fmt(c.niqe_without)} → có ${fmt(c.niqe_with)}`}</span>);
  if (c.dark_with != null) lines.push(<span key="d">{tv`vùng gần đen ${fmt((c.dark_without ?? 0) * 100, 1)}% → ${fmt(c.dark_with * 100, 1)}% · cháy ${fmt((c.clipped_without ?? 0) * 100, 1)}% → ${fmt((c.clipped_with ?? 0) * 100, 1)}%`}</span>);
  if (c.judge) lines.push(<span key="j" className={c.judge.ai_better_both ? "text-proof" : "text-mute"}>{c.judge.ai_better_both ? tr("Qwen3-VL: cả hai lần nhìn đều chọn bản AI") : tr("Qwen3-VL: hai lần nhìn không cùng ý, không chặn")}{c.judge.why ? ` · ${c.judge.why}` : ""}</span>);
  else if (c.judge === null) lines.push(<span key="nj" className="text-faint">{tr("không có giám khảo hình ảnh (Ollama không chạy)")}</span>);
  return <div className="grid gap-0.5 rounded-md bg-black/20 px-2 py-1.5 text-[12px] text-mute">{lines}</div>;
}

function SourceTab({ profile: p, info }: { profile: Profile | null; info: Info }) {
  if (!p) return <p className="text-[12.5px] text-faint">{tr("Chưa có hồ sơ nguồn.")}</p>;
  const t = p.technical;
  const rows: [string, unknown][] = [
    [tr("Định dạng"), [t.container, t.codec, t.profile].filter(Boolean).join(" · ")], [tr("Kích thước"), `${t.display_width ?? t.width}×${t.display_height ?? t.height}`],
    [tr("Độ sâu màu"), t.bit_depth ? `${t.bit_depth}-bit ${t.pixel_format ?? ""}` : null], [tr("Tốc độ khung"), t.frame_rate ? `${Number(t.frame_rate).toFixed(3)} fps${t.variable_frame_rate ? tr(" (thay đổi)") : ""}` : null],
    [tr("Quét"), t.field_order], [tr("Thẻ màu"), [t.color_primaries, t.color_transfer, t.color_space, t.color_range].filter(Boolean).join(" / ") || null],
    ["HDR", t.hdr ? (t.dolby_vision ? "Dolby Vision" : String(t.hdr)) : null], [tr("Thiết bị"), t.device], [tr("Phần mềm / encoder"), t.encoder ?? t.software],
    [tr("Bitrate"), t.video_bit_rate ? `${(Number(t.video_bit_rate) / 1e6).toFixed(1)} Mb/s` : null], [tr("Dữ liệu con quay"), t.gyro === true ? tr("có") : t.gyro === false ? tr("không") : null],
    ["RAW", t.raw ? tr("có (giải mã bằng LibRaw)") : t.decoded ? tr("giải mã bằng macOS") : null], [tr("Đường dẫn"), info.path],
  ];
  return (
    <div className="grid gap-3">
      <div className="rounded-lg border border-line p-3">
        <p className="eyebrow">{tr("Profile màu")}</p>
        <p className="mt-1 text-[14px] text-ink">{p.encoding_name ?? tr("chưa rõ")} <Tag tone={p.encoding_confidence === "high" ? "proof" : p.encoding_confidence === "medium" ? "cue" : "mute"} dot={false}>{tv`độ tin ${({ high: tr("cao"), medium: tr("vừa"), low: tr("thấp") } as Record<string, string>)[p.encoding_confidence] ?? p.encoding_confidence}`}</Tag></p>
        {(p.encoding_why ?? []).map((w) => <p key={w} className="text-[12px] text-faint">{w}</p>)}
        <p className="mt-2 eyebrow">{tr("Loại nội dung")}</p>
        <p className="mt-1 text-[13px] text-ink">{CONTENT[p.content] ?? p.content}</p>
        {(p.content_why ?? []).map((w) => <p key={w} className="text-[12px] text-faint">{w}</p>)}
      </div>
      {p.warnings.length > 0 && <div className="grid gap-1 rounded-lg border border-cue/30 bg-cue/[0.05] p-3">{p.warnings.map((w) => <p key={w} className="flex gap-1.5 text-[12.5px] text-cue"><Icon name="alert" size={13} />{w}</p>)}</div>}
      <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1.5 text-[12.5px]">
        {rows.filter(([, v]) => v != null && v !== "" && v !== "undefined×undefined").map(([k, v]) => <Fragment key={k}><dt className="text-faint">{k}</dt><dd className="min-w-0 break-words text-ink">{String(v)}</dd></Fragment>)}
      </dl>
    </div>
  );
}

function QATab({ previews, shot }: { previews: Preview[]; shot: Shot }) {
  const mine = previews.filter((p) => p.t >= shot.t_start - 0.01 && p.t <= Math.max(shot.t_end, shot.t_start) + 0.01);
  const list = mine.length ? mine : previews;
  const [pick, setPick] = useState(0);
  const p = list[Math.min(pick, list.length - 1)];
  if (!p) return <p className="text-[12.5px] text-faint">{tr("Chưa có lần xem trước nào. Bấm “Xem trước shot” để kiểm tra công thức theo thời gian.")}</p>;
  return (
    <div className="grid gap-3">
      {list.length > 1 && <select value={pick} onChange={(e) => setPick(Number(e.target.value))} className="h-8 rounded-md border border-line bg-raised px-2 text-[12.5px]">
        {list.map((x, i) => <option key={x.preview_id} value={i}>{`${timecode(x.t)} · ${VERDICT_NAME[x.qa.verdict] ?? x.qa.verdict} · ${new Date(x.at * 1000).toLocaleString()}`}</option>)}</select>}
      <div className="flex items-center gap-2"><Tag tone={VERDICT[p.qa.verdict] ?? "mute"}>{tv`kiểm tra: ${VERDICT_NAME[p.qa.verdict] ?? p.qa.verdict}`}</Tag>
        {!mine.length && <span className="text-[12px] text-faint">{tr("(của shot khác)")}</span>}</div>
      {p.qa.reasons.length > 0 ? <ul className="grid gap-1">{p.qa.reasons.map((r) => <li key={r} className="text-[12.5px] text-cue">{r}</li>)}</ul>
        : <p className="text-[12.5px] text-proof">{tr("Không thấy vấn đề theo thời gian: không nhấp nháy, không trôi màu, hình đi theo chuyển động của nguồn.")}</p>}
      <table className="w-full text-[12.5px]">
        <thead><tr className="text-left text-faint"><th className="pb-1 font-normal">{tr("Thước đo")}</th><th className="pb-1 text-right font-normal">{tr("trước")}</th><th className="pb-1 text-right font-normal">{tr("sau")}</th></tr></thead>
        <tbody>
          {Object.entries(p.qa.metrics).filter(([, v]) => v[1] != null).map(([k, [b, a]]) => {
            const g = SCALED.has(k) ? Math.max(1, Number(p.qa.metrics.gain?.[1] ?? 1)) : 1;
            const better = b != null && a != null && LOWER_BETTER.has(k) ? (a < b ? "text-proof" : a > b * g * 1.05 + 0.05 ? "text-cue" : "text-ink") : "text-ink";
            return <tr key={k} className="border-t border-line/60"><td className="py-1 text-mute">{METRIC[k] ?? k}</td><td className="mono py-1 text-right text-faint">{fmt(b)}</td><td className={`mono py-1 text-right ${better}`}>{fmt(a)}</td></tr>;
          })}
        </tbody>
      </table>
    </div>
  );
}

function DefectsTab({ shot, defects }: { shot: Shot; defects: Defect[] }) {
  const scores = shot.scores ?? {};
  return (
    <div className="grid gap-3">
      {shot.defects.length === 0 ? <p className="text-[12.5px] text-proof">{tr("Không có lỗi nào vượt ngưỡng ở shot này.")}</p> : (
        <ul className="grid gap-2">
          {shot.defects.map((d) => {
            const full = defects.find((x) => x.kind === d.kind && x.t_start <= shot.t_start + 0.01 && shot.t_start <= x.t_end);
            return <li key={d.kind} className="grid gap-1">
              <div className="flex items-center justify-between text-[12.5px]"><span className="text-ink">{DEFECT[d.kind] ?? d.kind}</span>
                <span className="mono text-faint">{`${Math.round(d.severity * 100)}%${full?.value != null ? ` · ${fmt(full.value, 3)}` : ""}`}</span></div>
              <Meter share={d.severity} tone={d.severity >= 0.6 ? "ai" : d.severity >= 0.25 ? "cue" : "proof"} /></li>;
          })}
        </ul>)}
      <div className="rounded-lg border border-line p-3">
        <p className="eyebrow">{tr("Số đo của shot")}</p>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-[12px]">
          {Object.entries(scores).filter(([, v]) => typeof v === "number").map(([k, v]) => <div key={k} className="flex justify-between gap-2"><dt className="text-faint">{METRIC[k] ?? DEFECT[k] ?? k}</dt><dd className="mono text-mute">{fmt(v as number, 3)}</dd></div>)}
        </dl>
      </div>
    </div>
  );
}

function VersionsTab({ versions, current, exports, onChanged }: { versions: Version[]; current: string; exports: View["exports"]; onChanged?: () => void }) {
  const approve = async (id: string) => { try { await post(`/api/v1/vq/recipes/${id}/approve`, {}); toast(tr("Đã duyệt phiên bản này.")); onChanged?.(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } };
  return (
    <div className="grid gap-4">
      <ol className="grid gap-1.5">
        {versions.map((v) => {
          const [label, tone] = STATE[v.status] ?? [v.status, "mute"];
          return <li key={v.recipe_id} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-[12.5px] ${v.recipe_id === current ? "border-accent/40 bg-accent/[0.05]" : "border-line"}`}>
            <span className="mono text-ink">v{v.version}</span><Tag tone={tone}>{label}</Tag>
            <span className="min-w-0 flex-1 truncate text-faint">{[v.decided_by === "operator" ? tr("bạn") : v.decided_by === "policy" ? tr("tự động") : null, v.edited ? tr("có chỉnh tay") : null,
              new Date(v.at * 1000).toLocaleString()].filter(Boolean).join(" · ")}</span>
            {v.status !== "approved" && <Button size="sm" kind="quiet" onClick={() => approve(v.recipe_id)}>{tr("Duyệt bản này")}</Button>}
          </li>;
        })}
      </ol>
      <div className="grid gap-1.5">
        <p className="eyebrow">{tr("File đã xuất")}</p>
        {exports.length === 0 ? <p className="text-[12.5px] text-faint">{tr("Chưa xuất file nào. Duyệt công thức rồi bấm “Xuất file”.")}</p>
          : exports.map((f) => <a key={f.name} href={f.url} download className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-[12.5px] hover:bg-raised">
            <Icon name="download" size={14} /><span className="min-w-0 flex-1 truncate text-ink">{f.name}</span><span className="mono text-faint">{`${(f.size / 1e6).toFixed(1)} MB`}</span></a>)}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------------------ analyse and export */
function AnalyseOptions({ recipeOptions, onRun, onClose }: { recipeOptions?: Record<string, unknown>; onRun: (o: Record<string, unknown>) => void; onClose: () => void }) {
  const o = recipeOptions ?? {};
  const [flags, setFlags] = useState<Record<string, boolean>>({
    denoise: o.denoise !== false, sharpen: o.sharpen !== false, stabilise: o.stabilise !== false, exposure: o.exposure !== false, deblur: o.deblur !== false,
    relight: o.relight !== false, faces: o.faces !== false, ai: o.ai !== false, allow_cloud: o.allow_cloud === true,
  });
  const [height, setHeight] = useState<string>(o.target_height ? String(o.target_height) : "");
  const [fps, setFps] = useState<string>(o.target_fps ? String(o.target_fps) : "");
  const names: [string, string][] = [["denoise", tr("Khử nhiễu")], ["sharpen", tr("Làm nét")], ["deblur", tr("Khử mờ")], ["stabilise", tr("Ổn định hình")], ["exposure", tr("Phơi sáng, cân bằng trắng")],
    ["relight", tr("Nâng sáng cục bộ")], ["faces", tr("Phục hồi khuôn mặt")], ["ai", tr("Cho phép bước AI")], ["allow_cloud", tr("Cho gửi footage lên GPU thuê")]];
  return (
    <div className="rise w-full rounded-lg border border-edge bg-overlay p-3 shadow-xl shadow-black/40">
      <div className="grid gap-3 md:grid-cols-[1fr_auto]">
        <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 sm:grid-cols-3">
          {names.map(([k, label]) => <label key={k} className="flex items-center gap-2 text-[12.5px]">
            <input type="checkbox" checked={flags[k]} onChange={(e) => setFlags({ ...flags, [k]: e.target.checked })} />
            <span className={k === "allow_cloud" ? "text-cue" : "text-mute"}>{label}</span></label>)}
        </div>
        <div className="grid content-start gap-1.5 text-[12.5px]">
          <label className="flex items-center gap-2"><span className="w-28 text-faint">{tr("Chiều cao đích")}</span>
            <input value={height} onChange={(e) => setHeight(e.target.value.replace(/\D/g, ""))} placeholder={tr("giữ nguyên")} className="h-7 w-24 rounded-md border border-line bg-raised px-2" /></label>
          <label className="flex items-center gap-2"><span className="w-28 text-faint">{tr("Khung/giây đích")}</span>
            <input value={fps} onChange={(e) => setFps(e.target.value.replace(/[^\d.]/g, ""))} placeholder={tr("giữ nguyên")} className="h-7 w-24 rounded-md border border-line bg-raised px-2" /></label>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" kind="primary" onClick={() => onRun({ ...flags, target_height: height ? Number(height) : null, target_fps: fps ? Number(fps) : null })}>{tr("Phân tích với các tuỳ chọn này")}</Button>
        <Button size="sm" kind="quiet" onClick={onClose}>{tr("Đóng")}</Button>
        <span className="text-[12px] text-faint">{tr("Mỗi lần phân tích tạo một phiên bản công thức mới; các bản cũ vẫn còn.")}</span>
      </div>
    </div>
  );
}

function ExportButton({ base, still, disabled, onDone }: { base: string; still: boolean; disabled?: boolean; onDone?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [master, setMaster] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await post(`${base}/apply`, { export: true, master }); toast(tr("Đang xuất file theo công thức đã duyệt; file hiện ở tab Phiên bản khi xong.")); onDone?.(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(false); }
  };
  return (
    <span className="inline-flex items-center gap-1.5">
      {!still && <label className="flex items-center gap-1 text-[12px] text-faint" title={tr("ProRes 422 HQ thay vì HEVC 10-bit")}><input type="checkbox" checked={master} onChange={(e) => setMaster(e.target.checked)} />ProRes</label>}
      <Button size="sm" onClick={go} busy={busy} disabled={disabled}><Icon name="download" size={14} />{tr("Xuất file")}</Button>
    </span>
  );
}
