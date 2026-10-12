import { useState } from "react";
import { call, megabytes, post, usePoll, type EvalRun, type Settings, type Template } from "./api";
import { Button, Icon, Meter, Page, Tag } from "./parts";

type Env = { ffmpeg?: { filters: Record<string, boolean>; encoders: Record<string, boolean> }; disk: { free_bytes: number; total_bytes: number };
             adapters: { name: string; runs: string; operations: string[] }[] };
type Control = { kill_switch: boolean; desktop_notifications: boolean; background_window: string; background_running_now: boolean };

const NEEDS: Record<string, string> = {
  zscale: "Chuyển video HDR về màu chuẩn", subtitles: "Gắn phụ đề bằng FFmpeg", drawtext: "Vẽ chữ bằng FFmpeg",
  blackdetect: "Tìm khung đen", loudnorm: "Chuẩn hoá âm lượng", tonemap: "Hạ dải sáng HDR", scale: "Đổi kích thước hình", fps: "Chuẩn hoá tốc độ khung hình",
};

type Storage = { stores: { key: string; label: string; bytes: number; files: number; cleanable: boolean }[]; backups: { name: string; size: number; created_at: number }[];
                 volumes: { volume_id: string; name: string; mount_path: string; online: boolean; files: number }[] };
type Check = { name: string; ok: boolean; detail: string; fix: string | null; optional: boolean };

/** One card of the settings screen. */
function Card({ title, icon, note, children, actions, tone }: { title: string; icon: string; note?: React.ReactNode; children?: React.ReactNode; actions?: React.ReactNode; tone?: "tally" | "ai" }) {
  const ring = tone === "tally" ? "bg-tally/12 text-tally" : tone === "ai" ? "bg-ai/12 text-ai" : "bg-accent/12 text-accent";
  return (
    <div className="panel p-5">
      <div className="mb-4 flex flex-wrap items-start gap-3">
        <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg ${ring}`}><Icon name={icon} size={17} /></span>
        <div className="min-w-0 grow basis-60"><h2 className="text-[15px] font-semibold">{title}</h2>{note && <div className="mt-0.5 max-w-2xl text-[13px] text-mute">{note}</div>}</div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}
const listCls = "rows overflow-hidden rounded-xl border border-line";
const rowCls = "flex items-center justify-between gap-4 px-3.5 py-2.5 text-[13px]";
const hourCls = "mono h-9 w-16 px-2 text-center";

function Health() {
  const { data } = usePoll<{ checks: Check[] }>("/api/v1/doctor", 30000);
  const bad = (data?.checks ?? []).filter((c) => !c.ok && !c.optional);
  return (
    <Card title="Kiểm tra hệ thống" icon="shield" tone="ai" note={data ? <span className={bad.length ? "text-cue" : "text-proof"}>{bad.length ? `Có ${bad.length} thứ cần xử lý trước khi làm video.` : "Mọi thứ hệ thống cần đều sẵn sàng."}</span> : "Đang kiểm tra…"}>
      <ul className={listCls}>
        {(data?.checks ?? []).map((c) => (
          <li key={c.name} className="px-3.5 py-2.5 text-[13px]"><div className="flex items-center justify-between gap-4"><span className="flex items-center gap-2 font-medium"><span className={`h-1.5 w-1.5 rounded-full ${c.ok ? "bg-proof" : c.optional ? "bg-faint" : "bg-cue"}`} />{c.name}</span><span className={`text-right ${c.ok || c.optional ? "text-mute" : "text-cue"}`}>{c.detail}</span></div>
            {c.fix && <p className="mt-0.5 pl-3.5 text-[12.5px] text-faint">{c.optional ? "Không bắt buộc. " : ""}{c.fix}</p>}</li>
        ))}
      </ul>
    </Card>
  );
}

const KINDS: [string, string][] = [["waiting_review", "Có việc chờ duyệt"], ["blocked", "Một việc bị dừng"], ["failed", "Một việc thất bại"], ["succeeded", "Một việc xong"]];

function NoticePrefs() {
  const { data, reload } = usePoll<{ quiet_hours: string; notify_off: string[] }>("/api/v1/usage", 15000);
  if (!data) return null;
  const toggle = async (kind: string) => { const off = data.notify_off.includes(kind) ? data.notify_off.filter((k) => k !== kind) : [...data.notify_off, kind]; await post("/api/v1/control/settings", { notify_off: off }); reload(); };
  return (
    <div className="mt-4 grid gap-4 border-t border-line pt-4">
      <div><p className="field-label">Báo khi</p>
        <div className="flex flex-wrap gap-2">{KINDS.map(([kind, name]) => { const on = !data.notify_off.includes(kind); return (
          <label key={kind} className={`flex h-8 cursor-pointer items-center gap-2 rounded-lg border px-3 text-[13px] transition-colors ${on ? "border-accent/40 bg-accent/10" : "border-line text-mute"}`}><input type="checkbox" checked={on} onChange={() => toggle(kind)} />{name}</label>); })}</div></div>
      <form className="flex flex-wrap items-center gap-2 text-[13px]" onSubmit={async (e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const a = String(f.get("qf") ?? ""), b = String(f.get("qt") ?? ""); await post("/api/v1/control/settings", { quiet_hours: a !== "" && b !== "" ? `${a}-${b}` : "" }).catch(() => {}); reload(); }}>
        <span className="field-label !mb-0 w-full">Giờ yên lặng</span>
        <label htmlFor="qf">Từ</label><input id="qf" name="qf" type="number" min="0" max="23" defaultValue={data.quiet_hours.split("-")[0] ?? ""} key={`a${data.quiet_hours}`} className={hourCls} />
        <label htmlFor="qt">giờ đến</label><input id="qt" name="qt" type="number" min="0" max="23" defaultValue={data.quiet_hours.split("-")[1] ?? ""} key={`b${data.quiet_hours}`} className={hourCls} /><span>giờ</span>
        <Button type="submit" size="sm">Lưu</Button>
        <span className="w-full text-[12.5px] text-faint">{data.quiet_hours ? "Trong giờ này thông báo chỉ nằm ở mục Thông báo." : "Để trống cả hai ô để báo bất cứ lúc nào."}</span>
      </form>
    </div>
  );
}

const WORK: Record<string, string> = { "library.ingest": "Nhập footage", "library.ingest_image": "Nhập ảnh", "library.ingest_audio": "Nhập nhạc", "library.understand": "Xem và mô tả footage",
  "sourcing.match": "Chọn clip cho kịch bản", "sourcing.generate": "Sinh hình bằng AI", "edit.render": "Dựng video" };
const NEED: Record<string, string> = { model: "mô hình thị giác", voice: "giọng đọc", image_gen: "nhà cung cấp sinh ảnh", video_gen: "nhà cung cấp sinh video", ffmpeg: "FFmpeg", ffprobe: "FFprobe", graphics: "bộ vẽ phụ đề" };

function Capabilities() {
  const { data } = usePoll<{ pipelines: { pipeline: string; available: boolean; missing: string[] }[] }>("/api/v1/capabilities", 30000);
  return (
    <Card title="Việc máy này làm được" icon="cpu" tone="ai">
      <ul className="grid gap-2 sm:grid-cols-2">
        {(data?.pipelines ?? []).map((p) => (
          <li key={p.pipeline} className={`rounded-xl border px-3.5 py-3 text-[13px] ${p.available ? "border-line bg-raised/40" : "border-cue/30 bg-cue/[0.04]"}`}>
            <p className="flex items-center gap-2 font-medium"><span className={`h-1.5 w-1.5 rounded-full ${p.available ? "bg-proof" : "bg-cue"}`} />{WORK[p.pipeline] ?? p.pipeline}</p>
            <p className={`mt-0.5 pl-3.5 text-[12px] ${p.available ? "text-faint" : "text-cue"}`}>{p.available ? "Sẵn sàng" : `Thiếu ${p.missing.map((m) => NEED[m] ?? m).join(", ")}`}</p></li>
        ))}
      </ul>
    </Card>
  );
}

type Level = { level: number; name: string; does: string; earned: boolean; progress: { have: number; need: number; text: string } | null };
/** How much the system may decide alone. A level can be chosen only once the operator's own review record has earned it. */
function AutonomyCard() {
  const { data, reload } = usePoll<{ level: number; levels: Level[]; log: { at: number; level: number; text: string }[] }>("/api/v1/autonomy", 8000);
  const [note, setNote] = useState<string | null>(null);
  const choose = async (level: number) => { setNote(null); try { await post("/api/v1/autonomy", { level }); } catch (e) { setNote((e as Error).message); } reload(); };
  return (
    <Card title="Mức tự chủ" icon="bolt" tone="ai" note="Mỗi mức cho hệ thống tự quyết thêm một việc. Mức cao hơn chỉ chọn được khi chính lịch sử duyệt của bạn cho thấy nó xứng đáng. Dừng khẩn cấp, ngân sách và chế độ riêng tư luôn được tuân theo trước.">
      {note && <p className="mb-3 rounded-lg border border-cue/30 bg-cue/[0.06] px-3 py-2 text-[13px] text-cue">{note}</p>}
      <ol className="grid gap-2">
        {(data?.levels ?? []).map((l) => {
          const now = data!.level === l.level, reachable = (data?.levels ?? []).filter((x) => x.level <= l.level).every((x) => x.earned) || l.level < data!.level;
          return (
            <li key={l.level} className={`rounded-xl border px-4 py-3 text-[13px] ${now ? "border-accent/60 bg-accent/[0.06]" : "border-line bg-raised/40"}`}>
              <div className="flex flex-wrap items-center gap-2"><span className="mono text-faint">A{l.level}</span><span className="font-medium">{l.name}</span>
                {now ? <Tag tone="accent">Đang dùng</Tag> : !reachable && <Tag tone="mute">Chưa đủ điều kiện</Tag>}
                {!now && <span className="ml-auto"><Button size="sm" disabled={!reachable} onClick={() => choose(l.level)}>{l.level < data!.level ? "Hạ xuống mức này" : "Chọn mức này"}</Button></span>}</div>
              <p className="mt-1 text-mute">{l.does}</p>
              {l.progress && !l.earned && <p className="mt-1 text-[12.5px] text-faint">{l.progress.text}</p>}
            </li>);
        })}
      </ol>
      {!!data?.log.length && <details className="mt-3 text-[13px]"><summary className="cursor-pointer list-none text-accent">Những việc hệ thống đã tự quyết</summary>
        <ul className="rows mt-2">{[...data.log].reverse().map((e, i) => <li key={i} className="flex gap-3 py-1.5"><span className="mono shrink-0 text-faint">{new Date(e.at * 1000).toLocaleString("vi-VN", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })}</span><span>{e.text}</span></li>)}</ul></details>}
    </Card>
  );
}

/** Which model answers each kind of text task. Anything with a picture in it never leaves this machine. */
function ModelRoutes() {
  const { data, reload } = usePoll<{ models: { name: string; runs: string }[]; routes: Record<string, string>; tasks: Record<string, string>; privacy_local_only: boolean }>("/api/v1/models/routes", 30000);
  const cloud = (data?.models ?? []).filter((m) => m.runs === "cloud");
  const set = async (task: string, name: string) => { const routes = { ...(data?.routes ?? {}) }; if (name) routes[task] = name; else delete routes[task]; await post("/api/v1/models/routes", { routes }); reload(); };
  return (
    <Card title="Mô hình cho việc chữ" icon="globe" note="Việc nào có hình (mô tả footage, chấm clip, tìm chủ thể) luôn chạy trên máy này. Việc chỉ có chữ có thể giao cho mô hình cloud; khi đó nội dung chữ của việc đó, gồm kịch bản và mô tả kho footage, được gửi ra ngoài.">
      {data && cloud.length === 0 && <p className="text-[13px] text-mute">Chưa có mô hình cloud nào. Đặt biến môi trường ANTHROPIC_API_KEY hoặc điền anthropic_api_key trong nexora.toml rồi khởi động lại để dùng Claude cho việc chữ.</p>}
      {data?.privacy_local_only && cloud.length > 0 && <p className="mb-2 text-[13px] text-cue">Chế độ riêng tư đang bật: mọi việc đều chạy trên máy, các lựa chọn dưới đây tạm không có tác dụng.</p>}
      {cloud.length > 0 && <ul className="rows text-[13px]">{Object.entries(data!.tasks).map(([task, name]) => (
        <li key={task} className="flex items-center gap-3 py-2"><span className="min-w-0 flex-1">{name}</span>
          <select aria-label={`Mô hình cho ${name}`} value={data!.routes[task] ?? ""} onChange={(e) => set(task, e.target.value)} className="h-8 pl-2"><option value="">Trên máy</option>{cloud.map((m) => <option key={m.name} value={m.name}>{m.name.replace("model.", "")} (cloud)</option>)}</select></li>))}</ul>}
    </Card>
  );
}

/** The order in which picture providers are tried. */
function Providers() {
  const { data, reload } = usePoll<{ stock?: { available: boolean; sources: { key: string; label: string; on: boolean }[] }; generators?: { image_providers: { name: string; label: string; runs: string }[]; video_providers: { name: string; label: string; runs: string }[] } }>("/api/v1/generators", 30000);
  const first = async (kind: string, list: { name: string }[], name: string) => { await post("/api/v1/control/providers", { kind, order: [name, ...list.map((p) => p.name).filter((n) => n !== name)] }); reload(); };
  const g = data?.generators;
  const row = (kind: string, title: string, list: { name: string; label: string; runs: string }[]) => (
    <div><p className="mb-1.5 text-[13px] font-medium">{title}</p>
      {list.length === 0 ? <p className="text-[13px] text-mute">Chưa có nhà cung cấp nào.</p> : <ol className="rows text-[13px]">{list.map((p, i) => (
        <li key={p.name} className="flex items-center gap-3 py-1.5"><span className="mono w-5 text-faint">{i + 1}</span><span className="min-w-0 flex-1">{p.label === "motion" ? "Chuyển động từ ảnh tĩnh" : p.label}</span><span className="text-faint">{p.runs === "cloud" ? "ngoài máy" : "trên máy"}</span>
          {i > 0 && <button type="button" className="link" onClick={() => first(kind, list, p.name)}>Dùng trước</button>}</li>))}</ol>}</div>);
  return <Card title="Nhà cung cấp hình sinh bằng AI" icon="spark" note="Mỗi cảnh được gửi tới nhà cung cấp đứng đầu; nếu nó hỏng, hết lượt hoặc bị chế độ riêng tư chặn thì tới nhà kế tiếp.">
    {g && <div className="grid gap-4 sm:grid-cols-2">{row("image_gen", "Ảnh", g.image_providers)}{row("video_gen", "Video", g.video_providers)}</div>}
    {data?.stock && <div className="mt-4 border-t border-line pt-3"><p className="mb-1.5 text-[13px] font-medium">Nguồn clip stock</p>
      {!data.stock.available ? <p className="text-[13px] text-mute">Máy này chưa có công cụ tìm clip stock (OpenMontage).</p>
        : <div className="flex flex-wrap gap-x-5 gap-y-2 text-[13px]">{data.stock.sources.map((s) => <label key={s.key} className="flex items-center gap-2"><input type="checkbox" checked={s.on}
            onChange={async (e) => { const next = data.stock!.sources.filter((x) => (x.key === s.key ? e.target.checked : x.on)).map((x) => x.key); if (next.length) { await post("/api/v1/control/stock-sources", { sources: next }); reload(); } }} />{s.label}</label>)}
          <span className="w-full text-[12px] text-faint">Cả ba đều không cần khoá và chỉ trả về clip thuộc phạm vi công cộng hoặc có giấy phép mở; giấy phép của từng clip được lưu cùng clip.</span></div>}</div>}</Card>;
}

const AUDIT_PATHS: [RegExp, string][] = [[/kill-switch/, "Dừng khẩn cấp"], [/autonomy/, "Đổi mức tự chủ"], [/models\/routes/, "Đổi mô hình cho việc chữ"], [/render\/decision/, "Duyệt hoặc từ chối bản dựng"], [/match\/approve/, "Duyệt clip"],
  [/generate\/approve/, "Duyệt hình sinh bằng AI"], [/\/publish$/, "Đăng hoặc ghi nhận bản đăng"], [/\/package$/, "Gói xuất bản"], [/\/render$/, "Dựng video"], [/\/preview$/, "Dựng bản xem thử"], [/\/match$/, "Tìm clip"], [/\/script$/, "Lưu kịch bản"],
  [/assets\/register/, "Thêm footage"], [/\/settings/, "Đổi cài đặt"], [/storage\/clean/, "Dọn bộ đệm"], [/storage\/backup/, "Sao lưu"], [/agent\/tasks/, "Giao việc cho trợ lý"], [/^\/api\/v1\/projects$/, "Tạo dự án"], [/projects\//, "Sửa dự án"], [/shots\//, "Sửa một câu"], [/assets\//, "Sửa một nguyên liệu"]];
/** Everything changed through the interface, newest first. */
function AuditCard() {
  const { data } = usePoll<{ entries: { audit_id: number; at: number; method: string; path: string; status: number }[] }>("/api/v1/audit?limit=200", 10000);
  return (
    <Card title="Nhật ký thao tác" icon="list" note="Mọi thao tác làm thay đổi hệ thống qua giao diện này đều được ghi lại: việc gì, lúc nào, có thành công không. Nhật ký của từng lần chạy nằm ở Bảng theo dõi của dự án.">
      {data && data.entries.length === 0 && <p className="text-[13px] text-mute">Chưa có thao tác nào được ghi.</p>}
      <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-[12.5px]"><tbody>
        {(data?.entries ?? []).map((e) => (
          <tr key={e.audit_id} className="border-t border-line first:border-t-0"><td className="mono whitespace-nowrap py-1.5 pr-3 text-faint">{new Date(e.at * 1000).toLocaleString("vi-VN", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" })}</td>
            <td className="py-1.5 pr-3">{AUDIT_PATHS.find(([re]) => re.test(e.path))?.[1] ?? "Thao tác khác"}</td><td className="mono max-w-[260px] truncate py-1.5 pr-3 text-faint" title={e.path}>{e.path.replace("/api/v1", "")}</td>
            <td className={`py-1.5 text-right ${e.status < 400 ? "text-proof" : "text-cue"}`}>{e.status < 400 ? "Được" : `Không được (${e.status})`}</td></tr>))}
      </tbody></table></div>
    </Card>
  );
}

/** The operator's own benchmark: known right answers, and how the search does on them from one run to the next. */
function Benchmark() {
  const { data, reload } = usePoll<{ cases: { case_id: string; line: string; t_in: number; t_out: number }[]; runs: EvalRun[] }>("/api/v1/evaluation", 15000);
  const [note, setNote] = useState<string | null>(null);
  const run = async () => { setNote(null); try { await post("/api/v1/evaluation/run"); } catch (e) { setNote((e as Error).message); } reload(); };
  const pct = (v: number) => `${Math.round(v * 100)}%`;
  const CONFIG: Record<string, string> = { models: "mô hình", describe_prompt: "câu hỏi mô tả", segment_seconds: "độ dài đoạn", moments: "số cảnh trong kho" };
  return (
    <Card title="Bộ mẫu chuẩn" icon="shield" tone="ai" note="Những cặp câu và clip bạn đã xác nhận là đúng. Chạy lại sau khi đổi mô hình, câu hỏi hoặc ngưỡng để biết hệ thống tìm tốt lên hay kém đi."
          actions={<Button kind="ai" disabled={!data?.cases.length} onClick={run}>Chạy đánh giá</Button>}>
      {note && <p className="mb-2 text-[13px] text-tally">{note}</p>}
      {data && data.cases.length === 0 && <p className="text-[13px] text-mute">Chưa có mẫu nào. Trong một dự án, bấm “Lưu làm mẫu chuẩn” dưới một clip đã duyệt.</p>}
      {!!data?.runs.length && (
        <ul className="rows mb-3 text-[13px]">
          {data.runs.map((r) => (
            <li key={r.run_id} className="py-2">
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1"><span className="mono text-faint">{new Date(r.created_at * 1000).toLocaleString("vi-VN", { day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
                <span>Đúng ngay lần đầu <span className="mono">{pct(r.first)}</span></span><span>Trong ba kết quả đầu <span className="mono">{pct(r.top3)}</span></span><span className="text-faint">{r.cases} mẫu</span>
                {r.change && <Tag tone={r.change.regression ? "tally" : r.change.first > 0 || r.change.top3 > 0 ? "proof" : "mute"}>{r.change.regression ? "Kém đi" : r.change.first > 0 || r.change.top3 > 0 ? "Tốt lên" : "Không đổi"}</Tag>}</p>
              {r.change && Object.keys(r.change.config).length > 0 && <p className="mt-0.5 text-[12.5px] text-mute">Đã đổi: {Object.entries(r.change.config).map(([k, [a, b]]) => `${CONFIG[k] ?? k} từ ${String(a)} thành ${String(b)}`).join("; ")}</p>}
              {r.change && r.change.lost.length > 0 && <p className="mt-0.5 text-[12.5px] text-cue">Không còn tìm ra: {r.change.lost.map((l) => `“${l}”`).join(", ")}</p>}
            </li>))}
        </ul>)}
      {!!data?.cases.length && (
        <details className="text-[13px]"><summary className="cursor-pointer list-none text-accent">{data.cases.length} mẫu đang giữ</summary>
          <ul className="rows mt-2">{data.cases.map((c) => <li key={c.case_id} className="flex gap-3 py-1.5"><span className="min-w-0 flex-1 truncate">{c.line}</span><span className="mono shrink-0 text-faint">{c.t_in.toFixed(1)} đến {c.t_out.toFixed(1)} giây</span>
            <button type="button" className="link shrink-0" onClick={async () => { await call(`/api/v1/evaluation/cases/${c.case_id}`, { method: "DELETE" }); reload(); }}>Bỏ</button></li>)}</ul></details>)}
    </Card>
  );
}

const ROLES: Record<string, string> = { vision: "Xem và mô tả footage", judge: "Chấm clip và tìm chủ thể", writer: "Viết kịch bản và từ khoá", embed: "Lập chỉ mục để tìm bằng lời" };
const SHAPES: Record<string, string> = { landscape: "Ngang 16:9", portrait: "Dọc 9:16", square: "Vuông 1:1" };

function useSettings() {
  const { data: s, reload } = usePoll<Settings>("/api/v1/settings", 20000);
  const [note, setNote] = useState<string | null>(null);
  const save = async (body: Record<string, unknown>, done?: string) => { setNote(null); try { await post("/api/v1/settings", body); if (done) setNote(done); } catch (e) { setNote((e as Error).message); } reload(); };
  return { s, save, note };
}

function VoiceModels() {
  const { s, save, note } = useSettings();
  if (!s) return null;
  return (
    <>
      <Card title="Giọng đọc và mô hình" icon="mic" note="Giọng dùng cho mọi dự án không đặt giọng riêng. Bản dựng sau sẽ đọc bằng giọng này.">
        <label htmlFor="voice" className="field-label">Giọng đọc lời dẫn</label>
        <select id="voice" value={s.voice} onChange={(e) => save({ voice: e.target.value })} className="mb-5 w-full max-w-xs pl-3">
          {[...new Set([s.voice, ...s.voices])].map((v) => <option key={v}>{v}</option>)}
        </select>
        <p className="field-label">Mô hình cho từng việc</p>
        <ul className={listCls}>
          {Object.entries(s.model_roles).map(([role, model]) => (
            <li key={role} className={rowCls}><span className="flex items-center gap-2"><Icon name="sparkles" size={14} className="text-ai" />{ROLES[role] ?? role}</span><span className={`mono text-[12.5px] ${s.models[model] === false ? "text-cue" : "text-mute"}`}>{model}{s.models[model] === false ? " · chưa tải" : ""}</span></li>
          ))}
        </ul>
        <p className="mt-2 text-[12.5px] text-faint">Đổi mô hình cho từng việc trong file <span className="mono text-mute">nexora.toml</span> rồi khởi động lại.</p>
        {note && <p role="status" className="mt-2 text-[13px] text-proof">{note}</p>}
      </Card>
      <Card title="Chế độ riêng tư" icon="shield" note="Footage bạn tự quay vốn không bao giờ được gửi đi.">
        <label className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition-colors ${s.privacy_local_only ? "border-proof/40 bg-proof/[0.05]" : "border-line"}`}>
          <input type="checkbox" className="mt-0.5" checked={s.privacy_local_only} onChange={(e) => save({ privacy_local_only: e.target.checked })} />
          <span className="text-[13px]"><span className="font-medium">Không gửi gì ra khỏi máy này</span><span className="block text-mute">Khi bật, tìm clip stock và sinh hình bằng dịch vụ ngoài đều bị chặn.</span></span></label>
      </Card>
    </>
  );
}

function WatchFolders() {
  const { s, save } = useSettings();
  const [folder, setFolder] = useState("");
  if (!s) return null;
  return (
    <Card title="Thư mục theo dõi" icon="folder" note="File mới chép vào các thư mục này tự được nhập vào thư viện, sau khi đã chép xong.">
      {s.watch_folders.length > 0 && <ul className={`${listCls} mb-3`}>
        {s.watch_folders.map((f) => <li key={f} className={rowCls}><span className="mono min-w-0 break-all text-[12.5px]">{f}</span>
          <button type="button" className="link shrink-0 text-[12.5px]" onClick={() => save({ watch_folders: s.watch_folders.filter((x) => x !== f) })}>Bỏ theo dõi</button></li>)}
      </ul>}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (folder.trim()) save({ watch_folders: [...s.watch_folders, folder.trim()] }).then(() => setFolder("")); }}>
        <label htmlFor="watch" className="sr-only">Thư mục cần theo dõi</label>
        <input id="watch" value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="Ví dụ: /Volumes/TheNho/DCIM" className="mono min-w-0 flex-1 px-3 text-[13px]" />
        <Button disabled={!folder.trim()} onClick={() => save({ watch_folders: [...s.watch_folders, folder.trim()] }).then(() => setFolder(""))}><Icon name="plus" size={14} />Theo dõi</Button>
      </form>
    </Card>
  );
}

function Templates() {
  const { s, save, note } = useSettings();
  const [draft, setDraft] = useState<Template[] | null>(null);
  if (!s) return null;
  const list = draft ?? s.templates;
  const edit = (i: number, change: Partial<Template>) => setDraft(list.map((t, k) => (k === i ? { ...t, ...change } : t)));
  const lab = "grid gap-1 text-[12.5px] text-mute";
  return (
    <Card title="Mẫu định dạng" icon="layers" note="Mỗi mẫu là điểm xuất phát cho một kiểu video. Chọn mẫu trong dự án để áp dụng."
          actions={<><Button onClick={() => setDraft([...list, { name: "Mẫu mới", format: "landscape", voice: "", music_gain: 0.35, auto_accept: false, caption_scale: 1, caption_position: "bottom", pronounce: {} }])}><Icon name="plus" size={14} />Thêm mẫu</Button>
            <Button kind="primary" disabled={draft === null} onClick={() => save({ templates: list }, "Đã lưu các mẫu.").then(() => setDraft(null))}>Lưu các mẫu</Button></>}>
      {draft !== null && <p className="mb-3 flex items-center gap-2 text-[12.5px] text-accent"><span className="h-1.5 w-1.5 rounded-full bg-accent" />Có thay đổi chưa lưu</p>}
      {note && <p role="status" className="mb-3 text-[13px] text-proof">{note}</p>}
      <ul className="grid gap-3 2xl:grid-cols-2">
        {list.map((t, i) => (
          <li key={i} className="panel-raised p-4">
            <div className="mb-3 flex items-center gap-2">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-overlay text-mute"><Icon name={t.format === "portrait" ? "image" : "film"} size={15} /></span>
              <label className="sr-only" htmlFor={`tn${i}`}>Tên mẫu</label><input id={`tn${i}`} value={t.name} onChange={(e) => edit(i, { name: e.target.value })} className="min-w-0 flex-1 px-3 font-medium" />
              <button type="button" className="grid h-8 w-8 place-items-center rounded-md text-faint hover:bg-tally/10 hover:text-tally" title="Xoá mẫu" aria-label="Xoá mẫu" onClick={() => setDraft(list.filter((_, k) => k !== i))}><Icon name="x" size={15} /></button>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <label className={lab}>Khung hình<select value={t.format} onChange={(e) => edit(i, { format: e.target.value })} className="h-9 pl-2.5 text-ink">{Object.entries(SHAPES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
              <label className={lab}>Giọng<select value={t.voice} onChange={(e) => edit(i, { voice: e.target.value })} className="h-9 pl-2.5 text-ink"><option value="">Theo máy</option>{s.voices.map((v) => <option key={v}>{v}</option>)}</select></label>
              <label className={lab}>Mức nhạc<input type="number" min="0.05" max="1" step="0.05" value={t.music_gain} onChange={(e) => edit(i, { music_gain: Number(e.target.value) })} className="mono h-9 px-2.5 text-ink" /></label>
              <label className={lab}>Cỡ phụ đề<select value={String(t.caption_scale ?? 1)} onChange={(e) => edit(i, { caption_scale: Number(e.target.value) })} className="h-9 pl-2.5 text-ink"><option value="0.85">Nhỏ</option><option value="1">Vừa</option><option value="1.15">Lớn</option><option value="1.3">Rất lớn</option></select></label>
              <label className={lab}>Vị trí phụ đề<select value={t.caption_position ?? "bottom"} onChange={(e) => edit(i, { caption_position: e.target.value })} className="h-9 pl-2.5 text-ink"><option value="bottom">Dưới</option><option value="middle">Giữa</option><option value="top">Trên</option></select></label>
              <label className={lab}>Kiểu chữ<select value={t.typeface ?? "sans"} onChange={(e) => edit(i, { typeface: e.target.value })} className="h-9 pl-2.5 text-ink"><option value="sans">Không chân</option><option value="serif">Có chân</option></select></label>
              <label className={lab}>Màu chữ<span className="flex items-center gap-2"><input type="color" aria-label="Màu chữ phụ đề" value={`#${(t.caption_colour ?? [240, 238, 232]).map((n) => n.toString(16).padStart(2, "0")).join("")}`}
                onChange={(e) => edit(i, { caption_colour: [1, 3, 5].map((k) => parseInt(e.target.value.slice(k, k + 2), 16)) })} className="h-9 w-12 cursor-pointer p-1" />
                <span className="rounded px-2 py-1 text-[12px] font-semibold" style={{ background: "#000", color: `rgb(${(t.caption_colour ?? [240, 238, 232]).join(",")})` }}>Phụ đề</span></span></label>
              <label className={`${lab} col-span-2`}>Logo<input value={t.logo_path ?? ""} onChange={(e) => edit(i, { logo_path: e.target.value })} placeholder="Đường dẫn tới file PNG (để trống nếu không dùng)" className="mono h-9 min-w-0 px-2.5 text-[12.5px] text-ink" /></label>
            </div>
            <label className="mt-3 flex items-center gap-2 text-[13px]"><input type="checkbox" checked={t.auto_accept} onChange={(e) => edit(i, { auto_accept: e.target.checked })} />Tự duyệt clip</label>
            <label className={`${lab} mt-3`}>Cách đọc riêng, mỗi dòng một cặp viết=đọc
              <textarea rows={2} defaultValue={Object.entries(t.pronounce ?? {}).map(([k, v]) => `${k}=${v}`).join("\n")} placeholder="NEXORA=nếch xô ra"
                        onBlur={(e) => edit(i, { pronounce: Object.fromEntries(e.target.value.split("\n").map((l) => l.split("=")).filter((x) => x.length === 2).map(([k, v]) => [k, v])) })} className="mono p-2 text-[12.5px] text-ink" /></label>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function StoreCards() {
  const { data, reload } = usePoll<Storage>("/api/v1/storage", 20000);
  const [note, setNote] = useState<string | null>(null);
  const cleanable = (data?.stores ?? []).filter((s) => s.cleanable && s.bytes > 0);
  const total = (data?.stores ?? []).reduce((sum, s) => sum + s.bytes, 0) || 1;
  const clean = async () => { const r = await post<{ freed_bytes: number }>("/api/v1/storage/clean", { keys: cleanable.map((s) => s.key) }); setNote(`Đã dọn ${megabytes(r.freed_bytes)}.`); reload(); };
  const backup = async () => { const r = await post<{ name: string }>("/api/v1/storage/backup"); setNote(`Đã sao lưu: ${r.name}`); reload(); };
  return (
    <>
      <Card title="Dữ liệu hệ thống đang giữ" icon="disk" note="Chỉ xoá những thứ hệ thống tự làm lại được khi cần. Footage, mô tả và bản dựng của dự án không bị đụng tới."
            actions={<Button disabled={cleanable.length === 0} onClick={clean}>Dọn dữ liệu tạm</Button>}>
        <ul className={listCls}>
          {(data?.stores ?? []).map((s) => <li key={s.key} className="grid gap-1.5 px-3.5 py-2.5 text-[13px]"><div className="flex justify-between gap-4"><span>{s.label}{!s.cleanable && <span className="ml-2 text-[11.5px] text-faint">giữ lại</span>}</span><span className="mono text-mute">{megabytes(s.bytes)}</span></div><Meter share={s.bytes / total} tone={s.cleanable ? "ai" : "accent"} /></li>)}
        </ul>
        {note && <p role="status" className="mt-3 text-[13px] text-proof">{note}</p>}
      </Card>
      <Card title="Sao lưu" icon="refresh" note={<>Cơ sở dữ liệu được sao lưu mỗi lần khởi động. Khôi phục bằng lệnh <span className="mono text-ink">python -m nexora restore</span> khi server đã dừng.</>}
            actions={<Button kind="primary" onClick={backup}>Sao lưu ngay</Button>}>
        {data && data.backups.length === 0 ? <p className="text-[13px] text-mute">Chưa có bản sao lưu nào.</p> : (
          <ul className={listCls}>
            {(data?.backups ?? []).slice(0, 5).map((b) => <li key={b.name} className={rowCls}><span className="mono text-[12.5px]">{b.name}</span><span className="mono text-[12px] text-mute">{new Date(b.created_at * 1000).toLocaleString("vi-VN")} · {megabytes(b.size)}</span></li>)}
          </ul>
        )}
      </Card>
    </>
  );
}

function Volumes() {
  const { data, reload } = usePoll<Storage>("/api/v1/storage", 20000);
  const [note, setNote] = useState<string | null>(null);
  const [mounts, setMounts] = useState<Record<string, string>>({});
  const relink = async (id: string) => { try { await post(`/api/v1/volumes/${id}/relink`, { mount: mounts[id] }); setNote("Đã trỏ lại vị trí footage."); } catch (e) { setNote((e as Error).message); } reload(); };
  return (
    <Card title="Nơi chứa footage" icon="disk" note="Footage không bị sao chép; hệ thống nhớ nó nằm ở ổ và thư mục nào. Nếu ổ đổi chỗ, trỏ lại ở đây.">
      <ul className="grid gap-2">
        {(data?.volumes ?? []).map((v) => (
          <li key={v.volume_id} className={`rounded-xl border px-3.5 py-3 ${v.online ? "border-line" : "border-cue/40 bg-cue/[0.04]"}`}>
            <div className="flex items-center justify-between gap-4 text-[13px]"><span className="flex min-w-0 items-center gap-2"><Icon name="folder" size={15} className={v.online ? "text-accent" : "text-cue"} /><span className="mono min-w-0 break-all text-[12.5px]">{v.mount_path}</span></span>
              {v.online ? <Tag tone="proof">{v.files} file</Tag> : <Tag tone="cue">Không tìm thấy</Tag>}</div>
            {!v.online && (
              <form className="mt-2.5 flex gap-2" onSubmit={(e) => { e.preventDefault(); relink(v.volume_id); }}>
                <label htmlFor={`m-${v.volume_id}`} className="sr-only">Vị trí mới của thư mục này</label>
                <input id={`m-${v.volume_id}`} value={mounts[v.volume_id] ?? ""} onChange={(e) => setMounts({ ...mounts, [v.volume_id]: e.target.value })} placeholder="Vị trí mới của thư mục này" className="mono min-w-0 flex-1 px-3 text-[12.5px]" />
                <Button disabled={!(mounts[v.volume_id] ?? "").trim()} onClick={() => relink(v.volume_id)}>Trỏ lại</Button>
              </form>
            )}
          </li>
        ))}
      </ul>
      {note && <p role="status" className="mt-3 text-[13px]">{note}</p>}
    </Card>
  );
}

function Tools() {
  const { data: env } = usePoll<Env>("/api/v1/environment", 15000);
  const missing = Object.entries(env?.ffmpeg?.filters ?? {}).filter(([, ok]) => !ok).map(([name]) => name);
  const used = env ? 1 - env.disk.free_bytes / env.disk.total_bytes : 0;
  return (
    <Card title="Công cụ trên máy này" icon="scissors" tone="ai" note={env && missing.length === 0 ? "FFmpeg có đủ các bộ lọc hệ thống cần." : undefined}>
      {missing.length > 0 && (
        <div className="mb-4 rounded-xl border border-cue/30 bg-cue/[0.04] p-3.5 text-[13px]">
          <p className="mb-2 text-cue">Bản FFmpeg đang cài thiếu {missing.length} bộ lọc. Các việc sau sẽ không làm được cho tới khi cài bản đầy đủ hơn:</p>
          <ul className="grid gap-1">{missing.map((m) => <li key={m} className="flex items-center gap-2"><span className="h-1 w-1 rounded-full bg-cue" />{NEEDS[m] ?? m} <span className="mono text-faint">{m}</span></li>)}</ul>
        </div>
      )}
      {env && <div className="mb-4"><div className="mb-1.5 flex justify-between text-[13px]"><span className="text-mute">Ổ đĩa</span><span className="mono">còn {megabytes(env.disk.free_bytes)} / {megabytes(env.disk.total_bytes)}</span></div><Meter share={used} tone={used > 0.9 ? "cue" : "ai"} /></div>}
      <ul className="grid gap-2 sm:grid-cols-2">
        {(env?.adapters ?? []).map((a) => (
          <li key={a.name} className="flex items-center justify-between gap-3 rounded-xl border border-line bg-raised/40 px-3.5 py-2.5 text-[13px]"><span className="font-medium">{a.name}</span>
            <span className={`rounded-md px-1.5 text-[11px] ${a.runs === "local" ? "bg-proof/12 text-proof" : "bg-ai/12 text-ai"}`}>{a.runs === "local" ? "trên máy" : "cloud"}</span></li>
        ))}
      </ul>
    </Card>
  );
}

type Area = "control" | "autonomy" | "ai" | "library" | "templates" | "storage" | "health" | "audit";
const AREAS: [Area, string, string][] = [["control", "Điều khiển", "power"], ["autonomy", "Mức tự chủ", "bolt"], ["ai", "Giọng & mô hình", "sparkles"], ["library", "Footage", "folder"], ["templates", "Mẫu định dạng", "layers"], ["storage", "Lưu trữ & sao lưu", "disk"], ["health", "Sức khoẻ máy", "shield"], ["audit", "Nhật ký thao tác", "list"]];

export default function System() {
  const { data: control, reload } = usePoll<Control>("/api/v1/control", 3000);
  const [area, setArea] = useState<Area>("control");
  const toggle = async () => { await call("/api/v1/control/kill-switch", { method: "POST", body: JSON.stringify({ on: !control?.kill_switch }) }); reload(); };
  const kill = !!control?.kill_switch;
  return (
    <Page eyebrow="Vận hành" title="Hệ thống" note="Điều khiển, cài đặt, dữ liệu và sức khoẻ của máy." wide
          actions={<><span className={`flex items-center gap-2 text-[13px] ${kill ? "text-tally" : "text-proof"}`}><span className={`h-2 w-2 rounded-full ${kill ? "bg-tally" : "bg-proof"}`} />{kill ? "Đang dừng khẩn cấp" : "Hoạt động bình thường"}</span><Button kind={kill ? "primary" : "danger"} onClick={toggle}><Icon name="power" size={15} />{kill ? "Cho chạy lại" : "Dừng khẩn cấp"}</Button></>}>
      <div className="grid items-start gap-6 lg:grid-cols-[220px_minmax(0,1fr)]">
        <nav className="flex gap-1 overflow-x-auto lg:sticky lg:top-0 lg:flex-col" aria-label="Mục cài đặt">
          {AREAS.map(([k, name, icon]) => (
            <button key={k} type="button" onClick={() => setArea(k)} aria-current={area === k ? "page" : undefined}
                    className={`flex h-9 shrink-0 items-center gap-2.5 whitespace-nowrap rounded-lg px-3 text-[13.5px] transition-colors ${area === k ? "bg-raised font-medium text-ink" : "text-mute hover:bg-raised/50 hover:text-ink"}`}>
              <Icon name={icon} size={16} className={area === k ? "text-accent" : ""} />{name}</button>
          ))}
        </nav>
        <div className="grid max-w-4xl gap-5">
          {area === "control" && (
            <>
              <Card title="Dừng khẩn cấp" icon="power" tone="tally" note="Khi bật, hệ thống không bắt đầu thêm bước nào tốn tiền hoặc tác động ra bên ngoài. Việc đang chạy dở vẫn được giữ nguyên trạng thái."
                    actions={<Button kind={kill ? "primary" : "danger"} onClick={toggle}>{kill ? "Cho chạy lại" : "Dừng khẩn cấp"}</Button>} />
              <Card title="Giờ phân tích footage" icon="clock" note="Xem và mô tả footage là việc nặng nhất của máy. Bạn có thể chỉ cho nó chạy trong một khung giờ, ví dụ ban đêm. Chọn clip và dựng video không bị ảnh hưởng.">
                <form className="flex flex-wrap items-center gap-2 text-[13px]" onSubmit={async (e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const a = String(f.get("from") ?? ""), b = String(f.get("to") ?? ""); await post("/api/v1/control/background-window", { window: a !== "" && b !== "" ? `${a}-${b}` : "" }).catch(() => {}); reload(); }}>
                  <label htmlFor="from">Từ</label><input id="from" name="from" type="number" min="0" max="23" defaultValue={control?.background_window.split("-")[0] ?? ""} key={`f${control?.background_window}`} className={hourCls} />
                  <label htmlFor="to">giờ đến</label><input id="to" name="to" type="number" min="0" max="23" defaultValue={control?.background_window.split("-")[1] ?? ""} key={`t${control?.background_window}`} className={hourCls} /><span>giờ</span>
                  <Button type="submit" size="sm">Lưu</Button>
                  <span className={`w-full text-[12.5px] ${control?.background_window && !control.background_running_now ? "text-cue" : "text-faint"}`}>{!control?.background_window ? "Đang cho chạy bất cứ lúc nào. Để trống cả hai ô để giữ như vậy." : control.background_running_now ? "Đang trong khung giờ, việc phân tích được chạy." : "Ngoài khung giờ, việc phân tích đang chờ."}</span>
                </form>
              </Card>
              <Card title="Thông báo trên máy Mac" icon="bell">
                <label className="flex cursor-pointer items-start gap-3 text-[13px]"><input type="checkbox" className="mt-0.5" checked={control?.desktop_notifications ?? false}
                  onChange={async (e) => { await call("/api/v1/control/desktop-notifications", { method: "POST", body: JSON.stringify({ on: e.target.checked }) }); reload(); }} />
                  <span>Báo ở góc màn hình khi có việc chờ bạn duyệt, bị dừng, thất bại, hoặc khi video dựng xong.<span className="block text-faint">Nhập và phân tích footage xong thì không báo.</span></span></label>
                <NoticePrefs />
              </Card>
            </>
          )}
          {area === "autonomy" && <AutonomyCard />}
          {area === "audit" && <AuditCard />}
          {area === "ai" && <><VoiceModels /><ModelRoutes /><Providers /></>}
          {area === "library" && <><WatchFolders /><Volumes /></>}
          {area === "templates" && <Templates />}
          {area === "storage" && <StoreCards />}
          {area === "health" && <><Health /><Capabilities /><Benchmark /><Tools /></>}
        </div>
      </div>
    </Page>
  );
}
