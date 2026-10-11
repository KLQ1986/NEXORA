import { useEffect, useState } from "react";
import { post, REASONS, STAGE_NAMES, usePoll, type Notice } from "./api";
import { Page, Tag } from "./parts";

const KIND: Record<string, string> = { gaps: "Thiếu hình", waiting_review: "Chờ bạn duyệt", blocked: "Đang dừng", failed: "Thất bại", succeeded: "Đã xong" };
const PIPE: Record<string, string> = { "library.ingest": "Nhập footage", "library.ingest_image": "Nhập ảnh", "library.ingest_audio": "Nhập nhạc", "sourcing.generate": "Sinh hình bằng AI", "library.understand": "Xem và mô tả video", "sourcing.match": "Chọn clip cho kịch bản", "edit.render": "Dựng video" };

const dayOf = (t: number) => { const d = new Date(t * 1000), now = new Date(); const y = new Date(now.getTime() - 86400000);
  return d.toDateString() === now.toDateString() ? "Hôm nay" : d.toDateString() === y.toDateString() ? "Hôm qua" : d.toLocaleDateString("vi-VN", { weekday: "long", day: "numeric", month: "numeric" }); };

export default function Notices() {
  const { data } = usePoll<{ unread: number; items: Notice[] }>("/api/v1/notifications", 4000);
  const [only, setOnly] = useState(false);
  useEffect(() => { const id = setTimeout(() => { post("/api/v1/notifications/read").catch(() => {}); }, 1500); return () => clearTimeout(id); }, []);
  const items = (data?.items ?? []).filter((n) => !only || n.kind !== "succeeded");
  const days: [string, Notice[]][] = [];
  for (const n of items) { const d = dayOf(n.created_at); if (days.length && days[days.length - 1][0] === d) days[days.length - 1][1].push(n); else days.push([d, [n]]); }
  const tone = (k: string) => (k === "waiting_review" || k === "blocked" || k === "gaps" ? "cue" : k === "failed" ? "tally" : k === "succeeded" ? "proof" : "mute") as "cue" | "tally" | "proof" | "mute";
  const dot = { cue: "bg-cue", tally: "bg-tally", proof: "bg-proof", mute: "bg-faint" };
  return (
    <Page title="Thông báo" note="Bản ghi đầy đủ của mọi việc đã xong, cần bạn duyệt, hoặc bị dừng."
          actions={<div className="flex rounded-md border border-line p-0.5" role="radiogroup" aria-label="Lọc thông báo">
            {([[false, "Tất cả"], [true, "Cần chú ý"]] as const).map(([v, name]) => <button key={name} type="button" role="radio" aria-checked={only === v} onClick={() => setOnly(v)} className={`h-8 rounded px-3 text-[13px] ${only === v ? "bg-raised font-medium" : "text-mute hover:text-ink"}`}>{name}</button>)}
          </div>}>
      {data && items.length === 0 && <p className="panel max-w-xl px-5 py-8 text-mute">{only ? "Không có việc nào cần chú ý." : "Chưa có thông báo. Hệ thống sẽ báo ở đây khi một việc xong, cần bạn duyệt, hoặc bị dừng."}</p>}
      <div className="grid max-w-4xl gap-7">
        {days.map(([day, list]) => (
          <div key={day}>
            <h2 className="mb-2 text-[13px] font-medium text-mute">{day}</h2>
            <ul className="panel rows overflow-hidden">
              {list.map((n) => (
                <li key={n.notification_id} className={`grid items-center gap-x-3 gap-y-1 px-4 py-2.5 sm:grid-cols-[10px_minmax(0,1fr)_auto_3.5rem] ${n.read_at === null ? "bg-raised/50" : ""}`}>
                  <span className={`hidden h-2 w-2 rounded-full sm:block ${dot[tone(n.kind)]}`} />
                  <span className={`min-w-0 truncate ${n.read_at === null ? "font-medium" : ""}`}>{n.subject_name && <><a href={n.link ?? "#"} className="hover:underline">{n.subject_name}</a><span className="text-faint">{"  "}</span></>}<span className={n.subject_name ? "text-mute" : ""}>{PIPE[n.pipeline ?? ""] ?? n.pipeline}</span>{n.stage_key ? <span className="text-mute">, bước {(STAGE_NAMES[n.stage_key] ?? n.stage_key).toLowerCase()}</span> : null}{n.reason ? <span className="text-mute"> ({n.kind === "gaps" ? `${n.reason} câu chưa có hình` : REASONS[n.reason] ?? n.reason})</span> : null}</span>
                  <Tag tone={tone(n.kind)}>{KIND[n.kind] ?? n.kind}</Tag>
                  <span className="tc text-right text-[13px] text-faint">{new Date(n.created_at * 1000).toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" })}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </Page>
  );
}
