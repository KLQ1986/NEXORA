import { t as tr, tv } from "./i18n";
import { useState } from "react";
import { timecode, usePoll } from "./api";
import { Tag } from "./parts";

/* How a recording tells its story and a proposal for cutting it again (design 2026-10-15, section 9 G): the energy of every
   beat, its role, notes on pace and opening, and a recut to a chosen length that opens in an editor as an EDL. */

type Beat = { index: number; t_start: number; t_end: number; role: string; energy: number; why: string[] };
type Piece = { order: number; t_in: number; t_out: number; seconds: number; role: string; why: string; description: string };
type View = {
  story: { beats: Beat[]; peak: number; notes: string[]; model: { agrees: boolean | null } };
  recut: { seconds: number; target: number; plan: Piece[]; dropped: { t_start: number; t_end: number; why: string }[]; notes: string[] };
};
const LENGTHS = [15, 30, 60];

export function AssetStory({ assetId, seek }: { assetId: string; seek?: (t: number) => void }) {
  const [seconds, setSeconds] = useState(30);
  const { data } = usePoll<View>(`/api/v1/assets/${assetId}/story?seconds=${seconds}`, 60000);
  if (!data || data.story.beats.length === 0) return null;
  const { story, recut } = data;
  return (
    <details className="rounded-lg border border-line bg-raised/30 p-2.5 text-meta">
      <summary className="cursor-pointer list-none"><span className="eyebrow">{tr("Kể chuyện và dựng lại")}</span>
        <span className="ml-2 text-faint">{tv`cao trào ở nhịp ${story.peak}; bản dựng ${recut.seconds}s`}</span></summary>
      <div className="mt-2 flex h-14 items-end gap-0.5" aria-label={tr("Năng lượng từng nhịp")}>
        {story.beats.map((b) => (
          <button key={b.index} title={`${b.role} · ${b.why.join(", ")}`} onClick={() => seek?.(b.t_start)}
            className={`flex-1 rounded-t ${b.index === story.peak ? "bg-accent" : "bg-faint/50"}`} style={{ height: `${Math.max(8, b.energy * 100)}%` }} />
        ))}
      </div>
      <p className="mt-1 text-faint">{story.beats.map((b) => `${b.index}: ${b.role}`).join(" · ")}</p>
      {[...story.notes, ...recut.notes].map((n) => <p key={n} className="text-cue">{n}</p>)}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <span className="text-faint">{tr("Dựng lại dài")}</span>
        {LENGTHS.map((s) => <button key={s} onClick={() => setSeconds(s)} className={`rounded px-2 ${s === seconds ? "bg-accent/15 text-accent" : "text-mute"}`}>{`${s}s`}</button>)}
        <a className="text-accent underline" href={`/api/v1/assets/${assetId}/story?seconds=${seconds}&format=edl`} download>{tr("Tải EDL (Premiere, Resolve)")}</a>
        <a className="text-accent underline" href={`/api/v1/assets/${assetId}/story?seconds=${seconds}&format=md`} download>{tr("Tải đề xuất (.md)")}</a>
      </div>
      <ol className="mt-2 grid gap-1">
        {recut.plan.map((p) => (
          <li key={p.order} className="flex flex-wrap items-baseline gap-2">
            <Tag tone={p.role === "mở (hook)" ? "accent" : "mute"}>{p.role}</Tag>
            <button className="mono text-ink underline" onClick={() => seek?.(p.t_in)}>{`${timecode(p.t_in)}–${timecode(p.t_out)}`}</button>
            <span className="text-faint">{p.why}</span>
          </li>
        ))}
      </ol>
      {recut.dropped.length > 0 && <p className="mt-1 text-faint">{tv`Bỏ ra: ${recut.dropped.map((d) => `${timecode(d.t_start)} (${d.why})`).join(", ")}`}</p>}
    </details>
  );
}
