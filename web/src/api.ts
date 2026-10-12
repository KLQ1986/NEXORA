import { useCallback, useEffect, useRef, useState } from "react";

export type Stage = { stage_id: string; stage_key: string; status: string; blocked_reason: string | null; attempts: number };
export type Run = { held?: boolean; stalled?: boolean; run_id: string; pipeline: string; subject_ref: string | null; created_at: number; status: string; cost: number; stages: Stage[] };
export type Word = { text: string; start: number; end: number; p: number };
export type Asset = {
  scene_cuts?: number[]; enhance: Run | null; enhanced: { upscale: number; smooth_fps: number | null } | null; rejected: boolean; session: string; used_in: { project_id: string; title: string }[]; speech: { words: number; sentences: number; seconds: number; doubtful: number } | null; transcribe: Run | null;
  asset_id: string; name: string; path: string; online: boolean; size: number; duplicate_of: string | null;
  duration: number | null; width: number | null; height: number | null; frame_rate: number | null; has_audio: boolean | null;
  usable_ranges: number[][]; black_ranges: number[][]; frozen_ranges: number[][];
  thumbnail_url: string | null; proxy_url: string | null; ingest: Run | null; understand: Run | null; still: boolean; kind: string; mean_db: number | null; rating: number; collections: string[]; note: string | null; angles: { asset_id: string; offset: number }[];
};

/** Whether the server answered the last request. Every screen polls, so this is known within a few seconds of it changing. */
const CONNECTION = "nexora:connection";
let online = true;
const setOnline = (now: boolean) => { if (now !== online) { online = now; window.dispatchEvent(new Event(CONNECTION)); } };
export function useConnection() {
  const [state, setState] = useState(online);
  useEffect(() => { const on = () => setState(online); window.addEventListener(CONNECTION, on); return () => window.removeEventListener(CONNECTION, on); }, []);
  return state;
}

export async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { headers: { "content-type": "application/json" }, ...init });
  } catch {
    setOnline(false);
    throw new Error("Không kết nối được với máy chủ NEXORA. Kiểm tra xem `nexora serve` còn chạy không.");
  }
  setOnline(true);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Yêu cầu thất bại (${res.status})`);
  }
  return res.json();
}

const CHANGED = "nexora:changed";
/** One connection for the whole page. If it cannot be opened, screens still refresh on their timers. */
export function listenForChanges() {
  try {
    const source = new EventSource("/api/v1/events/stream");
    let first = true;
    source.onmessage = () => { if (first) { first = false; return; } window.dispatchEvent(new Event(CHANGED)); };
  } catch { /* polling alone is enough */ }
}

/** Poll an endpoint. Refreshes every `ms`; `reload` forces one now. */
export function usePoll<T>(url: string, ms = 2000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const reload = useCallback(() => {
    call<T>(url).then((d) => { if (alive.current) { setData(d); setError(null); } })
      .catch((e) => { if (alive.current) setError(e.message); });
  }, [url]);
  useEffect(() => {
    alive.current = true;
    reload();
    const id = setInterval(reload, ms);
    const now = () => reload();
    window.addEventListener(CHANGED, now);         // the server says something changed: refresh at once, do not wait for the next poll
    return () => { alive.current = false; clearInterval(id); window.removeEventListener(CHANGED, now); };
  }, [reload, ms]);
  return { data, error, reload };
}

export const timecode = (s: number | null | undefined) => {
  if (s == null) return "–:––";
  const m = Math.floor(s / 60), r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
};
export const megabytes = (b: number) => (b >= 1e9 ? `${(b / 1e9).toFixed(1)} GB` : `${Math.round(b / 1e6)} MB`);

export const STAGE_NAMES: Record<string, string> = {
  checksum: "Kiểm tra file", probe: "Đọc thông số", usable: "Tìm phần dùng được", proxy: "Tạo bản xem", thumbnail: "Ảnh đại diện",
  structure: "Chia đoạn", describe: "Mô tả hình", understand: "Hiểu nội dung", index: "Lập chỉ mục",
};
/** Stage names depend on the pipeline: "segments" means one thing when understanding footage and another when rendering. */
export const stageName = (key: string, pipeline?: string | null) =>
  (pipeline === "edit.render" && key === "segments" ? "Dựng từng cảnh" : pipeline === "animation.generate" && key === "segments" ? "Dựng từng cảnh" : STAGE_NAMES[key] ?? key);
export const STATUS_NAMES: Record<string, string> = {
  queued: "Đang chờ", pending: "Chưa tới lượt", ready: "Sẵn sàng", running: "Đang chạy", waiting_review: "Chờ bạn duyệt",
  retry_wait: "Sẽ thử lại", blocked: "Cần bạn xử lý", succeeded: "Xong", skipped: "Bỏ qua", failed: "Thất bại", cancelled: "Đã huỷ",
};
export const REASONS: Record<string, string> = {
  daily_budget_exceeded: "Đã dùng hết ngân sách của hôm nay", monthly_budget_exceeded: "Đã dùng hết ngân sách của tháng này",
  retry_limit: "Đã thử lại hết số lần cho phép", budget_exceeded: "Vượt ngân sách của lần chạy này",
  insufficient_storage: "Ổ đĩa sắp đầy", auth: "Khoá truy cập không hợp lệ", quota_exhausted: "Hết hạn mức của nhà cung cấp",
};

export type Moment = { level?: string; words?: Word[]; moment_id: string; asset_id: string; t_start: number; t_end: number; text: string; source: string; score: number | null; frame_url: string | null; title?: string | null };
export type AssetBrief = { asset_id: string; name: string; proxy_url: string | null; duration: number | null; still: boolean; thumbnail_url: string | null };
export type Hit = Moment & { asset: AssetBrief };
export type Candidate = { moment_id: string; t_in: number; t_out: number; score: number; reason: string; frame_url: string; asset: AssetBrief };
export type Op = { op: string; line: number; describe: string; [k: string]: unknown };
export type RoughPlan = { asset_id: string; sentences: { index: number; text: string; keep: boolean; reason: string | null; t_in: number; t_out: number; doubtful: boolean; take_of: number | null; takes: number[] }[]; source_seconds: number | null; kept_seconds: number; removed_seconds: number };
export type Selection = { lipsync: boolean; upscale_ml: boolean; speed: number; stabilise: boolean; live_sound: boolean; sfx: string | null; status: string; t_in: number | null; t_out: number | null; score: number | null; reason: string | null; decided_by: string;
  moment_id: string | null; frame_url: string | null; asset: AssetBrief | null; alternates: Candidate[];
  inserts: { keyword: string; at: number; reason: string }[]; focus_x: number | null; angles: (AssetBrief & { offset: number; t_in: number })[] };
export type Source = { title: string; publisher: string; date: string; url: string; passage: string; retrieved_at?: number };
export type FactCheck = { verdict: "supported" | "contradicted" | "not_found"; source: string | null; quote: string; note: string; checked_at: number };
export type Critique = { line: number; issue: string; fix: string };
export type GenChoice = { subject?: string; shot_size?: string; camera?: string; provider_image?: string; provider_video?: string; attempt?: number };
export type BibleEntry = { model?: string | null; training?: { status: string; assets: string[]; trigger: string } | null; voice?: string | null; name: string; kind: "character" | "setting" | "prop" | "style"; description: string; asset_id: string | null };
export type Provider = { name: string; label: string; runs: string };
export type GapPlan = { line: number; shot_id: string; text: string; brief: string | null; scene: string | null; seconds: number; near: { moment_id: string; asset_id: string; text: string; score: number; t_start: number; t_end: number } | null; ways: { way: string; text: string }[] };
export type Shot = { gen: GenChoice; fact_check: FactCheck | null; target_seconds: number | null; sound_cue: string | null; is_fact: boolean; source: string | null; scene: string | null; brief: string | null; screen_text: string | null; shot_id: string; position: number; text: string; selection: Selection | null; keyframe_url: string | null;
  generation: { prompt: string; seed: number | null; provider: string; quality: { score: number; issues: string[]; tries: number } | null; tries: number } | null };
export type Finding = { check: string; shot: number; severity: string; text: string; fix: string };
export type Snapshot = { snapshot_id: string; at: number; hours: number; figures: Record<string, number> };
export type Publication = { publication_id: string; render_id: string; project_id: string; target: string; variant: string; status: string; url: string | null; title: string; error: string | null; attempts: number; manual: boolean; published_at: number | null; snapshots: Snapshot[] };
export type Experiment = { experiment_id: string; question: string; metric: string; closed_at: number | null; conclusion: string | null; compared_at_hours: number; verdict: { decided: boolean; text: string; leader?: string };
  variants: { publication_id: string; label: string; title: string; target: string; value: number | null }[] };
export type Publishing = { targets: { target: string; label: string; manual: boolean }[]; publications: Publication[]; due: { publication_id: string; title: string; target: string; mark: number }[];
  experiments: Experiment[]; breakdown: { kind: string; name: string; videos: number; median: number }[] };
export type Campaign = { campaign_id: string; name: string; metric: string; target: number; starts: string | null; ends: string | null; reached: number; share: number | null; published: number; late: number;
  pace: { time_gone: number; on_pace: boolean; text: string } | null; videos: { project_id: string; title: string; due_date: string | null; published: boolean; value: number; late: boolean }[] };
export type Rights = { items: { asset_id: string | null; name: string; origin: string; ok: boolean; note: string }[]; blockers: string[]; disclosures: string[]; clear: boolean; override_reason?: string | null };
export type EvalRun = { run_id: string; created_at: number; cases: number; first: number; top3: number; config: Record<string, unknown>; change?: { first: number; top3: number; regression: boolean; lost: string[]; config: Record<string, [unknown, unknown]> } };
export type Package = { rights?: Rights; checks?: Record<string, boolean>; captions_vtt?: string; translations?: Record<string, string>; title: string; description: string; thumbnails: string[]; thumbnail: string; folder: string; synthetic_content: boolean; captions: string; video: string };
export type RenderItem = { render_id: string; created_at: number; url: string; package: Package | null; review: { approved: boolean; comment: string | null; at: number } | null;
  qc: { viewer?: { at: number; judged: number; of: number; findings: Finding[] }; external?: boolean; draft?: boolean; passed: boolean; checks: Record<string, boolean>; duration: number; gaps: number; findings?: Finding[]; format?: string; music?: boolean;
        shots?: { text: string; duration: number; gap: boolean; asset_id?: string | null; t_in?: number | null; own_voice?: boolean; focus_x?: number | null; inserts?: { keyword: string; at: number }[] }[] } };
export type BoardEvent = { at: number; kind: string; pipeline: string; stage_key: string | null; actor: string; payload: Record<string, unknown> };
export type Notice = { notification_id: number; kind: string; run_id: string; stage_key: string | null; reason: string | null; created_at: number; read_at: number | null; pipeline: string | null; subject_name: string | null; link: string | null };
export type Project = { channel: string | null; project_id: string; title: string; created_at: number; format: string; music_path: string | null;
  due_date: string | null; script: { script_id: string; version: number; match_approved: boolean; critique: Critique[] | null } | null; shots: Shot[]; match: Run | null; render: Run | null; renders: RenderItem[];
  preview: Run | null; previews: { render_id: string; url: string; duration: number; gaps: number; created_at: number }[]; remote: string[]; options: { clean_audio?: boolean; match_colour?: boolean; music_cleared?: boolean; footage_may_leave?: boolean }; generate: Run | null; generators: { image: boolean; video: boolean; image_providers: Provider[]; video_providers: Provider[] }; bible: BibleEntry[]; auto_accept: boolean; style: string | null; narration_dir: string | null; own_takes: number[]; budget_cap: number | null; spent: number; template: string | null; voice: string | null; research: Source[] };
export type Template = { name: string; format: string; voice: string; music_gain: number; auto_accept: boolean; caption_scale: number; caption_position: string; pronounce: Record<string, string>; typeface?: string; caption_colour?: number[] | null; logo_path?: string };
export type Channel = { name: string; platform: string; audience: string; per_week: number; template: string | null };
export type CalendarRow = { channel: string | null; project_id: string; title: string; format: string; due_date: string | null; stage: string; ready: boolean };
export type RadarSubject = { subject: string; videos: number; seconds: number; unused_videos: number; unused_seconds: number; examples: { asset_id: string; title: string; summary: string }[] };
export type Radar = { unused: RadarSubject[]; subjects: RadarSubject[]; watched: { topic: string; moments: number; best: number; assets: number; verdict: string }[]; topics: string[] };
export type Idea = { title: string; summary: string; scores: Record<string, number>; total: number; risk: string };
/** The script as the operator types it: scene names on lines starting with "#", one spoken line per row. */
export const scriptText = (shots: Shot[]) => { const out: string[] = []; let scene: string | null = null; for (const s of shots) { if (s.scene && s.scene !== scene) out.push(`# ${s.scene}`); scene = s.scene; out.push(s.text); } return out.join("\n"); };
export type Settings = { voice: string; voices: string[]; models: Record<string, boolean>; model_roles: Record<string, string>; privacy_local_only: boolean; watch_folders: string[]; templates: Template[] };
export type AgentTask = { task_id: string; project_id: string; goal: string; status: string; step: string; created_at: number; log: { at: number; role: string; text: string }[] };
/** Every change the operator makes refreshes the open screens at once. */
export const post = <T,>(url: string, body?: unknown, method = "POST") =>
  call<T>(url, { method, body: body === undefined ? undefined : JSON.stringify(body) }).then((r) => { window.dispatchEvent(new Event(CHANGED)); return r; });
Object.assign(STAGE_NAMES, { segments: "Chia đoạn", summarise: "Tóm tắt", match: "Chọn clip", narration: "Đọc lời dẫn", assemble: "Ghép và kiểm tra" });

/** Where a project stands, in the operator's words. `step` counts the five stages from script to approved cut. */
export function projectState(p: Project): { label: string; tone: "mute" | "cue" | "proof" | "tally"; step: number } {
  const busy = (r: Run | null) => !!r && ["queued", "running"].includes(r.status);
  if (!p.script) return { label: "Chưa có kịch bản", tone: "mute", step: 0 };
  if (p.render?.status === "succeeded") return { label: "Đã xong", tone: "proof", step: 5 };
  if (p.render?.status === "waiting_review") return { label: "Chờ duyệt bản dựng", tone: "cue", step: 4 };
  if (p.render?.status === "failed" || p.match?.status === "failed") return { label: "Có lỗi", tone: "tally", step: p.render ? 3 : 1 };
  if (p.render?.status === "blocked" || p.match?.status === "blocked") return { label: "Đang dừng", tone: "cue", step: p.render ? 3 : 1 };
  if (busy(p.render)) return { label: "Đang dựng", tone: "mute", step: 3 };
  if (p.match?.status === "waiting_review") return { label: "Chờ duyệt clip", tone: "cue", step: 2 };
  if (busy(p.match)) return { label: "Đang tìm clip", tone: "mute", step: 1 };
  if (p.script.match_approved) return { label: "Sẵn sàng dựng", tone: "mute", step: 3 };
  return { label: p.match ? "Cần tìm lại clip" : "Có kịch bản", tone: "mute", step: 1 };
}
