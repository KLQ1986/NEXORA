import { useState } from "react";
import { call, megabytes, post, usePoll, type Run } from "./api";
import { Button, Page } from "./parts";

type Env = { ffmpeg?: { filters: Record<string, boolean>; encoders: Record<string, boolean> }; disk: { free_bytes: number; total_bytes: number };
             adapters: { name: string; runs: string; operations: string[] }[] };

const NEEDS: Record<string, string> = {
  zscale: "Chuyển video HDR về màu chuẩn", subtitles: "Gắn phụ đề bằng FFmpeg", drawtext: "Vẽ chữ bằng FFmpeg",
  blackdetect: "Tìm khung đen", loudnorm: "Chuẩn hoá âm lượng", tonemap: "Hạ dải sáng HDR", scale: "Đổi kích thước hình", fps: "Chuẩn hoá tốc độ khung hình",
};

type Storage = { stores: { key: string; label: string; bytes: number; files: number; cleanable: boolean }[]; backups: { name: string; size: number; created_at: number }[];
                 volumes: { volume_id: string; name: string; mount_path: string; online: boolean; files: number }[] };
type Check = { name: string; ok: boolean; detail: string; fix: string | null; optional: boolean };

function Health() {
  const { data } = usePoll<{ checks: Check[] }>("/api/v1/doctor", 30000);
  const bad = (data?.checks ?? []).filter((c) => !c.ok && !c.optional);
  return (
    <div>
      <h2 className="mb-2 text-[15px] font-semibold">Kiểm tra hệ thống</h2>
      {data && <p className={`mb-2 ${bad.length ? "text-cue" : "text-proof"}`}>{bad.length ? `Có ${bad.length} thứ cần xử lý trước khi làm video.` : "Mọi thứ hệ thống cần đều sẵn sàng."}</p>}
      <ul className="max-w-2xl divide-y divide-line border-y border-line">
        {(data?.checks ?? []).map((c) => (
          <li key={c.name} className="px-1 py-2"><div className="flex justify-between gap-4"><span className="font-medium">{c.name}</span><span className={`text-right ${c.ok ? "text-mute" : c.optional ? "text-mute" : "text-cue"}`}>{c.detail}</span></div>
            {c.fix && <p className="text-sm text-mute">{c.optional ? "Không bắt buộc. " : ""}{c.fix}</p>}</li>
        ))}
      </ul>
    </div>
  );
}

const KINDS: [string, string][] = [["waiting_review", "Có việc chờ duyệt"], ["blocked", "Một việc bị dừng"], ["failed", "Một việc thất bại"], ["succeeded", "Một việc xong"]];

function NoticePrefs() {
  const { data, reload } = usePoll<{ quiet_hours: string; notify_off: string[] }>("/api/v1/usage", 15000);
  if (!data) return null;
  const toggle = async (kind: string) => { const off = data.notify_off.includes(kind) ? data.notify_off.filter((k) => k !== kind) : [...data.notify_off, kind]; await post("/api/v1/control/settings", { notify_off: off }); reload(); };
  return (
    <div className="ml-6 mt-3 grid max-w-xl gap-3">
      <div className="flex flex-wrap gap-x-5 gap-y-1">{KINDS.map(([kind, name]) => <label key={kind} className="flex items-center gap-2"><input type="checkbox" checked={!data.notify_off.includes(kind)} onChange={() => toggle(kind)} />{name}</label>)}</div>
      <form className="flex flex-wrap items-center gap-2" onSubmit={async (e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const a = String(f.get("qf") ?? ""), b = String(f.get("qt") ?? ""); await post("/api/v1/control/settings", { quiet_hours: a !== "" && b !== "" ? `${a}-${b}` : "" }).catch(() => {}); reload(); }}>
        <label htmlFor="qf">Không báo từ</label><input id="qf" name="qf" type="number" min="0" max="23" defaultValue={data.quiet_hours.split("-")[0] ?? ""} key={`a${data.quiet_hours}`} className="tc w-16 rounded border border-line bg-canvas px-2 py-1.5" />
        <label htmlFor="qt">giờ đến</label><input id="qt" name="qt" type="number" min="0" max="23" defaultValue={data.quiet_hours.split("-")[1] ?? ""} key={`b${data.quiet_hours}`} className="tc w-16 rounded border border-line bg-canvas px-2 py-1.5" /><span>giờ</span>
        <button type="submit" className="rounded border border-line px-3 py-1.5 text-sm font-medium hover:border-mute">Lưu</button>
        <span className="text-mute">{data.quiet_hours ? "Trong giờ này thông báo chỉ nằm ở mục Thông báo." : "Để trống cả hai ô để báo bất cứ lúc nào."}</span>
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
    <div>
      <h2 className="mb-2 text-[15px] font-semibold">Việc máy này làm được</h2>
      <ul className="max-w-2xl divide-y divide-line border-y border-line">
        {(data?.pipelines ?? []).map((p) => <li key={p.pipeline} className="flex justify-between gap-4 px-1 py-2"><span>{WORK[p.pipeline] ?? p.pipeline}</span><span className={p.available ? "text-mute" : "text-cue"}>{p.available ? "Sẵn sàng" : `Thiếu ${p.missing.map((m) => NEED[m] ?? m).join(", ")}`}</span></li>)}
      </ul>
    </div>
  );
}

function StoragePanel() {
  const { data, reload } = usePoll<Storage>("/api/v1/storage", 20000);
  const [note, setNote] = useState<string | null>(null);
  const [mounts, setMounts] = useState<Record<string, string>>({});
  const cleanable = (data?.stores ?? []).filter((s) => s.cleanable && s.bytes > 0);
  const clean = async () => { const r = await post<{ freed_bytes: number }>("/api/v1/storage/clean", { keys: cleanable.map((s) => s.key) }); setNote(`Đã dọn ${megabytes(r.freed_bytes)}.`); reload(); };
  const backup = async () => { const r = await post<{ name: string }>("/api/v1/storage/backup"); setNote(`Đã sao lưu: ${r.name}`); reload(); };
  const relink = async (id: string) => { try { await post(`/api/v1/volumes/${id}/relink`, { mount: mounts[id] }); setNote("Đã trỏ lại vị trí footage."); } catch (e) { setNote((e as Error).message); } reload(); };
  return (
    <>
      <div>
        <h2 className="mb-2 text-[15px] font-semibold">Dữ liệu hệ thống đang giữ</h2>
        <ul className="max-w-2xl divide-y divide-line border-y border-line">
          {(data?.stores ?? []).map((s) => <li key={s.key} className="flex justify-between gap-4 px-1 py-2"><span>{s.label}{s.cleanable ? "" : " (giữ lại)"}</span><span className="tc text-mute">{megabytes(s.bytes)}</span></li>)}
        </ul>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button disabled={cleanable.length === 0} onClick={clean}>Dọn dữ liệu tạm</Button>
          <span className="max-w-md text-sm text-mute">Chỉ xoá những thứ hệ thống tự làm lại được khi cần. Footage, mô tả và bản dựng của dự án không bị đụng tới.</span>
        </div>
      </div>
      <div>
        <h2 className="mb-2 text-[15px] font-semibold">Sao lưu</h2>
        <p className="mb-2 max-w-xl text-mute">Cơ sở dữ liệu được sao lưu mỗi lần khởi động. Khôi phục bằng lệnh <span className="tc text-ink">python -m nexora restore</span> khi server đã dừng.</p>
        <ul className="max-w-2xl divide-y divide-line border-y border-line">
          {(data?.backups ?? []).slice(0, 5).map((b) => <li key={b.name} className="flex justify-between gap-4 px-1 py-2"><span className="tc">{b.name}</span><span className="tc text-mute">{new Date(b.created_at * 1000).toLocaleString("vi-VN")}, {megabytes(b.size)}</span></li>)}
        </ul>
        {data && data.backups.length === 0 && <p className="text-mute">Chưa có bản sao lưu nào.</p>}
        <div className="mt-3"><Button onClick={backup}>Sao lưu ngay</Button></div>
      </div>
      <div>
        <h2 className="mb-2 text-[15px] font-semibold">Nơi chứa footage</h2>
        <ul className="max-w-2xl divide-y divide-line border-y border-line">
          {(data?.volumes ?? []).map((v) => (
            <li key={v.volume_id} className="px-1 py-2">
              <div className="flex justify-between gap-4"><span className="min-w-0 break-all">{v.mount_path}</span><span className={`shrink-0 ${v.online ? "text-mute" : "text-cue"}`}>{v.online ? `${v.files} file` : "Không tìm thấy"}</span></div>
              {!v.online && (
                <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); relink(v.volume_id); }}>
                  <label htmlFor={`m-${v.volume_id}`} className="sr-only">Vị trí mới của thư mục này</label>
                  <input id={`m-${v.volume_id}`} value={mounts[v.volume_id] ?? ""} onChange={(e) => setMounts({ ...mounts, [v.volume_id]: e.target.value })} placeholder="Vị trí mới của thư mục này" className="min-w-0 flex-1 rounded border border-line bg-canvas px-3 py-1.5 placeholder:text-mute/70" />
                  <Button disabled={!(mounts[v.volume_id] ?? "").trim()} onClick={() => relink(v.volume_id)}>Trỏ lại</Button>
                </form>
              )}
            </li>
          ))}
        </ul>
      </div>
      {note && <p role="status">{note}</p>}
    </>
  );
}

export default function System() {
  const { data: env } = usePoll<Env>("/api/v1/environment", 15000);
  const { data: control, reload } = usePoll<{ kill_switch: boolean; desktop_notifications: boolean; background_window: string; background_running_now: boolean }>("/api/v1/control", 3000);
  const toggle = async () => { await call("/api/v1/control/kill-switch", { method: "POST", body: JSON.stringify({ on: !control?.kill_switch }) }); reload(); };
  const { data: runs } = usePoll<Run[]>("/api/v1/runs", 10000);
  const spent = (runs ?? []).reduce((sum, r) => sum + r.cost, 0);
  const missing = Object.entries(env?.ffmpeg?.filters ?? {}).filter(([, ok]) => !ok).map(([name]) => name);
  const used = env ? 1 - env.disk.free_bytes / env.disk.total_bytes : 0;
  return (
    <Page title="Hệ thống" note="Điều khiển, sức khoẻ của máy, dữ liệu và thông báo." wide
          actions={<><span className={`text-[13px] ${control?.kill_switch ? "text-cue" : "text-mute"}`}>{control?.kill_switch ? "Đang dừng khẩn cấp" : "Đang hoạt động bình thường"}</span><Button kind={control?.kill_switch ? "primary" : "danger"} onClick={toggle}>{control?.kill_switch ? "Cho chạy lại" : "Dừng khẩn cấp"}</Button></>}>
      <div className="cards columns-1 gap-5 xl:columns-2">
        <div>
          <h2 className="mb-2 text-[15px] font-semibold">Dừng khẩn cấp</h2>
          <p className="max-w-xl text-mute">Nút ở góc trên bên phải. Khi bật, hệ thống không bắt đầu thêm bước nào tốn tiền hoặc tác động ra bên ngoài. Việc đang chạy dở vẫn được giữ nguyên trạng thái.</p>
        </div>
        <div>
          <h2 className="mb-2 text-[15px] font-semibold">Giờ phân tích footage</h2>
          <p className="mb-3 max-w-xl text-mute">Xem và mô tả footage là việc nặng nhất của máy. Bạn có thể chỉ cho nó chạy trong một khung giờ, ví dụ ban đêm. Chọn clip và dựng video không bị ảnh hưởng.</p>
          <form className="flex flex-wrap items-center gap-2" onSubmit={async (e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const a = String(f.get("from") ?? ""), b = String(f.get("to") ?? ""); await post("/api/v1/control/background-window", { window: a !== "" && b !== "" ? `${a}-${b}` : "" }).catch(() => {}); reload(); }}>
            <label htmlFor="from">Từ</label><input id="from" name="from" type="number" min="0" max="23" defaultValue={control?.background_window.split("-")[0] ?? ""} key={`f${control?.background_window}`} className="tc w-16 rounded border border-line bg-canvas px-2 py-1.5" />
            <label htmlFor="to">giờ đến</label><input id="to" name="to" type="number" min="0" max="23" defaultValue={control?.background_window.split("-")[1] ?? ""} key={`t${control?.background_window}`} className="tc w-16 rounded border border-line bg-canvas px-2 py-1.5" /><span>giờ</span>
            <button type="submit" className="rounded border border-line px-3 py-1.5 text-sm font-medium hover:border-mute">Lưu</button>
            <span className={control?.background_window && !control.background_running_now ? "text-cue" : "text-mute"}>{!control?.background_window ? "Đang cho chạy bất cứ lúc nào. Để trống cả hai ô để giữ như vậy." : control.background_running_now ? "Đang trong khung giờ, việc phân tích được chạy." : "Ngoài khung giờ, việc phân tích đang chờ."}</span>
          </form>
        </div>
        <Health />
        <StoragePanel />
        <Capabilities />
        <div>
          <h2 className="mb-2 text-[15px] font-semibold">Thông báo trên máy Mac</h2>
          <label className="flex max-w-xl items-start gap-2"><input type="checkbox" className="mt-1" checked={control?.desktop_notifications ?? false}
            onChange={async (e) => { await call("/api/v1/control/desktop-notifications", { method: "POST", body: JSON.stringify({ on: e.target.checked }) }); reload(); }} />
            <span>Báo ở góc màn hình khi có việc chờ bạn duyệt, bị dừng, thất bại, hoặc khi video dựng xong.<span className="block text-mute">Nhập và phân tích footage xong thì không báo.</span></span></label>
          <NoticePrefs />
        </div>
        <div>
          <h2 className="mb-2 text-[15px] font-semibold">Công cụ trên máy này</h2>
          {env && missing.length === 0 && <p className="text-mute">FFmpeg có đủ các bộ lọc hệ thống cần.</p>}
          {missing.length > 0 && (
            <>
              <p className="mb-2 max-w-xl text-cue">Bản FFmpeg đang cài thiếu {missing.length} bộ lọc. Các việc sau sẽ không làm được cho tới khi cài bản đầy đủ hơn:</p>
              <ul className="list-disc pl-5">{missing.map((m) => <li key={m}>{NEEDS[m] ?? m} <span className="text-mute">({m})</span></li>)}</ul>
            </>
          )}
          <ul className="mt-4 divide-y divide-line border-y border-line">
            {(env?.adapters ?? []).map((a) => (
              <li key={a.name} className="flex justify-between gap-4 px-1 py-2"><span className="font-medium">{a.name}</span><span className="text-mute">{a.runs === "local" ? "Chạy trên máy này" : "Chạy trên cloud"}</span></li>
            ))}
          </ul>
        </div>
      </div>
    </Page>
  );
}
