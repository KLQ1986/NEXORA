import { t as tr, tv } from "./i18n";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { call, megabytes, post, timecode, usePoll, type Run } from "./api";
import { ask, Button, Empty, goTo, Icon, Meter, Seg, Spinner, StageRail, Tag, toast } from "./parts";
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
  frame_rate: number | null; thumbnail_url: string | null; proxy_url: string | null;
  enhanced?: { url: string | null; stale: boolean; visual_quality?: string; visual_quality_version?: number; vq?: boolean } | null; enhance_run?: Run | null };
type View = { subject: string; info: Info; profile: Profile | null; defects: Defect[]; state: string; run: Run | null;
  recipe: { recipe_id: string; version: number; status: string; decided_by: string | null; shots: Shot[]; notes: string[]; options?: Record<string, unknown> } | null;
  approved: string | null; previews: Preview[]; versions: Version[]; exports: { name: string; size: number; at: number; url: string }[] };
export type Row = { subject: string; in_library: boolean; name: string; still: boolean | null; thumbnail_url: string | null; duration?: number | null; width?: number | null;
  height?: number | null; state: string; recipe: { recipe_id: string; version: number; status: string } | null; encoding_name: string | null; content: string | null;
  warnings: number; defects: number; worst: { kind: string; severity: number } | null; steps: number; generative: number; verdict: string | null; code?: string };
type Tool = { name: string; label: string; available: boolean; fix: string | null };

export const STATE: Record<string, [string, "mute" | "cue" | "proof" | "tally" | "accent" | "ai"]> = {
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
  match: [{ key: "amount", label: tr("mức khớp"), min: 0, max: 1, step: 0.05 }, { key: "exposure", label: tr("phơi sáng"), min: -1.5, max: 1.5, step: 0.05 },
    { key: "temperature", label: tr("nhiệt độ màu"), min: -0.35, max: 0.35, step: 0.01 }, { key: "tint", label: tr("tint"), min: -0.25, max: 0.25, step: 0.01 },
    { key: "saturation", label: tr("bão hoà"), min: -0.5, max: 0.5, step: 0.02 }],
};

const sevTone = (s: number) => (s >= 0.6 ? "tally" : s >= 0.25 ? "cue" : "proof") as "tally" | "cue" | "proof";
const sevColour = (s: number) => (s >= 0.6 ? "bg-tally" : s >= 0.25 ? "bg-cue" : s > 0 ? "bg-proof/70" : "bg-white/[0.08]");
const fmt = (v: number | null | undefined, d = 2) => (v == null ? "–" : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(d));

/* The old address of the Visual Quality screen: it now lives in the Library, a library item's in its viewer's tab, a file
   outside the library on the library's shelf of such files. */
export default function Quality() {
  useEffect(() => {
    const s = new URLSearchParams(window.location.search).get("s");
    goTo(s ? (s.startsWith("ast_") ? `/thu-vien?mo=${encodeURIComponent(s)}&tab=vq` : `/thu-vien?file=${encodeURIComponent(s)}`) : "/thu-vien");
  }, []);
  return <div className="grid flex-1 place-items-center"><Spinner /></div>;
}

/* What the library's side shows for Visual Quality besides its shelves: analysing what is waiting, the room the work takes,
   and the tools this machine (and the operator's endpoint) has. */
export function VQTools({ rows, reload }: { rows: Row[]; reload?: () => void }) {
  const tools = usePoll<{ tools: Tool[] }>("/api/v1/vq/tools", 60000).data?.tools ?? [];
  const [busy, setBusy] = useState(false);
  const waiting = rows.filter((r) => r.in_library && r.state === "none");
  const analyseAll = async () => {
    setBusy(true);
    try { for (const r of waiting) await post(`/api/v1/vq/subjects/${r.subject}/plan`, {}); toast(tv`Đã xếp ${waiting.length} mục vào hàng phân tích.`); reload?.(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(false); }
  };
  const missing = tools.filter((t) => !t.available);
  return (
    <div className="grid gap-2 px-2 pt-1 text-mini">
      {waiting.length > 0 && <Button size="sm" onClick={analyseAll} busy={busy}><Icon name="sparkles" size={13} />{tv`Phân tích ${waiting.length} mục chưa làm`}</Button>}
      <Tidy />
      <details>
        <summary className="cursor-pointer list-none text-faint">
          {tv`Công cụ trên máy: ${tools.length - missing.length}/${tools.length}`}{missing.length > 0 && <span className="ml-1 text-cue">{tv`· thiếu ${missing.length}`}</span>}
        </summary>
        <ul className="mt-2 grid gap-1">
          {tools.map((t) => <li key={t.name} className="flex items-start gap-1.5">
            <span className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${t.available ? "bg-proof" : "bg-cue"}`} />
            <span className="min-w-0"><span className={t.available ? "text-mute" : "text-ink"}>{t.label}</span>
              {!t.available && t.fix && <code className="mono block truncate text-mini text-faint">{t.fix}</code>}</span></li>)}
        </ul>
      </details>
    </div>
  );
}

/* A file outside the library, given by its path, to have only its picture quality worked on. */
export function AddVQFile({ onAdded }: { onAdded: (subject: string) => void }) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const add = async () => {
    if (!path.trim()) return;
    setBusy(true);
    try { const r = await post<{ subject: string }>("/api/v1/vq/jobs", { path: path.trim() }); setPath(""); onAdded(r.subject); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(false); }
  };
  return (
    <form className="flex gap-1.5 px-1 py-1" onSubmit={(e) => { e.preventDefault(); add(); }}>
      <input value={path} onChange={(e) => setPath(e.target.value)} placeholder={tr("Đường dẫn file trên máy, ví dụ ~/Movies/clip.mov")} autoFocus aria-label={tr("Đường dẫn file")}
             className="h-8 min-w-0 flex-1 rounded-md border border-line bg-raised px-2 text-meta outline-none focus:border-accent" />
      <Button size="sm" kind="primary" type="submit" busy={busy}>{tr("Thêm")}</Button>
    </form>
  );
}

/* How much room the engine's working files take, and a way to give back what nothing will use again. */
function Tidy() {
  const { data, reload } = usePoll<{ bytes: number }>("/api/v1/vq/usage", 60000);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { const r = await post<{ freed_bytes: number }>("/api/v1/vq/tidy", {}); toast(tv`Đã dọn ${megabytes(r.freed_bytes)}.`); reload?.(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(false); }
  };
  return (
    <div className="flex items-center gap-2 text-mini">
      <span className="flex-1 text-faint">{data ? tv`File làm việc: ${megabytes(data.bytes)}` : "…"}</span>
      <Button size="sm" kind="quiet" busy={busy} onClick={go} title={tr("Xoá file trung gian, bản xem trước cũ, file chuẩn bị của công thức không còn duyệt. Công thức, bản xuất và bản enhanced vẫn giữ.")}>{tr("Dọn")}</Button>
    </div>
  );
}

/* --------------------------------------------------------------------------------------------------------- one source */
/* One source's Visual Quality, read and acted on: shared by the Library (its picture beside the player, its panel in the
   viewer's "VQ" tab) and by the whole workspace a file outside the library opens in. An empty subject asks
   for nothing. */
export type VQ = ReturnType<typeof useVQ>;
export function useVQ(subject: string) {
  const { data, reload } = usePoll<View>(subject ? `/api/v1/vq/subjects/${subject}` : "", 2500);
  const [shotIndex, setShotIndex] = useState(0);
  const [tab, setTab] = useState<"recipe" | "source" | "qa" | "defects" | "versions">("recipe");
  const [busy, setBusy] = useState<string | null>(null);
  const [options, setOptions] = useState(false);
  const act = async (key: string, url: string, body?: object, done?: string) => {
    setBusy(key);
    try { await post(url, body ?? {}); if (done) toast(done); reload?.(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(null); }
  };
  const r = data?.recipe ?? null;
  const shots = r?.shots ?? [];
  const shot = shots[Math.min(shotIndex, Math.max(0, shots.length - 1))] as Shot | undefined;
  return { subject, data, reload, shotIndex, setShotIndex, tab, setTab, busy, act, options, setOptions, r, shots, shot,
           running: data?.state === "running", mid: shot ? (shot.t_start + shot.t_end) / 2 : 0, base: `/api/v1/vq/subjects/${subject}` };
}

/* The picture: before and after of the chosen shot, and the shots to choose from. Nothing until there is a recipe. */
export function VQStage({ vq }: { vq: VQ }) {
  const { data, r, shot, shots } = vq;
  if (!data || !r || !shot) return null;
  return (
    <div className="grid gap-2">
      <Viewer subject={vq.subject} view={data} shot={shot} shotIndex={vq.shotIndex} onRemove={vq.reload} />
      {shots.length > 1 && <ShotStrip shots={shots} index={vq.shotIndex} onPick={vq.setShotIndex} duration={data.info.duration ?? shots[shots.length - 1].t_end} />}
    </div>
  );
}

/* What is decided and what to do: the state and version, the actions, the run under way, and the recipe, checks, defects,
   source and versions of the chosen shot. Before any analysis, the way to start one. */
export function VQPanel({ vq }: { vq: VQ }) {
  const { data, r, shot, busy, act, base, running } = vq;
  if (!data) return <div className="grid place-items-center p-8"><Spinner /></div>;
  const info = data.info, p = data.profile;
  return (
    <div className="grid gap-3">
      <div className="grid gap-2.5 rounded-xl border border-line bg-raised/30 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <Tag tone={(STATE[data.state] ?? ["", "mute"])[1]}>{(STATE[data.state] ?? [data.state])[0]}</Tag>
          {r && <span className="mono text-mini text-faint">{tv`công thức v${r.version}`}</span>}
          {data.previews[0] && <span className={`text-mini ${data.previews[0].qa.verdict === "pass" ? "text-proof" : data.previews[0].qa.verdict === "warn" ? "text-cue" : "text-tally"}`}>
            {tv`QA ${VERDICT_NAME[data.previews[0].qa.verdict] ?? data.previews[0].qa.verdict}`}</span>}
        </div>
        <p className="text-mini text-faint">
          {[info.width && info.height ? `${info.width}×${info.height}` : null, p?.technical.bit_depth ? `${p.technical.bit_depth}-bit` : null,
            info.frame_rate ? `${Number(info.frame_rate).toFixed(2)} fps` : null, info.duration ? timecode(info.duration) : info.still ? tr("ảnh tĩnh") : null,
            p?.encoding_name, p ? CONTENT[p.content] ?? p.content : null].filter(Boolean).join(" · ")}</p>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => vq.setOptions((v) => !v)} disabled={running}><Icon name="sliders" size={14} />{r ? tr("Phân tích lại") : tr("Phân tích")}</Button>
          {r && <Button size="sm" disabled={running} busy={busy === "preview"} onClick={() => act("preview", `${base}/preview`, { t: info.still ? 0 : vq.mid, seconds: 3, recipe_id: r.recipe_id }, tr("Đã xếp việc xem trước shot này."))}>
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
          {data.approved && (info.in_library ? <EnhanceButton subject={vq.subject} info={info} approvedVersion={data.versions.find((v) => v.recipe_id === data.approved)?.version} onDone={vq.reload} />
            : <ExportButton base={base} still={info.still} disabled={running} onDone={vq.reload} />)}
          {running && <Button size="sm" kind="danger" busy={busy === "cancel"} onClick={() => act("cancel", `${base}/cancel`, {}, tr("Đã huỷ."))}>{tr("Huỷ")}</Button>}
        </div>
        {vq.options && <AnalyseOptions recipeOptions={r?.options} onRun={(o) => { vq.setOptions(false); act("plan", `${base}/plan`, o, tr("Đã xếp việc phân tích.")); }} onClose={() => vq.setOptions(false)} />}
      </div>
      <RunBar run={data.run} state={data.state} />
      {!r && !running && (
        <Empty icon="sparkles" title={tr("Chưa phân tích VQ")} action={<Button kind="primary" busy={busy === "plan"} onClick={() => act("plan", `${base}/plan`, {}, tr("Đã xếp việc phân tích."))}>{tr("Phân tích VQ")}</Button>}>
          {tr("Hệ thống sẽ nhận diện profile màu, đo từng shot và đề xuất công thức sửa. Chưa áp gì cho tới khi bạn duyệt.")}
        </Empty>
      )}
      {r && shot && <>
        <div className="flex flex-wrap gap-1">
          {([["recipe", tr("Công thức")], ["qa", tr("Kiểm tra")], ["defects", tr("Lỗi")], ["source", tr("Nguồn")], ["versions", tr("Phiên bản")]] as const).map(([k, l]) => (
            <button key={k} type="button" onClick={() => vq.setTab(k)} aria-pressed={vq.tab === k}
                    className={`h-7 rounded-md px-2.5 text-meta ${vq.tab === k ? "bg-accent/15 text-ink shadow-[inset_0_0_0_1px_rgba(70,200,224,0.35)]" : "text-mute hover:bg-raised hover:text-ink"}`}>{l}
              {k === "defects" && shot.defects.length > 0 && <span className="mono ml-1 text-mini text-faint">{shot.defects.length}</span>}
              {k === "versions" && <span className="mono ml-1 text-mini text-faint">{data.versions.length}</span>}
            </button>))}
        </div>
        {vq.tab === "recipe" && <RecipeTab subject={vq.subject} recipe={r} shot={shot} shotIndex={vq.shotIndex} notes={r.notes} onChanged={vq.reload} />}
        {vq.tab === "source" && <SourceTab profile={p} info={info} />}
        {vq.tab === "qa" && <QATab previews={data.previews} shot={shot} />}
        {vq.tab === "defects" && <DefectsTab shot={shot} defects={data.defects} />}
        {vq.tab === "versions" && <VersionsTab versions={data.versions} current={r.recipe_id} exports={data.exports} info={info} onChanged={vq.reload} />}
      </>}
    </div>
  );
}

/* A file outside the library: its name, then the picture and the panel side by side. */
export function Workspace({ subject }: { subject: string }) {
  const vq = useVQ(subject);
  if (!vq.data) return <div className="grid flex-1 place-items-center"><Spinner /></div>;
  const info = vq.data.info, p = vq.data.profile;
  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-3">
        <h2 className="display min-w-0 truncate text-page">{info.name}</h2>
        {!info.in_library && <Tag tone="mute" dot={false}>{tr("ngoài thư viện")}</Tag>}
        <span className="min-w-0 truncate text-meta text-faint">
          {[info.width && info.height ? `${info.width}×${info.height}` : null, p?.technical.bit_depth ? `${p.technical.bit_depth}-bit` : null,
            info.frame_rate ? `${Number(info.frame_rate).toFixed(2)} fps` : null, info.duration ? timecode(info.duration) : info.still ? tr("ảnh tĩnh") : null].filter(Boolean).join(" · ")}</span>
      </header>
      <div className="flex min-h-0 flex-1 max-xl:flex-col">
        {vq.r && vq.shot && <div className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4"><VQStage vq={vq} /></div>}
        <aside className={`min-h-0 overflow-y-auto p-4 ${vq.r && vq.shot ? "w-[440px] shrink-0 border-l border-line max-xl:w-auto max-xl:border-l-0 max-xl:border-t" : "flex-1"}`}>
          <VQPanel vq={vq} />
        </aside>
      </div>
    </div>
  );
}

function RunBar({ run, state }: { run: Run | null; state: string }) {
  if (!run || (state !== "running" && state !== "failed")) return null;
  const failedStage = run.stages.find((s) => s.status === "failed");
  return (
    <div className={`flex flex-wrap items-center gap-3 border-b border-line px-5 py-2 text-meta ${state === "failed" ? "bg-tally/[0.06]" : "bg-accent/[0.05]"}`}>
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
        <span className="text-mini text-faint">
          {preview ? tv`xem trước tại ${timecode(preview.t)} · ${preview.seconds}s` : tr("chưa xem trước shot này: đang hiện khung gốc đã chuyển màu")}</span>
        <span className="flex-1" />
        {shot.defects.some((d) => view.defects.some((x) => x.kind === d.kind && x.region)) && (
          <select value={heat ?? ""} onChange={(e) => setHeat(e.target.value || null)} className="h-7 rounded-md border border-line bg-raised px-2 text-mini">
            <option value="">{tr("Bản đồ lỗi: tắt")}</option>
            {shot.defects.map((d) => <option key={d.kind} value={d.kind}>{tv`Bản đồ: ${DEFECT[d.kind] ?? d.kind}`}</option>)}
          </select>)}
        {!info.still && <Button size="sm" kind={marking ? "primary" : "quiet"} onClick={() => { setMarking((v) => !v); setBox(null); }}><Icon name="scissors" size={14} />{marking ? tr("Đang chọn vùng xoá") : tr("Xoá vật")}</Button>}
      </div>
      <Compare before={before} after={after} beforeVideo={marking ? undefined : preview?.urls.before_video} afterVideo={marking ? undefined : preview?.urls.after_video}
               split={split} onSplit={setSplit} label={preview ? undefined : tr("khung gốc (đã chuyển màu)")}
               onMouseDown={(e) => { if (!marking) return; const [x, y] = toSource(e); drag.current = { x, y }; setBox([x, y, 0, 0]); }}
               onMouseMove={(e) => { if (!marking || !drag.current) return; const [x, y] = toSource(e); const o = drag.current; setBox([Math.min(o.x, x), Math.min(o.y, y), Math.abs(x - o.x), Math.abs(y - o.y)]); }}
               onMouseUp={() => { drag.current = null; }} marking={marking}>
        {region && <Heat grid={region} kind={heat!} />}
        {marking && <div className="absolute inset-0 cursor-crosshair bg-black/10" />}
        {box && box[2] > 0 && <div className="pointer-events-none absolute border-2 border-tally bg-tally/10" style={{ left: `${box[0] / W * 100}%`, top: `${box[1] / H * 100}%`, width: `${box[2] / W * 100}%`, height: `${box[3] / H * 100}%` }} />}
      </Compare>
      {marking && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-tally/30 bg-tally/[0.06] px-3 py-2 text-meta">
          <span className="flex-1 text-mute">{box && box[2] > 8 ? tv`Vùng ${Math.round(box[2])}×${Math.round(box[3])} px tại (${Math.round(box[0])}, ${Math.round(box[1])}), giữ cho cả shot. ProPainter lấp từ các khung lân cận.` : tr("Kéo một khung quanh vật cần xoá. Khung được giữ cho cả shot.")}</span>
          <Button size="sm" kind="primary" disabled={!box || box[2] < 8 || box[3] < 8} onClick={removeIt}>{tr("Thêm bước xoá vật")}</Button>
          <Button size="sm" kind="quiet" onClick={() => { setMarking(false); setBox(null); }}>{tr("Thôi")}</Button>
        </div>
      )}
    </div>
  );
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

/* Before and after in one frame, divided by a line that can be dragged: video when the preview has it (both played together,
   the after following the before's time), the stills otherwise. Marking a region always shows the still, to draw on it. */
function Compare({ before, after, beforeVideo, afterVideo, split, onSplit, label, marking, children, onMouseDown, onMouseMove, onMouseUp }: {
  before: string; after?: string; beforeVideo?: string; afterVideo?: string; split: number; onSplit: (v: number) => void; label?: string; marking: boolean;
  children?: React.ReactNode; onMouseDown: (e: React.MouseEvent<HTMLDivElement>) => void; onMouseMove: (e: React.MouseEvent<HTMLDivElement>) => void; onMouseUp: () => void }) {
  const a = useRef<HTMLVideoElement>(null), b = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(false);
  const [now, setNow] = useState(0);
  const [length, setLength] = useState(0);
  const video = !!beforeVideo;
  const both = video && !!afterVideo;
  const shownAfter = video ? afterVideo : after;
  useEffect(() => {
    const x = a.current, y = b.current;
    if (!x) return;
    const tick = () => { setNow(x.currentTime); if (y && Math.abs(x.currentTime - y.currentTime) > 0.06) y.currentTime = x.currentTime; };
    const meta = () => setLength(x.duration || 0);
    x.addEventListener("timeupdate", tick); x.addEventListener("seeked", tick); x.addEventListener("loadedmetadata", meta);
    return () => { x.removeEventListener("timeupdate", tick); x.removeEventListener("seeked", tick); x.removeEventListener("loadedmetadata", meta); };
  }, [beforeVideo, afterVideo]);
  useEffect(() => { setPlaying(false); setNow(0); }, [beforeVideo]);
  const toggle = () => {
    const x = a.current, y = b.current;
    if (!x) return;
    if (playing) { x.pause(); y?.pause(); setPlaying(false); return; }
    if (y) y.currentTime = x.currentTime;
    x.play(); y?.play(); setPlaying(true);
  };
  const seek = (t: number) => { if (a.current) a.current.currentTime = t; if (b.current) b.current.currentTime = t; setNow(t); };
  return (
    <div className="grid gap-2">
      <div className="relative select-none overflow-hidden rounded-lg border border-line bg-black" onMouseDown={onMouseDown} onMouseMove={onMouseMove} onMouseUp={onMouseUp}>
        {video ? <video ref={a} src={beforeVideo} muted loop playsInline className="block w-full" />
          : <img src={before} alt="" draggable={false} className="block w-full" />}
        {shownAfter && !marking && (video
          ? <video ref={b} src={afterVideo} muted loop playsInline className="absolute inset-0 block h-full w-full" style={{ clipPath: `inset(0 0 0 ${split}%)` }} />
          : <img src={after} alt="" draggable={false} className="absolute inset-0 block h-full w-full" style={{ clipPath: `inset(0 0 0 ${split}%)` }} />)}
        {shownAfter && !marking && <>
          <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white/80 shadow-[0_0_8px_rgba(0,0,0,0.6)]" style={{ left: `${split}%` }} />
          <input type="range" min={0} max={100} value={split} onChange={(e) => onSplit(Number(e.target.value))} aria-label={tr("Vị trí so sánh")}
                 className="absolute inset-0 h-full w-full cursor-ew-resize opacity-0" />
          <span className="chip absolute left-2 top-2">{tr("trước")}</span><span className="chip absolute right-2 top-2">{tr("sau")}</span>
        </>}
        {!shownAfter && !marking && <span className="chip absolute left-2 top-2">{label ?? tr("trước")}</span>}
        {children}
      </div>
      {video && !marking && (
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={toggle}><Icon name={playing ? "pause" : "play"} size={14} />{playing ? tr("Dừng") : both ? tr("Phát cả hai") : tr("Phát")}</Button>
          <input type="range" min={0} max={length || 1} step={0.01} value={now} onChange={(e) => seek(Number(e.target.value))} aria-label={tr("Tua")} className="min-w-0 flex-1 accent-[#46c8e0]" />
          <span className="mono w-[86px] text-right text-mini text-faint">{`${now.toFixed(2)} / ${length.toFixed(2)}s`}</span>
        </div>
      )}
      {!shownAfter && !marking && <p className="text-mini text-faint">{tr("Bấm “Xem trước shot” để thấy bản sau")}</p>}
    </div>
  );
}

function ShotStrip({ shots, index, onPick, duration }: { shots: Shot[]; index: number; onPick: (i: number) => void; duration: number }) {
  return (
    <div className="mt-3 grid gap-1.5">
      <p className="text-mini text-faint">{tv`${shots.length} shot · màu theo lỗi nặng nhất`}</p>
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
      <div className="flex justify-between text-mini text-faint"><span className="mono">0:00</span><span className="mono">{timecode(duration)}</span></div>
    </div>
  );
}

/* ---------------------------------------------------------------------------------------------------------- the inspector */
function RecipeTab({ subject, recipe, shot, shotIndex, notes, onChanged }: { subject: string; recipe: NonNullable<View["recipe"]>; shot: Shot; shotIndex: number; notes: string[]; onChanged?: () => void }) {
  const edit = async (step: number, body: object) => {
    try { await call(`/api/v1/vq/recipes/${recipe.recipe_id}/shots/${shotIndex}/steps/${step}`, { method: "PATCH", body: JSON.stringify(body) }); toast(tr("Đã lưu thành phiên bản mới.")); onChanged?.(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); }
  };
  return (
    <div className="grid gap-3">
      <div className="flex items-center gap-2 text-meta">
        <span className="mono text-ink">{`${timecode(shot.t_start)}–${timecode(shot.t_end)}`}</span>
        <span className="text-faint">{tv`shot ${shotIndex + 1} · ${shot.steps.filter((s) => !s.off).length} bước đang bật`}</span>
      </div>
      {shot.defects.length > 0 && <div className="flex flex-wrap gap-1">{shot.defects.map((d) => <Tag key={d.kind} tone={sevTone(d.severity)}>{`${DEFECT[d.kind] ?? d.kind} ${Math.round(d.severity * 100)}%`}</Tag>)}</div>}
      {shot.steps.length === 0 && <p className="rounded-lg border border-line p-3 text-meta text-faint">{tr("Shot này không cần xử lý.")}</p>}
      <ol className="grid gap-2">{shot.steps.map((st, j) => <StepCard key={`${recipe.recipe_id}-${j}`} step={st} index={j} onEdit={(b) => edit(j, b)} />)}</ol>
      <MatchColour subject={subject} recipeId={recipe.recipe_id} shotIndex={shotIndex} onDone={onChanged} />
      {(shot.dropped ?? []).length > 0 && (
        <div className="grid gap-1.5 rounded-lg border border-line p-3">
          <p className="eyebrow">{tr("Đã cân nhắc rồi bỏ")}</p>
          {(shot.dropped ?? []).map((d, k) => <p key={k} className="text-meta"><span className={d.failed ? "text-tally" : "text-ink"}>{OP[d.op] ?? d.op}</span>
            <span className="text-faint">{`: ${d.why}`}</span></p>)}
        </div>
      )}
      {notes.length > 0 && <div className="grid gap-1 rounded-lg border border-line p-3"><p className="eyebrow">{tr("Ghi chú")}</p>{notes.map((n) => <p key={n} className="text-meta text-mute">{n}</p>)}</div>}
    </div>
  );
}

/* Footage from different sources cut together: this subject's colour brought to another's (its shot at a time, as its own
   recipe makes it look). The result is a `match` step in a new proposed version, previewed and approved like any step. */
function MatchColour({ subject, recipeId, shotIndex, onDone }: { subject: string; recipeId: string; shotIndex: number; onDone?: () => void }) {
  const [open, setOpen] = useState(false);
  const { data } = usePoll<{ subjects: Row[] }>(open ? "/api/v1/vq/subjects" : "", 60000);
  const catalog = usePoll<{ items: { subject: string; code: string; title: string | null }[] }>(open ? "/api/v1/catalog" : "", 60000).data;
  const book = useMemo(() => new Map((catalog?.items ?? []).map((e) => [e.subject, e])), [catalog]);
  const choices = (data?.subjects ?? []).filter((r) => r.subject !== subject && r.recipe)
    .map((r) => { const e = book.get(r.subject); return { ...r, label: e ? `${e.code} · ${e.title || r.name}` : r.name }; });
  const [reference, setReference] = useState(""), [t, setT] = useState(0), [every, setEvery] = useState(false), [mode, setMode] = useState<"look" | "scene">("look"), [busy, setBusy] = useState(false);
  const picked = choices.find((c) => c.subject === reference);
  const run = async () => {
    setBusy(true);
    try {
      await post(`/api/v1/vq/recipes/${recipeId}/match`, { reference, t, mode, shot: every ? null : shotIndex });
      toast(tr("Đã thêm bước khớp màu; xem trước rồi duyệt.")); setOpen(false); onDone?.();
    } catch (e) { toast((e as Error).message, { tone: "tally" }); }
    setBusy(false);
  };
  if (!open) return <button type="button" onClick={() => setOpen(true)} className="flex items-center gap-1.5 justify-self-start rounded-md px-2 py-1 text-meta text-mute hover:bg-raised hover:text-ink"><Icon name="layers" size={13} />{tr("Khớp màu theo nguồn khác…")}</button>;
  return (
    <div className="grid gap-2 rounded-lg border border-line p-3 text-meta">
      <p className="eyebrow">{tr("Khớp màu theo nguồn khác")}</p>
      <p className="text-faint">{tr("Cho nguồn này cùng tông màu với một nguồn sẽ đứng cạnh nó khi dựng (máy khác, điện thoại, stock). Chỉ chỉnh phơi sáng, tương phản, cân bằng trắng và bão hoà; nguồn tham chiếu được lấy như công thức của nó làm ra.")}</p>
      <select value={reference} onChange={(e) => { setReference(e.target.value); setT(0); }} aria-label={tr("Nguồn tham chiếu")} className="h-8 px-2">
        <option value="">{data ? tr("Chọn nguồn tham chiếu…") : tr("Đang tải…")}</option>
        {choices.map((c) => <option key={c.subject} value={c.subject}>{c.label}</option>)}
      </select>
      {picked && !picked.still && (picked.duration ?? 0) > 0 && (
        <label className="flex items-center gap-2"><span className="w-28 shrink-0 text-faint">{tr("Lấy màu lúc")}</span>
          <input type="range" min={0} max={picked.duration ?? 0} step={0.5} value={t} onChange={(e) => setT(Number(e.target.value))} className="min-w-0 flex-1" />
          <span className="mono w-12 text-right">{timecode(t)}</span></label>)}
      <Seg label={tr("Cách khớp")} value={mode} onChange={setMode} items={[["look", tr("Tông máy quay")], ["scene", tr("Cùng cảnh")]] as const} />
      <p className="text-faint">{mode === "look" ? tr("Hai cảnh khác nhau: chỉ khớp đường cong sáng tối, cân bằng trắng (đo trên mảng xám) và độ bão hoà; màu của vật thể giữ nguyên.") : tr("Hai shot cùng một nơi: khớp cả phân bố màu. Dùng cho cảnh khác nội dung sẽ làm lệch màu vật thể (trời xanh hoá xanh lá).")}</p>
      <label className="flex items-center gap-2"><input type="checkbox" checked={every} onChange={(e) => setEvery(e.target.checked)} />{tr("Áp cho mọi shot của nguồn này (không chỉ shot đang chọn)")}</label>
      <div className="flex gap-2"><Button size="sm" kind="primary" busy={busy} disabled={!reference} onClick={run}>{tr("Khớp màu")}</Button><Button size="sm" kind="quiet" onClick={() => setOpen(false)}>{tr("Thôi")}</Button></div>
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
            <span className="mono text-mini text-faint">{index + 1}</span>
            <span className={`text-ui ${step.off ? "line-through" : "text-ink"}`}>{OP[step.op] ?? step.op}</span>
            {step.tier && <span className="rounded bg-white/[0.05] px-1.5 text-mini text-mute">{TIER[step.tier] ?? step.tier}</span>}
            {step.generative && <Tag tone="ai" dot={false}>{tr("AI sinh chi tiết")}</Tag>}
            {step.remote && <Tag tone="cue" dot={false}>{tr("gửi lên GPU thuê")}</Tag>}
            {step.edited && <span className="text-mini text-faint">{tr("đã chỉnh tay")}</span>}
          </div>
          {step.why && <p className="text-meta text-mute">{step.why}</p>}
          {c && <Evidence checked={c} />}
          {step.method_noise != null && <p className="text-mini text-faint">{tv`lượng bỏ đi / nhiễu đo được: ${fmt(step.method_noise)} (tối đa 1,0)`}</p>}
          {knobs.length > 0 && !step.off && (
            <div className="mt-1 grid gap-1.5">
              {knobs.map((k) => (
                <label key={k.key} className="grid grid-cols-[96px_1fr_44px] items-center gap-2 text-mini">
                  <span className="text-faint">{k.label}</span>
                  <input type="range" min={k.min} max={k.max} step={k.step} value={value(k.key)} onChange={(e) => setDraft({ ...draft, [k.key]: Number(e.target.value) })} className="accent-[#46c8e0]" />
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
  return <div className="grid gap-0.5 rounded-md bg-black/20 px-2 py-1.5 text-mini text-mute">{lines}</div>;
}

function SourceTab({ profile: p, info }: { profile: Profile | null; info: Info }) {
  if (!p) return <p className="text-meta text-faint">{tr("Chưa có hồ sơ nguồn.")}</p>;
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
        <p className="mt-1 text-body text-ink">{p.encoding_name ?? tr("chưa rõ")} <Tag tone={p.encoding_confidence === "high" ? "proof" : p.encoding_confidence === "medium" ? "cue" : "mute"} dot={false}>{tv`độ tin ${({ high: tr("cao"), medium: tr("vừa"), low: tr("thấp") } as Record<string, string>)[p.encoding_confidence] ?? p.encoding_confidence}`}</Tag></p>
        {(p.encoding_why ?? []).map((w) => <p key={w} className="text-mini text-faint">{w}</p>)}
        <p className="mt-2 eyebrow">{tr("Loại nội dung")}</p>
        <p className="mt-1 text-ui text-ink">{CONTENT[p.content] ?? p.content}</p>
        {(p.content_why ?? []).map((w) => <p key={w} className="text-mini text-faint">{w}</p>)}
      </div>
      {p.warnings.length > 0 && <div className="grid gap-1 rounded-lg border border-cue/30 bg-cue/[0.05] p-3">{p.warnings.map((w) => <p key={w} className="flex gap-1.5 text-meta text-cue"><Icon name="alert" size={13} />{w}</p>)}</div>}
      <dl className="grid grid-cols-[120px_1fr] gap-x-3 gap-y-1.5 text-meta">
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
  if (!p) return <p className="text-meta text-faint">{tr("Chưa có lần xem trước nào. Bấm “Xem trước shot” để kiểm tra công thức theo thời gian.")}</p>;
  return (
    <div className="grid gap-3">
      {list.length > 1 && <select value={pick} onChange={(e) => setPick(Number(e.target.value))} className="h-8 rounded-md border border-line bg-raised px-2 text-meta">
        {list.map((x, i) => <option key={x.preview_id} value={i}>{`${timecode(x.t)} · ${VERDICT_NAME[x.qa.verdict] ?? x.qa.verdict} · ${new Date(x.at * 1000).toLocaleString()}`}</option>)}</select>}
      <div className="flex items-center gap-2"><Tag tone={VERDICT[p.qa.verdict] ?? "mute"}>{tv`kiểm tra: ${VERDICT_NAME[p.qa.verdict] ?? p.qa.verdict}`}</Tag>
        {!mine.length && <span className="text-mini text-faint">{tr("(của shot khác)")}</span>}</div>
      {p.qa.reasons.length > 0 ? <ul className="grid gap-1">{p.qa.reasons.map((r) => <li key={r} className="text-meta text-cue">{r}</li>)}</ul>
        : <p className="text-meta text-proof">{tr("Không thấy vấn đề theo thời gian: không nhấp nháy, không trôi màu, hình đi theo chuyển động của nguồn.")}</p>}
      <table className="w-full text-meta">
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
      {shot.defects.length === 0 ? <p className="text-meta text-proof">{tr("Không có lỗi nào vượt ngưỡng ở shot này.")}</p> : (
        <ul className="grid gap-2">
          {shot.defects.map((d) => {
            const full = defects.find((x) => x.kind === d.kind && x.t_start <= shot.t_start + 0.01 && shot.t_start <= x.t_end);
            return <li key={d.kind} className="grid gap-1">
              <div className="flex items-center justify-between text-meta"><span className="text-ink">{DEFECT[d.kind] ?? d.kind}</span>
                <span className="mono text-faint">{`${Math.round(d.severity * 100)}%${full?.value != null ? ` · ${fmt(full.value, 3)}` : ""}`}</span></div>
              <Meter share={d.severity} tone={d.severity >= 0.6 ? "ai" : d.severity >= 0.25 ? "cue" : "proof"} /></li>;
          })}
        </ul>)}
      <div className="rounded-lg border border-line p-3">
        <p className="eyebrow">{tr("Số đo của shot")}</p>
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-mini">
          {Object.entries(scores).filter(([, v]) => typeof v === "number").map(([k, v]) => <div key={k} className="flex justify-between gap-2"><dt className="text-faint">{METRIC[k] ?? DEFECT[k] ?? k}</dt><dd className="mono text-mute">{fmt(v as number, 3)}</dd></div>)}
        </dl>
      </div>
    </div>
  );
}

function VersionsTab({ versions, current, exports, info, onChanged }: { versions: Version[]; current: string; exports: View["exports"]; info: Info; onChanged?: () => void }) {
  const approve = async (id: string) => { try { await post(`/api/v1/vq/recipes/${id}/approve`, {}); toast(tr("Đã duyệt phiên bản này.")); onChanged?.(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } };
  return (
    <div className="grid gap-4">
      <ol className="grid gap-1.5">
        {versions.map((v) => {
          const [label, tone] = STATE[v.status] ?? [v.status, "mute"];
          return <li key={v.recipe_id} className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-meta ${v.recipe_id === current ? "border-accent/40 bg-accent/[0.05]" : "border-line"}`}>
            <span className="mono text-ink">v{v.version}</span><Tag tone={tone}>{label}</Tag>
            <span className="min-w-0 flex-1 truncate text-faint">{[v.decided_by === "operator" ? tr("bạn") : v.decided_by === "policy" ? tr("tự động") : null, v.edited ? tr("có chỉnh tay") : null,
              new Date(v.at * 1000).toLocaleString()].filter(Boolean).join(" · ")}</span>
            {v.status !== "approved" && <Button size="sm" kind="quiet" onClick={() => approve(v.recipe_id)}>{tr("Duyệt bản này")}</Button>}
          </li>;
        })}
      </ol>
      {info.in_library && (
        <div className="grid gap-1.5">
          <p className="eyebrow">{tr("Bản enhanced trong Thư viện")}</p>
          {!info.enhanced?.url ? <p className="text-meta text-faint">{tr("Chưa có. Duyệt công thức rồi bấm “Tạo bản enhanced”: bản này nằm cạnh bản gốc trong Thư viện.")}</p> : (
            <div className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-meta">
              <Icon name="layers" size={14} />
              <span className="min-w-0 flex-1 text-ink">{info.enhanced.visual_quality_version ? tv`từ công thức v${info.enhanced.visual_quality_version}` : tr("bản phóng to / làm mượt")}</span>
              {info.enhanced.stale ? <Tag tone="cue">{tr("cũ")}</Tag> : <Tag tone="proof">{tr("đang dùng")}</Tag>}
              <a href={`/thu-vien`} className="text-accent hover:underline">{tr("Mở Thư viện")}</a>
              <a href={info.enhanced.url} download className="text-mute hover:text-ink"><Icon name="download" size={14} /></a>
            </div>)}
          <p className="text-mini text-faint">{tr("Bản gốc không bao giờ bị sửa. Khi dựng, hệ thống lấy bản enhanced nếu nó khớp công thức đang duyệt; nếu đã cũ thì lấy bản gốc rồi áp công thức.")}</p>
        </div>)}
      {(!info.in_library || exports.length > 0) && <div className="grid gap-1.5">
        <p className="eyebrow">{tr("File đã xuất")}</p>
        {exports.length === 0 ? <p className="text-meta text-faint">{tr("Chưa xuất file nào. Duyệt công thức rồi bấm “Xuất file”.")}</p>
          : exports.map((f) => <a key={f.name} href={f.url} download className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-meta hover:bg-raised">
            <Icon name="download" size={14} /><span className="min-w-0 flex-1 truncate text-ink">{f.name}</span><span className="mono text-faint">{`${(f.size / 1e6).toFixed(1)} MB`}</span></a>)}
      </div>}
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
          {names.map(([k, label]) => <label key={k} className="flex items-center gap-2 text-meta">
            <input type="checkbox" checked={flags[k]} onChange={(e) => setFlags({ ...flags, [k]: e.target.checked })} />
            <span className={k === "allow_cloud" ? "text-cue" : "text-mute"}>{label}</span></label>)}
        </div>
        <div className="grid content-start gap-1.5 text-meta">
          <label className="flex items-center gap-2"><span className="w-28 text-faint">{tr("Chiều cao đích")}</span>
            <input value={height} onChange={(e) => setHeight(e.target.value.replace(/\D/g, ""))} placeholder={tr("giữ nguyên")} className="h-7 w-24 rounded-md border border-line bg-raised px-2" /></label>
          <label className="flex items-center gap-2"><span className="w-28 text-faint">{tr("Khung/giây đích")}</span>
            <input value={fps} onChange={(e) => setFps(e.target.value.replace(/[^\d.]/g, ""))} placeholder={tr("giữ nguyên")} className="h-7 w-24 rounded-md border border-line bg-raised px-2" /></label>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" kind="primary" onClick={() => onRun({ ...flags, target_height: height ? Number(height) : null, target_fps: fps ? Number(fps) : null })}>{tr("Phân tích với các tuỳ chọn này")}</Button>
        <Button size="sm" kind="quiet" onClick={onClose}>{tr("Đóng")}</Button>
        <span className="text-mini text-faint">{tr("Mỗi lần phân tích tạo một phiên bản công thức mới; các bản cũ vẫn còn.")}</span>
      </div>
    </div>
  );
}

/* For a library asset, the result of the approved recipe becomes its enhanced copy in the library, next to the original. */
function EnhanceButton({ subject, info, approvedVersion, onDone }: { subject: string; info: Info; approvedVersion?: number; onDone?: () => void }) {
  const [busy, setBusy] = useState(false);
  const run = info.enhance_run;
  const making = run && (run.status === "queued" || run.status === "running");
  const current = info.enhanced && !info.enhanced.stale && info.enhanced.visual_quality_version === approvedVersion;
  const go = async () => {
    setBusy(true);
    try { await post(`/api/v1/assets/${subject}/enhance`, { vq: true }); toast(tr("Đang tạo bản enhanced theo công thức đã duyệt; nó sẽ nằm cạnh bản gốc trong Thư viện.")); onDone?.(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(false); }
  };
  if (making) return <Tag tone="accent">{tr("đang tạo bản enhanced")}</Tag>;
  if (current) return <Tag tone="proof">{tv`bản enhanced v${approvedVersion} trong Thư viện`}</Tag>;
  return <Button size="sm" onClick={go} busy={busy}><Icon name="layers" size={14} />{info.enhanced ? tr("Tạo lại bản enhanced") : tr("Tạo bản enhanced")}</Button>;
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
      {!still && <label className="flex items-center gap-1 text-mini text-faint" title={tr("ProRes 422 HQ thay vì HEVC 10-bit")}><input type="checkbox" checked={master} onChange={(e) => setMaster(e.target.checked)} />ProRes</label>}
      <Button size="sm" onClick={go} busy={busy} disabled={disabled}><Icon name="download" size={14} />{tr("Xuất file")}</Button>
    </span>
  );
}
