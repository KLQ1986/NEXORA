import { t as tr, tv, locale } from "./i18n";
import { useEffect, useState } from "react";
import { post, REASONS, STAGE_NAMES, usePoll, type Notice } from "./api";
import { Empty, Icon, OpsSide, Page, Seg, Tag } from "./parts";

export const KIND: Record<string, string> = { model_fallback: tr("Mô hình cloud không dùng được"), autonomy_lowered: tr("Mức tự chủ bị hạ"), metrics_due: tr("Tới mốc ghi số liệu"), disk_low: tr("Ổ đĩa sắp đầy"), volume_offline: tr("Mất nơi chứa footage"), gaps: tr("Thiếu hình"), waiting_review: tr("Chờ bạn duyệt"), blocked: tr("Đang dừng"), failed: tr("Thất bại"), succeeded: tr("Đã xong") };
export const ICON: Record<string, string> = { model_fallback: "globe", autonomy_lowered: "bolt", metrics_due: "pulse", disk_low: "disk", volume_offline: "folder", gaps: "image", waiting_review: "eye", blocked: "alert", failed: "x", succeeded: "check" };
export const PIPE: Record<string, string> = { "library.ingest": tr("Nhập footage"), "library.ingest_image": tr("Nhập ảnh"), "library.ingest_audio": tr("Nhập nhạc"), "sourcing.generate": tr("Sinh hình bằng AI"), "library.understand": tr("Xem và mô tả video"), "sourcing.match": tr("Chọn clip cho kịch bản"), "edit.render": tr("Dựng video") };

/** How much a notice asks of the operator: amber waits for you, red has stopped, the rest is a record. */
export const noticeTone = (k: string) => (k === "waiting_review" || k === "blocked" || k === "gaps" || k === "model_fallback" || k === "autonomy_lowered" || k === "metrics_due" || k === "disk_low" || k === "volume_offline" ? "cue" : k === "failed" ? "tally" : k === "succeeded" ? "proof" : "mute") as "cue" | "tally" | "proof" | "mute";

const dayOf = (t: number) => { const d = new Date(t * 1000), now = new Date(); const y = new Date(now.getTime() - 86400000);
  return d.toDateString() === now.toDateString() ? tr("Hôm nay") : d.toDateString() === y.toDateString() ? tr("Hôm qua") : d.toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "numeric" }); };

export default function Notices() {
  const { data } = usePoll<{ unread: number; items: Notice[] }>("/api/v1/notifications", 4000);
  const [only, setOnly] = useState(false);
  useEffect(() => { const id = setTimeout(() => { post("/api/v1/notifications/read").catch(() => {}); }, 1500); return () => clearTimeout(id); }, []);
  const items = (data?.items ?? []).filter((n) => !only || n.kind !== "succeeded");
  const days: [string, Notice[]][] = [];
  for (const n of items) { const d = dayOf(n.created_at); if (days.length && days[days.length - 1][0] === d) days[days.length - 1][1].push(n); else days.push([d, [n]]); }
  const tone = noticeTone;
  const tile = { cue: "bg-cue/12 text-cue", tally: "bg-tally/12 text-tally", proof: "bg-proof/12 text-proof", mute: "bg-raised text-mute" };
  return (
    <Page side={<OpsSide />} eyebrow={tr("Vận hành")} title={tr("Thông báo")} note={tr("Bản ghi đầy đủ của mọi việc đã xong, cần bạn duyệt, hoặc bị dừng.")}
          actions={<Seg label={tr("Lọc thông báo")} value={only} onChange={setOnly} items={[[false, tr("Tất cả")], [true, tr("Cần chú ý")]] as const} />}>
      {data && items.length === 0 && <div className="max-w-xl"><Empty icon="bell" title={only ? tr("Không có việc nào cần chú ý") : tr("Chưa có thông báo")}>{only ? tr("Mọi thứ đang ổn.") : tr("Hệ thống sẽ báo ở đây khi một việc xong, cần bạn duyệt, hoặc bị dừng.")}</Empty></div>}
      <div className="grid max-w-4xl gap-7">
        {days.map(([day, list]) => (
          <div key={day}>
            <h2 className="eyebrow mb-2.5 flex items-center gap-3">{day}<span className="h-px flex-1 bg-line" /><span className="mono normal-case tracking-normal">{list.length}</span></h2>
            <ul className="panel rows overflow-hidden">
              {list.map((n) => {
                const t = tone(n.kind), unread = n.read_at === null;
                return (
                  <li key={n.notification_id} className={`relative grid items-center gap-x-3.5 gap-y-1 px-4 py-3 sm:grid-cols-[32px_minmax(0,1fr)_auto_3.5rem] ${unread ? "bg-accent/[0.04]" : ""}`}>
                    {unread && <span className="absolute left-0 top-3 bottom-3 w-0.5 rounded-r bg-accent" />}
                    <span className={`hidden h-8 w-8 place-items-center rounded-lg sm:grid ${tile[t]}`}><Icon name={ICON[n.kind] ?? "bell"} size={15} /></span>
                    <span className="min-w-0">
                      {n.subject_name && <a href={n.link ?? "#"} className={`block truncate hover:underline ${unread ? "font-medium" : ""}`}>{n.subject_name}</a>}
                      <span className={`block truncate text-[13px] ${n.subject_name ? "text-mute" : unread ? "font-medium" : ""}`}>{PIPE[n.pipeline ?? ""] ?? n.pipeline ?? (n.kind === "volume_offline" ? n.reason : tr("Máy này"))}{n.stage_key ? tv`, bước ${(STAGE_NAMES[n.stage_key] ?? n.stage_key).toLowerCase()}` : ""}{n.reason && n.kind !== "volume_offline" ? ` (${n.kind === "gaps" ? tv`${n.reason} câu chưa có hình` : REASONS[n.reason] ?? n.reason})` : ""}</span>
                    </span>
                    <Tag tone={t}>{KIND[n.kind] ?? n.kind}</Tag>
                    <span className="mono text-right text-[12px] text-faint">{new Date(n.created_at * 1000).toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" })}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>
    </Page>
  );
}
