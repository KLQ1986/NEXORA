import { t as tr, tv } from "./i18n";
import { timecode, usePoll } from "./api";
import { Tag } from "./parts";

/* The dossier of a recording (design 2026-10-15, section 9 B): everything learnt about it, and a word on every beat, can its
   picture and its sound be used, and what it could serve as in a cut. The grades come from what was measured. */

type Grade = { grade: string; why: string[] };
type DossierBeat = {
  index: number; t_start: number; t_end: number; seconds: number; description: string; things: string[]; actions: string[];
  picture: Grade; sound: Grade; uses: string[]; speech: string[]; text_on_screen: string[]; flags: string[];
};
type DossierView = {
  asset_id: string; title: string; summary: string;
  analysis: { out_of_date: string[] };
  verdict: { usable_seconds: number; careful_seconds: number; unusable_seconds: number; best_beat: number | null };
  beats: DossierBeat[];
};

const TONE: Record<string, "proof" | "cue" | "tally"> = { "dùng được": "proof", "dùng tạm": "cue", "lỗi": "tally" };

export function AssetDossier({ assetId, seek }: { assetId: string; seek?: (t: number) => void }) {
  const { data } = usePoll<DossierView>(`/api/v1/assets/${assetId}/dossier`, 30000);
  if (!data) return null;
  const v = data.verdict;
  return (
    <details className="rounded-lg border border-line bg-raised/30 p-2.5 text-[12.5px]">
      <summary className="cursor-pointer list-none"><span className="eyebrow">{tr("Hồ sơ nguyên liệu")}</span>
        <span className="ml-2 text-faint">{tv`dùng được ${v.usable_seconds}s, dùng tạm ${v.careful_seconds}s, lỗi ${v.unusable_seconds}s`}</span></summary>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <a className="text-accent underline" href={`/api/v1/assets/${assetId}/dossier?format=md`} download={`${assetId}.md`}>{tr("Tải hồ sơ (.md)")}</a>
        {data.analysis.out_of_date.length > 0 && <span className="text-faint">{tv`Phần phân tích đã cũ: ${data.analysis.out_of_date.join(", ")}`}</span>}
      </div>
      <ol className="mt-2 grid gap-2">
        {data.beats.map((b) => (
          <li key={b.index} className="rounded-md border border-line/60 p-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <button className="mono text-ink underline" onClick={() => seek?.(b.t_start)}>{`${timecode(b.t_start)}–${timecode(b.t_end)}`}</button>
              <span title={b.picture.why.join("; ")}><Tag tone={TONE[b.picture.grade] ?? "mute"}>{tv`hình: ${b.picture.grade}`}</Tag></span>
              <span title={b.sound.why.join("; ")}><Tag tone={TONE[b.sound.grade] ?? "mute"}>{tv`tiếng: ${b.sound.grade}`}</Tag></span>
              {v.best_beat === b.index && <Tag tone="accent">{tr("đẹp nhất")}</Tag>}
            </div>
            {b.description && <p className="mt-1">{b.description}</p>}
            <p className="mt-1 text-faint">{tv`Dùng làm: ${b.uses.join(", ")}`}</p>
            {(b.picture.why.length > 0 || b.sound.why.length > 0) && <p className="text-faint">{tv`Lưu ý: ${[...b.picture.why, ...b.sound.why].join(", ")}`}</p>}
            {b.speech.length > 0 && <p className="text-faint">{tv`Lời: ${b.speech.join(" ")}`}</p>}
            {b.flags.length > 0 && <p className="text-cue">{tv`Cần xem lại: ${b.flags.join("; ")}`}</p>}
          </li>
        ))}
      </ol>
    </details>
  );
}
