import { t as tr, tv } from "./i18n";
import { useEffect, useMemo, useRef, useState } from "react";
import { call, post, usePoll } from "./api";
import { Button, Empty, goTo, Icon, Spinner, toast, toggleSide } from "./parts";

/* The project's storyboard (design 2026-10-17): from an idea or the script to scenes and shots whose specs are contracts, the
   Director carrying them to acceptance, continuity at every cut and on a camera plan, and the conversation that changes it by
   typed operations shown as a diff. Everything here goes through /api/v1/projects/{id}/storyboard. */

type Crit = { check: string; by: "auto" | "human"; op: string; text: string; required: boolean; value?: unknown };
type Spec = {
  intent: string; line: string; duration: { target: number; min: number; max: number };
  framing: { size: string; angle: string; move: string; lens: string }; camera: { x: number; y: number; end?: { x: number; y: number } }; direction: string;
  source: { policy: string; query: string };
  generation: { provider: string; provider_video: string; model: string; prompt: Record<string, string>; seed: number | null };
  continuity: { entities: string[]; time_of_day: string; match_previous: boolean }; criteria: Crit[];
};
type Check = { check: string; text: string; by: string; required: boolean; st: "pass" | "fail" | "wait" | "unmeasured"; value: string };
type Cand = { asset_id: string; moment_id?: string | null; t_in: number; t_out: number; score: number | null; text: string; passed: number; of: number; failed: string[]; name: string; frame_url: string; chosen_before?: boolean };
type Treat = { speed?: number; stabilise?: boolean; live_sound?: boolean; sfx?: string | null; lipsync?: boolean; upscale_ml?: boolean };
type SbShot = { shot_id: string; code: string; scene_id: string; version: number; state: "planned" | "running" | "accepted" | "needs" | "stale"; spec: Spec;
  assignment: { kind: string; asset_id: string; t_in: number; t_out: number; score: number | null; text: string; gap_prev?: number; candidates?: Cand[]; others?: Cand[];
    name?: string; treat?: Treat; decided_by?: string } | null;
  checks: Check[]; frame_url: string | null; script_shot: string | null };
type SeamCheck = { key: string; st: "pass" | "warn" | "fail"; name: string; detail: string; value: string };
type Seam = { a: string; b: string; a_code: string; b_code: string; same_scene: boolean; checks: SeamCheck[]; worst: "pass" | "warn" | "fail"; fixes: { text: string; ops: object[] }[] };
type Plan = { scene_id: string; subject: { x: number; y: number; label: string; path?: number[] }; cams: { shot_id: string; x: number; y: number; end?: { x: number; y: number }; fov: number; crossed: boolean; aim: number }[]; crossed: string[] };
type Diff = { title: string; old: string; new: string };
type Msg = { message_id: string; role: "you" | "director"; text: string; status: string | null; proposal: { kind: string; diff: Diff[]; scope: string; summary?: string; problems?: string[] } | null };
type Board = {
  project: { project_id: string; title: string; format: string; budget_cap: number | null; spent: number };
  shared: { idea: string; seconds: number; palette: { name: string; hex: string }[]; fingerprint: string; moods: string[]; style_notes: string[]; autonomy: number };
  scenes: { scene_id: string; title: string; purpose: string; script: string; seconds: number; subject: { x: number; y: number; label: string } | null }[];
  shots: SbShot[]; seams: Seam[]; plans: Plan[]; messages: Msg[]; seconds: number; remote?: string[]; effects?: { asset_id: string; name: string }[];
  vocabulary: { sizes: string[]; angles: string[]; moves: string[]; lenses: string[]; sources: string[]; times: string[]; checks: Record<string, { text: string; by: string; op: string; value: unknown }> };
  providers: { image_providers?: { name: string; label: string; runs: string }[]; video_providers?: { name: string; label: string; runs: string }[] };
};

const STATE: Record<SbShot["state"], [string, string]> = { accepted: [tr("đạt"), "proof"], needs: [tr("cần bạn"), "ai"], running: [tr("đang làm"), "accent"], planned: [tr("đã lên"), "mute"], stale: [tr("cần kiểm lại"), "cue"] };
const SRC: Record<string, [string, string]> = { footage: [tr("Footage"), "#4fd1a5"], generate: [tr("AI"), "#ff8c52"], stock: [tr("Stock"), "#c9a7ff"], any: [tr("Bất kỳ"), "#a7b2c6"] };
const SEAM: Record<string, [string, string]> = { pass: [tr("liền"), "#4fd1a5"], warn: [tr("cần xem"), "#f5c451"], fail: [tr("đứt"), "#ff6b6b"] };
const MARK: Record<string, [string, string]> = { pass: ["✓", "bg-proof"], fail: ["✕", "bg-tally"], wait: ["?", "bg-cue"], unmeasured: ["–", "bg-white/20"], warn: ["!", "bg-cue"] };
const TONE = ["#2f5a47", "#3b4a3a", "#4d5a2f", "#5a4a35", "#2f4a5a", "#5a3f2f", "#4a3f5a", "#355a3c"];
const chip = (tone: string) => ({ proof: "bg-proof/15 text-proof", ai: "bg-ai/15 text-ai", accent: "bg-accent/15 text-accent", cue: "bg-cue/15 text-cue", mute: "bg-white/[0.06] text-mute" } as Record<string, string>)[tone] ?? "";
const mmss = (v: number) => `${Math.floor(v / 60)}:${String(Math.floor(v % 60)).padStart(2, "0")}`;
const lensFov = (lens: string) => { const n = parseInt(lens, 10) || 35; return n <= 24 ? 84 : n <= 35 ? 64 : n <= 50 ? 46 : n <= 85 ? 29 : 22; };

/* A text that saves when it is left (one version per edit, not per key). */
function Field({ value, onSave, area, label, placeholder }: { value: string; onSave: (v: string) => void; area?: boolean; label: string; placeholder?: string }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  const cls = "w-full rounded-md border border-line bg-canvas px-2.5 py-1.5 text-[13px] text-ink outline-none focus:border-accent";
  const save = () => { if (v.trim() !== value.trim()) onSave(v); };
  return (
    <label className="grid gap-1 text-[12px] text-faint">{label}
      {area ? <textarea rows={2} value={v} onChange={(e) => setV(e.target.value)} onBlur={save} placeholder={placeholder} className={`${cls} resize-y leading-relaxed`} />
        : <input value={v} onChange={(e) => setV(e.target.value)} onBlur={save} onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} placeholder={placeholder} className={cls} />}
    </label>
  );
}

function Pick({ label, value, items, onPick }: { label: string; value: string; items: readonly string[]; onPick: (v: string) => void }) {
  return (
    <label className="grid gap-1 text-[12px] text-faint">{label}
      <select value={value} onChange={(e) => onPick(e.target.value)} className="h-8 rounded-md border border-line bg-canvas px-2 text-[13px] text-ink">
        {items.map((x) => <option key={x} value={x}>{x || "—"}</option>)}
      </select>
    </label>
  );
}

export default function Storyboard({ projectId, back }: { projectId: string; back: () => void }) {
  const url = `/api/v1/projects/${projectId}/storyboard`;
  const { data, reload, set: show } = usePoll<Board>(url, 5000);
  const [sel, setSel] = useState<string | null>(null);
  const [seam, setSeam] = useState<string | null>(null);
  const [view, setView] = useState<"board" | "time" | "plan" | "copilot">("board");
  const [tab, setTab] = useState<"goal" | "source" | "gen" | "cont" | "crit" | "hist">("source");
  const [busy, setBusy] = useState<string | null>(null);
  const [sharedOpen, setSharedOpen] = useState(false);
  // The shot list repeats the board in words: folded by default so the board has the width, opened for a long storyboard.
  const [outline, setOutlineState] = useState(() => { try { return localStorage.getItem("nx.sb.outline") === "1"; } catch { return false; } });
  const setOutline = (v: boolean) => { setOutlineState(v); try { localStorage.setItem("nx.sb.outline", v ? "1" : "0"); } catch { /* private window */ } };
  const shots = data?.shots ?? [];
  const cur = shots.find((s) => s.shot_id === sel) ?? shots[0];
  const act = async (key: string, fn: () => Promise<unknown>, done?: string) => {
    setBusy(key);
    try { await fn(); if (done) toast(done); reload(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(null); }
  };
  // A change shows the storyboard the server answered with, at once, on every view (board, timeline, plan).
  const ops = (list: object[], note?: string) => act("ops", async () => { const r = await post<{ storyboard?: Board }>(`${url}/ops`, { ops: list, note }); if (r.storyboard) show(r.storyboard); });
  // Alt+← / Alt+→ move the chosen shot one place back or on, across scenes too, as dragging its card would.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (!e.altKey || (e.key !== "ArrowLeft" && e.key !== "ArrowRight") || !cur) return;
      if ((e.target as HTMLElement)?.closest("input, textarea, select, [contenteditable]")) return;
      const i = shots.findIndex((x) => x.shot_id === cur.shot_id);
      const to = shots[e.key === "ArrowLeft" ? i - 1 : i + 1];
      if (!to) return;
      e.preventDefault();
      ops([e.key === "ArrowLeft" ? { op: "move", shot: cur.shot_id, before: to.shot_id } : { op: "move", shot: cur.shot_id, after: to.shot_id }], tr("đổi thứ tự"));
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  const set = (shot: SbShot, field: string, value: unknown) => ops([{ op: "set", shot: shot.shot_id, field, value }]);

  if (!data) return <div className="grid flex-1 place-items-center"><Spinner /></div>;
  if (!shots.length) return <Start url={url} title={data.project.title} back={back} onMade={reload} messages={data.messages} />;

  const sceneOf = new Map(data.scenes.map((s, k) => [s.scene_id, k]));
  const tone = (s: SbShot) => TONE[(sceneOf.get(s.scene_id) ?? 0) * 3 % TONE.length + (s.code.length % 2)];
  const counts = shots.reduce((c, s) => ({ ...c, [s.state]: (c[s.state] ?? 0) + 1 }), {} as Record<string, number>);
  const curSeam = data.seams.find((x) => `${x.a}-${x.b}` === seam);
  const cap = data.project.budget_cap;
  const stages: [string, string, () => void][] = [
    [tr("Kịch bản"), tv`${shots.filter((s) => s.spec.line).length} câu`, () => goTo(`/du-an/${projectId}?tab=script`)],
    [tr("Storyboard"), tv`${data.scenes.length} cảnh · ${shots.length} shot`, () => setView("board")],
    [tr("Shot plan"), tv`${shots.reduce((n, s) => n + s.spec.criteria.length, 0)} tiêu chí`, () => { setView("board"); setTab("crit"); }],
    [tr("Gán asset"), tv`${counts.accepted ?? 0}/${shots.length} đạt`, () => { setView("board"); setTab("source"); }],
    [tr("Timeline nháp"), `${data.seconds}s`, () => setView("time")],
    [tr("Render"), tr("ở trang dự án"), () => goTo(`/du-an/${projectId}?tab=cut`)],
  ];
  const stageNow = view === "time" ? 4 : tab === "crit" ? 2 : tab === "source" ? 3 : 1;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-2.5">
        <button type="button" onClick={toggleSide} className="hidden h-8 w-8 shrink-0 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink lg:grid" title={tr("Ẩn/hiện menu bên (phím [)")} aria-label={tr("Ẩn/hiện menu bên (phím [)")}><Icon name="collapse" size={16} /></button>
        <button type="button" onClick={back} title={tr("Về trang dự án")} className="flex min-w-0 shrink items-center gap-1 text-[13px] text-mute transition-colors hover:text-ink"><Icon name="back" size={16} /><span className="truncate">{data.project.title}</span></button>
        <span className="text-edge">/</span>
        <h1 className="display shrink-0 text-[16px]">{tr("Storyboard")}</h1>
        <span className="mono rounded border border-line px-1.5 text-[11px] text-faint">{({ landscape: "16:9", portrait: "9:16", square: "1:1" } as Record<string, string>)[data.project.format] ?? data.project.format} · {data.seconds}s / {data.shared.seconds}s</span>
        <span className="flex-1" />
        <span className="flex items-center gap-2 text-[12px] text-mute">{tr("Chi phí")}
          {cap ? <span className="h-1.5 w-24 overflow-hidden rounded bg-white/[0.08]"><span className="block h-full bg-accent" style={{ width: `${Math.min(100, (data.project.spent / cap) * 100)}%` }} /></span> : null}
          <span className="mono text-ink">${data.project.spent.toFixed(2)}{cap ? ` / $${cap}` : ""}</span></span>
        <label className="flex items-center gap-1.5 text-[12px] text-mute">{tr("Tự chủ")}
          <select value={data.shared.autonomy} onChange={(e) => act("auto", () => call(`${url}/shared`, { method: "PATCH", body: JSON.stringify({ autonomy: Number(e.target.value) }) }))}
                  className="h-8 rounded-md border border-line bg-canvas px-2 text-[12.5px] text-ink">
            <option value={1}>{tr("Mức 1: Director đề xuất, bạn duyệt")}</option>
            <option value={2}>{tr("Mức 2: tự nhận shot footage đạt")}</option>
            <option value={3}>{tr("Mức 3: tự nhận cả shot AI")}</option>
          </select></label>

        {shots.some((s) => s.spec.source.policy === "generate") && <Button size="sm" busy={busy === "keys"} onClick={() => act("keys", () => post(`${url}/keyframes`), tr("Đã xếp việc tạo ảnh khung cho các shot AI."))}>
          <Icon name="sparkles" size={14} />{tr("Tạo ảnh khung")}</Button>}
        <Button size="sm" busy={busy === "run"} onClick={() => act("run", () => post(`${url}/run`, {}), tr("Director đã chạy một lượt."))}><Icon name="play" size={14} />{tr("Chạy Director")}</Button>
        <Button size="sm" kind="primary" busy={busy === "approve"} title={tr("Ghi storyboard vào kịch bản cùng hình, phương án và cách xử lý của từng shot; duyệt clip; sang bước dựng")}
                onClick={() => act("approve", async () => {
                  const r = await post<{ pictured: number; missing: number }>(`${url}/approve`);
                  toast(r.missing ? tv`Đã duyệt ${r.pictured} shot; ${r.missing} shot chưa có hình sẽ là nền trơn kèm phụ đề.` : tv`Đã duyệt ${r.pictured} shot.`, { tone: r.missing ? "tally" : "proof" });
                  goTo(`/du-an/${projectId}?tab=cut`);
                })}><Icon name="check" size={14} />{tr("Duyệt storyboard → Dựng")}</Button>
      </header>

      <nav aria-label={tr("Các bước")} className="scroll-x flex shrink-0 items-center gap-1 border-b border-line px-4 py-1.5">
        {stages.map(([label, note, go], k) => (
          <span key={label} className="flex items-center gap-1">
            <button type="button" onClick={go} aria-current={k === stageNow ? "step" : undefined}
                    className={`flex h-9 items-center gap-2 whitespace-nowrap rounded-lg border px-3 text-[13px] ${k === stageNow ? "border-accent/40 bg-accent/10 text-ink" : "border-transparent text-mute hover:text-ink"}`}>
              <span className={`grid h-5 w-5 place-items-center rounded-full text-[11px] font-semibold ${k < stageNow ? "bg-proof text-canvas" : k === stageNow ? "bg-accent text-canvas" : "bg-white/[0.08] text-mute"}`}>{k + 1}</span>
              {label}<span className="text-[11px] text-faint">{note}</span></button>
            {k < stages.length - 1 && <span aria-hidden className="text-faint/50">›</span>}
          </span>
        ))}
      </nav>

      <Shared board={data} url={url} open={sharedOpen} setOpen={setSharedOpen} onSaved={reload} />

      <div className="flex min-h-0 flex-1 gap-2 p-2 max-lg:flex-col">
        {outline && <aside aria-label={tr("Cảnh và shot")} className="flex w-[230px] shrink-0 flex-col overflow-hidden rounded-xl border border-line bg-surface max-lg:hidden">
          <div className="border-b border-line p-3"><Field label={tr("Ý tưởng")} area value={data.shared.idea} onSave={(v) => act("idea", () => call(`${url}/shared`, { method: "PATCH", body: JSON.stringify({ idea: v }) }))} /></div>
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {data.scenes.map((sc) => (
              <div key={sc.scene_id}>
                <p className="eyebrow px-1.5 pb-1 pt-2.5">{sc.title}</p>
                {shots.filter((s) => s.scene_id === sc.scene_id).map((s) => (
                  <button key={s.shot_id} type="button" onClick={() => { setSel(s.shot_id); setSeam(null); }}
                          className={`flex w-full items-center gap-1.5 rounded-md px-1.5 py-1.5 text-left text-[12.5px] ${s.shot_id === cur?.shot_id && !seam ? "bg-accent/10 text-ink" : "text-mute hover:bg-raised hover:text-ink"}`}>
                    <span className="mono w-8 shrink-0 text-[11px] text-faint">{s.code}</span><span className="min-w-0 flex-1 truncate">{s.spec.intent}</span>
                    <span className={`h-2 w-2 shrink-0 rounded-full ${s.state === "planned" ? "border border-faint" : ({ accepted: "bg-proof", needs: "bg-ai", running: "bg-accent", stale: "bg-cue" } as Record<string, string>)[s.state]}`} />
                  </button>))}
              </div>))}
          </div>
          <div className="grid grid-cols-2 gap-1.5 border-t border-line px-3 py-2.5 text-[11.5px] text-mute">
            {(["accepted", "needs", "running", "planned", "stale"] as const).filter((k) => counts[k]).map((k) => <span key={k}>{STATE[k][0]} {counts[k]}</span>)}
          </div>
        </aside>}

        <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-surface">
          <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
            <button type="button" onClick={() => setOutline(!outline)} aria-pressed={outline} title={outline ? tr("Ẩn danh sách shot và ý tưởng") : tr("Hiện danh sách shot và ý tưởng")}
                    className={`hidden h-8 items-center gap-1.5 rounded-md border px-2.5 text-[12.5px] lg:flex ${outline ? "border-accent/40 bg-accent/10 text-ink" : "border-line text-mute hover:text-ink"}`}><Icon name="list" size={14} />{tr("Danh sách shot")}</button>
            <div className="seg" role="radiogroup" aria-label={tr("Cách xem")}>
              {([["board", tr("Storyboard")], ["time", tr("Timeline nháp")], ["plan", tr("Mặt bằng máy")], ["copilot", "Copilot"]] as const).map(([k, l]) =>
                <button key={k} type="button" role="radio" aria-checked={view === k} onClick={() => setView(k)}>{l}</button>)}
            </div>
            <span className="text-[12px] text-faint">{tv`${shots.length} shot · ${data.seconds}s / mục tiêu ${data.shared.seconds}s`}</span>
            <span className="flex-1" />
            <Button size="sm" kind="quiet" onClick={() => ops([{ op: "insert", after: cur?.shot_id, spec: { intent: tr("Shot mới"), duration: 4, source: "any" } }], tr("thêm shot"))}><Icon name="plus" size={13} />{tr("Thêm shot")}</Button>
          </div>
          {view === "board" && <BoardView board={data} cur={cur} seam={seam} tone={tone} pick={(id) => { setSel(id); setSeam(null); }} pickSeam={setSeam}
                                          move={(o) => ops([{ op: "move", ...o }], tr("đổi thứ tự"))} />}
          {view === "time" && <TimeView board={data} cur={cur} tone={tone} pick={(id) => { setSel(id); setSeam(null); }} pickSeam={setSeam} />}
          {view === "copilot" && <CopilotView url={url} board={data} shots={shots.length} onApplied={() => { reload(); setView("board"); }} />}
          {view === "plan" && <PlanView board={data} cur={cur} pick={(id) => { setSel(id); setSeam(null); }} flip={(id) => ops([{ op: "flip_camera", shot: id }], tr("lật sang bên kia trục"))} />}
        </main>

        <aside className="flex w-[480px] shrink-0 flex-col gap-2 max-lg:w-auto">
          {curSeam ? <SeamPanel seam={curSeam} board={data} tone={tone} close={() => setSeam(null)} fix={(list, text) => { ops(list, text); setSeam(null); }} />
            : cur && <Inspector shot={cur} board={data} url={url} tab={tab} setTab={setTab} set={set} ops={ops} act={act} busy={busy} />}
          <Chat board={data} url={url} cur={cur} onDone={reload} />
        </aside>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------------------------------- an empty storyboard */
function Start({ url, title, back, onMade, messages }: { url: string; title: string; back: () => void; onMade: () => void; messages: Msg[] }) {
  const [idea, setIdea] = useState(""), [seconds, setSeconds] = useState(60), [busy, setBusy] = useState<string | null>(null);
  const open = [...messages].reverse().find((m) => m.proposal && m.status === "open" && m.proposal.kind !== "copilot");
  const run = async (key: string, fn: () => Promise<unknown>) => { setBusy(key); try { await fn(); onMade(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } setBusy(null); };
  return (
    <div className="flex flex-1 flex-col">
      <header className="flex items-center gap-3 border-b border-line px-4 py-2.5">
        <button type="button" onClick={back} className="flex h-8 items-center gap-1.5 rounded-md border border-line px-2.5 text-[13px] text-mute hover:text-ink"><Icon name="back" size={14} />{tr("Dự án")}</button>
        <h1 className="display text-[16px]">{title}</h1>
      </header>
      <div className="grid flex-1 place-items-center p-6">
        <div className="grid w-full max-w-2xl gap-4">
          <Empty icon="layers" title={tr("Chưa có storyboard")}>{tr("Dựng từ ý tưởng (Director đề xuất cảnh và shot, bạn áp dụng) hoặc từ kịch bản dự án đang có (mỗi câu thành một shot).")}</Empty>
          <div className="grid gap-2 rounded-xl border border-line p-4">
            <label className="grid gap-1 text-[12.5px] text-faint">{tr("Ý tưởng")}
              <textarea rows={3} value={idea} onChange={(e) => setIdea(e.target.value)} placeholder={tr("Ví dụ: một ngày làm vườn của chú Tư ở Bến Tre, từ bình minh tới hoàng hôn; nhẹ nhàng, ấm")}
                        className="rounded-md border border-line bg-canvas px-3 py-2 text-[13.5px] text-ink outline-none focus:border-accent" /></label>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 text-[12.5px] text-faint">{tr("Thời lượng (giây)")}<input type="number" value={seconds} min={10} max={1800} onChange={(e) => setSeconds(Number(e.target.value))} className="h-8 w-20 rounded-md border border-line bg-canvas px-2 text-ink" /></label>
              <span className="flex-1" />
              <Button kind="primary" busy={busy === "idea"} disabled={!idea.trim()} onClick={() => run("idea", () => post(`${url}/idea`, { idea, seconds }))}><Icon name="sparkles" size={14} />{tr("Director đề xuất storyboard")}</Button>
              <Button busy={busy === "script"} onClick={() => run("script", () => post(`${url}/from-script`))}>{tr("Từ kịch bản dự án")}</Button>
            </div>
          </div>
          <details className="group rounded-xl border border-line p-4" open={messages.some((m) => m.proposal?.kind === "copilot" && m.status === "open")}>
            <summary className="flex cursor-pointer list-none items-center gap-2 text-[13px]"><Icon name="sparkles" size={14} className="text-ai" />
              <span className="font-medium">{tr("Copilot: dựng từ bản ghi có người nói")}</span><span className="text-faint">{tr("(phỏng vấn, nói trước máy: rút ngắn, giữ luận điểm, bỏ lặp)")}</span></summary>
            <div className="mt-3 -mx-3"><CopilotView url={url} board={{ messages }} onApplied={onMade} /></div>
          </details>
          {open && open.proposal?.kind !== "copilot" && <Proposal m={open} url={url} onDone={onMade} />}
          {!open && messages.length > 0 && <p className="text-[12.5px] text-faint">{messages[messages.length - 1].text}</p>}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------------------------------- the look of the whole film */
function Shared({ board, url, open, setOpen, onSaved }: { board: Board; url: string; open: boolean; setOpen: (v: boolean) => void; onSaved: () => void }) {
  const s = board.shared;
  const save = async (body: object) => { try { await call(`${url}/shared`, { method: "PATCH", body: JSON.stringify(body) }); onSaved(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } };
  return (
    <section aria-label={tr("Chung cho mọi shot")} className="grid shrink-0 gap-2.5 border-b border-line px-4 py-2">
      <div className="flex min-h-7 flex-wrap items-center gap-3">
        <span className="eyebrow">{tr("Chung cho mọi shot")}</span>
        <span className="mono rounded border border-line px-1.5 text-[11px] text-mute">{tv`${board.shots.length} cut`}</span>
        <span className="flex gap-1" role="img" aria-label={tr("Bảng màu")}>{s.palette.map((p) => <span key={p.hex + p.name} title={`${p.name} ${p.hex}`} className="h-[18px] w-[18px] rounded border border-white/20" style={{ background: p.hex }} />)}</span>
        <span className="min-w-0 flex-[1_1_260px] truncate text-[12px] text-mute"><span className="text-faint">{tr("Bối cảnh")} </span>{s.fingerprint || "—"}</span>
        <span className="flex flex-wrap gap-1.5">{s.moods.map((m) => <span key={m} className="rounded-full bg-white/[0.06] px-2 text-[11.5px] text-mute">{m}</span>)}</span>
        <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="h-7 rounded-md border border-line px-2.5 text-[12px] text-accent">{open ? tr("Thu gọn") : tr("Chi tiết")}</button>
      </div>
      {open && (
        <div className="grid gap-4 pb-1 md:grid-cols-3">
          <div className="grid content-start gap-1.5">
            <span className="text-[12px] text-faint">{tr("Bảng màu")}</span>
            {[...s.palette, { name: "", hex: "#808080" }].map((p, k) => (
              <div key={k} className="flex items-center gap-2">
                <input type="color" value={p.hex} aria-label={tr("Màu")} onChange={(e) => save({ palette: Object.assign([...s.palette], { [k]: { name: p.name || tr("Màu mới"), hex: e.target.value } }) })} className="h-6 w-8 rounded border-0 bg-transparent" />
                <input defaultValue={p.name} placeholder={k === s.palette.length ? tr("Thêm màu…") : ""} aria-label={tr("Tên màu")}
                       onBlur={(e) => { const name = e.target.value.trim(); if (name === p.name) return; save({ palette: name || k < s.palette.length ? Object.assign([...s.palette], { [k]: { name, hex: p.hex } }).filter((x) => x.name) : s.palette }); }}
                       className="h-7 min-w-0 flex-1 rounded-md border border-line bg-canvas px-2 text-[12.5px] text-ink" />
                <span className="mono text-[11px] text-faint">{p.hex}</span>
              </div>))}
          </div>
          <div className="grid content-start gap-2">
            <Field label={tr("Dấu vân tay bối cảnh")} area value={s.fingerprint} onSave={(v) => save({ fingerprint: v })} />
            <Field label={tr("Giọng điệu (cách nhau bằng dấu phẩy)")} value={s.moods.join(", ")} onSave={(v) => save({ moods: v.split(",").map((x) => x.trim()).filter(Boolean) })} />
          </div>
          <div className="grid content-start gap-2">
            <label className="grid gap-1 text-[12px] text-faint">{tr("Phong cách quay (mỗi dòng một ý)")}
              <textarea rows={4} defaultValue={s.style_notes.join("\n")} onBlur={(e) => save({ style_notes: e.target.value.split("\n").map((x) => x.trim()).filter(Boolean) })}
                        className="rounded-md border border-line bg-canvas px-2.5 py-1.5 text-[13px] text-ink outline-none focus:border-accent" /></label>
            <span className="text-[12px] text-faint">{tr("Director dùng các lựa chọn này khi dựng storyboard và tạo hình; ghi vào kịch bản thì chúng thành phong cách của dự án.")}</span>
          </div>
        </div>
      )}
    </section>
  );
}

/* ----------------------------------------------------------------------------------------------------- the board, by scene */
function BoardView({ board, cur, seam, tone, pick, pickSeam, move }: { board: Board; cur?: SbShot; seam: string | null; tone: (s: SbShot) => string; pick: (id: string) => void; pickSeam: (id: string) => void;
  move: (op: { shot: string; before?: string; scene?: string }) => void }) {
  const seamBefore = new Map(board.seams.map((x) => [x.b, x]));
  // A card is carried by hand: dropped on another it goes before it, dropped on a scene's last place it ends that scene.
  const [drag, setDrag] = useState<string | null>(null), [over, setOver] = useState<string | null>(null);
  const end = () => { setDrag(null); setOver(null); };
  const drop = (e: React.DragEvent, target: { before?: string; scene?: string }) => {
    e.preventDefault();
    const id = drag ?? e.dataTransfer.getData("text/plain");
    end();
    if (id && id !== target.before) move({ shot: id, ...target });
  };
  return (
    <div className="grid min-h-0 flex-1 content-start gap-5 overflow-y-auto p-3">
      {board.scenes.map((sc) => (
        <section key={sc.scene_id} className="grid gap-2.5">
          <div className="flex flex-wrap items-baseline gap-2.5"><h2 className="text-[14px] font-semibold">{sc.title}</h2><span className="text-[12px] text-faint">{sc.purpose}</span><span className="mono text-[11px] text-mute">{sc.seconds}s</span></div>
          {sc.script && <p className="border-l-2 border-line pl-2.5 text-[12.5px] leading-relaxed text-mute"><span className="text-faint">{tr("Kịch bản cảnh · ")}</span>{sc.script}</p>}
          {/* Three shots a row, each as wide as its column, so a scene reads as a sheet and a long scene wraps onto rows. A seam that is
              clean stays out of the way; one that needs a look (or is broken) flags the shot it leads into, and opens its panel. */}
          <div className="grid grid-cols-3 items-start gap-x-4 gap-y-5 pb-1 max-md:grid-cols-2 max-[480px]:grid-cols-1">
            {board.shots.filter((s) => s.scene_id === sc.scene_id).map((s) => {
              const sm = seamBefore.get(s.shot_id);
              const flagged = sm && sm.worst !== "pass";
              return (
                <div key={s.shot_id} draggable onDragStart={(e) => { setDrag(s.shot_id); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", s.shot_id); }}
                     onDragEnd={end} onDragOver={(e) => { if (drag && drag !== s.shot_id) { e.preventDefault(); setOver(s.shot_id); } }} onDragLeave={() => setOver((o) => (o === s.shot_id ? null : o))}
                     onDrop={(e) => drop(e, { before: s.shot_id })}
                     className={`relative grid min-w-0 cursor-grab content-start gap-2 active:cursor-grabbing ${drag === s.shot_id ? "opacity-40" : ""}`}>
                  {over === s.shot_id && <span className="pointer-events-none absolute -left-2.5 bottom-0 top-0 w-[3px] rounded-full bg-accent shadow-[0_0_8px_var(--color-accent)]" aria-hidden="true" />}
                  {sm && flagged && <button type="button" onClick={() => pickSeam(`${sm.a}-${sm.b}`)} title={tv`Mối nối ${sm.a_code} → ${sm.b_code}: ${SEAM[sm.worst][0]}`}
                                            className={`flex h-[22px] items-center justify-self-start rounded-full border px-2 text-[11px] ${seam === `${sm.a}-${sm.b}` ? "border-accent" : ""}`}
                                            style={{ color: SEAM[sm.worst][1], background: `${SEAM[sm.worst][1]}1f`, borderColor: seam === `${sm.a}-${sm.b}` ? undefined : `${SEAM[sm.worst][1]}66` }}>
                    {tv`Mối nối ${sm.a_code} → ${sm.b_code}: ${SEAM[sm.worst][0]}`}</button>}
                  {!flagged && <span className="h-[22px]" aria-hidden="true" />}{/* the chip's line kept, so the cards of a row stay level */}
                  <ShotCard s={s} on={s.shot_id === cur?.shot_id && !seam} tone={tone(s)} pick={() => pick(s.shot_id)} />
                </div>);
            })}
            {drag && <div onDragOver={(e) => { e.preventDefault(); setOver(`end-${sc.scene_id}`); }} onDragLeave={() => setOver(null)} onDrop={(e) => drop(e, { scene: sc.scene_id })}
                          className={`mt-[30px] grid aspect-video place-items-center rounded-lg border-2 border-dashed text-[12px] ${over === `end-${sc.scene_id}` ? "border-accent bg-accent/10 text-ink" : "border-line text-faint"}`}>
              {tr("Thả vào cuối cảnh")}</div>}
          </div>
        </section>))}
    </div>
  );
}

/* ------------------------------------------------------------------------------------------- the Copilot (a mode) */
type Decision = { decision_id: string; sentence: number; asset_id: string; text: string; t_in: number; t_out: number; seconds: number;
  action: "KEEP" | "REMOVE" | "MOVE"; reasons: string[]; confidence: number; review: "proposed" | "needs_review"; required?: boolean; protect: string[];
  evidence: { transcript: string; range: [number, number]; observed: string[]; inferred: { role?: string; weight?: number; why?: string } } };
type CopilotProposal = { kind: "copilot"; goal: string; target_seconds: number | null; decisions: Decision[]; notes: string[];
  coverage: { point: string; sentences: number[]; kept: boolean }[]; summary: { source_seconds: number; kept_seconds: number; keep: number; move: number; remove: number; review: number } };
type Source = { asset_id: string; name: string; sentences: number; spoken_seconds: number; duration: number | null; media_url: string };
const PRESET_NAMES: [string, string][] = [["shorten", tr("Rút ngắn")], ["opening", tr("Mở đầu mạnh hơn")], ["repetition", tr("Bỏ lặp ý")], ["vertical", tr("Bản dọc")]];

/** The Semantic Editing Copilot: a goal over recordings someone speaks in, answered with a decision per sentence (keep,
    remove, move to the front), each with its reason, what was measured and what the model read, and how sure it is; the
    operator turns any of them over, then applies, and the kept sentences become the storyboard's shots with their own sound. */
function CopilotView({ url, board, onApplied, shots = 0 }: { url: string; board: { messages: Msg[] }; onApplied: () => void; shots?: number }) {
  const { data: src } = usePoll<{ sources: Source[] }>(`${url}/copilot/sources`, 60000);
  const [chosen, setChosen] = useState<string[]>([]);
  const [presets, setPresets] = useState<string[]>(["shorten", "repetition"]);
  const [target, setTarget] = useState("45");
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [keep, setKeep] = useState<Record<string, boolean>>({});
  const [onlyReview, setOnlyReview] = useState(false);
  const player = useRef<HTMLVideoElement>(null);
  const open = [...board.messages].reverse().find((m) => m.proposal?.kind === "copilot" && m.status === "open");
  const p = open?.proposal as unknown as CopilotProposal | undefined;
  useEffect(() => { if (p) setKeep(Object.fromEntries(p.decisions.map((d) => [d.decision_id, d.action !== "REMOVE"]))); }, [open?.message_id]);
  useEffect(() => { if (src?.sources.length && !chosen.length) setChosen([src.sources[0].asset_id]); }, [src]);
  const sources = src?.sources ?? [];
  const urlOf = Object.fromEntries(sources.map((x) => [x.asset_id, x.media_url]));
  const kept = p ? p.decisions.filter((d) => keep[d.decision_id]) : [];
  const seconds = kept.reduce((t, d) => t + d.seconds, 0);
  const propose = async () => {
    setBusy("propose");
    try { await post(`${url}/copilot`, { assets: chosen, presets, target_seconds: presets.includes("shorten") ? Number(target) || null : null, goal }); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); }
    setBusy(null);
  };
  const apply = async () => {
    if (!open) return;
    if (shots && !window.confirm(tv`Thay storyboard hiện tại (${shots} shot) bằng ${kept.length} câu của Copilot? Bản dựng đã lưu ở bước Dựng vẫn giữ nguyên.`)) return;
    setBusy("apply");
    try { await post(`${url}/copilot/${open.message_id}/apply`, { keep: Object.keys(keep).filter((k) => keep[k]) }); toast(tv`Đã áp dụng: ${kept.length} shot từ bản ghi.`, { tone: "proof" }); onApplied(); }
    catch (e) { toast((e as Error).message, { tone: "tally" }); }
    setBusy(null);
  };
  const hear = (d: Decision) => {
    const v = player.current;
    const media = urlOf[d.asset_id];
    if (!v || !media) return;
    if (!v.src.endsWith(media)) v.src = media;
    v.currentTime = d.t_in;
    void v.play();
    const stop = () => { if (v.currentTime >= d.t_out) { v.pause(); v.removeEventListener("timeupdate", stop); } };
    v.addEventListener("timeupdate", stop);
  };
  const tone = (d: Decision) => d.action === "REMOVE" ? "text-tally" : d.action === "MOVE" ? "text-ai" : "text-proof";
  return (
    <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_300px] gap-3 overflow-y-auto p-3 max-xl:grid-cols-1">
      <div className="grid min-w-0 content-start gap-3">
        <div className="grid gap-2 rounded-xl border border-line bg-raised/30 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[12px] text-faint">{tr("Bản ghi có lời nói")}</span>
            {sources.length === 0 && <span className="text-[12.5px] text-mute">{tr("Thư viện chưa có bản ghi nào được chép lời.")}</span>}
            {sources.map((x) => (
              <button key={x.asset_id} type="button" onClick={() => setChosen(chosen.includes(x.asset_id) ? chosen.filter((a) => a !== x.asset_id) : [...chosen, x.asset_id])}
                      className={`rounded-full border px-2.5 py-0.5 text-[12px] ${chosen.includes(x.asset_id) ? "border-accent bg-accent/10 text-ink" : "border-line text-mute hover:text-ink"}`}
                      title={tv`${x.sentences} câu, ${x.spoken_seconds}s lời nói`}>{x.name} · {Math.round(x.spoken_seconds)}s</button>))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {PRESET_NAMES.map(([k, l]) => (
              <button key={k} type="button" onClick={() => setPresets(presets.includes(k) ? presets.filter((x) => x !== k) : [...presets, k])}
                      className={`rounded-md border px-2.5 py-1 text-[12.5px] ${presets.includes(k) ? "border-accent bg-accent/10 text-ink" : "border-line text-mute hover:text-ink"}`}>{l}</button>))}
            {presets.includes("shorten") && <label className="flex items-center gap-1.5 text-[12.5px] text-mute">{tr("còn")}
              <input value={target} onChange={(e) => setTarget(e.target.value)} inputMode="numeric" className="h-7 w-14 rounded border border-line bg-canvas px-1.5 text-ink" />{tr("giây")}</label>}
          </div>
          <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void propose(); }}>
            <input value={goal} onChange={(e) => setGoal(e.target.value)} placeholder={tr("Ví dụ: rút còn 45 giây, giữ luận điểm, mở đầu mạnh hơn, bỏ lặp, giữ nguyên ý nghĩa")}
                   className="h-9 min-w-0 flex-1 rounded-md border border-line bg-canvas px-2.5 text-[13px] outline-none focus:border-accent" />
            <Button kind="primary" type="submit" busy={busy === "propose"} disabled={!chosen.length}><Icon name="sparkles" size={14} />{tr("Đề xuất")}</Button>
          </form>
          {busy === "propose" && <p className="text-[12px] text-ai">{tr("Copilot đang đọc lời nói và cân từng câu (mô hình trên máy, khoảng một phút)…")}</p>}
        </div>

        {p && <div className="grid gap-2">
          <div className="flex flex-wrap items-center gap-2 text-[12.5px]">
            <span className="font-semibold">{tr("Quyết định dựng")}</span>
            <span className="text-faint">{tv`giữ ${p.summary.keep + p.summary.move} · bỏ ${p.summary.remove} · chờ bạn xem ${p.summary.review}`}</span>
            <span className="flex-1" />
            <label className="flex items-center gap-1.5 text-mute"><input type="checkbox" checked={onlyReview} onChange={(e) => setOnlyReview(e.target.checked)} />{tr("chỉ những câu chờ xem")}</label>
          </div>
          <ul className="grid gap-1.5">
            {p.decisions.filter((d) => !onlyReview || d.review === "needs_review").map((d) => (
              <li key={d.decision_id} className={`grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-2.5 rounded-lg border p-2 ${keep[d.decision_id] ? "border-line" : "border-line/50 opacity-60"}`}>
                <input type="checkbox" checked={!!keep[d.decision_id]} onChange={(e) => setKeep({ ...keep, [d.decision_id]: e.target.checked })} aria-label={tr("Giữ câu này")} className="mt-1" />
                <span className="grid min-w-0 gap-1">
                  <span className="flex flex-wrap items-center gap-2 text-[11.5px]">
                    <span className={`mono font-semibold ${tone(d)}`}>{d.action}</span>
                    <span className="mono text-faint">{`${d.t_in.toFixed(1)}–${d.t_out.toFixed(1)}s`}</span>
                    {d.evidence.inferred.role && <span className="rounded bg-ai/10 px-1.5 text-ai" title={tr("Mô hình đọc ra, không phải số đo")}>{d.evidence.inferred.role}{d.evidence.inferred.weight != null ? ` · ${d.evidence.inferred.weight}` : ""}</span>}
                    {d.required && <span className="rounded bg-proof/15 px-1.5 text-proof">{tr("bắt buộc giữ")}</span>}
                    {d.review === "needs_review" && <span className="rounded bg-cue/15 px-1.5 text-cue">{tr("chờ bạn xem")}</span>}
                    <span className="text-faint">{tv`tin cậy ${Math.round(d.confidence * 100)}%`}</span>
                  </span>
                  <span className="text-[13px] leading-snug text-ink">{d.text}</span>
                  <span className="text-[11.5px] text-mute">{d.reasons.join(" · ")}</span>
                  {(d.evidence.observed.length > 0 || d.evidence.inferred.why) && <span className="text-[11px] text-faint">
                    {d.evidence.observed.length > 0 && <>{tr("Đo được: ")}{d.evidence.observed.join("; ")}</>}{d.evidence.observed.length > 0 && d.evidence.inferred.why ? " · " : ""}
                    {d.evidence.inferred.why && <>{tr("Mô hình: ")}{d.evidence.inferred.why}</>}</span>}
                </span>
                <button type="button" onClick={() => hear(d)} className="grid h-8 w-8 place-items-center rounded-md border border-line text-mute hover:text-ink" title={tr("Nghe đoạn này")} aria-label={tr("Nghe đoạn này")}><Icon name="play" size={13} /></button>
              </li>))}
          </ul>
        </div>}
      </div>

      <aside className="grid content-start gap-3">
        <video ref={player} className="aspect-video w-full rounded-lg bg-black" controls playsInline />
        {p && <>
          <div className="grid gap-1.5 rounded-xl border border-line p-3">
            <span className="text-[12px] text-faint">{tr("Thời lượng dự kiến")}</span>
            <span className="mono text-[20px]">{`${Math.round(p.summary.source_seconds)}s → ${Math.round(seconds)}s`}{p.target_seconds ? <span className="text-[13px] text-faint">{tv` / mục tiêu ${p.target_seconds}s`}</span> : null}</span>
            <span className="h-1.5 overflow-hidden rounded bg-white/[0.08]"><span className="block h-full bg-accent" style={{ width: `${Math.min(100, (seconds / Math.max(1, p.summary.source_seconds)) * 100)}%` }} /></span>
            {p.notes.map((n) => <p key={n} className="rounded-md bg-cue/10 px-2 py-1.5 text-[12px] text-cue">{n}</p>)}
          </div>
          {p.coverage.length > 0 && <div className="grid gap-1 rounded-xl border border-line p-3">
            <span className="text-[12px] text-faint">{tr("Luận điểm (mô hình đọc ra)")}</span>
            {p.coverage.map((c) => { const held = c.sentences.some((k) => keep[p.decisions[k - 1]?.decision_id]); return (
              <span key={c.point} className={`flex items-start gap-1.5 text-[12.5px] ${held ? "text-ink" : "text-tally"}`}><Icon name={held ? "check" : "x"} size={13} className="mt-0.5" />{c.point}</span>); })}
          </div>}
          <Button kind="primary" busy={busy === "apply"} disabled={!kept.length} onClick={() => void apply()}
                  title={tr("Thay storyboard bằng các câu được giữ: mỗi câu một shot, đúng đoạn của bản ghi, tiếng của chính nó")}><Icon name="check" size={14} />{tv`Áp dụng ${kept.length} câu vào storyboard`}</Button>
        </>}
      </aside>
    </div>
  );
}

/** A shot's picture: a sweeping placeholder until the frame has arrived, then the frame faded in over the scene's colour. */
function Frame({ src, className = "absolute inset-0 h-full w-full object-cover" }: { src: string; className?: string }) {
  const [state, setState] = useState<"wait" | "ok" | "gone">("wait");
  return (
    <>
      {state === "wait" && <span className="skeleton absolute inset-0 rounded-none opacity-60" aria-hidden="true" />}
      {state !== "gone" && <img src={src} alt="" loading="lazy" decoding="async" onLoad={() => setState("ok")} onError={() => setState("gone")}
                                 className={`${className} transition-opacity duration-300 ${state === "ok" ? "opacity-100" : "opacity-0"}`} />}
    </>
  );
}

function ShotCard({ s, on, tone, pick }: { s: SbShot; on: boolean; tone: string; pick: () => void }) {
  const [label, t] = STATE[s.state];
  const passed = s.checks.filter((c) => c.st === "pass").length, of = s.checks.length || s.spec.criteria.length;
  const dot = ({ proof: "bg-proof", ai: "bg-ai", accent: "bg-accent", cue: "bg-cue", mute: "bg-faint" } as Record<string, string>)[t] ?? "bg-faint";
  const f = s.spec.framing;
  return (
    <button type="button" onClick={pick} className="grid w-full min-w-0 gap-2 text-left">
      <span className={`relative block aspect-video overflow-hidden rounded-lg ${on ? "outline outline-2 outline-offset-2 outline-accent" : "outline outline-1 outline-line"}`} style={{ background: tone }}>
        {s.frame_url && <Frame src={s.frame_url} />}
        <span className="mono absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 text-[11px] font-semibold ring-1 ring-white/25">{s.code}</span>
        <span className="absolute right-1.5 top-1.5 rounded px-1.5 text-[11px] font-semibold text-canvas" style={{ background: SRC[s.spec.source.policy][1] }}>{SRC[s.spec.source.policy][0]}</span>
        {s.version > 1 && <span className="mono absolute bottom-1.5 left-1.5 rounded bg-black/60 px-1.5 text-[11px] text-mute">v{s.version}</span>}
      </span>
      <span className="text-[11px] font-semibold uppercase leading-snug tracking-wide text-ink">{`${s.code}: ${f.lens} | ${s.spec.duration.target}s | ${f.move} | ${f.size} · ${f.angle}`}</span>
      <span className="text-[12.5px] leading-relaxed text-mute">{s.spec.intent}</span>
      {s.spec.line && <span className="border-l-2 border-accent/40 pl-2 text-[12px] italic leading-snug text-mute">“{s.spec.line}”</span>}
      <span className="flex items-center gap-1.5 text-[11px] text-faint"><span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />{label}
        {of > 0 && <><span aria-hidden="true">·</span><span className={of && passed === of ? "text-proof" : passed ? "text-cue" : "text-faint"}>{tv`nghiệm thu ${passed}/${of}`}</span></>}</span>
    </button>
  );
}

/* ---------------------------------------------------------------------------------------- the timeline draft (an animatic) */
function TimeView({ board, cur, tone, pick, pickSeam }: { board: Board; cur?: SbShot; tone: (s: SbShot) => string; pick: (id: string) => void; pickSeam: (id: string) => void }) {
  const shots = board.shots, total = Math.max(0.1, shots.reduce((t, s) => t + s.spec.duration.target, 0));
  const [at, setAt] = useState(0), [playing, setPlaying] = useState(false);
  const starts = useMemo(() => { let t = 0; return shots.map((s) => { const a = t; t += s.spec.duration.target; return a; }); }, [shots]);
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setAt((v) => { if (v + 0.1 >= total) { setPlaying(false); return total; } return v + 0.1; }), 100);
    return () => clearInterval(id);
  }, [playing, total]);
  const k = Math.max(0, starts.findIndex((a, i) => at >= a && (i === starts.length - 1 || at < starts[i + 1])));
  const now = shots[k];
  const entities = [...new Set(shots.flatMap((s) => s.spec.continuity.entities))];
  const times = shots.map((s) => s.spec.continuity.time_of_day);
  const seamAt = (sid: string) => starts[shots.findIndex((s) => s.shot_id === sid)];
  const ent = ["#ff8c52", "#c9a07a", "#4fd1a5", "#c9a7ff", "#7cc8ff", "#f5c451"];
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto p-3.5">
      <div className="relative mx-auto grid aspect-video w-full max-w-[680px] shrink-0 place-items-center overflow-hidden rounded-lg" style={{ background: now ? tone(now) : "#000" }}>
        {now?.frame_url && <img src={now.frame_url} alt="" className="absolute inset-0 h-full w-full object-cover" />}
        {now && <div className="relative grid gap-1 rounded-lg bg-black/55 px-3.5 py-2 text-center"><span className="mono text-[12px]">{now.code} · {mmss(at)}</span><span className="text-[13px]">{now.spec.line || now.spec.intent}</span></div>}
      </div>
      <div className="flex items-center gap-2.5 text-[12px] text-faint">
        <Button size="sm" onClick={() => { if (at >= total) setAt(0); setPlaying(!playing); }}><Icon name={playing ? "pause" : "play"} size={13} />{playing ? tr("Dừng") : tr("Phát animatic")}</Button>
        <span className="mono">{mmss(at)}</span>
        <input type="range" min={0} max={total} step={0.1} value={at} onChange={(e) => setAt(Number(e.target.value))} aria-label={tr("Vị trí trên timeline")} className="min-w-0 flex-1 accent-[#30afff]" />
        <span className="mono">{mmss(total)}</span>
      </div>
      {/* Each shot as its frame, so the order reads at a glance and a move shows at once (the codes follow the order and alone look the same). */}
      <Lane label={tr("Hình")}>{shots.map((s) => <button key={s.shot_id} type="button" onClick={() => { pick(s.shot_id); setAt(starts[shots.indexOf(s)]); }} title={s.spec.intent}
                                                         className={`mono relative h-11 min-w-0 overflow-hidden rounded text-[11px] ${s.shot_id === cur?.shot_id ? "outline outline-2 outline-accent" : ""}`} style={{ flex: `${s.spec.duration.target} 1 0`, background: tone(s) }}>
        {s.frame_url && <img src={s.frame_url} alt="" loading="lazy" className="absolute inset-0 h-full w-full object-cover" />}
        <span className="relative rounded bg-black/65 px-1">{s.code}</span></button>)}</Lane>
      <Lane label={tr("Lời dẫn")} top>{shots.map((s) => <div key={s.shot_id} className="line-clamp-4 min-w-0 border-t-2 border-accent/40 pt-1 text-[10.5px] leading-snug text-mute" style={{ flex: `${s.spec.duration.target} 1 0` }}>{s.spec.line}</div>)}</Lane>
      <div className="grid gap-1.5 border-t border-line pt-3">
        <div className="flex items-baseline gap-2.5"><span className="font-semibold">{tr("Liền mạch")}</span><span className="text-[12px] text-faint">{tr("mỗi làn là một thực thể; vạch đứt là chỗ nó vắng mặt")}</span><span className="flex-1" />
          <span className="text-[12px]" style={{ color: board.seams.some((x) => x.worst === "fail") ? "#ff6b6b" : board.seams.some((x) => x.worst === "warn") ? "#f5c451" : "#4fd1a5" }}>
            {tv`${board.seams.length} mối nối · ${board.seams.filter((x) => x.worst === "fail").length} đứt · ${board.seams.filter((x) => x.worst === "warn").length} cần xem`}</span></div>
        {entities.map((e, i) => <Lane key={e} label={e} thin>{shots.map((s) => <div key={s.shot_id} className="h-3 min-w-0 rounded-sm" style={{ flex: `${s.spec.duration.target} 1 0`, background: s.spec.continuity.entities.includes(e) ? ent[i % ent.length] : "transparent", border: s.spec.continuity.entities.includes(e) ? "none" : "1px dashed rgba(255,255,255,0.12)" }} />)}</Lane>)}
        {!entities.length && <p className="text-[12px] text-faint">{tr("Chưa shot nào gắn thực thể (tab Liên tục); làn nhân vật, nơi chốn, đạo cụ sẽ hiện ở đây.")}</p>}
        <Lane label={tr("Hướng")}>{shots.map((s) => <div key={s.shot_id} className="min-w-0 text-center text-[13px]" style={{ flex: `${s.spec.duration.target} 1 0`, color: s.spec.direction ? "var(--color-ink)" : "#4a5670" }}>{s.spec.direction === "phải" ? "→" : s.spec.direction === "trái" ? "←" : "·"}</div>)}</Lane>
        <Lane label={tr("Thời điểm")}>{shots.map((s, i) => <div key={s.shot_id} className="min-w-0 truncate text-center text-[11px] text-mute" style={{ flex: `${s.spec.duration.target} 1 0` }}>{times[i] && times[i] !== times[i - 1] ? times[i] : times[i] ? "·" : ""}</div>)}</Lane>
        <Lane label={tr("Mối nối")}>
          <div className="relative h-4 flex-1">{board.seams.map((x) => <button key={`${x.a}-${x.b}`} type="button" onClick={() => pickSeam(`${x.a}-${x.b}`)} title={tv`Mối nối ${x.a_code} → ${x.b_code}: ${SEAM[x.worst][0]}`}
                                                                         className="absolute top-0.5 h-3.5 w-3.5 rounded-full border-2 border-canvas" style={{ left: `calc(${(seamAt(x.b) / total) * 100}% - 7px)`, background: SEAM[x.worst][1] }} />)}</div>
        </Lane>
      </div>
      <p className="text-[12px] text-faint">{tr("Animatic: mỗi shot là hình của nó (footage đã gán hoặc ảnh khung) giữ đúng thời lượng, kèm lời dẫn. Duyệt nhịp ở đây trước khi tạo video hay render.")}</p>
    </div>
  );
}

function Lane({ label, children, top, thin }: { label: string; children: React.ReactNode; top?: boolean; thin?: boolean }) {
  return <div className={`flex gap-2 ${top ? "items-start" : "items-center"}`}><span className={`w-16 shrink-0 truncate ${thin ? "text-[11px] text-mute" : "text-[11px] text-faint"}`}>{label}</span><div className="flex min-w-0 flex-1 gap-0.5">{children}</div></div>;
}

/* ------------------------------------------------------------------------------------------- the camera plan, seen from above */
function PlanView({ board, cur, pick, flip }: { board: Board; cur?: SbShot; pick: (id: string) => void; flip: (id: string) => void }) {
  const codes = new Map(board.shots.map((s) => [s.shot_id, s]));
  const crossedCur = cur && board.plans.some((p) => p.crossed.includes(cur.shot_id));
  return (
    <div className="grid min-h-0 flex-1 content-start gap-4 overflow-y-auto p-3">
      <p className="text-[12px] leading-relaxed text-faint">{tr("Nhìn từ trên xuống. Chấm cam là chủ thể, vùng sáng là góc nhìn của ống kính, nét đứt là máy đang chạy. Máy nằm khác phía trục 180° so với shot đầu của cảnh sẽ làm hình bị đảo hướng.")}</p>
      {cur && <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-line bg-raised/30 px-3 py-2">
        <span className="mono text-faint">{cur.code}</span>
        <span className="min-w-0 flex-[1_1_200px] text-[13px]">{tv`${cur.spec.framing.lens} · máy ở ${cur.spec.camera.y < 110 ? tr("phía trên") : tr("phía dưới")} trục · hướng ${cur.spec.direction || tr("không có")}`}{crossedCur ? tr(" · vượt trục so với shot đầu của cảnh") : ""}</span>
        <Button size="sm" onClick={() => flip(cur.shot_id)}>{tr("Lật sang bên kia trục")}</Button>
      </div>}
      {board.plans.map((pl) => {
        const sc = board.scenes.find((x) => x.scene_id === pl.scene_id);
        return (
          <section key={pl.scene_id} className="grid gap-2">
            <div className="flex flex-wrap items-baseline gap-2.5"><h2 className="text-[14px] font-semibold">{sc?.title}</h2>
              <span className={`rounded-full px-2 text-[11px] ${pl.crossed.length ? "bg-tally/15 text-tally" : "bg-proof/15 text-proof"}`}>
                {pl.crossed.length ? tv`${pl.crossed.length} shot vượt trục: ${pl.crossed.map((id) => codes.get(id)?.code).join(", ")}` : tr("giữ một phía trục")}</span></div>
            <div className="scroll-x pb-1">
              <div className="relative h-[220px] w-[560px] overflow-hidden rounded-lg border border-line bg-canvas" role="img" aria-label={tv`Mặt bằng ${sc?.title ?? ""}`}>
                <div className="absolute left-0 top-[110px] h-0 w-full border-t border-dashed border-white/25" /><span className="absolute left-2 top-[94px] text-[10px] text-faint">{tr("trục 180°")}</span>
                <div className="absolute h-3.5 w-3.5 rounded-full border-2 border-canvas bg-ai" style={{ left: pl.subject.x - 7, top: pl.subject.y - 7 }} />
                {pl.subject.label && <span className="absolute w-[120px] text-center text-[10px] text-ai" style={{ left: pl.subject.x - 60, top: pl.subject.y + 12 }}>{pl.subject.label}</span>}
                {pl.cams.map((c) => {
                  const s = codes.get(c.shot_id)!, isSel = c.shot_id === cur?.shot_id, f = (lensFov(s.spec.framing.lens) * Math.PI) / 360, th = (c.aim * Math.PI) / 180, L = 85;
                  const pt = (a: number) => `${(c.x + L * Math.cos(a)).toFixed(0)}px ${(c.y + L * Math.sin(a)).toFixed(0)}px`;
                  const col = c.crossed ? "#ff6b6b" : isSel ? "#30afff" : "#8592a9";
                  return (
                    <span key={c.shot_id}>
                      <span className="pointer-events-none absolute inset-0" style={{ background: c.crossed ? "rgba(255,107,107,0.2)" : isSel ? "rgba(48,175,255,0.24)" : "rgba(133,146,169,0.12)", clipPath: `polygon(${c.x}px ${c.y}px, ${pt(th - f)}, ${pt(th + f)})` }} />
                      {c.end && <span className="pointer-events-none absolute h-0 origin-top-left border-t-2 border-dashed" style={{ left: c.x, top: c.y, width: Math.hypot(c.end.x - c.x, c.end.y - c.y), borderColor: col, transform: `rotate(${Math.atan2(c.end.y - c.y, c.end.x - c.x)}rad)` }} />}
                      <button type="button" onClick={() => pick(c.shot_id)} title={s.code} className="mono absolute grid h-8 w-8 place-items-center rounded-full border-2 text-[10px] font-semibold"
                              style={{ left: c.x - 16, top: c.y - 16, background: isSel || c.crossed ? col : "#26354f", color: isSel || c.crossed ? "#04121f" : "#e6edf7", borderColor: isSel ? "#e6edf7" : "#070c16" }}>{s.code}</button>
                    </span>);
                })}
              </div>
            </div>
            <div className="mono flex flex-wrap gap-3.5 text-[11px] text-faint">{pl.cams.map((c) => { const s = codes.get(c.shot_id)!; return <span key={c.shot_id}>{s.code} · {s.spec.framing.lens} · {s.spec.duration.target}s</span>; })}</div>
          </section>);
      })}
    </div>
  );
}

/* ---------------------------------------------------------------------------------------------- one shot's spec, in tabs */
const SPEEDS = [0.5, 0.75, 1, 1.5, 2];
const secs = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;

/** The shot's picture, where the clip step's work now happens: the clip given (its stretch, how it is treated in the cut), its
    other options (each can be used for the shot or become a shot of its own after it), and what to do when none fits. */
function PictureTab({ shot: s, board, url, set, act, busy }: { shot: SbShot; board: Board; url: string; set: (s: SbShot, field: string, value: unknown) => void;
  act: (k: string, fn: () => Promise<unknown>, done?: string) => void; busy: string | null }) {
  const v = board.vocabulary, a = s.assignment, has = !!a?.asset_id, t = a?.treat ?? {};
  const others = a?.others ?? [];
  const [inOut, setInOut] = useState<[string, string]>(["", ""]);
  const [query, setQuery] = useState("");
  useEffect(() => { setInOut(a ? [a.t_in.toFixed(1), a.t_out.toFixed(1)] : ["", ""]); }, [s.shot_id, a?.t_in, a?.t_out]);
  const shotUrl = `${url}/shots/${s.shot_id}`;
  const treat = (body: Treat) => act("treat", () => call(`${shotUrl}/treatment`, { method: "PATCH", body: JSON.stringify(body) }));
  const remote = board.remote ?? [], effects = board.effects ?? [];
  return (
    <>
      <div className="seg w-fit" role="radiogroup" aria-label={tr("Nguồn")}>
        {v.sources.map((k) => <button key={k} type="button" role="radio" aria-checked={s.spec.source.policy === k} onClick={() => set(s, "source.policy", k)}>{SRC[k][0]}</button>)}
      </div>
      {s.spec.source.policy === "generate" ? <p className="text-[12.5px] text-faint">{tr("Shot tạo bằng AI: xem tab Tạo sinh.")}</p> : <>
        <Field label={tr("Tìm trong footage")} value={s.spec.source.query} onSave={(x) => set(s, "source.query", x)} />

        {has ? (
          <div className="grid gap-2 rounded-lg border border-accent/40 bg-accent/[0.04] p-2.5">
            <div className="flex items-start gap-2.5">
              <span className="relative block aspect-video w-[132px] shrink-0 overflow-hidden rounded bg-black">{s.frame_url && <Frame src={s.frame_url} />}</span>
              <span className="grid min-w-0 flex-1 gap-0.5 text-[12.5px]">
                <span className="flex items-center gap-1.5"><span className="text-[11px] font-semibold text-proof">{tr("Hình của shot")}</span>{a?.decided_by === "operator" && <span className="text-[11px] text-accent">{tr("bạn chọn")}</span>}</span>
                <span className="truncate" title={a?.name}>{a?.name}</span>
                <span className="mono text-[11px] text-faint">{`${secs(a!.t_in)}–${secs(a!.t_out)} · ${(a!.t_out - a!.t_in).toFixed(1)}s`}{a?.score != null ? ` · ${tr("khớp")} ${a.score.toFixed(2)}` : ""}</span>
                {a?.text && <span className="line-clamp-2 text-[11.5px] text-mute" title={a.text}>{a.text}</span>}
              </span>
            </div>
            <form className="flex flex-wrap items-end gap-2 text-[12px] text-faint" onSubmit={(e) => { e.preventDefault(); act("trim", () => post(`${shotUrl}/trim`, { t_in: Number(inOut[0]), t_out: Number(inOut[1]) }), tr("Đã cắt lại đoạn.")); }}>
              <label className="grid gap-0.5">{tr("Vào (s)")}<input value={inOut[0]} onChange={(e) => setInOut([e.target.value, inOut[1]])} inputMode="decimal" className="h-7 w-16 rounded border border-line bg-canvas px-1.5 text-ink" /></label>
              <label className="grid gap-0.5">{tr("Ra (s)")}<input value={inOut[1]} onChange={(e) => setInOut([inOut[0], e.target.value])} inputMode="decimal" className="h-7 w-16 rounded border border-line bg-canvas px-1.5 text-ink" /></label>
              <Button size="sm" type="submit" busy={busy === "trim"} disabled={a && inOut[0] === a.t_in.toFixed(1) && inOut[1] === a.t_out.toFixed(1)}>{tr("Cắt lại")}</Button>
            </form>
            <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1.5 text-[12px] text-mute">
              <label className="flex items-center gap-1.5">{tr("Tốc độ")}<select value={t.speed ?? 1} onChange={(e) => treat({ speed: Number(e.target.value) })} className="h-7 rounded border border-line bg-canvas pl-1.5 text-[12px] text-ink">{SPEEDS.map((x) => <option key={x} value={x}>{x}×</option>)}</select></label>
              <label className="flex items-center gap-1.5"><input type="checkbox" checked={!!t.stabilise} onChange={(e) => treat({ stabilise: e.target.checked })} />{tr("Chống rung")}</label>
              <label className="flex items-center gap-1.5" title={tr("Giữ âm thanh của chính clip thay cho lời dẫn; độ dài cảnh bằng đúng đoạn đã chọn")}><input type="checkbox" checked={!!t.live_sound} onChange={(e) => treat({ live_sound: e.target.checked })} />{tr("Dùng âm thanh gốc")}</label>
              {remote.includes("lipsync") && <label className="flex items-center gap-1.5"><input type="checkbox" checked={!!t.lipsync && !t.live_sound} disabled={!!t.live_sound} onChange={(e) => treat({ lipsync: e.target.checked })} />{tr("Khớp khẩu hình")}</label>}
              {remote.includes("upscale") && <label className="flex items-center gap-1.5"><input type="checkbox" checked={!!t.upscale_ml} onChange={(e) => treat({ upscale_ml: e.target.checked })} />{tr("Phóng to bằng mô hình")}</label>}
              {effects.length > 0 && <label className="flex items-center gap-1.5">{tr("Tiếng động")}<select value={t.sfx ?? ""} onChange={(e) => treat({ sfx: e.target.value || null })} className="h-7 max-w-[150px] rounded border border-line bg-canvas pl-1.5 text-[12px] text-ink"><option value="">{tr("Không")}</option>{effects.map((x) => <option key={x.asset_id} value={x.asset_id}>{x.name}</option>)}</select></label>}
            </div>
          </div>
        ) : <p className="rounded-lg border border-dashed border-line p-2.5 text-[12.5px] text-faint">{tr("Shot chưa có hình. Bấm \"Chạy lại shot này\", đổi câu tìm, chọn một phương án bên dưới, hoặc tìm clip stock.")}</p>}

        {others.length > 0 && <div className="grid gap-1.5">
          <span className="eyebrow">{tv`Phương án khác · ${others.length}`}</span>
          <ul className="grid grid-cols-2 gap-2">
            {others.map((c, i) => (
              <li key={c.asset_id + c.t_in} className="grid gap-1 rounded-lg border border-line p-1.5">
                <span className="relative block aspect-video overflow-hidden rounded bg-black" title={c.text}>
                  <Frame src={c.frame_url} />
                  <span className="mono absolute bottom-1 left-1 rounded bg-black/70 px-1 text-[10px]">{secs(c.t_in)} · {(c.t_out - c.t_in).toFixed(1)}s</span>
                  {c.chosen_before && <span className="absolute right-1 top-1 rounded bg-accent px-1 text-[10px] font-semibold text-canvas">{tr("từng chọn")}</span>}
                </span>
                <span className="truncate text-[11.5px] text-mute" title={c.text || c.name}>{c.name}</span>
                {c.of > 0 && <span className={`text-[11px] ${c.passed === c.of ? "text-proof" : c.passed ? "text-cue" : "text-faint"}`} title={c.failed.join("; ")}>{tv`nghiệm thu ${c.passed}/${c.of}`}</span>}
                <span className="grid grid-cols-2 gap-1">
                  <button type="button" onClick={() => act(`use${i}`, () => post(`${shotUrl}/use`, { candidate: i }), tv`${s.code} dùng clip này.`)} disabled={!!busy}
                          className="h-7 rounded-md border border-line text-[11.5px] text-ink hover:border-accent hover:bg-accent/10">{tr("Dùng cho shot")}</button>
                  <button type="button" onClick={() => act(`add${i}`, () => post(`${shotUrl}/add-clip`, { candidate: i }), tv`Đã thêm shot mới sau ${s.code}.`)} disabled={!!busy}
                          title={tr("Thêm clip này thành một shot mới ngay sau shot đang chọn")}
                          className="flex h-7 items-center justify-center gap-1 rounded-md border border-line text-[11.5px] text-ink hover:border-accent hover:bg-accent/10"><Icon name="plus" size={12} />{tr("Thêm vào cảnh")}</button>
                </span>
              </li>))}
          </ul>
        </div>}

        <div className="grid gap-2 border-t border-line pt-2.5">
          {(has || others.length > 0) && <button type="button" className="link justify-self-start text-[12.5px]" onClick={() => act("none", () => post(`${shotUrl}/none-fits`), tr("Đã ghi nhận: các clip này không hợp với shot."))}>{tr("Không clip nào hợp")}</button>}
          <form className="flex gap-1.5" onSubmit={(e) => { e.preventDefault(); if (query.trim()) act("stock", async () => { const r = await post<{ stock: { found: boolean } }>(`${shotUrl}/stock`, { query }); if (!r.stock?.found) toast(tr("Không tìm được clip stock cho từ khoá này."), { tone: "tally" }); }); }}>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={tr("Từ khoá tiếng Anh, ví dụ: fishing boat at sea")} aria-label={tr("Từ khoá tìm clip stock")}
                   className="h-8 min-w-0 flex-1 rounded-md border border-line bg-canvas px-2.5 text-[12.5px] outline-none focus:border-accent" />
            <Button size="sm" type="submit" busy={busy === "stock"} disabled={!query.trim()}><Icon name="globe" size={13} />{tr("Tìm clip stock")}</Button>
          </form>
        </div>
      </>}
    </>
  );
}

function Inspector({ shot: s, board, url, tab, setTab, set, ops, act, busy }: {
  shot: SbShot; board: Board; url: string; tab: string; setTab: (t: "goal" | "source" | "gen" | "cont" | "crit" | "hist") => void;
  set: (s: SbShot, field: string, value: unknown) => void; ops: (list: object[], note?: string) => void; act: (k: string, fn: () => Promise<unknown>, done?: string) => void; busy: string | null }) {
  const v = board.vocabulary;
  const [label, t] = STATE[s.state];
  const { data: hist } = usePoll<{ versions: { version: number; made_by: string; note: string | null; at: number }[] }>(tab === "hist" ? `${url}/shots/${s.shot_id}/versions` : "", 10000);
  const [newEnt, setNewEnt] = useState(""), [newCheck, setNewCheck] = useState("human"), [newText, setNewText] = useState("");
  const tabs = [["source", tr("Hình")], ["goal", tr("Mục tiêu")], ["gen", tr("Tạo sinh")], ["cont", tr("Liên tục")], ["crit", tr("Nghiệm thu")], ["hist", tr("Lịch sử")]] as const;
  const results = new Map(s.checks.map((c) => [c.check + c.text, c]));
  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <span className="mono text-faint">{s.code}</span><span className="min-w-0 flex-1 truncate font-semibold">{s.spec.intent}</span>
        <span className={`rounded-full px-2 text-[11px] ${chip(t)}`}>{label}</span><span className="mono text-[11px] text-faint">v{s.version}</span>
      </div>
      {(s.state === "needs" || s.state === "stale") && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-ai/[0.05] px-3 py-2 text-[12.5px]">
          <span className="min-w-0 flex-1 text-mute">{s.checks.filter((c) => c.st !== "pass").map((c) => c.text).slice(0, 2).join("; ") || tr("Chờ bạn xem")}</span>
          {s.assignment && <Button size="sm" kind="primary" onClick={() => act("decide", () => post(`${url}/shots/${s.shot_id}/decide`, { accept: true }), tr("Đã nhận shot."))}>{tr("Nhận shot")}</Button>}
          <Button size="sm" busy={busy === "one"} onClick={() => act("one", () => post(`${url}/run`, { shot: s.shot_id }))}>{tr("Chạy lại shot này")}</Button>
        </div>)}
      <div role="tablist" className="scroll-x flex gap-0.5 border-b border-line px-2">
        {tabs.map(([k, l]) => <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
                                      className={`-mb-px h-9 whitespace-nowrap border-b-2 px-2.5 text-[12.5px] ${tab === k ? "border-accent text-ink" : "border-transparent text-mute hover:text-ink"}`}>{l}</button>)}
      </div>
      <div className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto p-3">
        {tab === "goal" && <>
          <Field label={tr("Mục tiêu nội dung")} area value={s.spec.intent} onSave={(x) => set(s, "intent", x)} />
          <Field label={tr("Lời dẫn / thoại của shot")} area value={s.spec.line} onSave={(x) => set(s, "line", x)} />
          <span className="-mt-1.5 text-[11px] text-faint">{tr("Câu này hiện trên thẻ shot và làn Lời dẫn của timeline; ghi vào kịch bản thì thành câu của dự án.")}</span>
          <div className="grid grid-cols-3 gap-2">
            {(["target", "min", "max"] as const).map((k) => <Field key={k} label={{ target: tr("Thời lượng (s)"), min: tr("Tối thiểu"), max: tr("Tối đa") }[k]} value={String(s.spec.duration[k])} onSave={(x) => set(s, `duration.${k}`, Number(x))} />)}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Pick label={tr("Cỡ cảnh")} value={s.spec.framing.size} items={v.sizes} onPick={(x) => set(s, "framing.size", x)} />
            <Pick label={tr("Góc máy")} value={s.spec.framing.angle} items={v.angles} onPick={(x) => set(s, "framing.angle", x)} />
            <Pick label={tr("Chuyển động")} value={s.spec.framing.move} items={v.moves} onPick={(x) => set(s, "framing.move", x)} />
            <Pick label={tr("Ống kính")} value={s.spec.framing.lens} items={v.lenses} onPick={(x) => set(s, "framing.lens", x)} />
          </div>
        </>}
        {tab === "source" && <PictureTab shot={s} board={board} url={url} set={set} act={act} busy={busy} />}
        {tab === "gen" && <>
          <div className="grid grid-cols-2 gap-2">
            {([["provider", tr("Ảnh khung"), board.providers.image_providers], ["provider_video", tr("Video"), board.providers.video_providers]] as const).map(([k, l, list]) => (
              <label key={k} className="grid gap-1 text-[12px] text-faint">{tv`Nhà cung cấp ${l}`}
                <select value={s.spec.generation[k]} onChange={(e) => set(s, `generation.${k}`, e.target.value)} className="h-8 rounded-md border border-line bg-canvas px-2 text-[13px] text-ink">
                  <option value="">{tr("theo thứ tự của dự án")}</option>
                  {(list ?? []).map((p) => <option key={p.name} value={p.name}>{`${p.label} · ${p.runs === "local" ? tr("trên máy") : tr("cloud")}`}</option>)}
                </select></label>))}
          </div>
          {!(board.providers.image_providers ?? []).length && <p className="text-[12px] text-cue">{tr("Chưa có nhà cung cấp ảnh nào (RunPod, Pollinations…): cấu hình trong nexora.toml.")}</p>}
          <Field label={tr("Model (ghi chú)")} value={s.spec.generation.model} placeholder={tr("mặc định của nhà cung cấp")} onSave={(x) => set(s, "generation.model", x)} />
          {(["subject", "action", "setting", "light", "camera"] as const).map((k) =>
            <Field key={k} label={{ subject: tr("Chủ thể"), action: tr("Hành động"), setting: tr("Bối cảnh"), light: tr("Ánh sáng"), camera: tr("Máy quay") }[k]} value={s.spec.generation.prompt[k] ?? ""} onSave={(x) => set(s, `generation.prompt.${k}`, x)} />)}
          <Field label={tr("Seed")} value={s.spec.generation.seed == null ? "" : String(s.spec.generation.seed)} placeholder={tr("ngẫu nhiên")} onSave={(x) => set(s, "generation.seed", x)} />
          {s.assignment?.kind === "generated" && s.frame_url && <img src={s.frame_url} alt={tr("Ảnh khung")} className="w-full rounded-lg" />}
          <p className="text-[12px] text-faint">{tr("Ảnh khung được tạo trước và phải duyệt rồi mới trả tiền cho video. Bấm \"Tạo ảnh khung\" ở trên: storyboard được ghi vào kịch bản và phần tạo hình của dự án chạy cho các shot AI.")}</p>
        </>}
        {tab === "cont" && <>
          <div className="flex flex-wrap gap-1.5">
            {s.spec.continuity.entities.map((e) => <span key={e} className="flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[12.5px]">{e}
              <button type="button" aria-label={tv`Bỏ ${e}`} onClick={() => set(s, "continuity.entities", s.spec.continuity.entities.filter((x) => x !== e))} className="text-faint hover:text-tally"><Icon name="x" size={11} /></button></span>)}
            <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); if (newEnt.trim()) { set(s, "continuity.entities", [...s.spec.continuity.entities, newEnt.trim()]); setNewEnt(""); } }}>
              <input value={newEnt} onChange={(e) => setNewEnt(e.target.value)} placeholder={tr("+ nhân vật, nơi, đạo cụ")} aria-label={tr("Thêm thực thể")} className="h-7 w-40 rounded-md border border-dashed border-line bg-transparent px-2 text-[12.5px]" /></form>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Pick label={tr("Hướng nhìn, hướng đi")} value={s.spec.direction} items={["", "phải", "trái"]} onPick={(x) => set(s, "direction", x)} />
            <Pick label={tr("Thời điểm trong ngày")} value={s.spec.continuity.time_of_day} items={v.times} onPick={(x) => set(s, "continuity.time_of_day", x)} />
          </div>
          <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={s.spec.continuity.match_previous} onChange={(e) => set(s, "continuity.match_previous", e.target.checked)} />{tr("Nối màu và ánh sáng với shot trước")}</label>
          <div className="flex items-center gap-2 text-[12.5px] text-mute">{tv`Máy ở ${s.spec.camera.y < 110 ? tr("phía trên") : tr("phía dưới")} trục`}<Button size="sm" kind="quiet" onClick={() => ops([{ op: "flip_camera", shot: s.shot_id }])}>{tr("Lật sang bên kia trục")}</Button></div>
        </>}
        {tab === "crit" && <>
          {s.spec.criteria.map((c, i) => {
            const r = results.get(c.check + c.text);
            const [m, cls] = MARK[r?.st ?? "wait"];
            return (
              <div key={i} className="flex items-center gap-2.5 rounded-lg border border-line px-2.5 py-2">
                <span className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-canvas ${cls}`}>{m}</span>
                <span className="min-w-0 flex-1 text-[13px]">{c.text}{c.value != null && c.value !== "" ? <span className="mono text-[11px] text-faint">{` ${c.op} ${String(c.value)}`}</span> : null}</span>
                <span className="text-[11px] text-faint">{c.by === "auto" ? tr("tự động") : tr("người duyệt")}</span>
                <span className="mono w-[86px] truncate text-right text-[11px] text-mute">{r?.value ?? "—"}</span>
                <button type="button" aria-label={tr("Bỏ tiêu chí")} onClick={() => ops([{ op: "remove_criterion", shot: s.shot_id, index: i }])} className="text-faint hover:text-tally"><Icon name="x" size={12} /></button>
              </div>);
          })}
          <form className="flex flex-wrap gap-1.5" onSubmit={(e) => { e.preventDefault(); ops([{ op: "add_criterion", shot: s.shot_id, criterion: { check: newCheck, text: newText.trim() || undefined } }]); setNewText(""); }}>
            <select value={newCheck} onChange={(e) => setNewCheck(e.target.value)} aria-label={tr("Loại tiêu chí")} className="h-8 rounded-md border border-line bg-canvas px-2 text-[12.5px]">
              {Object.entries(v.checks).map(([k, c]) => <option key={k} value={k}>{c.text}</option>)}</select>
            <input value={newText} onChange={(e) => setNewText(e.target.value)} placeholder={tr("mô tả (với tiêu chí người duyệt)")} aria-label={tr("Mô tả tiêu chí")} className="h-8 min-w-0 flex-1 rounded-md border border-line bg-canvas px-2 text-[12.5px]" />
            <Button size="sm" type="submit">{tr("Thêm")}</Button>
          </form>
          <p className="text-[12px] text-faint">{tr("Tiêu chí máy đo được thì Director tự kiểm; tiêu chí người duyệt chờ bạn. Trường VI chưa kiểm định và footage VQ chưa đo hiện \"–\", không bao giờ được coi là đạt.")}</p>
        </>}
        {tab === "hist" && <div className="grid gap-1.5">
          {(hist?.versions ?? []).map((h) => (
            <div key={h.version} className="flex items-center gap-2.5 text-[12.5px]"><span className="mono w-8 text-faint">v{h.version}</span>
              <span className="min-w-0 flex-1 text-mute">{h.note || h.made_by}<span className="text-faint"> · {h.made_by}</span></span>
              {h.version !== s.version && <button type="button" onClick={() => act("rev", () => post(`${url}/shots/${s.shot_id}/revert`, { version: h.version }), tv`Đã quay lại v${h.version}.`)} className="text-accent">{tr("quay lại")}</button>}
            </div>))}
        </div>}
      </div>
    </section>
  );
}

/* ---------------------------------------------------------------------------------------------------- a cut, read for continuity */
function SeamPanel({ seam, board, tone, close, fix }: { seam: Seam; board: Board; tone: (s: SbShot) => string; close: () => void; fix: (ops: object[], text: string) => void }) {
  const a = board.shots.find((s) => s.shot_id === seam.a)!, b = board.shots.find((s) => s.shot_id === seam.b)!;
  const pic = (s: SbShot, label: string) => (
    <div className="grid gap-1"><div className="relative aspect-video overflow-hidden rounded-md" style={{ background: tone(s) }}>{s.frame_url && <Frame src={s.frame_url} />}</div>
      <span className="truncate text-[11px] text-faint">{label} {s.code} · {s.spec.intent}</span></div>);
  return (
    <section aria-label={tr("Mối nối")} className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-line bg-surface">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <span className="font-semibold">{tv`Mối nối ${seam.a_code} → ${seam.b_code}`}</span>
        <span className="rounded-full px-2 text-[11px]" style={{ color: SEAM[seam.worst][1], background: `${SEAM[seam.worst][1]}22` }}>{SEAM[seam.worst][0]}</span>
        <span className="flex-1" /><Button size="sm" kind="quiet" onClick={close}>{tr("Về shot")}</Button>
      </div>
      <div className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto p-3">
        <div className="grid grid-cols-2 gap-1.5">{pic(a, tr("hình cuối"))}{pic(b, tr("hình đầu"))}</div>
        {seam.checks.map((c) => { const [m, cls] = MARK[c.st]; return (
          <div key={c.key} className="flex items-center gap-2.5 rounded-lg border border-line px-2.5 py-2">
            <span className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-canvas ${cls}`}>{m}</span>
            <span className="grid min-w-0 flex-1"><span className="text-[13px]">{c.name}</span><span className="text-[11px] text-faint">{c.detail}</span></span>
            <span className="mono text-[11px] text-mute">{c.value}</span></div>); })}
        {seam.fixes.length > 0 && <div className="grid gap-1.5"><span className="text-[12px] text-faint">{tr("Cách sửa Director đề xuất")}</span>
          {seam.fixes.map((f) => <button key={f.text} type="button" onClick={() => fix(f.ops, f.text)} className="rounded-lg border border-accent/40 bg-accent/10 px-3 py-2 text-left text-[13px] hover:bg-accent/15">{f.text}</button>)}</div>}
      </div>
    </section>
  );
}

/* --------------------------------------------------------------------------------------------------- talking to the Director */
function Proposal({ m, url, onDone }: { m: Msg; url: string; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const settle = async (verdict: "apply" | "drop") => { setBusy(true); try { await post(`${url}/messages/${m.message_id}/${verdict}`); onDone(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } setBusy(false); };
  const p = m.proposal!;
  if (p.kind === "copilot") {
    // Its decisions are reviewed one by one in the Copilot mode; here it can only be set aside.
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-ai/40 bg-ai/[0.05] p-2.5 text-[12.5px]">
        <Icon name="sparkles" size={14} className="text-ai" /><span className="min-w-0 flex-1 text-mute">{tr("Đề xuất của Copilot: mở chế độ Copilot để xem từng quyết định và áp dụng.")}</span>
        <Button size="sm" kind="quiet" busy={busy} onClick={() => settle("drop")}>{tr("Bỏ")}</Button>
      </div>);
  }
  return (
    <div className="grid gap-1.5 rounded-xl border border-accent/40 bg-raised/40 p-2.5">
      <span className="text-[12px] text-faint">{tv`Đề xuất · ${p.scope} · ${p.diff.length} thay đổi`}{p.summary ? ` · ${p.summary}` : ""}</span>
      {p.diff.map((d, i) => <div key={i} className="mono grid gap-px text-[12px]"><span className="text-ink">{d.title}</span>{d.old && <span className="text-tally">− {d.old}</span>}<span className="text-proof">+ {d.new}</span></div>)}
      {p.problems && p.problems.length > 0 && <span className="text-[11.5px] text-faint">{tv`Bỏ qua: ${p.problems.join("; ")}`}</span>}
      <div className="mt-1 flex gap-2"><Button size="sm" kind="primary" busy={busy} onClick={() => settle("apply")}>{tr("Áp dụng")}</Button><Button size="sm" kind="quiet" onClick={() => settle("drop")}>{tr("Bỏ")}</Button></div>
    </div>
  );
}

function Chat({ board, url, cur, onDone }: { board: Board; url: string; cur?: SbShot; onDone: () => void }) {
  const [scope, setScope] = useState<"shot" | "scene" | "all">("scene"), [text, setText] = useState(""), [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const [past, setPast] = useState(false);
  // The talk folds to its input line so the shot's inspector has the height; it opens by itself when a proposal waits.
  const waiting = board.messages.some((m) => m.proposal && m.status === "open");
  const [open, setOpenState] = useState(() => { try { return localStorage.getItem("nx.sb.chat") === "1"; } catch { return false; } });
  const setOpen = (v: boolean) => { setOpenState(v); try { localStorage.setItem("nx.sb.chat", v ? "1" : "0"); } catch { /* private window */ } };
  const shown = open || waiting;
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [board.messages.length]);
  // What needs the operator stays in view: the latest exchange, and any proposal still waiting to be applied or dropped.
  // Everything settled before them folds into one line, opened on demand.
  const msgs = board.messages;
  const lastYou = msgs.map((m) => m.role).lastIndexOf("you");
  const cut = lastYou < 0 ? Math.max(0, msgs.length - 1) : lastYou;
  const settled = msgs.slice(0, cut).filter((m) => !(m.proposal && m.status === "open"));
  const live = [...msgs.slice(0, cut).filter((m) => m.proposal && m.status === "open"), ...msgs.slice(cut)];
  const bubble = (m: Msg) => (
    <div key={m.message_id} className="grid gap-1.5">
      <div className={m.role === "you" ? "max-w-[85%] justify-self-end rounded-[10px_10px_2px_10px] bg-accent/10 px-2.5 py-1.5 text-[13px] leading-relaxed" : "max-w-[92%] text-[13px] leading-relaxed text-mute"}>{m.text}</div>
      {m.proposal && m.status === "open" && <Proposal m={m} url={url} onDone={onDone} />}
      {m.proposal && m.status !== "open" && <span className={`text-[11px] ${m.status === "applied" ? "text-proof" : "text-faint"}`}>{m.status === "applied" ? tr("đã áp dụng") : tr("đã bỏ")}</span>}
    </div>);
  const send = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try { await post(`${url}/say`, { text, scope, shot: cur?.shot_id }); setText(""); setOpen(true); onDone(); } catch (e) { toast((e as Error).message, { tone: "tally" }); }
    setBusy(false);
  };
  return (
    <section aria-label={tr("Hội thoại với Director")} className={`flex shrink-0 flex-col overflow-hidden rounded-xl border border-line bg-surface ${shown ? "h-[330px]" : ""}`}>
      <div className="flex items-center gap-2 border-b border-line px-3 py-1.5">
        <button type="button" onClick={() => setOpen(!shown)} aria-expanded={shown} className="flex items-center gap-1.5 font-semibold" title={shown ? tr("Thu gọn hội thoại") : tr("Mở hội thoại")}>
          <Icon name={shown ? "down" : "next"} size={13} />Director</button>
        {waiting && <span className="rounded-full bg-ai/15 px-2 text-[11px] text-ai">{tr("có đề xuất chờ")}</span>}
        <span className="flex-1" />
        <div className="seg" role="radiogroup" aria-label={tr("Phạm vi")}>
          {([["shot", tr("Shot này")], ["scene", tr("Cảnh")], ["all", tr("Toàn bộ")]] as const).map(([k, l]) => <button key={k} type="button" role="radio" aria-checked={scope === k} onClick={() => setScope(k)}>{l}</button>)}
        </div>
      </div>
      {shown && <div className="grid min-h-0 flex-1 content-start gap-2.5 overflow-y-auto px-3 py-2.5">
        {board.messages.length === 0 && <p className="text-[12.5px] text-faint">{tr("Nói với Director điều cần đổi, ví dụ: \"cảnh 2 hơi dài, rút còn 20 giây và thêm một shot cận tay bổ dừa\". Director trả lời bằng một đề xuất; chưa có gì thay đổi cho tới khi bạn áp dụng.")}</p>}
        {settled.length > 0 && (
          <button type="button" onClick={() => setPast(!past)} aria-expanded={past}
                  className="flex items-center gap-1.5 justify-self-start rounded-md px-1.5 py-0.5 text-[11.5px] text-faint hover:bg-raised hover:text-ink">
            <Icon name={past ? "down" : "next"} size={12} />
            {tv`Lịch sử · ${settled.length} tin đã xử lý`}
            {(() => { const a = settled.filter((m) => m.status === "applied").length, d = settled.filter((m) => m.status && m.status !== "applied" && m.status !== "open").length;
              return <span className="text-faint">{a ? tv` · ${a} áp dụng` : ""}{d ? tv` · ${d} bỏ` : ""}</span>; })()}
          </button>)}
        {past && <div className="grid gap-2.5 border-l border-line pl-2.5 opacity-75">{settled.map(bubble)}</div>}
        {live.map(bubble)}
        <div ref={end} />
      </div>}
      <form className="flex gap-1.5 border-t border-line p-2" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder={cur ? tv`Với ${cur.code}: ví dụ đổi góc máy thấp, ánh hoàng hôn ấm hơn` : tr("Nói với Director")} aria-label={tr("Nói với Director")}
               className="h-9 min-w-0 flex-1 rounded-md border border-line bg-canvas px-2.5 text-[13px] outline-none focus:border-accent" />
        <Button size="sm" type="submit" busy={busy}>{tr("Gửi")}</Button>
      </form>
    </section>
  );
}
