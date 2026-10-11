import { useEffect } from "react";
import { post, REASONS, STAGE_NAMES, usePoll, type Notice } from "./api";
import { Page, Tag } from "./parts";

const KIND: Record<string, string> = { waiting_review: "Chờ bạn duyệt", blocked: "Đang dừng", failed: "Thất bại", succeeded: "Đã xong" };
const PIPE: Record<string, string> = { "library.ingest": "Nhập footage", "library.ingest_image": "Nhập ảnh", "library.ingest_audio": "Nhập nhạc", "sourcing.generate": "Sinh hình bằng AI", "library.understand": "Xem và mô tả video", "sourcing.match": "Chọn clip cho kịch bản", "edit.render": "Dựng video" };

export default function Notices() {
  const { data } = usePoll<{ unread: number; items: Notice[] }>("/api/v1/notifications", 4000);
  useEffect(() => { const id = setTimeout(() => { post("/api/v1/notifications/read").catch(() => {}); }, 1500); return () => clearTimeout(id); }, []);
  return (
    <Page title="Thông báo" note="Mọi việc đã xong, cần bạn duyệt, hoặc bị dừng. Đây là bản ghi đầy đủ; thông báo trên máy Mac chỉ là bản sao.">
      {data && data.items.length === 0 && <p className="panel max-w-xl px-4 py-6 text-mute">Chưa có thông báo. Hệ thống sẽ báo ở đây khi một việc xong, cần bạn duyệt, hoặc bị dừng.</p>}
      <ul className="panel rows max-w-4xl overflow-hidden empty:hidden">
        {(data?.items ?? []).map((n) => (
          <li key={n.notification_id} className={`grid items-center gap-x-4 gap-y-1 px-4 py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)_auto] ${n.read_at === null ? "bg-raised/40" : ""}`}>
            <span className="tc text-[13px] text-mute">{new Date(n.created_at * 1000).toLocaleString("vi-VN")}</span>
            <span className={`min-w-0 truncate ${n.read_at === null ? "font-medium" : ""}`}>{PIPE[n.pipeline ?? ""] ?? n.pipeline}{n.stage_key ? `, bước ${STAGE_NAMES[n.stage_key] ?? n.stage_key}` : ""}{n.reason ? ` (${REASONS[n.reason] ?? n.reason})` : ""}</span>
            <Tag tone={n.kind === "waiting_review" || n.kind === "blocked" ? "cue" : n.kind === "failed" ? "tally" : n.kind === "succeeded" ? "proof" : "mute"}>{KIND[n.kind] ?? n.kind}</Tag>
          </li>
        ))}
      </ul>
    </Page>
  );
}
