import { megabytes, projectState, REASONS, stageName, timecode, usePoll, type AgentTask, type Project, type Stage } from "./api";
import { Button, Empty, Filmstrip, Icon, Meter, Page, Section, Skeleton, SkeletonCards, StageRail, Stat, Steps, Tag } from "./parts";

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
const WORK_ICON: Record<string, string> = { "library.ingest": "film", "library.ingest_image": "image", "library.ingest_audio": "music", "library.understand": "eye",
  "sourcing.match": "sparkles", "sourcing.generate": "spark", "edit.render": "scissors" };
const ASK: Record<string, (i: Item) => string> = {
  waiting_review: (i) => (i.pipeline === "edit.render" ? "Bản dựng chờ bạn duyệt" : i.pipeline === "sourcing.generate" ? "Hình vừa sinh chờ bạn duyệt" : "Các clip đã chọn chờ bạn duyệt"),
  blocked: (i) => `${WORK[i.pipeline] ?? i.pipeline} đang dừng: ${REASONS[i.reason ?? ""] ?? i.reason ?? "cần bạn xử lý"}`,
  failed: (i) => `${WORK[i.pipeline] ?? i.pipeline} thất bại ở bước ${stageName(i.stage_key ?? "", i.pipeline)}`,
};
const NEEDS: Record<string, string> = { model: "mô hình thị giác (Ollama)", voice: "giọng đọc", image_gen: "nhà cung cấp sinh ảnh", video_gen: "nhà cung cấp sinh video", ffmpeg: "FFmpeg", ffprobe: "FFprobe", graphics: "bộ vẽ phụ đề" };
const hours = (s: number) => (s >= 3600 ? `${(s / 3600).toFixed(1)}h` : timecode(s));

/** The first screen: what waits for the operator, what the machine is doing, and where things stand. */
export default function Home({ go }: { go: (to: string) => void }) {
  const { data: d, error } = usePoll<HomeData>("/api/v1/home", 3000);
  const { data: projects } = usePoll<Project[]>("/api/v1/projects", 6000);
  const open = (to: string) => (e: React.MouseEvent) => { e.preventDefault(); go(to); };
  const hour = new Date().getHours();
  const greet = hour < 11 ? "Chào buổi sáng" : hour < 14 ? "Chào buổi trưa" : hour < 18 ? "Chào buổi chiều" : "Chào buổi tối";
  if (!d) return (
    <Page eyebrow={new Date().toLocaleDateString("vi-VN", { weekday: "long", day: "numeric", month: "long" })} title={greet} note={error ? `Không tải được: ${error}` : "Đang mở…"}>
      <div className="grid gap-8" aria-busy="true">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="panel grid gap-3 p-4"><Skeleton height={12} className="w-24" /><Skeleton height={28} className="w-20" /><Skeleton height={12} className="w-32" /></div>)}</div>
        <SkeletonCards count={2} className="grid gap-4 md:grid-cols-2" />
      </div>
    </Page>);
  const asks = d.attention.length + d.gaps.length + d.offline_volumes.length + d.problems.length;
  const c = d.counts;
  const used = 1 - d.disk.free_bytes / d.disk.total_bytes;
  const ask = (key: string, to: string, icon: string, title: React.ReactNode, what: React.ReactNode, tone: "cue" | "tally" = "cue") => (
    <li key={key}><a href={to} onClick={open(to)} className="group flex items-center gap-4 px-4 py-3.5 transition-colors hover:bg-white/[0.02]">
      <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${tone === "tally" ? "bg-tally/12 text-tally" : "bg-cue/12 text-cue"}`}><Icon name={icon} size={17} /></span>
      <span className="min-w-0 flex-1"><span className="block truncate font-medium">{title}</span><span className={`block truncate text-[13px] ${tone === "tally" ? "text-tally" : "text-cue"}`}>{what}</span></span>
      <span className="flex items-center gap-1 text-[12.5px] text-faint transition-colors group-hover:text-ink">Mở<Icon name="next" size={14} /></span>
    </a></li>
  );
  return (
    <Page eyebrow={new Date().toLocaleDateString("vi-VN", { weekday: "long", day: "numeric", month: "long" })} title={greet}
          note={asks ? `Có ${asks} việc đang chờ bạn quyết định.` : d.running.length ? "Máy đang làm việc, chưa cần bạn." : "Không có việc nào đang chờ. Một ngày tốt để làm video mới."}
          actions={<><Button onClick={() => go("/thu-vien")}><Icon name="plus" />Thêm footage</Button><Button kind="primary" onClick={() => go("/du-an?moi=1")}><Icon name="clapper" />Làm video mới</Button></>}>
      <div className="grid gap-8">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <Stat label="Kho footage" icon="film" value={hours(c.footage_seconds)} sub={`${c.videos} video${c.photos ? `, ${c.photos} ảnh` : ""}${c.music ? `, ${c.music} nhạc` : ""}`} />
          <Stat label="Cảnh đã hiểu" icon="eye" tone="ai" value={c.moments} sub="Tìm được bằng lời" />
          <Stat label="Dự án" icon="clapper" value={c.projects} sub={`${(projects ?? []).filter((p) => projectState(p).step === 5).length} đã xong`} />
          <Stat label="Chi phí hôm nay" icon="coins" tone="proof" value={<>{d.spent_today.toFixed(2)}<span className="ml-1 text-[13px] font-medium text-mute">USD</span></>} sub={d.spent_today === 0 ? "Mọi thứ chạy trên máy" : "Dịch vụ trả tiền"} />
          <Stat label="Ổ đĩa" icon="disk" tone={used > 0.9 ? "cue" : "accent"} value={megabytes(d.disk.free_bytes)} sub={`trống trên ${megabytes(d.disk.total_bytes)}`}><Meter share={used} tone={used > 0.9 ? "cue" : "ai"} /></Stat>
        </div>

        {asks > 0 && (
          <Section title="Cần bạn" icon="alert" note="Hệ thống dừng ở những chỗ này và chờ quyết định của bạn.">
            <ul className="cue-card rows overflow-hidden">
              {d.attention.map((i) => ask(i.run_id, i.link, i.status === "failed" ? "alert" : i.pipeline === "edit.render" ? "play" : "check", i.name,
                <>{ASK[i.status]?.(i) ?? i.status}{i.gaps ? `, còn ${i.gaps} câu chưa có hình` : ""}</>, i.status === "failed" ? "tally" : "cue"))}
              {d.gaps.map((g) => ask(g.project_id, `/du-an/${g.project_id}`, "image", g.title, `Còn ${g.gaps} câu chưa có hình`))}
              {d.offline_volumes.map((v) => ask(v.volume_id, "/he-thong", "disk", v.mount_path, `Không tìm thấy nơi chứa ${v.files} file footage`))}
              {d.problems.map((p) => ask(p.name, "/he-thong", "cpu", <>{p.name}{p.fix && <span className="ml-2 text-[12.5px] font-normal text-mute">{p.fix}</span>}</>, p.detail))}
            </ul>
          </Section>
        )}

        <div className="grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_400px]">
          <Section title="Dự án gần đây" icon="clapper" actions={<Button kind="quiet" size="sm" onClick={() => go("/du-an")}>Tất cả dự án<Icon name="next" size={14} /></Button>}>
            {projects && projects.length === 0 && <Empty icon="clapper" title="Chưa có dự án nào" action={<Button kind="primary" onClick={() => go("/du-an?moi=1")}><Icon name="plus" />Làm video đầu tiên</Button>}>Mỗi dự án là một video: bạn viết kịch bản, hệ thống tìm clip trong kho footage rồi dựng thành video có lời dẫn và phụ đề.</Empty>}
            <ul className="grid gap-4 sm:grid-cols-2 2xl:grid-cols-3">
              {(projects ?? []).slice(0, 6).map((p) => {
                const st = projectState(p);
                const latest = p.renders[0];
                return (
                  <li key={p.project_id}><a href={`/du-an/${p.project_id}`} onClick={open(`/du-an/${p.project_id}`)} className="panel group block overflow-hidden transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-edge">
                    <div className="relative">
                      <Filmstrip shots={p.shots} height={120} className="transition-[filter] duration-300 group-hover:brightness-110" />
                      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-surface via-transparent to-transparent" />
                      <span className="absolute left-2.5 top-2.5 rounded-full bg-black/55 backdrop-blur"><Tag tone={st.tone}>{st.label}</Tag></span>
                      {latest && <span className="chip mono absolute right-2.5 top-2.5"><Icon name="play" size={11} />{timecode(latest.qc.duration)}</span>}
                    </div>
                    <div className="px-4 pb-4 pt-1">
                      <p className="truncate text-[15px] font-medium">{p.title}</p>
                      <div className="mt-2 flex items-center justify-between gap-3"><Steps step={st.step} tone={st.tone} /><span className="mono text-[11.5px] text-faint">{p.shots.length ? `${p.shots.length} câu` : "chưa có kịch bản"}</span></div>
                    </div>
                  </a></li>
                );
              })}
            </ul>
          </Section>

          <div className="grid gap-8">
            <Section title="Đang chạy" icon="pulse" actions={<Button kind="quiet" size="sm" onClick={() => go("/tien-trinh")}>Tiến trình<Icon name="next" size={14} /></Button>}>
              {d.running.length === 0 && d.agent.length === 0 && <div className="panel flex items-center gap-3 px-4 py-4 text-mute"><span className="h-2 w-2 rounded-full bg-proof" />Máy đang rảnh.</div>}
              {(d.running.length > 0 || d.agent.length > 0) && (
                <ul className="grid gap-2">
                  {d.running.map((i) => (
                    <li key={i.run_id} className="panel p-3.5">
                      <div className="mb-3 flex items-center gap-3">
                        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-ai/10 text-ai"><Icon name={WORK_ICON[i.pipeline] ?? "pulse"} size={16} /></span>
                        <span className="min-w-0 flex-1"><span className="block truncate text-[13.5px] font-medium">{WORK[i.pipeline] ?? i.pipeline}<span className="font-normal text-mute"> · {i.name}</span></span>
                          <span className="block truncate text-[12px] text-mute">{i.held ? "Chờ tới giờ phân tích" : i.stage_key ? `Bước ${stageName(i.stage_key, i.pipeline)}` : "Trong hàng đợi"}</span></span>
                      </div>
                      <StageRail stages={i.stages ?? []} name={(k) => stageName(k, i.pipeline)} />
                    </li>
                  ))}
                  {d.agent.map((t) => (
                    <li key={t.task_id}><a href={`/du-an/${t.project_id}`} onClick={open(`/du-an/${t.project_id}`)} className="ai-card flex items-start gap-3 p-3.5 transition-colors hover:border-ai/40">
                      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-ai/15 text-ai"><Icon name="sparkles" size={16} /></span>
                      <span className="min-w-0"><span className="block truncate text-[13.5px] font-medium">Trợ lý sản xuất: {t.goal}</span>
                        <span className={`line-clamp-2 text-[12.5px] ${t.status === "waiting_operator" ? "text-cue" : "text-mute"}`}>{t.log[t.log.length - 1]?.text}</span></span></a></li>
                  ))}
                </ul>
              )}
            </Section>
            {d.unavailable.length > 0 && (
              <Section title="Chưa dùng được trên máy này" icon="cpu">
                <ul className="panel rows">
                  {d.unavailable.map((u) => (
                    <li key={u.pipeline} className="flex items-start gap-3 px-4 py-3 text-[13px]"><span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-cue" />
                      <span><span className="font-medium">{WORK[u.pipeline] ?? u.pipeline}</span><span className="block text-mute">Thiếu {u.missing.map((m) => NEEDS[m] ?? m).join(", ")}</span></span></li>
                  ))}
                </ul>
              </Section>
            )}
          </div>
        </div>
      </div>
    </Page>
  );
}
