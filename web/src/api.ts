import { useCallback, useEffect, useRef, useState } from "react";

export type Stage = { stage_id: string; stage_key: string; status: string; blocked_reason: string | null; attempts: number };
export type Run = { run_id: string; pipeline: string; subject_ref: string | null; created_at: number; status: string; cost: number; stages: Stage[] };
export type Asset = {
  asset_id: string; name: string; path: string; online: boolean; size: number; duplicate_of: string | null;
  duration: number | null; width: number | null; height: number | null; frame_rate: number | null; has_audio: boolean | null;
  usable_ranges: number[][]; black_ranges: number[][]; frozen_ranges: number[][];
  thumbnail_url: string | null; proxy_url: string | null; ingest: Run | null;
};

export async function call<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { headers: { "content-type": "application/json" }, ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Yêu cầu thất bại (${res.status})`);
  }
  return res.json();
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
    return () => { alive.current = false; clearInterval(id); };
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
export const STATUS_NAMES: Record<string, string> = {
  queued: "Đang chờ", pending: "Chưa tới lượt", ready: "Sẵn sàng", running: "Đang chạy", waiting_review: "Chờ bạn duyệt",
  retry_wait: "Sẽ thử lại", blocked: "Cần bạn xử lý", succeeded: "Xong", skipped: "Bỏ qua", failed: "Thất bại", cancelled: "Đã huỷ",
};
export const REASONS: Record<string, string> = {
  retry_limit: "Đã thử lại hết số lần cho phép", budget_exceeded: "Vượt ngân sách của lần chạy này",
  insufficient_storage: "Ổ đĩa sắp đầy", auth: "Khoá truy cập không hợp lệ", quota_exhausted: "Hết hạn mức của nhà cung cấp",
};
