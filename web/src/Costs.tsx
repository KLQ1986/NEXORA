import { t as tr, tv } from "./i18n";
import { useState } from "react";
import { post, usePoll } from "./api";
import { Button, Icon, Meter, Page, Section, Seg, Stat } from "./parts";

type Tool = { adapter: string; operation: string; runs: string; calls: number; seconds: number; failures: number; cost: number };
type Usage = { budget_day: number | null; budget_month: number | null; spent_today: number; spent_month: number; spent_total: number;
  by_day: { day: string; cost: number }[]; projects: { project_id: string; title: string; spent: number; budget_cap: number | null }[]; tools_today: Tool[]; tools_all: Tool[] };

const TOOLS: Record<string, string> = { model: tr("Mô hình"), ffmpeg: "FFmpeg", ffprobe: "FFprobe", voice: tr("Giọng đọc"), graphics: tr("Phụ đề"), stock: "Kho stock", desktop: tr("Thông báo"), image_gen: tr("Sinh ảnh"), video_gen: "Sinh video" };
const TOOL_ICON: Record<string, string> = { model: "sparkles", ffmpeg: "scissors", ffprobe: "eye", voice: "mic", graphics: "captions", stock: "globe", desktop: "bell", image_gen: "image", video_gen: "film" };
const OPS: Record<string, string> = { describe: tr("xem khung hình"), chat: tr("viết và suy luận"), embed: tr("lập chỉ mục chữ"), proxy: tr("tạo bản xem"), segment: tr("dựng cảnh"), concat: tr("ghép video"), frames: tr("tách khung hình"),
  thumbnail: tr("ảnh đại diện"), blackdetect: tr("tìm khung đen"), freezedetect: tr("tìm hình đứng yên"), loudness: tr("đo âm lượng"), envelope: tr("so tiếng hai máy quay"), probe: tr("đọc thông số"), duration: tr("đo độ dài"),
  speak: tr("đọc lời dẫn"), caption: tr("vẽ phụ đề"), search: tr("tìm clip"), notify: tr("báo trên màn hình"), generate: tr("sinh hình") };
const long = (s: number) => (s >= 3600 ? tv`${(s / 3600).toFixed(1)} giờ` : s >= 60 ? tv`${Math.round(s / 60)} phút` : tv`${s.toFixed(1)} giây`);

function Budget({ label, spent, cap }: { label: string; spent: number; cap: number | null }) {
  const share = cap ? Math.min(1, spent / cap) : 0;
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between gap-4"><span className="text-[13px] text-mute">{label}</span>
        <span className="mono text-[13px]"><span className="text-[17px] font-semibold">{spent.toFixed(2)}</span><span className="text-mute"> / {cap != null ? `${cap.toFixed(2)} USD` : tr("không giới hạn")}</span></span></div>
      {cap != null ? <Meter share={Math.max(share, spent > 0 ? 0.01 : 0)} tone={share >= 1 ? "cue" : "accent"} /> : <div className="h-1.5 rounded-full border border-dashed border-line" />}
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
  if (!u) return <Page title={tr("Chi phí")}><p className="text-mute">{tr("Đang mở…")}</p></Page>;
  const save = async () => { setNote(null); try { await post("/api/v1/control/settings", { budget_day: day ?? u.budget_day ?? "", budget_month: month ?? u.budget_month ?? "" }); setDay(null); setMonth(null); } catch (e) { setNote((e as Error).message); } reload(); };
  const tools = all ? u.tools_all : u.tools_today;
  const total = tools.reduce((sum, t) => sum + t.seconds, 0) || 1;
  const calls = tools.reduce((sum, t) => sum + t.calls, 0);
  const fails = tools.reduce((sum, t) => sum + t.failures, 0);
  const peak = Math.max(...u.by_day.map((d) => d.cost), 0.01);
  return (
    <Page eyebrow={tr("Vận hành")} title={tr("Chi phí")} note={tr("Tiền so với ngân sách, và thời gian máy đã dùng cho từng việc.")}>
      <div className="grid gap-8">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Stat label={tr("Hôm nay")} icon="coins" value={<>{u.spent_today.toFixed(2)}<span className="ml-1 text-[13px] font-medium text-mute">USD</span></>} sub={u.budget_day != null ? tv`Ngân sách ${u.budget_day.toFixed(2)} USD` : tr("Chưa đặt ngân sách")} />
          <Stat label={tr("Tháng này")} icon="gauge" value={<>{u.spent_month.toFixed(2)}<span className="ml-1 text-[13px] font-medium text-mute">USD</span></>} sub={u.budget_month != null ? tv`Ngân sách ${u.budget_month.toFixed(2)} USD` : tr("Chưa đặt ngân sách")} />
          <Stat label={tr("Từ trước tới nay")} icon="layers" tone="proof" value={<>{u.spent_total.toFixed(2)}<span className="ml-1 text-[13px] font-medium text-mute">USD</span></>} sub={tr("Chỉ dịch vụ trả tiền")} />
          <Stat label={tr("Thời gian máy")} icon="cpu" tone="ai" value={long(tools.reduce((s, t) => s + t.seconds, 0))} sub={tv`${calls} lần gọi${fails ? tv`, ${fails} lỗi` : ""} · ${all ? tr("từ trước tới nay") : tr("hôm nay")}`} />
        </div>

        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Section title={tr("Ngân sách")} icon="coins" note={tr("Mô hình và công cụ chạy trên máy này không tốn tiền. Chỉ việc gọi dịch vụ trả tiền, như sinh ảnh và video, mới tính vào đây. Hết ngân sách thì việc trả tiền dừng lại chờ bạn; việc trên máy vẫn chạy.")}>
            <div className="panel p-5">
              <div className="grid gap-5"><Budget label={tr("Hôm nay")} spent={u.spent_today} cap={u.budget_day} /><Budget label={tr("Tháng này")} spent={u.spent_month} cap={u.budget_month} /></div>
              <form className="mt-5 flex flex-wrap items-end gap-3 border-t border-line pt-5" onSubmit={(e) => { e.preventDefault(); save(); }}>
                <div><label htmlFor="bd" className="field-label">{tr("Mỗi ngày (USD)")}</label><input id="bd" type="number" inputMode="decimal" min="0" step="0.5" value={day ?? u.budget_day ?? ""} onChange={(e) => setDay(e.target.value)} placeholder={tr("Không giới hạn")} className="mono w-40 px-3" /></div>
                <div><label htmlFor="bm" className="field-label">{tr("Mỗi tháng (USD)")}</label><input id="bm" type="number" inputMode="decimal" min="0" step="1" value={month ?? u.budget_month ?? ""} onChange={(e) => setMonth(e.target.value)} placeholder={tr("Không giới hạn")} className="mono w-40 px-3" /></div>
                <Button kind="primary" disabled={day === null && month === null} onClick={save}>{tr("Lưu ngân sách")}</Button>
                {note && <p className="w-full text-tally">{note}</p>}
              </form>
            </div>
          </Section>
          <Section title={tr("Chi theo ngày")} icon="gauge" note={tr("14 ngày gần đây.")}>
            <div className="panel p-5">
              {u.by_day.length > 0 ? (
                <>
                  <div className="flex h-40 items-end gap-1.5" role="img" aria-label={tr("Chi phí theo ngày")}>
                    {u.by_day.map((d) => <div key={d.day} className="group relative flex-1 rounded-t-md bg-accent/80 transition-[filter] hover:brightness-125" style={{ height: `${Math.max(3, (d.cost / peak) * 100)}%` }}>
                      <span className="mono pointer-events-none absolute -top-6 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-overlay px-1.5 text-[10.5px] group-hover:block">{d.cost.toFixed(2)}</span></div>)}
                  </div>
                  <div className="mono mt-2 flex justify-between text-[10.5px] text-faint"><span>{u.by_day[0].day}</span><span>{u.by_day[u.by_day.length - 1].day}</span></div>
                </>
              ) : <p className="grid h-40 place-items-center text-[13px] text-mute">{tr("Chưa có khoản chi nào.")}</p>}
              {u.projects.length > 0 && (
                <ul className="rows mt-5 border-t border-line pt-1">
                  {u.projects.map((p) => <li key={p.project_id} className="flex justify-between gap-4 py-2 text-[13px]"><span className="min-w-0 truncate">{p.title}</span><span className="mono shrink-0 text-mute">{p.spent.toFixed(2)} USD{p.budget_cap != null ? ` / ${p.budget_cap.toFixed(2)}` : ""}</span></li>)}
                </ul>
              )}
            </div>
          </Section>
        </div>

        <Section title={tr("Thời gian máy")} icon="cpu" actions={<Seg label={tr("Khoảng thời gian")} value={all} onChange={setAll} items={[[false, tr("Hôm nay")], [true, tr("Từ trước tới nay")]] as const} />}>
          {tools.length === 0 ? <p className="panel px-4 py-5 text-mute">{tr("Chưa có công cụ nào được gọi trong khoảng này.")}</p> : (
            <div className="panel overflow-x-auto"><table className="w-full min-w-[620px] text-left text-[13px]">
              <thead className="eyebrow"><tr className="[&>th]:px-4 [&>th]:py-3"><th>{tr("Việc")}</th><th>{tr("Số lần")}</th><th>{tr("Tổng thời gian")}</th><th className="w-1/3">{tr("Phần trong tổng")}</th><th className="text-right">{tr("Lỗi")}</th></tr></thead>
              <tbody className="divide-y divide-line border-t border-line">
                {tools.map((t) => (
                  <tr key={`${t.adapter}.${t.operation}`} className="[&>td]:px-4 [&>td]:py-2.5">
                    <td><span className="flex items-center gap-2.5"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-raised text-mute"><Icon name={TOOL_ICON[t.adapter] ?? "cpu"} size={14} /></span><span>{TOOLS[t.adapter] ?? t.adapter}: {OPS[t.operation] ?? t.operation}{t.runs === "cloud" && <span className="ml-1.5 rounded bg-ai/12 px-1.5 text-[11px] text-ai">cloud</span>}</span></span></td>
                    <td className="mono text-mute">{t.calls}</td><td className="mono">{long(t.seconds)}</td>
                    <td><Meter share={t.seconds / total} tone="ai" /></td>
                    <td className={`mono text-right ${t.failures ? "text-tally" : "text-faint"}`}>{t.failures}</td>
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
