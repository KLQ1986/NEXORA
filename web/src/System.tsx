import { call, megabytes, usePoll, type Run } from "./api";
import { Button } from "./parts";

type Env = { ffmpeg?: { filters: Record<string, boolean>; encoders: Record<string, boolean> }; disk: { free_bytes: number; total_bytes: number };
             adapters: { name: string; runs: string; operations: string[] }[] };

const NEEDS: Record<string, string> = {
  zscale: "Chuyển video HDR về màu chuẩn", subtitles: "Gắn phụ đề bằng FFmpeg", drawtext: "Vẽ chữ bằng FFmpeg",
  blackdetect: "Tìm khung đen", loudnorm: "Chuẩn hoá âm lượng", tonemap: "Hạ dải sáng HDR", scale: "Đổi kích thước hình", fps: "Chuẩn hoá tốc độ khung hình",
};

export default function System() {
  const { data: env } = usePoll<Env>("/api/v1/environment", 15000);
  const { data: control, reload } = usePoll<{ kill_switch: boolean }>("/api/v1/control", 3000);
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
