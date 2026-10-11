import { useState } from "react";
import { call, megabytes, post, usePoll, type Run } from "./api";
import { Button } from "./parts";

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
      <h2 className="mb-2 text-base font-semibold">Kiểm tra hệ thống</h2>
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
        <h2 className="mb-2 text-base font-semibold">Dữ liệu hệ thống đang giữ</h2>
        <ul className="max-w-2xl divide-y divide-line border-y border-line">
          {(data?.stores ?? []).map((s) => <li key={s.key} className="flex justify-between gap-4 px-1 py-2"><span>{s.label}{s.cleanable ? "" : " (giữ lại)"}</span><span className="tc text-mute">{megabytes(s.bytes)}</span></li>)}
        </ul>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Button disabled={cleanable.length === 0} onClick={clean}>Dọn dữ liệu tạm</Button>
          <span className="max-w-md text-sm text-mute">Chỉ xoá những thứ hệ thống tự làm lại được khi cần. Footage, mô tả và bản dựng của dự án không bị đụng tới.</span>
        </div>
      </div>
      <div>
        <h2 className="mb-2 text-base font-semibold">Sao lưu</h2>
        <p className="mb-2 max-w-xl text-mute">Cơ sở dữ liệu được sao lưu mỗi lần khởi động. Khôi phục bằng lệnh <span className="tc text-ink">python -m nexora restore</span> khi server đã dừng.</p>
        <ul className="max-w-2xl divide-y divide-line border-y border-line">
          {(data?.backups ?? []).slice(0, 5).map((b) => <li key={b.name} className="flex justify-between gap-4 px-1 py-2"><span className="tc">{b.name}</span><span className="tc text-mute">{new Date(b.created_at * 1000).toLocaleString("vi-VN")}, {megabytes(b.size)}</span></li>)}
        </ul>
        {data && data.backups.length === 0 && <p className="text-mute">Chưa có bản sao lưu nào.</p>}
        <div className="mt-3"><Button onClick={backup}>Sao lưu ngay</Button></div>
      </div>
      <div>
        <h2 className="mb-2 text-base font-semibold">Nơi chứa footage</h2>
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
      {note && <p className="text-proof">{note}</p>}
    </>
  );
}

export default function System() {
  const { data: env } = usePoll<Env>("/api/v1/environment", 15000);
  const { data: control, reload } = usePoll<{ kill_switch: boolean; desktop_notifications: boolean }>("/api/v1/control", 3000);
  const toggle = async () => { await call("/api/v1/control/kill-switch", { method: "POST", body: JSON.stringify({ on: !control?.kill_switch }) }); reload(); };
  const { data: runs } = usePoll<Run[]>("/api/v1/runs", 10000);
  const spent = (runs ?? []).reduce((sum, r) => sum + r.cost, 0);
  const missing = Object.entries(env?.ffmpeg?.filters ?? {}).filter(([, ok]) => !ok).map(([name]) => name);
  const used = env ? 1 - env.disk.free_bytes / env.disk.total_bytes : 0;
  return (
    <section className="flex-1 overflow-y-auto p-6">
      <h1 className="mb-6 text-2xl font-semibold tracking-tight">Hệ thống</h1>
      <div className="grid max-w-3xl gap-8">
        <div>
          <h2 className="mb-2 text-base font-semibold">Dừng khẩn cấp</h2>
          <p className="mb-3 max-w-xl text-mute">Khi bật, hệ thống không bắt đầu thêm bước nào tốn tiền hoặc tác động ra bên ngoài. Việc đang chạy dở vẫn được giữ nguyên trạng thái.</p>
          <div className="flex items-center gap-4">
            <Button kind={control?.kill_switch ? "primary" : "danger"} onClick={toggle}>{control?.kill_switch ? "Cho chạy lại" : "Dừng khẩn cấp"}</Button>
            <span className={control?.kill_switch ? "text-cue" : "text-mute"}>{control?.kill_switch ? "Đang dừng" : "Đang hoạt động bình thường"}</span>
          </div>
        </div>
        <Health />
        <StoragePanel />
        <div>
          <h2 className="mb-2 text-base font-semibold">Thông báo trên máy Mac</h2>
          <label className="flex max-w-xl items-start gap-2"><input type="checkbox" className="mt-1" checked={control?.desktop_notifications ?? false}
            onChange={async (e) => { await call("/api/v1/control/desktop-notifications", { method: "POST", body: JSON.stringify({ on: e.target.checked }) }); reload(); }} />
            <span>Báo ở góc màn hình khi có việc chờ bạn duyệt, bị dừng, thất bại, hoặc khi video dựng xong.<span className="block text-mute">Nhập và phân tích footage xong thì không báo.</span></span></label>
        </div>
        <div>
          <h2 className="mb-2 text-base font-semibold">Chi phí mô hình</h2>
          <p className="tc">{spent.toFixed(2)} USD cho {(runs ?? []).length} lần chạy</p>
          <p className="max-w-xl text-mute">Mô hình đang chạy trên máy này nên không phát sinh phí. Nếu sau này dùng mô hình trên cloud, chi phí từng lần chạy sẽ cộng vào đây và bị chặn theo ngân sách.</p>
        </div>
        <div>
          <h2 className="mb-2 text-base font-semibold">Ổ đĩa</h2>
          {env && <>
            <div className="h-2 max-w-xl overflow-hidden rounded-sm bg-raised"><div className={`h-full ${used > 0.9 ? "bg-cue" : "bg-ink/80"}`} style={{ width: `${used * 100}%` }} /></div>
            <p className="tc mt-1 text-mute">Còn trống {megabytes(env.disk.free_bytes)} trên tổng {megabytes(env.disk.total_bytes)}</p>
          </>}
        </div>
        <div>
          <h2 className="mb-2 text-base font-semibold">Công cụ trên máy này</h2>
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
    </section>
  );
}
