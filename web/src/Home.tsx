import { megabytes, REASONS, stageName, timecode, usePoll, type AgentTask, type Stage } from "./api";
import { StageRail } from "./parts";

type Item = { gaps?: number; run_id: string; pipeline: string; name: string; link: string; status: string; held: boolean; stage_key: string | null; reason?: string | null; stages?: Stage[] };
type HomeData = {
  attention: Item[]; running: Item[]; gaps: { project_id: string; title: string; gaps: number }[];
  offline_volumes: { volume_id: string; mount_path: string; files: number }[]; problems: { name: string; detail: string; fix: string | null }[];
  unavailable: { pipeline: string; missing: string[] }[]; agent: AgentTask[];
  counts: { videos: number; photos: number; music: number; footage_seconds: number; projects: number; moments: number };
  disk: { free_bytes: number; total_bytes: number }; spent_today: number; kill_switch: boolean;
  recent: { project_id: string; title: string; created_at: number; renders: number }[];
};

const WORK: Record<string, string> = { "library.ingest": "Nhập footage", "library.ingest_image": "Nhập ảnh", "library.ingest_audio": "Nhập nhạc", "library.understand": "Xem và mô tả",
  "sourcing.match": "Chọn clip", "sourcing.generate": "Sinh hình bằng AI", "edit.render": "Dựng video" };
const ASK: Record<string, (i: Item) => string> = {
  waiting_review: (i) => (i.pipeline === "edit.render" ? "Bản dựng chờ bạn duyệt" : i.pipeline === "sourcing.generate" ? "Hình vừa sinh chờ bạn duyệt" : "Các clip đã chọn chờ bạn duyệt"),
  blocked: (i) => `${WORK[i.pipeline] ?? i.pipeline} đang dừng: ${REASONS[i.reason ?? ""] ?? i.reason ?? "cần bạn xử lý"}`,
  failed: (i) => `${WORK[i.pipeline] ?? i.pipeline} thất bại ở bước ${stageName(i.stage_key ?? "", i.pipeline)}`,
};
const NEEDS: Record<string, string> = { model: "mô hình thị giác (Ollama)", voice: "giọng đọc", image_gen: "nhà cung cấp sinh ảnh", video_gen: "nhà cung cấp sinh video", ffmpeg: "FFmpeg", ffprobe: "FFprobe", graphics: "bộ vẽ phụ đề" };

/** The first screen: what waits for the operator, what the machine is doing, and where things stand. */
export default function Home({ go }: { go: (to: string) => void }) {
  const { data: d, error } = usePoll<HomeData>("/api/v1/home", 3000);
  const open = (to: string) => (e: React.MouseEvent) => { e.preventDefault(); go(to); };
  if (!d) return <section className="p-6 text-mute">{error ? `Không tải được: ${error}` : "Đang mở"}</section>;
  const asks = d.attention.length + d.gaps.length + d.offline_volumes.length + d.problems.length;
  const c = d.counts;
  const used = 1 - d.disk.free_bytes / d.disk.total_bytes;
  return (
    <section className="flex-1 overflow-y-auto p-6">
      <div className="grid max-w-5xl gap-10">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight">{asks ? `Có ${asks} việc đang chờ bạn` : d.running.length ? "Máy đang làm việc, chưa cần bạn" : "Không có việc nào đang chờ"}</h1>
          {d.kill_switch && <p className="mt-1 text-cue">Đang bật dừng khẩn cấp: hệ thống không bắt đầu việc tốn tiền hay tác động ra ngoài. Tắt ở mục Hệ thống.</p>}
        </header>

        {asks > 0 && (
          <div>
            <h2 className="mb-2 text-base font-semibold">Cần bạn</h2>
            <ul className="divide-y divide-line border-y border-line">
              {d.attention.map((i) => (
                <li key={i.run_id}><a href={i.link} onClick={open(i.link)} className="grid gap-x-6 px-2 py-3 hover:bg-surface/60 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <span className="min-w-0 truncate font-medium">{i.name}</span><span className={i.status === "failed" ? "text-tally" : "text-cue"}>{ASK[i.status]?.(i) ?? i.status}{i.gaps ? `, còn ${i.gaps} câu chưa có hình` : ""}</span></a></li>
              ))}
              {d.gaps.map((g) => (
                <li key={g.project_id}><a href={`/du-an/${g.project_id}`} onClick={open(`/du-an/${g.project_id}`)} className="grid gap-x-6 px-2 py-3 hover:bg-surface/60 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <span className="min-w-0 truncate font-medium">{g.title}</span><span className="text-cue">Còn {g.gaps} câu chưa có hình</span></a></li>
              ))}
              {d.offline_volumes.map((v) => (
                <li key={v.volume_id}><a href="/he-thong" onClick={open("/he-thong")} className="grid gap-x-6 px-2 py-3 hover:bg-surface/60 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <span className="min-w-0 truncate font-medium">{v.mount_path}</span><span className="text-cue">Không tìm thấy nơi chứa {v.files} file footage</span></a></li>
              ))}
              {d.problems.map((p) => (
                <li key={p.name}><a href="/he-thong" onClick={open("/he-thong")} className="grid gap-x-6 px-2 py-3 hover:bg-surface/60 sm:grid-cols-[minmax(0,1fr)_auto]">
                  <span className="min-w-0 font-medium">{p.name}<span className="block text-sm font-normal text-mute">{p.fix}</span></span><span className="text-cue">{p.detail}</span></a></li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <h2 className="mb-2 text-base font-semibold">Đang chạy</h2>
          {d.running.length === 0 && <p className="text-mute">Máy đang rảnh.</p>}
          <ul className="divide-y divide-line border-y border-line empty:hidden">
            {d.running.map((i) => (
              <li key={i.run_id} className="grid items-center gap-x-6 gap-y-1 px-2 py-3 sm:grid-cols-[minmax(0,1fr)_220px_170px]">
                <span className="min-w-0 truncate"><span className="font-medium">{WORK[i.pipeline] ?? i.pipeline}</span> <span className="text-mute">{i.name}</span></span>
                <StageRail stages={i.stages ?? []} />
                <span className="text-sm text-mute sm:text-right">{i.held ? "Chờ tới giờ phân tích" : i.stage_key ? `Bước ${stageName(i.stage_key, i.pipeline)}` : "Trong hàng đợi"}</span>
              </li>
            ))}
          </ul>
          {d.agent.map((t) => (
            <a key={t.task_id} href={`/du-an/${t.project_id}`} onClick={open(`/du-an/${t.project_id}`)} className="mt-2 flex justify-between gap-4 px-2 text-sm hover:underline">
              <span className="min-w-0 truncate">Trợ lý sản xuất: {t.goal}</span><span className={t.status === "waiting_operator" ? "shrink-0 text-cue" : "shrink-0 text-mute"}>{t.log[t.log.length - 1]?.text}</span></a>
          ))}
        </div>

        <div className="grid gap-10 md:grid-cols-2">
          <div>
            <h2 className="mb-2 text-base font-semibold">Dự án gần đây</h2>
            {d.recent.length === 0 && <p className="text-mute">Chưa có dự án nào. <a className="text-ink underline underline-offset-2" href="/du-an" onClick={open("/du-an")}>Tạo dự án đầu tiên</a></p>}
            <ul className="divide-y divide-line border-y border-line empty:hidden">
              {d.recent.map((p) => (
                <li key={p.project_id}><a href={`/du-an/${p.project_id}`} onClick={open(`/du-an/${p.project_id}`)} className="flex justify-between gap-4 px-2 py-2.5 hover:bg-surface/60">
                  <span className="min-w-0 truncate">{p.title}</span><span className="shrink-0 text-mute">{p.renders ? `${p.renders} bản dựng` : "Chưa dựng"}</span></a></li>
              ))}
            </ul>
          </div>
          <div>
            <h2 className="mb-2 text-base font-semibold">Hiện trạng</h2>
            <dl className="divide-y divide-line border-y border-line">
              <div className="flex justify-between gap-4 px-2 py-2.5"><dt>Kho footage</dt><dd className="tc text-right text-mute">{c.videos} video dài {timecode(c.footage_seconds)}{c.photos ? `, ${c.photos} ảnh` : ""}{c.music ? `, ${c.music} bản nhạc` : ""}</dd></div>
              <div className="flex justify-between gap-4 px-2 py-2.5"><dt>Cảnh đã mô tả, tìm được bằng lời</dt><dd className="tc text-mute">{c.moments}</dd></div>
              <div className="flex justify-between gap-4 px-2 py-2.5"><dt>Chi phí hôm nay</dt><dd className="tc text-mute">{d.spent_today.toFixed(2)} USD</dd></div>
              <div className="px-2 py-2.5"><div className="flex justify-between gap-4"><dt>Ổ đĩa</dt><dd className={`tc ${used > 0.9 ? "text-cue" : "text-mute"}`}>còn trống {megabytes(d.disk.free_bytes)}</dd></div>
                <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-raised"><div className={`h-full ${used > 0.9 ? "bg-cue" : "bg-ink/70"}`} style={{ width: `${used * 100}%` }} /></div></div>
            </dl>
            {d.unavailable.length > 0 && (
              <p className="mt-3 text-sm text-mute">Chưa dùng được trên máy này: {d.unavailable.map((u) => `${WORK[u.pipeline] ?? u.pipeline} (thiếu ${u.missing.map((m) => NEEDS[m] ?? m).join(", ")})`).join("; ")}.</p>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
