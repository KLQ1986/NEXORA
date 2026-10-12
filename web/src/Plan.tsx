import { t as tr, tv, locale } from "./i18n";
import { useMemo, useState } from "react";
import { call, post, timecode, usePoll, type Campaign, type Channel, type CalendarRow, type Publication, type Publishing, type Radar, type RadarSubject } from "./api";
import { Button, Empty, Icon, Page, Section, Tabs, Tag, ask, toast } from "./parts";

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const WEEKDAYS = ["Th 2", "Th 3", "Th 4", "Th 5", "Th 6", "Th 7", "CN"];
const open = (path: string) => { window.history.pushState(null, "", path); window.dispatchEvent(new PopStateEvent("popstate")); };

/** The month as a grid of weeks starting on Monday; days of the neighbouring months fill the first and last rows. */
function weeksOf(year: number, month: number): Date[][] {
  const first = new Date(year, month, 1);
  const start = new Date(year, month, 1 - ((first.getDay() + 6) % 7));
  const weeks: Date[][] = [];
  for (let d = new Date(start); weeks.length < 6; ) {
    const week: Date[] = [];
    for (let i = 0; i < 7; i++) { week.push(new Date(d)); d.setDate(d.getDate() + 1); }
    if (weeks.length >= 4 && week[0].getMonth() !== month) break;
    weeks.push(week);
  }
  return weeks;
}

function Calendar() {
  const { data, reload } = usePoll<{ projects: CalendarRow[]; today: string; channels: Channel[]; cadence: { channel: string; per_week: number; short: number; weeks: { from: string; planned: number; short: number }[] }[] }>("/api/v1/calendar", 15000);
  const saveChannels = (channels: Channel[]) => post("/api/v1/channels", { channels }).then(reload);
  const now = new Date();
  const [at, setAt] = useState({ y: now.getFullYear(), m: now.getMonth() });
  const weeks = useMemo(() => weeksOf(at.y, at.m), [at]);
  const byDay = new Map<string, CalendarRow[]>();
  for (const p of data?.projects ?? []) if (p.due_date) byDay.set(p.due_date, [...(byDay.get(p.due_date) ?? []), p]);
  const unplanned = (data?.projects ?? []).filter((p) => !p.due_date);
  const late = (data?.projects ?? []).filter((p) => p.due_date && data && p.due_date < data.today && !p.ready);
  const shift = (by: number) => setAt(({ y, m }) => { const d = new Date(y, m + by, 1); return { y: d.getFullYear(), m: d.getMonth() }; });
  const plan = (id: string, day: string) => post(`/api/v1/projects/${id}`, { due_date: day }, "PATCH").then(reload);
  return (
    <div className="grid items-start gap-8 xl:grid-cols-[minmax(0,1fr)_320px]">
      <div className="min-w-0">
        <div className="mb-3 flex items-center gap-2">
          <h2 className="text-[16px] font-semibold capitalize">{new Date(at.y, at.m, 1).toLocaleDateString(locale, { month: "long", year: "numeric" })}</h2>
          <span className="ml-auto flex gap-1.5">
            <Button size="sm" onClick={() => shift(-1)} title={tr("Tháng trước")}><Icon name="back" size={14} /></Button>
            <Button size="sm" onClick={() => setAt({ y: now.getFullYear(), m: now.getMonth() })}>{tr("Hôm nay")}</Button>
            <Button size="sm" onClick={() => shift(1)} title={tr("Tháng sau")}><Icon name="next" size={14} /></Button>
          </span>
        </div>
        {late.length > 0 && <p className="mb-3 flex items-center gap-2 rounded-xl border border-cue/40 bg-cue/10 px-4 py-2.5 text-[13px] text-cue"><Icon name="alert" size={15} />{tv`${late.length} video đã quá ngày dự định mà chưa có bản dựng được duyệt.`}</p>}
        <div className="panel overflow-x-auto">
          <div className="grid min-w-[680px] grid-cols-7 border-b border-line text-[12px] text-faint">{WEEKDAYS.map((d) => <div key={d} className="px-2.5 py-2">{d}</div>)}</div>
          {weeks.map((week, i) => (
            <div key={i} className="grid min-w-[680px] grid-cols-7 border-b border-line last:border-b-0">
              {week.map((d) => {
                const day = iso(d), items = byDay.get(day) ?? [], today = day === data?.today;
                return (
                  <div key={day} onDragOver={(e) => e.preventDefault()} onDrop={(e) => { const id = e.dataTransfer.getData("text/plain"); if (id) plan(id, day); }}
                       className={`min-h-[96px] border-r border-line p-1.5 last:border-r-0 ${d.getMonth() === at.m ? "" : "bg-raised/30 text-faint"}`}>
                    <div className={`mono mb-1 inline-grid h-6 min-w-6 place-items-center rounded-md px-1 text-[12px] ${today ? "bg-accent text-white" : ""}`}>{d.getDate()}</div>
                    <div className="grid gap-1">
                      {items.map((p) => (
                        <button key={p.project_id} type="button" draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", p.project_id)} onClick={() => open(`/du-an/${p.project_id}`)} title={`${p.title} — ${p.stage}`}
                                className={`truncate rounded-md border px-1.5 py-1 text-left text-[12px] leading-tight ${p.ready ? "border-proof/40 bg-proof/10" : day < (data?.today ?? "") ? "border-cue/40 bg-cue/10" : "border-line bg-raised"}`}>{p.title}</button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <p className="mt-2 text-[12px] text-faint">{tr("Kéo một video sang ngày khác để dời lịch. Viền xanh là video đã có bản dựng được duyệt; viền vàng là video đã quá ngày.")}</p>
      </div>
      <div className="grid gap-8">
      <Section title={tr("Kênh")} icon="user" note={tr("Mỗi kênh có nhịp đăng riêng. Lịch cho biết tuần nào còn thiếu video so với nhịp đó.")}>
        <ul className="panel rows empty:hidden">
          {(data?.channels ?? []).map((c) => { const gap = data!.cadence.find((x) => x.channel === c.name); return (
            <li key={c.name} className="px-3 py-2.5 text-[13px]"><div className="flex items-center gap-2"><span className="font-medium">{c.name}</span><span className="text-faint">{[c.platform, c.per_week ? tv`${c.per_week} video mỗi tuần` : "", c.audience].filter(Boolean).join(", ")}</span>
              <button type="button" className="link ml-auto" onClick={() => { const before = data!.channels; saveChannels(before.filter((x) => x.name !== c.name)); toast(tv`Đã bỏ kênh “${c.name}”.`, { undo: () => saveChannels(before) }); }}>{tr("Bỏ")}</button></div>
              {gap && <p className="mt-1 flex flex-wrap gap-1.5">{gap.weeks.map((w) => <span key={w.from} title={tv`Tuần từ ${w.from}`} className={`mono rounded-md border px-1.5 py-0.5 text-[11.5px] ${w.short ? "border-cue/40 bg-cue/10 text-cue" : "border-proof/40 bg-proof/10 text-proof"}`}>{w.from.slice(5)}: {w.short ? tv`thiếu ${w.short}` : tr("đủ")}</span>)}</p>}
            </li>); })}
        </ul>
        <form className="mt-2 grid gap-2 text-[13px]" onSubmit={(e) => { e.preventDefault(); const f = new FormData(e.currentTarget); const name = String(f.get("name") ?? "").trim(); if (!name || !data) return;
          saveChannels([...data.channels.filter((c) => c.name !== name), { name, platform: String(f.get("platform") ?? ""), audience: String(f.get("audience") ?? ""), per_week: Number(f.get("per_week") || 0), template: null }]); e.currentTarget.reset(); }}>
          <div className="flex gap-2"><input name="name" aria-label={tr("Tên kênh")} placeholder={tr("Tên kênh")} className="h-8 min-w-0 flex-1 px-2.5" /><input name="platform" aria-label={tr("Nền tảng")} placeholder={tr("Nền tảng")} className="h-8 w-28 px-2.5" /></div>
          <div className="flex items-center gap-2"><input name="audience" aria-label={tr("Người xem")} placeholder={tr("Người xem là ai")} className="h-8 min-w-0 flex-1 px-2.5" /><input name="per_week" type="number" inputMode="decimal" min="0" max="21" aria-label={tr("Số video mỗi tuần")} placeholder="0" className="mono h-8 w-16 px-2" /><span className="text-faint">{tr("mỗi tuần")}</span></div>
          <div><Button size="sm" type="submit">{tr("Thêm kênh")}</Button></div>
        </form>
      </Section>
      <Section title={tr("Chưa có ngày đăng")} icon="clock" note={tr("Kéo vào một ngày trên lịch, hoặc chọn ngày ở đây.")}>
        {data && unplanned.length === 0 && <p className="text-[13px] text-mute">{tr("Mọi dự án đều đã có ngày.")}</p>}
        <ul className="panel rows empty:hidden">
          {unplanned.map((p) => (
            <li key={p.project_id} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", p.project_id)} className="grid cursor-grab gap-1.5 px-3 py-2.5 text-[13px]">
              <button type="button" className="truncate text-left font-medium hover:text-accent" onClick={() => open(`/du-an/${p.project_id}`)}>{p.title}</button>
              <div className="flex items-center gap-2"><Tag tone={p.ready ? "proof" : "mute"}>{p.stage}</Tag>
                <input type="date" aria-label={tv`Ngày đăng của ${p.title}`} onChange={(e) => e.target.value && plan(p.project_id, e.target.value)} className="mono ml-auto h-8 px-2 text-[12px]" /></div>
            </li>
          ))}
        </ul>
      </Section>
      </div>
    </div>
  );
}

function SubjectRows({ rows, unusedOnly }: { rows: RadarSubject[]; unusedOnly: boolean }) {
  return (
    <ul className="panel rows">
      {rows.map((s) => (
        <li key={s.subject} className="px-4 py-3 text-[13px]">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1"><span className="font-medium capitalize">{s.subject}</span>
            <span className="mono text-faint">{unusedOnly ? tv`${s.unused_videos} video chưa dùng, ${timecode(s.unused_seconds)}` : `${s.videos} video, ${timecode(s.seconds)}`}</span>
            {!unusedOnly && <span className="ml-auto text-faint">{tv`${s.videos - s.unused_videos} đã dùng trong dự án`}</span>}</div>
          {unusedOnly && s.examples.length > 0 && <ul className="mt-1.5 grid gap-1 text-mute">{s.examples.map((e) => (
            <li key={e.asset_id} className="truncate"><button type="button" className="hover:text-accent" onClick={() => open(`/thu-vien?q=${encodeURIComponent(e.title || e.summary)}`)}>{e.title || tr("Video chưa có tên")}</button><span className="text-faint"> {e.summary}</span></li>))}</ul>}
        </li>
      ))}
    </ul>
  );
}

function RadarView() {
  const { data, reload } = usePoll<Radar>("/api/v1/radar", 30000);
  const [topic, setTopic] = useState("");
  const save = (topics: string[]) => post("/api/v1/radar/topics", { topics }).then(reload);
  const tone = (v: string) => (v === tr("đủ hình để làm") ? "proof" : v === tr("có ít hình") ? "cue" : "mute") as "proof" | "cue" | "mute";
  return (
    <div className="grid max-w-5xl gap-10">
      <Section title={tr("Chủ đề bạn đang theo dõi")} icon="radar" note={tr("Với mỗi chủ đề, hệ thống đo xem kho footage có bao nhiêu cảnh trả lời được nó. Số đo lấy từ chỉ mục của kho, không do mô hình phỏng đoán.")}>
        <form className="mb-3 flex max-w-xl gap-2" onSubmit={(e) => { e.preventDefault(); const t = topic.trim(); if (t && data) { save([...data.topics, t]); setTopic(""); } }}>
          <input value={topic} onChange={(e) => setTopic(e.target.value)} aria-label={tr("Chủ đề muốn theo dõi")} placeholder={tr("Ví dụ: món ăn đường phố buổi tối")} className="h-9 min-w-0 flex-1 px-3" />
          <Button type="submit" disabled={!topic.trim()}><Icon name="plus" size={14} />{tr("Theo dõi")}</Button>
        </form>
        {data && data.watched.length === 0 && <p className="text-[13px] text-mute">{tr("Chưa có chủ đề nào. Thêm một chủ đề bạn định làm để biết kho đã đủ hình hay cần quay thêm.")}</p>}
        <ul className="panel rows empty:hidden">
          {(data?.watched ?? []).map((w) => (
            <li key={w.topic} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-[13px]">
              <span className="min-w-0 font-medium">{w.topic}</span><Tag tone={tone(w.verdict)}>{w.verdict}</Tag>
              <span className="mono text-faint">{tv`${w.moments} cảnh khớp trong ${w.assets} video`}</span>
              <span className="ml-auto flex items-center gap-3">
                {w.moments > 0 && <button type="button" className="link" onClick={() => open(`/thu-vien?q=${encodeURIComponent(w.topic)}`)}>{tr("Xem các cảnh")}</button>}
                <button type="button" className="link" onClick={() => open(`/du-an?moi=1`)}>{tr("Làm video")}</button>
                <button type="button" className="text-faint hover:text-ink" aria-label={tv`Bỏ theo dõi ${w.topic}`} onClick={() => save(data!.topics.filter((t) => t !== w.topic))}><Icon name="x" size={14} /></button>
              </span>
            </li>
          ))}
        </ul>
      </Section>
      <Section title={tr("Footage chưa dùng vào video nào")} icon="film" note={tr("Xếp theo thời lượng còn nằm yên trong kho. Đây là chỗ dễ làm video mới nhất vì hình đã có sẵn.")}>
        {data && data.unused.length === 0 && <Empty icon="film" title={tr("Không có footage nào nằm yên")}>{tr("Mọi video đã được mô tả trong kho đều đang được một dự án dùng, hoặc kho chưa có video nào được mô tả.")}</Empty>}
        {!!data?.unused.length && <SubjectRows rows={data.unused} unusedOnly />}
      </Section>
      {!!data?.subjects.length && <Section title={tr("Kho đang có gì")} icon="layers" note={tr("Mọi chủ đề hệ thống nhận ra trong kho, xếp theo thời lượng.")}><SubjectRows rows={data.subjects} unusedOnly={false} /></Section>}
      <p className="text-[12px] text-faint">{tr("Radar này chỉ nhìn vào kho của bạn. Xu hướng trên các nền tảng và số liệu video đã đăng chưa được nối vào vì hệ thống chưa có tài khoản nền tảng nào.")}</p>
    </div>
  );
}

const FIGURE: [string, string][] = [["views", tr("Lượt xem")], ["likes", tr("Thích")], ["comments", tr("Bình luận")], ["shares", tr("Chia sẻ")], ["watch_seconds", tr("Giây xem")]];
type Forecast = { ready: boolean; reason?: string; week?: number; low?: number; high?: number; based_on?: number; from_hours?: number };

/** One published video: its figures at each mark, a place to add the next ones, and where it may stand after a week. */
function PublicationRow({ p, target, due, picked, pick, reload }: { p: Publication; target: string; due: number | null; picked: boolean; pick: () => void; reload: () => void }) {
  const [open, setOpen] = useState(due !== null);
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const last = p.snapshots[p.snapshots.length - 1];
  const age = p.published_at ? (Date.now() / 1000 - p.published_at) / 3600 : 0;
  return (
    <li className="px-4 py-3 text-[13px]">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <input type="checkbox" aria-label={tv`Chọn ${p.title} để so sánh`} checked={picked} onChange={pick} />
        <button type="button" className="min-w-0 truncate text-left font-medium hover:text-accent" onClick={() => open_(`/du-an/${p.project_id}`)}>{p.title}</button>
        <span className="text-faint">{target}{p.variant ? tv`, biến thể ${p.variant}` : ""}</span>
        <span className="mono text-faint">{age < 48 ? tv`${age.toFixed(0)} giờ trước` : tv`${(age / 24).toFixed(0)} ngày trước`}</span>
        {due !== null && <Tag tone="cue">{tv`Tới mốc ${due} giờ, chưa ghi`}</Tag>}
        <span className="ml-auto flex items-center gap-3">{last && <span className="mono">{tv`${Math.round(last.figures.views ?? 0)} lượt xem`}</span>}
          <button type="button" className="link" onClick={() => setOpen(!open)}>{open ? tr("Đóng") : tr("Ghi số liệu")}</button></span>
      </div>
      {open && (
        <div className="mt-3 grid gap-3">
          {p.snapshots.length > 0 && (
            <div className="overflow-x-auto"><table className="w-full min-w-[420px] text-[12.5px]"><thead><tr className="text-left text-faint"><th className="py-1 font-normal">Sau</th>{FIGURE.map(([k, n]) => <th key={k} className="py-1 font-normal">{n}</th>)}</tr></thead>
              <tbody>{p.snapshots.map((s) => <tr key={s.snapshot_id} className="border-t border-line"><td className="mono py-1">{s.hours < 48 ? tv`${s.hours.toFixed(0)} giờ` : tv`${(s.hours / 24).toFixed(0)} ngày`}</td>{FIGURE.map(([k]) => <td key={k} className="mono py-1">{s.figures[k] !== undefined ? Math.round(s.figures[k]) : ""}</td>)}</tr>)}</tbody></table></div>)}
          <form className="flex flex-wrap items-end gap-2" onSubmit={async (e) => { e.preventDefault(); const f = e.currentTarget; const body = Object.fromEntries([...new FormData(f).entries()].filter(([, v]) => String(v).trim() !== ""));
            setNote(null); try { await post(`/api/v1/publications/${p.publication_id}/metrics`, body); f.reset(); } catch (err) { setNote((err as Error).message); } reload(); }}>
            {FIGURE.map(([k, n]) => <label key={k} className="grid gap-1 text-[12px] text-mute">{n}<input name={k} type="number" inputMode="decimal" min="0" className="mono h-8 w-24 px-2" /></label>)}
            <Button size="sm" type="submit">{tr("Ghi số liệu lúc này")}</Button>
            <Button size="sm" onClick={async () => setForecast(await call<Forecast>(`/api/v1/publications/${p.publication_id}/forecast`))}>{tr("Dự báo một tuần")}</Button>
          </form>
          {note && <p className="text-tally">{note}</p>}
          {forecast && <p className="text-mute">{forecast.ready ? <>{tr("Sau một tuần có thể vào khoảng")} <span className="mono text-ink">{forecast.week}</span> {tv`lượt xem (từ ${forecast.low} đến ${forecast.high}), suy từ cách ${forecast.based_on} video trước của bạn tăng lên từ cùng thời điểm. Đây là tỷ lệ trung vị, không phải mô hình dự đoán.`}</> : forecast.reason}</p>}
        </div>)}
    </li>
  );
}
const open_ = (path: string) => { window.history.pushState(null, "", path); window.dispatchEvent(new PopStateEvent("popstate")); };

/** Campaigns: a set of videos meant to reach a figure together, and how far along they are. */
function Campaigns() {
  const { data, reload } = usePoll<{ campaigns: Campaign[] }>("/api/v1/campaigns", 20000);
  const { data: cal } = usePoll<{ projects: CalendarRow[] }>("/api/v1/calendar", 30000);
  const [picked, setPicked] = useState<string[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const [change, setChange] = useState<{ text: string } | null>(null);
  return (
    <Section title={tr("Chiến dịch")} icon="calendar" note={tr("Một nhóm video cùng hướng tới một con số trong một khoảng thời gian. Tiến độ tính từ số liệu bạn đã ghi.")}>
      <ul className="grid gap-3 empty:hidden">
        {(data?.campaigns ?? []).map((c) => (
          <li key={c.campaign_id} className="panel p-4 text-[13px]">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1"><span className="font-medium">{c.name}</span><span className="mono text-faint">{tv`${c.starts ?? "?"} đến ${c.ends ?? "?"}`}</span>
              {c.late > 0 && <Tag tone="cue">{tv`${c.late} video quá ngày`}</Tag>}{c.pace && <Tag tone={c.pace.on_pace ? "proof" : "cue"}>{c.pace.on_pace ? tr("Đúng tiến độ") : tr("Chậm tiến độ")}</Tag>}
              <button type="button" className="link ml-auto" onClick={async () => { if (!(await ask(tv`Xoá chiến dịch “${c.name}”?`, { body: tr("Các video và số liệu của chúng vẫn còn; chỉ nhóm này và mục tiêu của nó bị xoá."), confirm: tr("Xoá chiến dịch") }))) return; await call(`/api/v1/campaigns/${c.campaign_id}`, { method: "DELETE" }); reload(); }}>{tr("Xoá")}</button></div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-raised"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, (c.share ?? 0) * 100)}%` }} /></div>
            <p className="mt-1.5 text-mute"><span className="mono text-ink">{Math.round(c.reached)}</span> {tr("trên")} <span className="mono">{Math.round(c.target)}</span> {tv`lượt xem, ${c.published} trên ${c.videos.length} video đã đăng. ${c.pace?.text}`}</p>
            <ul className="mt-2 flex flex-wrap gap-2">{c.videos.map((v) => <li key={v.project_id}><button type="button" onClick={() => open_(`/du-an/${v.project_id}`)} className={`rounded-lg border px-2.5 py-1 text-left ${v.late ? "border-cue/40 bg-cue/10" : v.published ? "border-proof/40 bg-proof/10" : "border-line bg-raised/50"}`}>{v.title} <span className="mono text-faint">{v.published ? Math.round(v.value) : v.due_date ?? tr("chưa có ngày")}</span></button></li>)}</ul>
          </li>))}
      </ul>
      <details className="mt-3 text-[13px]"><summary className="cursor-pointer list-none text-accent">{tr("Lập chiến dịch mới")}</summary>
        <form className="panel mt-2 grid gap-3 p-4" onSubmit={async (e) => { e.preventDefault(); const f = new FormData(e.currentTarget); setNote(null);
          try { await post("/api/v1/campaigns", { name: f.get("name"), target: Number(f.get("target") || 0), starts: f.get("starts"), ends: f.get("ends"), projects: picked }); e.currentTarget.reset(); setPicked([]); } catch (err) { setNote((err as Error).message); } reload(); }}>
          <div className="flex flex-wrap gap-2"><input name="name" aria-label={tr("Tên chiến dịch")} placeholder={tr("Tên chiến dịch, ví dụ: Tháng ẩm thực đường phố")} className="h-9 min-w-0 flex-1 px-3" />
            <label className="flex items-center gap-2 text-mute">{tr("Mục tiêu")}<input name="target" type="number" inputMode="decimal" min="0" aria-label={tr("Số lượt xem mục tiêu")} className="mono h-9 w-28 px-2" />{tr("lượt xem")}</label></div>
          <div className="flex flex-wrap items-center gap-2 text-mute"><label className="flex items-center gap-2">{tr("Từ")}<input name="starts" type="date" className="mono h-9 px-2" /></label><label className="flex items-center gap-2">{tr("đến")}<input name="ends" type="date" className="mono h-9 px-2" /></label></div>
          <div className="flex flex-wrap gap-2">{(cal?.projects ?? []).map((p) => <label key={p.project_id} className={`flex cursor-pointer items-center gap-2 rounded-lg border px-2.5 py-1.5 ${picked.includes(p.project_id) ? "border-accent/60 bg-accent/[0.08]" : "border-line"}`}><input type="checkbox" checked={picked.includes(p.project_id)} onChange={() => setPicked(picked.includes(p.project_id) ? picked.filter((x) => x !== p.project_id) : [...picked, p.project_id])} />{p.title}</label>)}</div>
          <div className="flex items-center gap-3"><Button type="submit" kind="primary">{tr("Lập chiến dịch")}</Button>{note && <span className="text-tally">{note}</span>}</div>
        </form>
      </details>
      <form className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-4 text-[13px]" onSubmit={async (e) => { e.preventDefault(); const on = String(new FormData(e.currentTarget).get("on") ?? ""); if (on) setChange(await call(`/api/v1/publishing/change?on=${on}`)); }}>
        <label htmlFor="changed" className="text-mute">{tr("Bạn đổi cách làm từ ngày")}</label><input id="changed" name="on" type="date" className="mono h-8 px-2" /><Button size="sm" type="submit">{tr("So trước và sau")}</Button>
        {change && <p className="w-full text-mute">{change.text}</p>}
      </form>
    </Section>
  );
}

function Results() {
  const { data, reload } = usePoll<Publishing>("/api/v1/publishing", 20000);
  const [picked, setPicked] = useState<string[]>([]);
  const [question, setQuestion] = useState("");
  const published = (data?.publications ?? []).filter((p) => p.status === "published");
  const name = (t: string) => data?.targets.find((x) => x.target === t)?.label ?? t;
  const toggle = (id: string) => setPicked(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  return (
    <div className="grid max-w-5xl gap-10">
      <Section title={tr("Video đã đăng")} icon="external" note={tr("Ghi số liệu ở các mốc 1 giờ, 1 ngày, 3 ngày và 1 tuần sau khi đăng. Hệ thống nhắc khi tới mốc. Số liệu do bạn nhập vì chưa có tài khoản nền tảng nào được nối.")}>
        {data && published.length === 0 && <Empty icon="external" title={tr("Chưa có video nào được đăng")}>{tr("Sau khi chuẩn bị gói xuất bản của một dự án, đưa nó vào thư mục xuất bản hoặc ghi lại địa chỉ video bạn đã đăng tay.")}</Empty>}
        <ul className="panel rows empty:hidden">
          {published.map((p) => <PublicationRow key={p.publication_id} p={p} target={name(p.target)} due={data!.due.find((d) => d.publication_id === p.publication_id)?.mark ?? null} picked={picked.includes(p.publication_id)} pick={() => toggle(p.publication_id)} reload={reload} />)}
        </ul>
        {picked.length >= 2 && (
          <form className="ai-card mt-3 flex flex-wrap items-center gap-2 p-3 text-[13px]" onSubmit={async (e) => { e.preventDefault(); if (!question.trim()) return; await post("/api/v1/experiments", { question, publications: picked }); setPicked([]); setQuestion(""); reload(); }}>
            <label htmlFor="question" className="font-medium">{tv`So sánh ${picked.length} video đã chọn`}</label>
            <input id="question" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={tr("Câu hỏi của thí nghiệm, ví dụ: ảnh đại diện có chữ có hơn không?")} className="h-8 min-w-0 flex-1 px-2.5" />
            <Button size="sm" kind="ai" type="submit" disabled={!question.trim()}>{tr("Lập thí nghiệm")}</Button>
          </form>)}
      </Section>
      <Campaigns />
      {!!data?.experiments.length && (
        <Section title={tr("Thí nghiệm")} icon="sparkles" note={tr("Các biến thể được so ở cùng một tuổi của video, không so tổng số hôm nay.")}>
          <ul className="grid gap-3">
            {data.experiments.map((x) => (
              <li key={x.experiment_id} className="panel p-4 text-[13px]">
                <p className="font-medium">{x.question}</p>
                <div className="mt-2 flex flex-wrap gap-2">{x.variants.map((v) => <span key={v.publication_id} className={`rounded-lg border px-2.5 py-1.5 ${x.verdict.decided && x.verdict.leader === v.label ? "border-proof/50 bg-proof/10" : "border-line bg-raised/50"}`}><span className="font-medium">{v.label}</span> <span className="text-mute">{v.title}</span> <span className="mono">{v.value === null ? tr("chưa có số") : Math.round(v.value)}</span></span>)}</div>
                <p className={`mt-2 ${x.verdict.decided ? "" : "text-mute"}`}>{x.verdict.text}</p>
                {x.conclusion ? <p className="mt-1 text-mute">{tv`Kết luận của bạn: ${x.conclusion}`}</p>
                  : <form className="mt-2 flex gap-2" onSubmit={async (e) => { e.preventDefault(); const c = String(new FormData(e.currentTarget).get("c") ?? "").trim(); if (c) { await post(`/api/v1/experiments/${x.experiment_id}/close`, { conclusion: c }); reload(); } }}>
                      <input name="c" aria-label={tr("Kết luận")} placeholder={tr("Ghi kết luận của bạn rồi khép thí nghiệm")} className="h-8 min-w-0 flex-1 px-2.5" /><Button size="sm" type="submit">{tr("Khép lại")}</Button></form>}
              </li>))}
          </ul>
        </Section>)}
      {!!data?.breakdown.length && (
        <Section title={tr("Những gì đi cùng nhau")} icon="layers" note={tr("Lượt xem trung vị sau một ngày, nhóm theo đặc điểm của video. Đây là những thứ xuất hiện cùng nhau, không phải nguyên nhân; với ít video thì có thể chỉ là ngẫu nhiên.")}>
          <ul className="panel rows text-[13px]">{data.breakdown.map((g) => <li key={g.kind + g.name} className="flex gap-3 px-4 py-2"><span className="w-28 shrink-0 text-faint">{g.kind}</span><span className="min-w-0 flex-1">{g.name}</span><span className="mono">{tv`${Math.round(g.median)} lượt xem`}</span><span className="mono w-20 text-right text-faint">{g.videos} video</span></li>)}</ul>
        </Section>)}
    </div>
  );
}

export default function Plan() {
  const asked = new URLSearchParams(window.location.search).get("xem");
  const [tab, setTab] = useState<"calendar" | "radar" | "results">(() => (asked === "radar" ? "radar" : asked === "ket-qua" ? "results" : "calendar"));
  return (
    <Page eyebrow={tr("Sản xuất")} title={tr("Kế hoạch")} note={tr("Lịch đăng của các video đang làm, những gì kho footage còn làm được, và kết quả của các video đã đăng.")}
          tabs={<Tabs value={tab} onChange={setTab} items={[{ key: "calendar", label: tr("Lịch biên tập"), icon: "calendar" }, { key: "radar", label: tr("Radar cơ hội"), icon: "radar" }, { key: "results", label: tr("Kết quả"), icon: "pulse" }]} />}>
      {tab === "calendar" ? <Calendar /> : tab === "radar" ? <RadarView /> : <Results />}
    </Page>
  );
}
