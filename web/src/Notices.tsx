import { useEffect } from "react";
import { post, REASONS, STAGE_NAMES, usePoll, type Notice } from "./api";

const KIND: Record<string, string> = { waiting_review: "Chờ bạn duyệt", blocked: "Đang dừng, cần bạn xử lý", failed: "Thất bại", succeeded: "Đã xong" };
const PIPE: Record<string, string> = { "library.ingest": "Nhập footage", "library.understand": "Xem và mô tả video", "sourcing.match": "Chọn clip cho kịch bản", "edit.render": "Dựng video" };

export default function Notices() {
  const { data } = usePoll<{ unread: number; items: Notice[] }>("/api/v1/notifications", 4000);
  useEffect(() => { const id = setTimeout(() => { post("/api/v1/notifications/read").catch(() => {}); }, 1500); return () => clearTimeout(id); }, []);
  return (
    <section className="flex-1 overflow-y-auto p-6">
      <h1 className="mb-4 text-2xl font-semibold tracking-tight">Thông báo</h1>
      {data && data.items.length === 0 && <p className="max-w-md text-mute">Chưa có thông báo. Hệ thống sẽ báo ở đây khi một việc xong, cần bạn duyệt, hoặc bị dừng.</p>}
      <ul className="max-w-3xl divide-y divide-line border-y border-line">
        {(data?.items ?? []).map((n) => (
          <li key={n.notification_id} className="grid grid-cols-[9.5rem_1fr] gap-3 py-2">
            <span className="tc text-sm text-mute">{new Date(n.created_at * 1000).toLocaleString("vi-VN")}</span>
            <span className={n.read_at === null ? "font-medium" : ""}>
              <span className={n.kind === "waiting_review" || n.kind === "blocked" ? "text-cue" : n.kind === "failed" ? "text-tally" : n.kind === "succeeded" ? "text-proof" : ""}>{KIND[n.kind] ?? n.kind}</span>
              : {PIPE[n.pipeline ?? ""] ?? n.pipeline}{n.stage_key ? `, bước ${STAGE_NAMES[n.stage_key] ?? n.stage_key}` : ""}{n.reason ? ` (${REASONS[n.reason] ?? n.reason})` : ""}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
