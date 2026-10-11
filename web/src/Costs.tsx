import { useState } from "react";
import { post, usePoll } from "./api";
import { Button, Page, Section } from "./parts";

type Tool = { adapter: string; operation: string; runs: string; calls: number; seconds: number; failures: number; cost: number };
type Usage = { budget_day: number | null; budget_month: number | null; spent_today: number; spent_month: number; spent_total: number;
  by_day: { day: string; cost: number }[]; projects: { project_id: string; title: string; spent: number; budget_cap: number | null }[]; tools_today: Tool[]; tools_all: Tool[] };

const TOOLS: Record<string, string> = { model: "Mô hình", ffmpeg: "FFmpeg", ffprobe: "FFprobe", voice: "Giọng đọc", graphics: "Phụ đề", stock: "Kho stock", desktop: "Thông báo", image_gen: "Sinh ảnh", video_gen: "Sinh video" };
const OPS: Record<string, string> = { describe: "xem khung hình", chat: "viết và suy luận", embed: "lập chỉ mục chữ", proxy: "tạo bản xem", segment: "dựng cảnh", concat: "ghép video", frames: "tách khung hình",
  thumbnail: "ảnh đại diện", blackdetect: "tìm khung đen", freezedetect: "tìm hình đứng yên", loudness: "đo âm lượng", envelope: "so tiếng hai máy quay", probe: "đọc thông số", duration: "đo độ dài",
  speak: "đọc lời dẫn", caption: "vẽ phụ đề", search: "tìm clip", notify: "báo trên màn hình", generate: "sinh hình" };
const long = (s: number) => (s >= 3600 ? `${(s / 3600).toFixed(1)} giờ` : s >= 60 ? `${Math.round(s / 60)} phút` : `${s.toFixed(1)} giây`);

function Meter({ label, spent, cap }: { label: string; spent: number; cap: number | null }) {
  const share = cap ? Math.min(1, spent / cap) : 0;
  return (
    <div>
      <div className="flex justify-between gap-4"><span>{label}</span><span className="tc text-mute">{spent.toFixed(2)} USD{cap != null ? ` trên ${cap.toFixed(2)} USD` : ", chưa đặt giới hạn"}</span></div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-raised">{cap != null && <div className={`h-full ${share >= 1 ? "bg-cue" : "bg-ink/70"}`} style={{ width: `${Math.max(share * 100, spent > 0 ? 1 : 0)}%` }} />}</div>
    </div>
  );
}

/** Money against budgets, and time: what every tool and model on this machine has been asked to do. */
export default function Costs() {
  const { data: u, reload } = usePoll<Usage>("/api/v1/usage", 6000);
  const [day, setDay] = useState<string | null>(null);
  const [month, setMonth] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  if (!u) return <Page title="Chi phí"><p className="text-mute">Đang mở</p></Page>;
  const save = async () => { setNote(null); try { await post("/api/v1/control/settings", { budget_day: day ?? u.budget_day ?? "", budget_month: month ?? u.budget_month ?? "" }); setDay(null); setMonth(null); } catch (e) { setNote((e as Error).message); } reload(); };
  const tools = all ? u.tools_all : u.tools_today;
  const total = tools.reduce((sum, t) => sum + t.seconds, 0) || 1;
  const peak = Math.max(...u.by_day.map((d) => d.cost), 0.01);
  return (
    <Page title="Chi phí" note="Tiền so với ngân sách, và thời gian máy đã dùng cho từng việc.">
      <div className="grid gap-10">
        <Section title="Tiền" note="Mô hình và công cụ chạy trên máy này không tốn tiền. Chỉ việc gọi dịch vụ trả tiền, như sinh ảnh và video, mới tính vào đây. Hết ngân sách thì việc trả tiền dừng lại chờ bạn; việc trên máy vẫn chạy.">
          <div className="panel max-w-3xl p-5"><div className="grid gap-5"><Meter label="Hôm nay" spent={u.spent_today} cap={u.budget_day} /><Meter label="Tháng này" spent={u.spent_month} cap={u.budget_month} /></div>
          <form className="mt-5 flex flex-wrap items-end gap-3 border-t border-line pt-5" onSubmit={(e) => { e.preventDefault(); save(); }}>
            <div><label htmlFor="bd" className="mb-1 block text-sm">Ngân sách mỗi ngày (USD)</label><input id="bd" type="number" min="0" step="0.5" value={day ?? u.budget_day ?? ""} onChange={(e) => setDay(e.target.value)} placeholder="Không giới hạn" className="tc w-40 rounded border border-line bg-canvas px-3 py-1.5 placeholder:text-mute/70" /></div>
            <div><label htmlFor="bm" className="mb-1 block text-sm">Ngân sách mỗi tháng (USD)</label><input id="bm" type="number" min="0" step="1" value={month ?? u.budget_month ?? ""} onChange={(e) => setMonth(e.target.value)} placeholder="Không giới hạn" className="tc w-40 rounded border border-line bg-canvas px-3 py-1.5 placeholder:text-mute/70" /></div>
            <Button disabled={day === null && month === null} onClick={save}>Lưu ngân sách</Button>
            {note && <p className="w-full text-tally">{note}</p>}
          </form></div>
          {u.by_day.length > 0 && (
            <div className="mt-6 max-w-2xl">
              <p className="mb-2 text-sm text-mute">Chi theo ngày, 14 ngày gần đây. Tổng từ trước tới nay {u.spent_total.toFixed(2)} USD.</p>
              <div className="flex h-24 items-end gap-1" role="img" aria-label="Chi phí theo ngày">
                {u.by_day.map((d) => <div key={d.day} className="flex-1 bg-ink/70" style={{ height: `${Math.max(3, (d.cost / peak) * 100)}%` }} title={`${d.day}: ${d.cost.toFixed(2)} USD`} />)}
              </div>
            </div>
          )}
          {u.projects.length > 0 && (
            <ul className="mt-6 max-w-2xl divide-y divide-line border-y border-line">
              {u.projects.map((p) => <li key={p.project_id} className="flex justify-between gap-4 px-1 py-2"><span className="min-w-0 truncate">{p.title}</span><span className="tc shrink-0 text-mute">{p.spent.toFixed(2)} USD{p.budget_cap != null ? ` trên ${p.budget_cap.toFixed(2)}` : ""}</span></li>)}
            </ul>
          )}
        </Section>

        <Section title="Thời gian máy" actions={
            <div className="flex rounded-md border border-line p-0.5" role="radiogroup" aria-label="Khoảng thời gian">
              {([[false, "Hôm nay"], [true, "Từ trước tới nay"]] as const).map(([v, name]) => <button key={name} type="button" role="radio" aria-checked={all === v} onClick={() => setAll(v)} className={`h-7 rounded px-2.5 text-[13px] ${all === v ? "bg-raised font-medium" : "text-mute hover:text-ink"}`}>{name}</button>)}
            </div>}>
          {tools.length === 0 ? <p className="panel px-4 py-5 text-mute">Chưa có công cụ nào được gọi trong khoảng này.</p> : (
            <div className="panel overflow-hidden"><table className="w-full text-left">
              <thead className="text-[13px] text-mute"><tr className="[&>th]:px-4"><th className="py-2.5 font-medium">Việc</th><th className="font-medium">Số lần</th><th className="font-medium">Tổng thời gian</th><th className="w-1/3 font-medium">Phần trong tổng</th><th className="text-right font-medium">Lỗi</th></tr></thead>
              <tbody className="divide-y divide-line border-t border-line">
                {tools.map((t) => (
                  <tr key={`${t.adapter}.${t.operation}`} className="[&>td]:px-4">
                    <td className="py-2.5">{TOOLS[t.adapter] ?? t.adapter}: {OPS[t.operation] ?? t.operation}{t.runs === "cloud" && <span className="text-mute">, ngoài máy</span>}</td>
                    <td className="tc">{t.calls}</td><td className="tc">{long(t.seconds)}</td>
                    <td><div className="h-1.5 overflow-hidden rounded-full bg-raised"><div className="h-full bg-ink/70" style={{ width: `${(t.seconds / total) * 100}%` }} /></div></td>
                    <td className={`tc text-right ${t.failures ? "text-tally" : "text-mute"}`}>{t.failures}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
        </Section>
      </div>
    </Page>
  );
}
