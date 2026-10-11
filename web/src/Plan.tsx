import { useMemo, useState } from "react";
import { post, timecode, usePoll, type CalendarRow, type Radar, type RadarSubject } from "./api";
import { Button, Empty, Icon, Page, Section, Tabs, Tag } from "./parts";

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
  const { data, reload } = usePoll<{ projects: CalendarRow[]; today: string }>("/api/v1/calendar", 15000);
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
          <h2 className="text-[16px] font-semibold capitalize">{new Date(at.y, at.m, 1).toLocaleDateString("vi-VN", { month: "long", year: "numeric" })}</h2>
          <span className="ml-auto flex gap-1.5">
            <Button size="sm" onClick={() => shift(-1)} title="Tháng trước"><Icon name="back" size={14} /></Button>
            <Button size="sm" onClick={() => setAt({ y: now.getFullYear(), m: now.getMonth() })}>Hôm nay</Button>
            <Button size="sm" onClick={() => shift(1)} title="Tháng sau"><Icon name="next" size={14} /></Button>
          </span>
        </div>
        {late.length > 0 && <p className="mb-3 flex items-center gap-2 rounded-xl border border-cue/40 bg-cue/10 px-4 py-2.5 text-[13px] text-cue"><Icon name="alert" size={15} />{late.length} video đã quá ngày dự định mà chưa có bản dựng được duyệt.</p>}
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
        <p className="mt-2 text-[12px] text-faint">Kéo một video sang ngày khác để dời lịch. Viền xanh là video đã có bản dựng được duyệt; viền vàng là video đã quá ngày.</p>
      </div>
      <Section title="Chưa có ngày đăng" icon="clock" note="Kéo vào một ngày trên lịch, hoặc chọn ngày ở đây.">
        {data && unplanned.length === 0 && <p className="text-[13px] text-mute">Mọi dự án đều đã có ngày.</p>}
        <ul className="panel rows empty:hidden">
          {unplanned.map((p) => (
            <li key={p.project_id} draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", p.project_id)} className="grid cursor-grab gap-1.5 px-3 py-2.5 text-[13px]">
              <button type="button" className="truncate text-left font-medium hover:text-accent" onClick={() => open(`/du-an/${p.project_id}`)}>{p.title}</button>
              <div className="flex items-center gap-2"><Tag tone={p.ready ? "proof" : "mute"}>{p.stage}</Tag>
                <input type="date" aria-label={`Ngày đăng của ${p.title}`} onChange={(e) => e.target.value && plan(p.project_id, e.target.value)} className="mono ml-auto h-8 px-2 text-[12px]" /></div>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

function SubjectRows({ rows, unusedOnly }: { rows: RadarSubject[]; unusedOnly: boolean }) {
  return (
    <ul className="panel rows">
      {rows.map((s) => (
        <li key={s.subject} className="px-4 py-3 text-[13px]">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1"><span className="font-medium capitalize">{s.subject}</span>
            <span className="mono text-faint">{unusedOnly ? `${s.unused_videos} video chưa dùng, ${timecode(s.unused_seconds)}` : `${s.videos} video, ${timecode(s.seconds)}`}</span>
            {!unusedOnly && <span className="ml-auto text-faint">{s.videos - s.unused_videos} đã dùng trong dự án</span>}</div>
          {unusedOnly && s.examples.length > 0 && <ul className="mt-1.5 grid gap-1 text-mute">{s.examples.map((e) => (
            <li key={e.asset_id} className="truncate"><button type="button" className="hover:text-accent" onClick={() => open(`/thu-vien?q=${encodeURIComponent(e.title || e.summary)}`)}>{e.title || "Video chưa có tên"}</button><span className="text-faint"> {e.summary}</span></li>))}</ul>}
        </li>
      ))}
    </ul>
  );
}

function RadarView() {
  const { data, reload } = usePoll<Radar>("/api/v1/radar", 30000);
  const [topic, setTopic] = useState("");
  const save = (topics: string[]) => post("/api/v1/radar/topics", { topics }).then(reload);
  const tone = (v: string) => (v === "đủ hình để làm" ? "proof" : v === "có ít hình" ? "cue" : "mute") as "proof" | "cue" | "mute";
  return (
    <div className="grid max-w-5xl gap-10">
      <Section title="Chủ đề bạn đang theo dõi" icon="radar" note="Với mỗi chủ đề, hệ thống đo xem kho footage có bao nhiêu cảnh trả lời được nó. Số đo lấy từ chỉ mục của kho, không do mô hình phỏng đoán.">
        <form className="mb-3 flex max-w-xl gap-2" onSubmit={(e) => { e.preventDefault(); const t = topic.trim(); if (t && data) { save([...data.topics, t]); setTopic(""); } }}>
          <input value={topic} onChange={(e) => setTopic(e.target.value)} aria-label="Chủ đề muốn theo dõi" placeholder="Ví dụ: món ăn đường phố buổi tối" className="h-9 min-w-0 flex-1 px-3" />
          <Button type="submit" disabled={!topic.trim()}><Icon name="plus" size={14} />Theo dõi</Button>
        </form>
        {data && data.watched.length === 0 && <p className="text-[13px] text-mute">Chưa có chủ đề nào. Thêm một chủ đề bạn định làm để biết kho đã đủ hình hay cần quay thêm.</p>}
        <ul className="panel rows empty:hidden">
          {(data?.watched ?? []).map((w) => (
            <li key={w.topic} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 text-[13px]">
              <span className="min-w-0 font-medium">{w.topic}</span><Tag tone={tone(w.verdict)}>{w.verdict}</Tag>
              <span className="mono text-faint">{w.moments} cảnh khớp trong {w.assets} video</span>
              <span className="ml-auto flex items-center gap-3">
                {w.moments > 0 && <button type="button" className="link" onClick={() => open(`/thu-vien?q=${encodeURIComponent(w.topic)}`)}>Xem các cảnh</button>}
                <button type="button" className="link" onClick={() => open(`/du-an?moi=1`)}>Làm video</button>
                <button type="button" className="text-faint hover:text-ink" aria-label={`Bỏ theo dõi ${w.topic}`} onClick={() => save(data!.topics.filter((t) => t !== w.topic))}><Icon name="x" size={14} /></button>
              </span>
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Footage chưa dùng vào video nào" icon="film" note="Xếp theo thời lượng còn nằm yên trong kho. Đây là chỗ dễ làm video mới nhất vì hình đã có sẵn.">
        {data && data.unused.length === 0 && <Empty icon="film" title="Không có footage nào nằm yên">Mọi video đã được mô tả trong kho đều đang được một dự án dùng, hoặc kho chưa có video nào được mô tả.</Empty>}
        {!!data?.unused.length && <SubjectRows rows={data.unused} unusedOnly />}
      </Section>
      {!!data?.subjects.length && <Section title="Kho đang có gì" icon="layers" note="Mọi chủ đề hệ thống nhận ra trong kho, xếp theo thời lượng."><SubjectRows rows={data.subjects} unusedOnly={false} /></Section>}
      <p className="text-[12px] text-faint">Radar này chỉ nhìn vào kho của bạn. Xu hướng trên các nền tảng và số liệu video đã đăng chưa được nối vào vì hệ thống chưa có tài khoản nền tảng nào.</p>
    </div>
  );
}

export default function Plan() {
  const [tab, setTab] = useState<"calendar" | "radar">(() => (new URLSearchParams(window.location.search).get("xem") === "radar" ? "radar" : "calendar"));
  return (
    <Page eyebrow="Sản xuất" title="Kế hoạch" note="Lịch đăng của các video đang làm, và những gì kho footage còn làm được."
          tabs={<Tabs value={tab} onChange={setTab} items={[{ key: "calendar", label: "Lịch biên tập", icon: "calendar" }, { key: "radar", label: "Radar cơ hội", icon: "radar" }]} />}>
      {tab === "calendar" ? <Calendar /> : <RadarView />}
    </Page>
  );
}
