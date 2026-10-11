import { useCallback, useEffect, useRef, useState } from "react";

export type Stage = { stage_id: string; stage_key: string; status: string; blocked_reason: string | null; attempts: number };
export type Run = { held?: boolean; run_id: string; pipeline: string; subject_ref: string | null; created_at: number; status: string; cost: number; stages: Stage[] };
export type Asset = {
  asset_id: string; name: string; path: string; online: boolean; size: number; duplicate_of: string | null;
  duration: number | null; width: number | null; height: number | null; frame_rate: number | null; has_audio: boolean | null;
  usable_ranges: number[][]; black_ranges: number[][]; frozen_ranges: number[][];
  thumbnail_url: string | null; proxy_url: string | null; ingest: Run | null; understand: Run | null; still: boolean; kind: string; mean_db: number | null; rating: number; collections: string[]; angles: { asset_id: string; offset: number }[];
};

export async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { headers: { "content-type": "application/json" }, ...init });
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

export type Moment = { moment_id: string; asset_id: string; t_start: number; t_end: number; text: string; source: string; score: number | null; frame_url: string | null; title?: string | null };
export type AssetBrief = { asset_id: string; name: string; proxy_url: string | null; duration: number | null; still: boolean; thumbnail_url: string | null };
export type Hit = Moment & { asset: AssetBrief };
export type Candidate = { moment_id: string; t_in: number; t_out: number; score: number; reason: string; frame_url: string; asset: AssetBrief };
export type Selection = { status: string; t_in: number | null; t_out: number | null; score: number | null; reason: string | null; decided_by: string;
  moment_id: string | null; frame_url: string | null; asset: AssetBrief | null; alternates: Candidate[];
  inserts: { keyword: string; at: number; reason: string }[]; focus_x: number | null; angles: (AssetBrief & { offset: number; t_in: number })[] };
export type Shot = { shot_id: string; position: number; text: string; selection: Selection | null; keyframe_url: string | null;
  generation: { prompt: string; seed: number | null; provider: string } | null };
export type Finding = { check: string; shot: number; severity: string; text: string; fix: string };
export type Package = { title: string; description: string; thumbnails: string[]; thumbnail: string; folder: string; synthetic_content: boolean; captions: string; video: string };
export type RenderItem = { render_id: string; created_at: number; url: string; package: Package | null; review: { approved: boolean; comment: string | null; at: number } | null;
  qc: { passed: boolean; checks: Record<string, boolean>; duration: number; gaps: number; findings?: Finding[]; format?: string; music?: boolean;
        shots?: { text: string; duration: number; gap: boolean; asset_id?: string | null; t_in?: number | null; own_voice?: boolean; focus_x?: number | null; inserts?: { keyword: string; at: number }[] }[] } };
export type BoardEvent = { at: number; kind: string; pipeline: string; stage_key: string | null; actor: string; payload: Record<string, unknown> };
export type Notice = { notification_id: number; kind: string; run_id: string; stage_key: string | null; reason: string | null; created_at: number; read_at: number | null; pipeline: string | null };
export type Project = { project_id: string; title: string; created_at: number; format: string; music_path: string | null;
  script: { script_id: string; version: number; match_approved: boolean } | null; shots: Shot[]; match: Run | null; render: Run | null; renders: RenderItem[];
  generate: Run | null; generators: { image: boolean; video: boolean }; auto_accept: boolean; style: string | null; narration_dir: string | null; own_takes: number[]; budget_cap: number | null; spent: number };
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
