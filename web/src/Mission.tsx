import { t as tr, tv, locale } from "./i18n";
import { useEffect, useState } from "react";
import { megabytes, post, stageName, usePoll } from "./api";
import { ask, Button, Empty, goTo, Icon, Meter, OpsSide, Page, Seg, Spinner, Tabs, Tag, toast } from "./parts";

/* Mission Control (design 2026-10-18): the control plane. Every service keeps its own state; this screen reads them and
   sends commands through their own endpoints. A mission keeps only what was asked, the plan and what it started. */

type Tone = "mute" | "cue" | "proof" | "tally" | "ai" | "accent";
type Plan = { kind: string; goal: string; title: string; count: number; format: string; lines: number; channel: string | null; template: string | null; budget: number | null;
  paid: boolean; stock: boolean; critique: boolean; constraints: string[]; acceptance: string[]; autonomy: number };
type Child = { kind: "task" | "run"; id: string; project_id?: string; pipeline?: string; status: string; state: string; step?: string; note: string | null };
type MissionEvent = { at: number; kind: string; text: string | null };
type Mission = { mission_id: string; text: string; plan: Plan; problems: string[]; state: string; status: string; kind_name: string | null; children: Child[];
  links: { projects: string[]; tasks: string[]; runs: string[] }; events: MissionEvent[]; spent: number; created_at: number; updated_at: number };
type Attempt = { number: number; outcome: string | null; started_at: number; seconds: number | null; error_code: string | null; error_message: string | null };
type RunDetail = { run_id: string; pipeline: string; name: string; status: string; created_at: number; cost: number; stalled: boolean;
  stages: { stage_id: string; stage_key: string; status: string; blocked_reason: string | null; attempts: Attempt[] }[]; events: { at: number; kind: string; actor: string }[] };
type Task = { task_id: string; project_id: string; goal: string; status: string; step: string; log: { at: number; role: string; text: string }[] };
type Detail = Mission & { runs: RunDetail[]; tasks: Task[]; projects: { project_id: string; title: string }[] };
type SystemRun = { run_id: string; pipeline: string; name: string; status: string; created_at: number; project_id: string | null; title: string | null };
type MissionList = { missions: Mission[]; system: SystemRun[]; kinds: { kind: string; name: string }[]; channels: string[]; templates: string[] };
type Approval = { key: string; kind: string; id: string; title: string; asked_by: string; why: string; touches: string; cost: number | null; next: string; at: number; actions: string[]; link: string | null };
type Unit = { key: string; name: string; group: string; role?: string; state: string; detail: string; fix?: string | null; queue?: Record<string, number> };
type Fleet = { agents: Unit[]; workers: Unit[]; engines: Unit[]; live_pipelines: string[] };
type Machine = { cpus: number; load: number | null; memory_total: number | null; memory_used: number | null; disk_free: number | null; disk_total: number | null };
type Resources = { machine: Machine; lanes: Record<string, Record<string, number>>; running: number; memory_pressure: number | null; hold_heavy: boolean;
  spent_today: number; spent_month: number; budget_day: number | null; budget_month: number | null; by_day: { day: string; cost: number }[];
  providers: { adapter: string; operation: string; runs: string; calls: number; seconds: number; failures: number; cost: number }[] };
type Overview = { kpis: { active: number; awaiting: number; missions: number; alerts: number; health: Record<string, number> }; active: Mission[]; approvals: Approval[];
  alerts: { kind: string; text: string; link: string | null }[]; resources: Resources; fleet: Fleet; kill_switch: boolean; autonomy: number; unavailable: string[] };
type QualityRow = { render_id: string; project_id: string; title: string; created_at: number; verdict: string; duration: number | null; width: number | null; height: number | null;
  failed: string[]; findings: string[]; review: string; comment: string | null };
type ArtifactRow = { project_id: string; title: string; mission_id: string | null; created_at: number; sources: number; scripts: number; script_version: number | null;
  renders: { render_id: string; created_at: number; verdict: string; approved: boolean; packaged: boolean }[] };
type LogEntry = { at: number; kind: string; level: string; source: string; text: string; ref: string | null };

const STATUS: Record<string, [string, Tone]> = {
  draft: [tr("Nháp"), "mute"], planned: [tr("Chờ xác nhận"), "cue"], queued: [tr("Trong hàng đợi"), "accent"], running: [tr("Đang chạy"), "ai"],
  awaiting_approval: [tr("Chờ bạn duyệt"), "cue"], completed: [tr("Hoàn thành"), "proof"], blocked: [tr("Bị chặn"), "tally"], failed: [tr("Lỗi"), "tally"],
  cancelled: [tr("Đã huỷ"), "mute"], partially_completed: [tr("Xong một phần"), "cue"], paused: [tr("Tạm dừng"), "mute"],
};
const UNIT: Record<string, [string, Tone]> = {
  healthy: [tr("Ổn định"), "proof"], busy: [tr("Đang làm"), "ai"], degraded: [tr("Suy giảm"), "cue"], offline: [tr("Mất kết nối"), "tally"], disabled: [tr("Tắt"), "mute"],
};
const VERDICT: Record<string, [string, Tone]> = {
  pass: ["PASS", "proof"], pass_with_warnings: ["PASS WITH WARNINGS", "cue"], fail: ["FAIL", "tally"], manual_review: ["MANUAL REVIEW", "accent"],
};
const REVIEW: Record<string, string> = { approved: tr("Đã duyệt"), changes: tr("Trả lại sửa"), waiting: tr("Chờ bạn duyệt"), none: tr("Không duyệt") };
const CHILD_STATE: Record<string, string> = { running: tr("đang chạy"), waiting: tr("chờ bạn"), done: tr("xong"), failed: tr("lỗi"), cancelled: tr("đã huỷ"), paused: tr("tạm dừng"),
  queued: tr("chờ chạy"), blocked: tr("đang dừng") };
const FORMATS: [string, string][] = [["landscape", tr("Ngang 16:9")], ["portrait", tr("Dọc 9:16")], ["square", tr("Vuông 1:1")]];
const DOT: Record<Tone, string> = { mute: "bg-faint", cue: "bg-cue", proof: "bg-proof", tally: "bg-tally", ai: "bg-ai", accent: "bg-accent" };

type TabKey = "overview" | "missions" | "approvals" | "agents" | "quality" | "artifacts" | "resources" | "logs";
const TABS: { key: TabKey; label: string; icon: string }[] = [
  { key: "overview", label: tr("Tổng quan"), icon: "gauge" }, { key: "missions", label: tr("Nhiệm vụ"), icon: "bolt" }, { key: "approvals", label: tr("Phê duyệt"), icon: "check" },
  { key: "agents", label: tr("Agents"), icon: "cpu" }, { key: "quality", label: tr("Chất lượng"), icon: "shield" }, { key: "artifacts", label: tr("Artifacts"), icon: "layers" },
  { key: "resources", label: tr("Ngân sách & tài nguyên"), icon: "coins" }, { key: "logs", label: tr("Nhật ký"), icon: "list" },
];

const clock = (t: number) => new Date(t * 1000).toLocaleString(locale, { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
const usd = (n: number | null | undefined) => (n == null ? "–" : `$${n.toFixed(n < 1 ? 3 : 2)}`);
const secs = (s: number | null) => (s == null ? "–" : s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}m${String(Math.round(s % 60)).padStart(2, "0")}`);
const fail = (e: unknown) => toast((e as Error).message, { tone: "tally" });

function State({ map, value }: { map: Record<string, [string, Tone]>; value: string }) {
  const [label, tone] = map[value] ?? [value, "mute" as Tone];
  return <Tag tone={tone}>{label}</Tag>;
}

/** A bento card: glass, a small HUD label in its corner, optional actions at the end of its head. */
function Bento({ label, code, end, children, className = "" }: { label: string; code?: string; end?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`bento flex min-w-0 flex-col p-4 md:p-5 ${className}`}>
      <header className="mb-3 flex items-center justify-between gap-3">
        <h2 className="flex min-w-0 items-center gap-2 text-[13px] font-medium text-mute"><span className="hud-dot" aria-hidden="true" /><span className="truncate">{label}</span>
          {code && <span className="hud-label hidden sm:inline">{code}</span>}</h2>
        {end && <div className="flex shrink-0 items-center gap-2">{end}</div>}
      </header>
      <div className="min-w-0 flex-1">{children}</div>
    </section>
  );
}

function Kpi({ label, value, sub, tone = "accent", code, onClick }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: Tone; code: string; onClick?: () => void }) {
  const c = { mute: "text-ink", cue: "text-cue", proof: "text-proof", tally: "text-tally", ai: "text-ai", accent: "text-accent" }[tone];
  return (
    <button type="button" onClick={onClick} className="bento bento-hover flex min-w-0 flex-col p-4 text-left">
      <span className="flex items-center justify-between gap-2"><span className="truncate text-[12.5px] text-mute">{label}</span><span className="hud-label">{code}</span></span>
      <span className={`mono mt-2 text-[30px] font-semibold leading-none tracking-tight ${c}`}>{value}</span>
      {sub && <span className="mt-2 truncate text-[12px] text-faint">{sub}</span>}
    </button>
  );
}

export default function MissionControl() {
  const [tab, setTab] = useState<TabKey>(() => (TABS.find((t) => t.key === new URLSearchParams(window.location.search).get("tab"))?.key ?? "overview"));
  const [open, setOpen] = useState<string | null>(() => new URLSearchParams(window.location.search).get("nv"));
  const choose = (k: TabKey) => { setTab(k); setOpen(null); window.history.replaceState(null, "", k === "overview" ? window.location.pathname : `?tab=${k}`); };
  const show = (id: string) => { setTab("missions"); setOpen(id); window.history.replaceState(null, "", `?tab=missions&nv=${id}`); };
  const { data: ov, reload } = usePoll<Overview>("/api/v1/mission-control", 4000);
  return (
    <Page full title={tr("Mission Control")} side={<OpsSide />}
          tabs={<Tabs items={TABS.map((t) => ({ ...t, count: t.key === "approvals" ? ov?.kpis.awaiting : t.key === "missions" ? ov?.kpis.active : undefined }))} value={tab} onChange={choose} />}
          actions={ov && <Kill on={ov.kill_switch} done={reload} />}>
      <div className="mx-auto max-w-[1680px]">
        {tab === "overview" && <OverviewTab ov={ov} go={choose} show={show} />}
        {tab === "missions" && (open ? <Monitor id={open} back={() => { setOpen(null); window.history.replaceState(null, "", "?tab=missions"); }} /> : <MissionsTab show={show} />)}
        {tab === "approvals" && <ApprovalsTab show={show} />}
        {tab === "agents" && <FleetTab />}
        {tab === "quality" && <QualityTab />}
        {tab === "artifacts" && <ArtifactsTab show={show} />}
        {tab === "resources" && <ResourcesTab />}
        {tab === "logs" && <LogsTab show={show} />}
      </div>
    </Page>
  );
}

function Kill({ on, done }: { on: boolean; done: () => void }) {
  const flip = async () => {
    if (!on && !(await ask(tr("Dừng khẩn cấp?"), { body: tr("Không bước nào được bắt đầu cho tới khi bạn cho chạy lại. Bước đang chạy sẽ dừng ở điểm an toàn kế tiếp."), confirm: tr("Dừng hết"), danger: true }))) return;
    try { await post("/api/v1/control/kill-switch", { on: !on }); toast(on ? tr("Hệ thống chạy lại.") : tr("Đã bật dừng khẩn cấp."), { tone: on ? "proof" : "tally" }); done(); } catch (e) { fail(e); }
  };
  return <Button kind={on ? "primary" : "danger"} size="sm" onClick={flip}><Icon name="power" size={14} />{on ? tr("Cho chạy lại") : tr("Dừng khẩn cấp")}</Button>;
}

/* ─────────────────────────────────────────────── Overview ─────────────────────────────────────────────── */
function OverviewTab({ ov, go, show }: { ov: Overview | null; go: (k: TabKey) => void; show: (id: string) => void }) {
  if (!ov) return <div className="grid place-items-center py-24"><Spinner size={22} /></div>;
  const h = ov.kpis.health, units = Object.values(h).reduce((a, b) => a + b, 0) || 1, r = ov.resources;
  const budget = r.budget_day ? r.spent_today / r.budget_day : null;
  return (
    <div className="grid gap-4">
      {ov.kill_switch && <p className="bento border-tally/40 px-4 py-3 text-[13.5px] text-tally"><Icon name="power" size={15} className="mr-2 inline" />{tr("Dừng khẩn cấp đang bật: không bước nào được bắt đầu.")}</p>}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
        <Kpi code="MSN.ACT" label={tr("Nhiệm vụ đang chạy")} value={ov.kpis.active} sub={tv`${ov.kpis.missions} nhiệm vụ tất cả`} tone="ai" onClick={() => go("missions")} />
        <Kpi code="APR.Q" label={tr("Chờ bạn duyệt")} value={ov.kpis.awaiting} sub={tr("Im lặng không phải đồng ý")} tone={ov.kpis.awaiting ? "cue" : "mute"} onClick={() => go("approvals")} />
        <Kpi code="SYS.HLTH" label={tr("Sức khoẻ hệ thống")} value={`${Math.round(((h.healthy + h.busy) / units) * 100)}%`} sub={tv`${h.offline} mất kết nối · ${h.degraded} suy giảm`} tone={h.offline ? "tally" : h.degraded ? "cue" : "proof"} onClick={() => go("agents")} />
        <Kpi code="BDG.DAY" label={tr("Đã tiêu hôm nay")} value={usd(r.spent_today)} sub={r.budget_day != null ? tv`hạn mức ${usd(r.budget_day)}` : tr("Chưa đặt hạn mức")} tone={budget != null && budget >= 1 ? "tally" : "accent"} onClick={() => go("resources")} />
        <Kpi code="ALR.N" label={tr("Cảnh báo")} value={ov.kpis.alerts} sub={ov.alerts[0]?.text ?? tr("Không có gì bất thường")} tone={ov.kpis.alerts ? "tally" : "mute"} onClick={() => go("logs")} />
      </div>
      <div className="grid gap-4 xl:grid-cols-12">
        <Bento label={tr("Giao nhiệm vụ")} code="CMP.01" className="xl:col-span-7"><Composer onPlanned={(m) => show(m.mission_id)} autonomy={ov.autonomy} /></Bento>
        <Bento label={tr("Chờ bạn duyệt")} code="APR.02" className="xl:col-span-5" end={<button type="button" className="link text-[12.5px]" onClick={() => go("approvals")}>{tr("Xem hết")}</button>}>
          {ov.approvals.length ? <ul className="grid gap-2">{ov.approvals.slice(0, 4).map((a) => (
            <li key={a.key}><button type="button" onClick={() => (a.kind === "mission" ? show(a.id) : a.link ? goTo(a.link) : go("approvals"))} className="tile flex w-full items-start gap-3 px-3 py-2.5 text-left">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cue" /><span className="min-w-0 flex-1"><span className="block truncate text-[13.5px]">{a.title}</span>
              <span className="block truncate text-[12px] text-faint">{a.asked_by} · {a.why}</span></span></button></li>))}</ul>
            : <p className="text-[13px] text-mute">{tr("Không có gì đang chờ bạn.")}</p>}
        </Bento>
        <Bento label={tr("Tài nguyên máy")} code="RES.03" className="xl:col-span-5" end={<button type="button" className="link text-[12.5px]" onClick={() => go("resources")}>{tr("Chi tiết")}</button>}>
          <MachineMeters r={r} />
        </Bento>
        <Bento label={tr("Nhiệm vụ đang chạy")} code="MSN.04" className="xl:col-span-7" end={<button type="button" className="link text-[12.5px]" onClick={() => go("missions")}>{tr("Hàng đợi")}</button>}>
          {ov.active.length ? <ul className="grid gap-2">{ov.active.map((m) => <MissionRow key={m.mission_id} m={m} onOpen={() => show(m.mission_id)} />)}</ul>
            : <p className="text-[13px] text-mute">{tr("Chưa có nhiệm vụ nào đang chạy. Giao một nhiệm vụ ở trên.")}</p>}
        </Bento>
        <Bento label={tr("Agent Fleet")} code="FLT.05" className="xl:col-span-5" end={<button type="button" className="link text-[12.5px]" onClick={() => go("agents")}>{tr("Tất cả")}</button>}>
          <ul className="grid grid-cols-2 gap-2">{[...ov.fleet.agents, ...ov.fleet.workers].map((u) => (
            <li key={u.key} className="tile flex items-center gap-2.5 px-3 py-2" title={u.detail}><Lamp state={u.state} /><span className="min-w-0 flex-1 truncate text-[13px]">{u.name}</span>
              <span className="text-[11.5px] text-faint">{UNIT[u.state]?.[0]}</span></li>))}</ul>
        </Bento>
        {ov.alerts.length > 0 && <Bento label={tr("Cảnh báo")} code="ALR.06" className="xl:col-span-12">
          <ul className="grid gap-2 md:grid-cols-2">{ov.alerts.map((a, i) => (
            <li key={i} className="tile flex items-center gap-2.5 px-3 py-2 text-[13px]"><Icon name="alert" size={15} className="text-tally" /><span className="min-w-0 flex-1 truncate">{a.text}</span>
              {a.link && <button type="button" className="link text-[12.5px]" onClick={() => goTo(a.link!)}>{tr("Mở")}</button>}</li>))}</ul>
        </Bento>}
      </div>
      <p className="hud-label text-center" aria-hidden="true">NEXORA · MISSION CONTROL · AUTONOMY L{ov.autonomy} · {new Date().toLocaleTimeString(locale)}</p>
    </div>
  );
}

function Lamp({ state }: { state: string }) {
  const tone = UNIT[state]?.[1] ?? "mute";
  return <span className={`relative inline-block h-2 w-2 shrink-0 rounded-full ${DOT[tone]} ${state === "busy" ? "ping" : ""}`} />;
}

function MachineMeters({ r }: { r: Resources }) {
  const m = r.machine;
  const mem = m.memory_total && m.memory_used != null ? m.memory_used / m.memory_total : null;
  const disk = m.disk_total && m.disk_free != null ? 1 - m.disk_free / m.disk_total : null;
  const load = m.load != null ? m.load / m.cpus : null;
  const rows: [string, number | null, string, "accent" | "cue" | "ai"][] = [
    [tr("Bộ nhớ"), mem, mem != null ? `${megabytes(m.memory_used!)} / ${megabytes(m.memory_total!)}` : tr("không đo được"), mem != null && mem > 0.85 ? "cue" : "accent"],
    [tr("CPU (tải 1 phút)"), load, m.load != null ? tv`${m.load} trên ${m.cpus} lõi` : tr("không đo được"), load != null && load > 1 ? "cue" : "ai"],
    [tr("Ổ đĩa"), disk, m.disk_free != null ? tv`còn trống ${megabytes(m.disk_free)}` : "–", disk != null && disk > 0.9 ? "cue" : "accent"],
  ];
  return (
    <div className="grid gap-3">
      {rows.map(([label, share, text, tone]) => (
        <div key={label}><div className="mb-1 flex items-baseline justify-between gap-2 text-[12.5px]"><span className="text-mute">{label}</span><span className="mono text-faint">{text}</span></div>
          <Meter share={share ?? 0} tone={tone} /></div>))}
      <p className="mono text-[12px] text-faint">{tv`${r.running} bước đang chạy`}{r.hold_heavy ? ` · ${tr("bộ nhớ gần đầy: việc nặng chạy lần lượt")}` : ""}</p>
    </div>
  );
}

/* ─────────────────────────────────────────────── Composer ─────────────────────────────────────────────── */
function Composer({ onPlanned, autonomy }: { onPlanned: (m: Mission) => void; autonomy: number }) {
  const [text, setText] = useState(""), [busy, setBusy] = useState(false);
  const plan = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try { const m = await post<Mission>("/api/v1/missions", { text }); setText(""); onPlanned(m); } catch (e) { fail(e); }
    setBusy(false);
  };
  return (
    <div className="flex h-full flex-col gap-3">
      <p className="text-[13px] text-mute">{tr("Nói việc cần làm bằng lời. Mô hình chỉ lập kế hoạch từ những gì NEXORA làm được; máy kiểm tra năng lực, ngân sách và quyền. Không có gì chạy trước khi bạn xác nhận.")}</p>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={4} aria-label={tr("Nhiệm vụ")} className="min-h-[112px] w-full resize-y p-3 text-[14px]"
                onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) plan(); }}
                placeholder={tr("Ví dụ: làm 2 video dọc về buổi sáng ở chợ quê từ footage chưa dùng, không dùng dịch vụ trả tiền, dừng ở bước duyệt clip")} />
      <div className="flex flex-wrap items-center gap-3">
        <Button kind="primary" busy={busy} disabled={!text.trim()} onClick={plan}>{busy ? <Spinner /> : <Icon name="sparkles" size={15} />}{busy ? tr("Đang lập kế hoạch…") : tr("Lập kế hoạch")}</Button>
        <span className="mono text-[12px] text-faint">⌘↵ · {tv`mức tự chủ ${autonomy}`}</span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-[12px] text-faint">
        {[[tr("Làm video từ kho"), "clapper"], [tr("Mô tả footage"), "eye"], [tr("Nghe lời nói"), "mic"]].map(([label, icon]) => (
          <span key={label} className="tile flex items-center gap-2 px-2.5 py-2"><Icon name={icon} size={14} className="text-accent" /><span className="truncate">{label}</span></span>))}
      </div>
    </div>
  );
}

function PlanEditor({ m, kinds, channels, templates, done }: { m: Mission; kinds: { kind: string; name: string }[]; channels: string[]; templates: string[]; done: () => void }) {
  const [plan, setPlan] = useState<Plan>(m.plan), [busy, setBusy] = useState<string | null>(null);
  useEffect(() => { setPlan(m.plan); }, [m.plan]);
  const set = (k: keyof Plan, v: unknown) => setPlan({ ...plan, [k]: v });
  const dirty = JSON.stringify(plan) !== JSON.stringify(m.plan);
  const run = async (key: string, fn: () => Promise<unknown>) => { setBusy(key); try { await fn(); done(); } catch (e) { fail(e); } setBusy(null); };
  const save = () => run("save", () => post(`/api/v1/missions/${m.mission_id}`, { plan }, "PATCH"));
  const confirm = () => run("confirm", async () => { if (dirty) await post(`/api/v1/missions/${m.mission_id}`, { plan }, "PATCH"); await post(`/api/v1/missions/${m.mission_id}/confirm`); toast(tr("Đã xác nhận. Nhiệm vụ bắt đầu chạy."), { tone: "proof" }); });
  const lines = (v: string[]) => v.join("\n"), split = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
  const video = plan.kind === "video";
  return (
    <div className="grid gap-4">
      {m.problems.length > 0 && <ul className="grid gap-1.5 rounded-xl border border-tally/30 bg-tally/[0.06] px-4 py-3 text-[13px] text-tally">{m.problems.map((p) => <li key={p} className="flex gap-2"><Icon name="alert" size={14} className="mt-0.5 shrink-0" />{p}</li>)}</ul>}
      <div className="grid gap-4 md:grid-cols-2">
        <label className="md:col-span-2"><span className="field-label">{tr("Mục tiêu")}</span><input value={plan.goal} onChange={(e) => set("goal", e.target.value)} className="w-full px-3" /></label>
        {video && <label className="md:col-span-2"><span className="field-label">{tr("Tên video")}</span><input value={plan.title ?? ""} onChange={(e) => set("title", e.target.value)} maxLength={60} className="w-full px-3" /></label>}
        <label><span className="field-label">{tr("Loại việc")}</span>
          <select value={plan.kind} onChange={(e) => set("kind", e.target.value)} className="w-full pl-3"><option value="">{tr("Chọn…")}</option>{kinds.map((k) => <option key={k.kind} value={k.kind}>{k.name}</option>)}</select></label>
        {video && <label><span className="field-label">{tr("Số video")}</span><input type="number" min={1} max={10} value={plan.count} onChange={(e) => set("count", Number(e.target.value))} className="mono w-full px-3" /></label>}
        {video && <div><span className="field-label">{tr("Khung hình")}</span><Seg items={FORMATS} value={plan.format} onChange={(v) => set("format", v)} label={tr("Khung hình")} /></div>}
        {video && <label><span className="field-label">{tr("Số câu lời dẫn mỗi video")}</span><input type="number" min={2} max={12} value={plan.lines} onChange={(e) => set("lines", Number(e.target.value))} className="mono w-full px-3" /></label>}
        {video && <label><span className="field-label">{tr("Kênh")}</span><select value={plan.channel ?? ""} onChange={(e) => set("channel", e.target.value || null)} className="w-full pl-3"><option value="">{tr("Không chọn")}</option>{channels.map((c) => <option key={c}>{c}</option>)}</select></label>}
        {video && <label><span className="field-label">{tr("Mẫu video")}</span><select value={plan.template ?? ""} onChange={(e) => set("template", e.target.value || null)} className="w-full pl-3"><option value="">{tr("Không chọn")}</option>{templates.map((c) => <option key={c}>{c}</option>)}</select></label>}
        <label><span className="field-label">{tr("Ngân sách tối đa (USD)")}</span><input type="number" min={0} step={0.1} value={plan.budget ?? ""} onChange={(e) => set("budget", e.target.value === "" ? null : Number(e.target.value))} placeholder={tr("không giới hạn riêng")} className="mono w-full px-3" /></label>
        <div className="grid content-start gap-2 text-[13px]"><span className="field-label">{tr("Quyền")}</span>
          <label className="flex items-center gap-2"><input type="checkbox" checked={plan.paid} onChange={(e) => set("paid", e.target.checked)} />{tr("Được dùng dịch vụ trả tiền")}</label>
          {video && <label className="flex items-center gap-2"><input type="checkbox" checked={plan.stock} onChange={(e) => set("stock", e.target.checked)} />{tr("Lấy video stock miễn phí cho câu thiếu hình")}</label>}
          {video && <label className="flex items-center gap-2"><input type="checkbox" checked={plan.critique} onChange={(e) => set("critique", e.target.checked)} />{tr("Tự phản biện kịch bản")}</label>}
          <span className="flex items-center gap-2 text-faint"><Icon name="shield" size={14} />{tr("Xuất bản không bao giờ nằm trong nhiệm vụ: chỉ bạn bấm.")}</span>
        </div>
        <label><span className="field-label">{tr("Ràng buộc (mỗi dòng một ý)")}</span><textarea rows={3} value={lines(plan.constraints)} onChange={(e) => set("constraints", split(e.target.value))} className="w-full p-2.5 text-[13px]" /></label>
        <label><span className="field-label">{tr("Điều kiện nghiệm thu (mỗi dòng một ý)")}</span><textarea rows={3} value={lines(plan.acceptance)} onChange={(e) => set("acceptance", split(e.target.value))} className="w-full p-2.5 text-[13px]" /></label>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button kind="primary" busy={busy === "confirm"} disabled={!!busy || (!dirty && m.status !== "planned")} onClick={confirm}><Icon name="check" size={15} />{tr("Xác nhận và chạy")}</Button>
        <Button busy={busy === "save"} disabled={!dirty || !!busy} onClick={save}>{tr("Lưu và kiểm tra lại")}</Button>
        <Button kind="quiet" disabled={!!busy} onClick={() => run("cancel", () => post(`/api/v1/missions/${m.mission_id}/cancel`))}>{tr("Bỏ nhiệm vụ")}</Button>
        <span className="mono ml-auto text-[12px] text-faint">{tv`mức tự chủ ${plan.autonomy}: cổng duyệt theo mức này`}</span>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────── Missions ─────────────────────────────────────────────── */
function MissionRow({ m, onOpen }: { m: Mission; onOpen: () => void }) {
  const done = m.children.filter((c) => c.state === "done").length;
  return (
    <li><button type="button" onClick={onOpen} className="tile flex w-full flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5 text-left">
      <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px]">{m.text}</span>
        <span className="block truncate text-[12px] text-faint">{m.kind_name ?? tr("Chưa rõ loại việc")} · {clock(m.created_at)}{m.children.length ? ` · ${tv`${done}/${m.children.length} xong`}` : ""}</span></span>
      {m.spent > 0 && <span className="mono text-[12px] text-faint">{usd(m.spent)}</span>}
      <State map={STATUS} value={m.status} />
    </button></li>
  );
}

function MissionsTab({ show }: { show: (id: string) => void }) {
  const { data } = usePoll<MissionList>("/api/v1/missions", 4000);
  const [filter, setFilter] = useState("");
  const all = data?.missions ?? [];
  const shown = all.filter((m) => !filter || (filter === "active" ? ["queued", "running", "awaiting_approval", "blocked", "paused"].includes(m.status) : filter === "plan" ? ["draft", "planned"].includes(m.status) : ["completed", "partially_completed", "failed", "cancelled"].includes(m.status)));
  return (
    <div className="grid gap-4 xl:grid-cols-12">
      <Bento label={tr("Giao nhiệm vụ")} code="CMP.01" className="xl:col-span-4"><Composer onPlanned={(m) => show(m.mission_id)} autonomy={all[0]?.plan.autonomy ?? 0} /></Bento>
      <Bento label={tr("Hàng đợi nhiệm vụ")} code="MSN.Q" className="xl:col-span-8"
             end={<Seg items={[["", tr("Tất cả")], ["active", tr("Đang chạy")], ["plan", tr("Kế hoạch")], ["done", tr("Đã xong")]] as const} value={filter} onChange={setFilter} label={tr("Lọc")} />}>
        {!data ? <Spinner /> : shown.length ? <ul className="grid gap-2">{shown.map((m) => <MissionRow key={m.mission_id} m={m} onOpen={() => show(m.mission_id)} />)}</ul>
          : <p className="text-[13px] text-mute">{tr("Chưa có nhiệm vụ nào ở đây.")}</p>}
      </Bento>
      <Bento label={tr("Việc của hệ thống")} code="SYS.Q" className="xl:col-span-12">
        <p className="mb-3 text-[12.5px] text-faint">{tr("Việc hệ thống tự chạy hoặc bạn bắt đầu ở màn hình khác (nhập footage, mô tả, làm nét…), không thuộc nhiệm vụ nào.")}</p>
        {data && data.system.length ? <ul className="grid gap-2 md:grid-cols-2 2xl:grid-cols-3">{data.system.map((r) => (
          <li key={r.run_id}><button type="button" onClick={() => goTo(r.project_id ? `/du-an/${r.project_id}` : "/tien-trinh")} className="tile flex w-full items-center gap-3 px-3 py-2 text-left">
            <span className="min-w-0 flex-1"><span className="block truncate text-[13px]">{r.name}{r.title ? ` · ${r.title}` : ""}</span><span className="mono block text-[11.5px] text-faint">{clock(r.created_at)}</span></span>
            <Tag tone={r.status === "failed" ? "tally" : r.status === "running" ? "ai" : r.status === "queued" ? "accent" : "cue"}>{CHILD_STATE[{ waiting_review: "waiting" }[r.status] ?? r.status] ?? r.status}</Tag></button></li>))}</ul>
          : <p className="text-[13px] text-mute">{tr("Không có việc nào của hệ thống đang chạy hay chờ.")}</p>}
      </Bento>
    </div>
  );
}

function Monitor({ id, back }: { id: string; back: () => void }) {
  const { data: m, reload } = usePoll<Detail>(`/api/v1/missions/${id}`, 3000);
  const { data: list } = usePoll<MissionList>("/api/v1/missions", 30000);
  const [busy, setBusy] = useState<string | null>(null);
  const act = async (name: string, ok: string) => {
    if (name === "cancel" && !(await ask(tr("Huỷ nhiệm vụ?"), { body: tr("Các việc của trợ lý dừng lại và các lượt chạy đang chạy bị huỷ. Những gì đã làm xong vẫn giữ."), confirm: tr("Huỷ nhiệm vụ"), danger: true }))) return;
    setBusy(name); try { await post(`/api/v1/missions/${id}/${name}`); toast(ok); reload(); } catch (e) { fail(e); } setBusy(null);
  };
  if (!m) return <div className="grid place-items-center py-24"><Spinner size={22} /></div>;
  const planning = m.status === "draft" || m.status === "planned";
  const running = ["queued", "running", "awaiting_approval", "blocked"].includes(m.status);
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Button kind="quiet" size="sm" onClick={back}><Icon name="back" size={14} />{tr("Hàng đợi")}</Button>
        <h2 className="display min-w-0 flex-1 truncate text-[18px]">{m.text}</h2>
        <State map={STATUS} value={m.status} />
        {running && <Button size="sm" busy={busy === "pause"} onClick={() => act("pause", tr("Đã tạm dừng."))}><Icon name="pause" size={14} />{tr("Tạm dừng")}</Button>}
        {m.status === "paused" && <Button size="sm" kind="primary" busy={busy === "resume"} onClick={() => act("resume", tr("Tiếp tục chạy."))}><Icon name="play" size={14} />{tr("Tiếp tục")}</Button>}
        {["failed", "partially_completed", "blocked"].includes(m.status) && <Button size="sm" busy={busy === "retry"} onClick={() => act("retry", tr("Đã cho chạy lại các bước lỗi."))}><Icon name="refresh" size={14} />{tr("Chạy lại bước lỗi")}</Button>}
        {!planning && m.status !== "cancelled" && m.status !== "completed" && <Button size="sm" kind="danger" busy={busy === "cancel"} onClick={() => act("cancel", tr("Đã huỷ nhiệm vụ."))}>{tr("Huỷ")}</Button>}
      </div>
      {planning ? <Bento label={tr("Kế hoạch")} code="PLN.EDIT"><PlanEditor m={m} kinds={list?.kinds ?? []} channels={list?.channels ?? []} templates={list?.templates ?? []} done={reload} /></Bento> : (
        <div className="grid gap-4 xl:grid-cols-12">
          <Bento label={tr("Kế hoạch đã xác nhận")} code="PLN.LOCK" className="xl:col-span-4"><PlanFacts m={m} /></Bento>
          <Bento label={tr("Theo dõi trực tiếp")} code="LIVE.MON" className="xl:col-span-8">
            {m.tasks.length === 0 && m.runs.length === 0 && <p className="text-[13px] text-mute">{tr("Nhiệm vụ này không tạo việc nào.")}</p>}
            <div className="grid gap-3">
              {m.tasks.map((t) => <TaskCard key={t.task_id} t={t} child={m.children.find((c) => c.id === t.task_id)} title={m.projects.find((p) => p.project_id === t.project_id)?.title ?? ""} />)}
              {m.runs.map((r) => <RunCard key={r.run_id} r={r} />)}
            </div>
          </Bento>
        </div>)}
      <Bento label={tr("Dòng sự kiện")} code="EVT.LOG">
        <ol className="grid gap-1.5 border-l border-line pl-4">{[...m.events].reverse().map((e, i) => (
          <li key={i} className="relative text-[13px]"><span className="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-accent" />
            <span className="mono mr-2 text-[12px] text-faint">{clock(e.at)}</span><span className="text-mute">{EVENT[e.kind] ?? e.kind}</span>{e.text && <span className="text-faint"> · {e.text}</span>}</li>))}</ol>
      </Bento>
    </div>
  );
}
const EVENT: Record<string, string> = { created: tr("Giao việc"), planned: tr("Đã lập kế hoạch"), edited: tr("Sửa kế hoạch"), confirmed: tr("Xác nhận"), paused: tr("Tạm dừng"), resumed: tr("Tiếp tục"),
  cancelled: tr("Huỷ"), retried: tr("Chạy lại"), note: tr("Ghi chú") };

function PlanFacts({ m }: { m: Mission }) {
  const p = m.plan;
  const rows: [string, React.ReactNode][] = [[tr("Loại việc"), m.kind_name ?? p.kind], [tr("Mục tiêu"), p.goal], ...(p.kind === "video" && p.title ? [[tr("Tên video"), p.title] as [string, React.ReactNode]] : [])];
  if (p.kind === "video") rows.push([tr("Video"), tv`${p.count} video · ${FORMATS.find((f) => f[0] === p.format)?.[1] ?? p.format} · ${p.lines} câu`], [tr("Kênh / mẫu"), [p.channel, p.template].filter(Boolean).join(" · ") || "–"]);
  rows.push([tr("Ngân sách"), p.budget != null ? usd(p.budget) : tr("theo hạn mức chung")], [tr("Dịch vụ trả tiền"), p.paid ? tr("được dùng") : tr("không")], [tr("Đã tiêu"), usd(m.spent)]);
  return (
    <div className="grid gap-3 text-[13px]">
      <dl className="grid gap-1.5">{rows.map(([k, v]) => <div key={k} className="flex gap-3"><dt className="w-28 shrink-0 text-faint">{k}</dt><dd className="min-w-0">{v}</dd></div>)}</dl>
      {p.constraints.length > 0 && <div><p className="field-label">{tr("Ràng buộc")}</p><ul className="list-inside list-disc text-mute">{p.constraints.map((c) => <li key={c}>{c}</li>)}</ul></div>}
      {p.acceptance.length > 0 && <div><p className="field-label">{tr("Nghiệm thu")}</p><ul className="grid gap-1 text-mute">{p.acceptance.map((c) => <li key={c} className="flex gap-2"><Icon name="check" size={14} className="mt-0.5 text-proof" />{c}</li>)}</ul></div>}
    </div>
  );
}

function TaskCard({ t, child, title }: { t: Task; child?: Child; title: string }) {
  return (
    <div className="tile p-3.5">
      <div className="mb-2 flex flex-wrap items-center gap-2"><Icon name="sparkles" size={15} className="text-ai" /><span className="min-w-0 flex-1 truncate font-medium">{title || t.goal}</span>
        <span className="mono text-[11.5px] text-faint">{tv`bước ${t.step}`}</span><Tag tone={child?.state === "waiting" ? "cue" : child?.state === "failed" ? "tally" : child?.state === "done" ? "proof" : "ai"}>{CHILD_STATE[child?.state ?? ""] ?? t.status}</Tag>
        <button type="button" className="link text-[12.5px]" onClick={() => goTo(`/du-an/${t.project_id}`)}>{tr("Mở dự án")}</button></div>
      <ol className="grid max-h-44 gap-1 overflow-y-auto text-[12.5px]">{t.log.slice(-8).map((l, i) => <li key={i}><span className="mono mr-2 text-faint">{clock(l.at)}</span><span className="text-accent">{l.role}</span> <span className="text-mute">{l.text}</span></li>)}</ol>
    </div>
  );
}

function RunCard({ r }: { r: RunDetail }) {
  const [open, setOpen] = useState(false);
  const done = r.stages.filter((s) => s.status === "succeeded" || s.status === "skipped").length;
  return (
    <div className="tile p-3.5">
      <button type="button" onClick={() => setOpen(!open)} className="flex w-full flex-wrap items-center gap-2 text-left" aria-expanded={open}>
        <Icon name={open ? "down" : "next"} size={14} className="text-faint" /><span className="min-w-0 flex-1 truncate font-medium">{r.name}</span>
        <span className="mono text-[11.5px] text-faint">{tv`${done}/${r.stages.length} bước`} · {usd(r.cost)}</span>
        {r.stalled && <Tag tone="tally">{tr("không thấy nhịp")}</Tag>}<Tag tone={r.status === "failed" ? "tally" : r.status === "running" ? "ai" : r.status === "succeeded" ? "proof" : r.status === "queued" ? "accent" : "cue"}>{CHILD_STATE[{ waiting_review: "waiting", succeeded: "done" }[r.status] ?? r.status] ?? r.status}</Tag>
      </button>
      <div className="mt-2.5 flex gap-[3px]">{r.stages.map((s) => <span key={s.stage_id} title={`${stageName(s.stage_key, r.pipeline)}: ${s.status}`} className={`h-1.5 flex-1 rounded-full ${s.status === "succeeded" || s.status === "skipped" ? "bg-proof" : s.status === "running" ? "working" : s.status === "failed" ? "bg-tally" : s.status === "waiting_review" || s.status === "blocked" ? "bg-cue" : "bg-overlay"}`} />)}</div>
      {open && <table className="mt-3 w-full text-[12.5px]"><thead><tr className="text-left text-faint"><th className="py-1">{tr("Bước")}</th><th>{tr("Trạng thái")}</th><th>{tr("Lần")}</th><th>{tr("Thời gian")}</th><th>{tr("Lỗi")}</th></tr></thead>
        <tbody>{r.stages.map((s) => { const last = s.attempts[s.attempts.length - 1]; return (
          <tr key={s.stage_id} className="border-t border-line align-top"><td className="py-1.5 pr-2">{stageName(s.stage_key, r.pipeline)}</td><td className="pr-2 text-mute">{s.status}{s.blocked_reason ? ` · ${s.blocked_reason}` : ""}</td>
            <td className="mono pr-2">{s.attempts.length}</td><td className="mono pr-2">{secs(last?.seconds ?? null)}</td><td className="max-w-[260px] truncate text-tally" title={last?.error_message ?? ""}>{last?.error_code ?? ""}</td></tr>); })}</tbody></table>}
    </div>
  );
}

/* ─────────────────────────────────────────────── Approvals ─────────────────────────────────────────────── */
const KIND: Record<string, [string, string]> = { mission: [tr("Kế hoạch nhiệm vụ"), "bolt"], gate: [tr("Cổng duyệt"), "check"], blocked: [tr("Bước bị chặn"), "alert"], task: [tr("Trợ lý chờ"), "sparkles"],
  idea: [tr("Ý tưởng bị chặn"), "spark"], proposal: [tr("Đề xuất Storyboard"), "board"], vq: [tr("Công thức VQ"), "eye"] };

function ApprovalsTab({ show }: { show: (id: string) => void }) {
  const { data, reload } = usePoll<{ approvals: Approval[] }>("/api/v1/approvals", 4000);
  const [note, setNote] = useState<Record<string, string>>({}), [busy, setBusy] = useState<string | null>(null), [kind, setKind] = useState("");
  const decide = async (a: Approval, decision: string) => {
    setBusy(a.key + decision);
    try { await post("/api/v1/approvals/decide", { kind: a.kind, id: a.id, decision, note: note[a.key] ?? "" }); toast(tr("Đã ghi quyết định của bạn."), { tone: "proof" }); reload(); } catch (e) { fail(e); }
    setBusy(null);
  };
  const all = data?.approvals ?? [], kinds = [...new Set(all.map((a) => a.kind))];
  const shown = all.filter((a) => !kind || a.kind === kind);
  const NAME: Record<string, string> = { confirm: tr("Xác nhận"), cancel: tr("Bỏ"), approve: tr("Duyệt"), reject: tr("Từ chối"), changes: tr("Yêu cầu sửa"), resume: tr("Cho chạy tiếp") };
  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <p className="min-w-0 flex-1 text-[13px] text-mute">{tr("Mọi thứ đang chờ bạn ở một chỗ. Không có gì tự đi tiếp: im lặng không phải đồng ý. Việc cần xem kỹ (clip, công thức làm nét) thì mở ra để duyệt ở đúng màn hình của nó.")}</p>
        {kinds.length > 1 && <Seg items={[["", tr("Tất cả")], ...kinds.map((k) => [k, KIND[k]?.[0] ?? k] as const)] as const} value={kind} onChange={setKind} label={tr("Lọc")} />}
      </div>
      {!data ? <Spinner /> : shown.length === 0 ? <Empty icon="check" title={tr("Không có gì đang chờ bạn.")} /> : (
        <ul className="grid gap-3 lg:grid-cols-2 2xl:grid-cols-3">{shown.map((a) => (
          <li key={a.key} className="bento flex flex-col gap-3 p-4">
            <div className="flex items-start gap-3"><span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-cue/12 text-cue"><Icon name={KIND[a.kind]?.[1] ?? "info"} size={16} /></span>
              <div className="min-w-0 flex-1"><p className="font-medium">{a.title}</p><p className="text-[12px] text-faint">{KIND[a.kind]?.[0]} · {a.asked_by} · {clock(a.at)}</p></div></div>
            <dl className="grid gap-1 text-[12.5px]">
              <div className="flex gap-2"><dt className="w-20 shrink-0 text-faint">{tr("Lý do")}</dt><dd className="text-mute">{a.why}</dd></div>
              <div className="flex gap-2"><dt className="w-20 shrink-0 text-faint">{tr("Ảnh hưởng")}</dt><dd className="text-mute">{a.touches}</dd></div>
              {a.cost != null && <div className="flex gap-2"><dt className="w-20 shrink-0 text-faint">{tr("Chi phí")}</dt><dd className="mono">{usd(a.cost)}</dd></div>}
              <div className="flex gap-2"><dt className="w-20 shrink-0 text-faint">{tr("Tiếp theo")}</dt><dd className="text-mute">{a.next}</dd></div>
            </dl>
            {a.actions.includes("changes") && <input value={note[a.key] ?? ""} onChange={(e) => setNote({ ...note, [a.key]: e.target.value })} placeholder={tr("Cần sửa gì (bắt buộc khi trả lại)")} aria-label={tr("Ghi chú")} className="h-8 px-2.5 text-[12.5px]" />}
            <div className="mt-auto flex flex-wrap gap-2">
              {a.actions.map((d) => <Button key={d} size="sm" kind={d === "approve" || d === "confirm" ? "primary" : d === "reject" || d === "cancel" ? "quiet" : "plain"} busy={busy === a.key + d}
                                            disabled={d === "changes" && !(note[a.key] ?? "").trim()} onClick={() => decide(a, d)}>{NAME[d] ?? d}</Button>)}
              {a.kind === "mission" ? <Button size="sm" kind="quiet" onClick={() => show(a.id)}>{tr("Xem và sửa kế hoạch")}</Button>
                : a.link && <Button size="sm" kind="quiet" onClick={() => goTo(a.link!)}><Icon name="external" size={13} />{tr("Mở để xem")}</Button>}
            </div>
          </li>))}</ul>)}
    </div>
  );
}

/* ─────────────────────────────────────────────── Fleet ─────────────────────────────────────────────── */
function FleetTab() {
  const { data } = usePoll<Fleet>("/api/v1/fleet", 6000);
  if (!data) return <div className="grid place-items-center py-24"><Spinner size={22} /></div>;
  const group = (label: string, code: string, units: Unit[]) => (
    <Bento label={label} code={code}>
      <ul className="grid gap-2 md:grid-cols-2 2xl:grid-cols-3">{units.map((u) => (
        <li key={u.key} className="tile flex flex-col gap-1.5 p-3.5">
          <span className="flex items-center gap-2.5"><Lamp state={u.state} /><span className="min-w-0 flex-1 truncate font-medium">{u.name}</span><State map={UNIT} value={u.state} /></span>
          {u.role && <span className="text-[12px] text-faint">{u.role}</span>}
          <span className="text-[12.5px] text-mute">{u.detail}</span>
          {u.fix && <span className="text-[12px] text-cue">{u.fix}</span>}
        </li>))}</ul>
    </Bento>
  );
  return (
    <div className="grid gap-4">
      <p className="text-[13px] text-mute">{tr("Trạng thái đọc từ kiểm tra thật: kết nối, mô hình đã tải, việc đang chạy, nhịp của máy làm. Ổn định, Đang làm, Suy giảm (chạy được nhưng thiếu một thứ cần), Mất kết nối (thiếu thứ bắt buộc), Tắt (dừng khẩn cấp, hoặc máy không cài thứ không bắt buộc).")}</p>
      {group(tr("Các agent"), "FLT.AGT", data.agents)}
      {group(tr("Làn chạy"), "FLT.WRK", data.workers)}
      {group(tr("Máy móc phía sau"), "FLT.ENG", data.engines)}
    </div>
  );
}

/* ─────────────────────────────────────────────── Quality ─────────────────────────────────────────────── */
function QualityTab() {
  const { data } = usePoll<{ renders: QualityRow[]; counts: Record<string, number> }>("/api/v1/quality", 15000);
  const [only, setOnly] = useState("");
  if (!data) return <div className="grid place-items-center py-24"><Spinner size={22} /></div>;
  const rows = data.renders.filter((r) => !only || r.verdict === only);
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Object.entries(VERDICT).map(([k, [label, tone]]) => <Kpi key={k} code={`QC.${k.slice(0, 4).toUpperCase()}`} label={label} value={data.counts[k] ?? 0} tone={tone} onClick={() => setOnly(only === k ? "" : k)} />)}
      </div>
      <Bento label={tr("Kết quả kiểm tra từng bản dựng")} code="QC.LIST" end={only && <button type="button" className="link text-[12.5px]" onClick={() => setOnly("")}>{tr("Bỏ lọc")}</button>}>
        <p className="mb-3 text-[12.5px] text-faint">{tr("Quy từ kiểm tra đo được: FAIL khi một phép đo không đạt, PASS WITH WARNINGS khi đạt nhưng có điểm nên xem, MANUAL REVIEW khi không có gì đo được (bản dựng nhập từ ngoài). Bên cạnh là quyết định của bạn.")}</p>
        {rows.length === 0 ? <p className="text-[13px] text-mute">{tr("Chưa có bản dựng nào.")}</p> : (
          <div className="scroll-x"><table className="w-full min-w-[720px] text-[13px]">
            <thead><tr className="text-left text-[12px] text-faint"><th className="py-2">{tr("Dự án")}</th><th>{tr("Kết quả")}</th><th>{tr("Thông số")}</th><th>{tr("Phát hiện")}</th><th>{tr("Bạn")}</th><th /></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.render_id} className="border-t border-line align-top">
                <td className="py-2 pr-3"><span className="block">{r.title}</span><span className="mono text-[11.5px] text-faint">{clock(r.created_at)}</span></td>
                <td className="py-2 pr-3"><State map={VERDICT} value={r.verdict} /></td>
                <td className="mono py-2 pr-3 text-[12px] text-mute">{r.width && r.height ? `${r.width}×${r.height}` : "–"} · {secs(r.duration)}</td>
                <td className="max-w-[320px] py-2 pr-3 text-[12.5px] text-mute">{[...r.failed.map((f) => `✕ ${f}`), ...r.findings].slice(0, 4).join(" · ") || "–"}</td>
                <td className="py-2 pr-3 text-[12.5px]">{REVIEW[r.review]}{r.comment ? <span className="block text-faint">{r.comment}</span> : null}</td>
                <td className="py-2"><button type="button" className="link text-[12.5px]" onClick={() => goTo(`/du-an/${r.project_id}`)}>{tr("Mở")}</button></td>
              </tr>))}</tbody></table></div>)}
      </Bento>
    </div>
  );
}

/* ─────────────────────────────────────────────── Artifacts ─────────────────────────────────────────────── */
type Lineage = { render_id: string; script: { version: number }; shots: { line: number; text: string; duration: number; source: { name: string; t_in: number | null; derived: { role: string }[] } | null; generated: { kind: string; provider: string }[] | null }[] };

function ArtifactsTab({ show }: { show: (id: string) => void }) {
  const { data } = usePoll<{ projects: ArtifactRow[] }>("/api/v1/artifacts", 20000);
  const [trace, setTrace] = useState<string | null>(null);
  const { data: lineage } = usePoll<Lineage>(trace ? `/api/v1/renders/${trace}/lineage` : "", 60000);
  if (!data) return <div className="grid place-items-center py-24"><Spinner size={22} /></div>;
  return (
    <div className="grid gap-4 xl:grid-cols-12">
      <Bento label={tr("Sản phẩm theo dự án")} code="ART.TREE" className={trace ? "xl:col-span-7" : "xl:col-span-12"}>
        <p className="mb-3 text-[12.5px] text-faint">{tr("Footage gốc → kịch bản → bản dựng → gói xuất bản. Chỉ là đường dẫn tới file có sẵn; không chép media. Dự án của nhiệm vụ đứng trước.")}</p>
        {data.projects.length === 0 ? <p className="text-[13px] text-mute">{tr("Chưa có dự án nào.")}</p> : (
          <ul className="grid gap-2">{data.projects.map((p) => (
            <li key={p.project_id} className="tile flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5">
              <span className="min-w-0 flex-1"><button type="button" className="block truncate text-left text-[13.5px] hover:text-accent" onClick={() => goTo(`/du-an/${p.project_id}`)}>{p.title}</button>
                {p.mission_id && <button type="button" className="link text-[11.5px]" onClick={() => show(p.mission_id!)}>{tr("thuộc một nhiệm vụ")}</button>}</span>
              <span className="flex flex-wrap items-center gap-1.5 text-[11.5px]">
                <span className="chip">{tv`${p.sources} footage`}</span><Icon name="next" size={12} className="text-faint" />
                <span className="chip">{p.script_version ? tv`kịch bản v${p.script_version}` : tr("chưa có kịch bản")}</span><Icon name="next" size={12} className="text-faint" />
                {p.renders.length ? p.renders.slice(0, 3).map((r) => (
                  <button key={r.render_id} type="button" onClick={() => setTrace(trace === r.render_id ? null : r.render_id)} aria-pressed={trace === r.render_id}
                          className={`chip ${trace === r.render_id ? "ring-1 ring-accent" : ""}`}><span className={`h-1.5 w-1.5 rounded-full ${DOT[VERDICT[r.verdict]?.[1] ?? "mute"]}`} />{clock(r.created_at)}{r.approved ? " ✓" : ""}{r.packaged ? " · gói" : ""}</button>))
                  : <span className="chip">{tr("chưa dựng")}</span>}
              </span>
            </li>))}</ul>)}
      </Bento>
      {trace && <Bento label={tr("Nguồn gốc bản dựng")} code="ART.LIN" className="xl:col-span-5" end={<button type="button" className="link text-[12.5px]" onClick={() => setTrace(null)}>{tr("Đóng")}</button>}>
        {!lineage ? <Spinner /> : <ol className="grid gap-2 text-[12.5px]">
          <li className="text-faint">{tv`Kịch bản phiên bản ${lineage.script.version}`}</li>
          {lineage.shots.map((s) => (
            <li key={s.line} className="tile px-3 py-2"><span className="mono mr-2 text-accent">{s.line}</span>{s.text}
              <span className="block text-faint">{s.source ? `${s.source.name}${s.source.t_in != null ? ` @ ${s.source.t_in.toFixed(1)}s` : ""}${s.source.derived.length ? ` · ${s.source.derived.map((d) => d.role).join(", ")}` : ""}` : s.generated?.length ? s.generated.map((g) => `${g.kind} · ${g.provider}`).join(", ") : tr("không có hình")}</span></li>))}
        </ol>}
      </Bento>}
    </div>
  );
}

/* ─────────────────────────────────────────────── Budget & resources ─────────────────────────────────────────────── */
function ResourcesTab() {
  const { data: r } = usePoll<Resources>("/api/v1/resources", 5000);
  if (!r) return <div className="grid place-items-center py-24"><Spinner size={22} /></div>;
  const max = Math.max(0.01, ...r.by_day.map((d) => d.cost));
  const lanes: [string, string][] = [["interactive", tr("Làn tương tác")], ["background", tr("Làn chạy nền")]];
  return (
    <div className="grid gap-4 xl:grid-cols-12">
      <Bento label={tr("Ngân sách")} code="BDG.01" className="xl:col-span-5" end={<button type="button" className="link text-[12.5px]" onClick={() => goTo("/chi-phi")}>{tr("Đặt hạn mức")}</button>}>
        <div className="grid gap-4">
          {([[tr("Hôm nay"), r.spent_today, r.budget_day], [tr("Tháng này"), r.spent_month, r.budget_month]] as const).map(([label, spent, cap]) => (
            <div key={label}><div className="mb-1 flex items-baseline justify-between text-[13px]"><span className="text-mute">{label}</span><span className="mono">{usd(spent)} <span className="text-faint">/ {cap != null ? usd(cap) : "∞"}</span></span></div>
              <Meter share={cap ? spent / cap : 0} tone={cap && spent >= cap ? "cue" : "accent"} /></div>))}
          <div className="flex h-20 items-end gap-1" role="img" aria-label={tr("Chi phí 14 ngày")}>{r.by_day.map((d) => <span key={d.day} title={`${d.day}: ${usd(d.cost)}`} className="flex-1 rounded-t bg-gradient-to-t from-accent/40 to-ai/80" style={{ height: `${Math.max(3, (d.cost / max) * 100)}%` }} />)}</div>
        </div>
      </Bento>
      <Bento label={tr("Máy này")} code="RES.MAC" className="xl:col-span-7"><MachineMeters r={r} /></Bento>
      <Bento label={tr("Hàng đợi theo làn")} code="RES.LANE" className="xl:col-span-5">
        <ul className="grid gap-2">{lanes.map(([k, name]) => { const q = r.lanes[k] ?? {}; return (
          <li key={k} className="tile grid grid-cols-4 gap-2 px-3 py-2.5 text-[12.5px]"><span className="col-span-4 font-medium">{name}</span>
            {[[tr("chờ"), q.ready], [tr("đang chạy"), q.running], [tr("chờ thử lại"), q.retry_wait], [tr("tốn tiền"), q.costly_running]].map(([l, n]) => <span key={l as string}><span className="mono block text-[18px]">{n ?? 0}</span><span className="text-faint">{l}</span></span>)}</li>); })}</ul>
        <p className="mt-3 text-[12px] text-faint">{tr("Máy có 24 GB: việc nặng (render 4K, làm nét) chạy lần lượt trên làn chạy nền.")}</p>
      </Bento>
      <Bento label={tr("Theo nhà cung cấp và mô hình (tháng này)")} code="BDG.PRV" className="xl:col-span-7">
        {r.providers.length === 0 ? <p className="text-[13px] text-mute">{tr("Chưa có lần gọi nào tháng này.")}</p> : (
          <div className="scroll-x"><table className="w-full min-w-[520px] text-[12.5px]"><thead><tr className="text-left text-faint"><th className="py-1.5">{tr("Công cụ")}</th><th>{tr("Việc")}</th><th>{tr("Chạy ở")}</th><th className="text-right">{tr("Lần gọi")}</th><th className="text-right">{tr("Lỗi")}</th><th className="text-right">{tr("Chi phí")}</th></tr></thead>
            <tbody>{[...r.providers].sort((a, b) => b.cost - a.cost || b.calls - a.calls).slice(0, 14).map((p) => (
              <tr key={`${p.adapter}-${p.operation}`} className="border-t border-line"><td className="py-1.5">{p.adapter}</td><td className="text-mute">{p.operation}</td><td className="text-mute">{p.runs}</td>
                <td className="mono text-right">{p.calls}</td><td className={`mono text-right ${p.failures ? "text-tally" : ""}`}>{p.failures}</td><td className="mono text-right">{usd(p.cost)}</td></tr>))}</tbody></table></div>)}
      </Bento>
    </div>
  );
}

/* ─────────────────────────────────────────────── Logs ─────────────────────────────────────────────── */
function LogsTab({ show }: { show: (id: string) => void }) {
  const [kind, setKind] = useState("");
  const { data } = usePoll<{ entries: LogEntry[] }>(`/api/v1/logs?kind=${kind}&limit=300`, 6000);
  const KINDS = [["", tr("Tất cả")], ["mission", tr("Nhiệm vụ")], ["run", tr("Lượt chạy")], ["audit", tr("Thao tác")], ["notice", tr("Thông báo")]] as const;
  return (
    <Bento label={tr("Nhật ký và truy vết")} code="LOG.AUD" end={<Seg items={KINDS} value={kind} onChange={setKind} label={tr("Lọc")} />}>
      <p className="mb-3 text-[12.5px] text-faint">{tr("Sự kiện của nhiệm vụ và lượt chạy, mọi thay đổi bạn làm qua giao diện, và thông báo. Khoá API không bao giờ được ghi.")}</p>
      {!data ? <Spinner /> : <ol className="mono grid gap-0.5 text-[12px]">{data.entries.map((e, i) => (
        <li key={i} className="flex gap-3 rounded px-2 py-1 hover:bg-white/[0.03]">
          <span className="w-28 shrink-0 text-faint">{clock(e.at)}</span>
          <span className={`w-14 shrink-0 uppercase ${e.level === "error" ? "text-tally" : e.level === "warn" ? "text-cue" : "text-accent"}`}>{e.level}</span>
          <span className="w-16 shrink-0 text-faint">{e.kind}</span>
          <span className="w-44 shrink-0 truncate text-mute">{e.source}</span>
          <span className="min-w-0 flex-1 truncate">{e.text}</span>
          {e.kind === "mission" && e.ref && <button type="button" className="link shrink-0" onClick={() => show(e.ref!)}>{tr("Mở")}</button>}
        </li>))}</ol>}
    </Bento>
  );
}
