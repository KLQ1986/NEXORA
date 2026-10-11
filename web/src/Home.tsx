import { megabytes, projectState, REASONS, stageName, timecode, usePoll, type AgentTask, type Project, type Stage } from "./api";
import { Button, Filmstrip, Icon, Page, Section, StageRail, Steps, Tag } from "./parts";

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
  const { data: projects } = usePoll<Project[]>("/api/v1/projects", 6000);
  const open = (to: string) => (e: React.MouseEvent) => { e.preventDefault(); go(to); };
  if (!d) return <Page title="Tổng quan"><p className="text-mute">{error ? `Không tải được: ${error}` : "Đang mở"}</p></Page>;
  const asks = d.attention.length + d.gaps.length + d.offline_volumes.length + d.problems.length;
  const c = d.counts;
  const used = 1 - d.disk.free_bytes / d.disk.total_bytes;
  const row = "grid items-center gap-x-6 gap-y-1 px-4 py-3 transition-colors hover:bg-raised/60 sm:grid-cols-[minmax(0,1fr)_auto]";
  return (
    <Page title="Tổng quan" note={asks ? `Có ${asks} việc đang chờ bạn` : d.running.length ? "Máy đang làm việc, chưa cần bạn" : "Không có việc nào đang chờ"}
          actions={<><Button onClick={() => go("/thu-vien")}><Icon name="plus" />Thêm footage</Button><Button kind="primary" onClick={() => go("/du-an")}><Icon name="clapper" />Làm video mới</Button></>}>
      <div className="grid gap-10">
        {d.kill_switch && <p className="panel border-tally/50 px-4 py-3 text-tally">Đang bật dừng khẩn cấp: hệ thống không bắt đầu việc tốn tiền hay tác động ra ngoài. Tắt ở mục Hệ thống.</p>}

        {asks > 0 && (
          <Section title="Cần bạn">
            <ul className="panel rows overflow-hidden border-cue/40">
              {d.attention.map((i) => (
                <li key={i.run_id}><a href={i.link} onClick={open(i.link)} className={row}>
                  <span className="min-w-0 truncate font-medium">{i.name}</span><span className={i.status === "failed" ? "text-tally" : "text-cue"}>{ASK[i.status]?.(i) ?? i.status}{i.gaps ? `, còn ${i.gaps} câu chưa có hình` : ""}</span></a></li>
              ))}
              {d.gaps.map((g) => (
                <li key={g.project_id}><a href={`/du-an/${g.project_id}`} onClick={open(`/du-an/${g.project_id}`)} className={row}>
                  <span className="min-w-0 truncate font-medium">{g.title}</span><span className="text-cue">Còn {g.gaps} câu chưa có hình</span></a></li>
              ))}
              {d.offline_volumes.map((v) => (
                <li key={v.volume_id}><a href="/he-thong" onClick={open("/he-thong")} className={row}>
                  <span className="min-w-0 truncate font-medium">{v.mount_path}</span><span className="text-cue">Không tìm thấy nơi chứa {v.files} file footage</span></a></li>
              ))}
              {d.problems.map((p) => (
                <li key={p.name}><a href="/he-thong" onClick={open("/he-thong")} className={row}>
                  <span className="min-w-0 font-medium">{p.name}<span className="block text-[13px] font-normal text-mute">{p.fix}</span></span><span className="text-cue">{p.detail}</span></a></li>
              ))}
            </ul>
          </Section>
        )}

        <Section title="Dự án gần đây" actions={<Button kind="quiet" size="sm" onClick={() => go("/du-an")}>Tất cả dự án</Button>}>
          {projects && projects.length === 0 && <p className="panel px-4 py-6 text-mute">Chưa có dự án nào. Mỗi dự án là một video: bạn viết kịch bản, hệ thống tìm clip trong kho footage rồi dựng thành video có lời dẫn và phụ đề.</p>}
          <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {(projects ?? []).slice(0, 6).map((p) => {
              const st = projectState(p);
              return (
                <li key={p.project_id}><a href={`/du-an/${p.project_id}`} onClick={open(`/du-an/${p.project_id}`)} className="panel group block overflow-hidden transition-colors hover:border-faint">
                  <Filmstrip shots={p.shots} height={84} />
                  <div className="px-4 py-3">
                    <p className="truncate font-medium">{p.title}</p>
                    <div className="mt-2 flex items-center justify-between gap-3"><Steps step={st.step} tone={st.tone} /><Tag tone={st.tone}>{st.label}</Tag></div>
                  </div>
                </a></li>
              );
            })}
          </ul>
        </Section>

        <div className="grid gap-10 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <Section title="Đang chạy">
            {d.running.length === 0 && d.agent.length === 0 && <p className="panel px-4 py-5 text-mute">Máy đang rảnh.</p>}
            {(d.running.length > 0 || d.agent.length > 0) && (
              <ul className="panel rows overflow-hidden">
                {d.running.map((i) => (
                  <li key={i.run_id} className="grid items-center gap-x-5 gap-y-1 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_150px]">
                    <span className="min-w-0"><span className="block truncate"><span className="font-medium">{WORK[i.pipeline] ?? i.pipeline}</span> <span className="text-mute">{i.name}</span></span>
                      <span className="text-[13px] text-mute">{i.held ? "Chờ tới giờ phân tích" : i.stage_key ? `Bước ${stageName(i.stage_key, i.pipeline)}` : "Trong hàng đợi"}</span></span>
                    <StageRail stages={i.stages ?? []} />
                  </li>
                ))}
                {d.agent.map((t) => (
                  <li key={t.task_id}><a href={`/du-an/${t.project_id}`} onClick={open(`/du-an/${t.project_id}`)} className="flex items-start gap-3 px-4 py-3 hover:bg-raised/60">
                    <span className="mt-0.5 text-mute"><Icon name="spark" /></span><span className="min-w-0"><span className="block truncate font-medium">Trợ lý sản xuất: {t.goal}</span>
                      <span className={`text-[13px] ${t.status === "waiting_operator" ? "text-cue" : "text-mute"}`}>{t.log[t.log.length - 1]?.text}</span></span></a></li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Hiện trạng">
            <dl className="panel rows">
              <div className="flex justify-between gap-4 px-4 py-3"><dt className="text-mute">Kho footage</dt><dd className="tc text-right">{c.videos} video, {timecode(c.footage_seconds)}{c.photos ? `, ${c.photos} ảnh` : ""}{c.music ? `, ${c.music} nhạc` : ""}</dd></div>
              <div className="flex justify-between gap-4 px-4 py-3"><dt className="text-mute">Cảnh tìm được bằng lời</dt><dd className="tc">{c.moments}</dd></div>
              <div className="flex justify-between gap-4 px-4 py-3"><dt className="text-mute">Chi phí hôm nay</dt><dd className="tc">{d.spent_today.toFixed(2)} USD</dd></div>
              <div className="px-4 py-3"><div className="flex justify-between gap-4"><dt className="text-mute">Ổ đĩa</dt><dd className={`tc ${used > 0.9 ? "text-cue" : ""}`}>còn trống {megabytes(d.disk.free_bytes)}</dd></div>
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-raised"><div className={`h-full ${used > 0.9 ? "bg-cue" : "bg-ink/70"}`} style={{ width: `${used * 100}%` }} /></div></div>
            </dl>
            {d.unavailable.length > 0 && <p className="mt-3 text-[13px] text-mute">Chưa dùng được trên máy này: {d.unavailable.map((u) => `${WORK[u.pipeline] ?? u.pipeline} (thiếu ${u.missing.map((m) => NEEDS[m] ?? m).join(", ")})`).join("; ")}.</p>}
          </Section>
        </div>
      </div>
    </Page>
  );
}
