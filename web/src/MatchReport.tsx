import { t as tr, tv } from "./i18n";
import { timecode, usePoll } from "./api";
import { Section, Tag } from "./parts";

/* How well the footage serves the script (design 2026-10-15, section 9 C): what each line got and how well its frames show
   it, which recordings carry the script, and how much of it has a picture. Read after a match; nothing is searched again. */

type Found = { name: string; t_in: number; t_out: number; seconds: number; picture: string | null; picture_why: string[] };
type Line = { line: number; text: string; grade: string; judge: number | null; seconds_needed: number; short: boolean; found: Found | null; alternates: { name: string; judge: number | null }[] };
type Report = {
  lines: Line[]; clips: { asset_id: string; name: string; lines: number[]; alternate_for: number[]; seconds: number }[]; unused: string[];
  totals: { lines: number; "tốt": number; "tạm": number; "thiếu": number; seconds_needed: number; seconds_covered: number; coverage: number; judge_mean: number | null };
};
const TONE: Record<string, "proof" | "cue" | "tally"> = { "tốt": "proof", "tạm": "cue", "thiếu": "tally" };

export function MatchReport({ projectId }: { projectId: string }) {
  const { data } = usePoll<Report>(`/api/v1/projects/${projectId}/match/report`, 10000);
  if (!data || data.lines.every((l) => !l.found && l.grade !== "thiếu")) return null;
  const t = data.totals;
  return (
    <Section title={tr("Báo cáo ghép nguyên liệu")} icon="check" note={tv`${t["tốt"]} tốt · ${t["tạm"]} tạm · ${t["thiếu"]} thiếu · có hình ${Math.round(t.coverage * 100)}%`}
      actions={<a className="text-accent underline" href={`/api/v1/projects/${projectId}/match/report?format=md`} download="bao-cao-ghep.md">{tr("Tải báo cáo (.md)")}</a>}>
      <div className="panel grid gap-3 p-3 text-[12.5px]">
        <ol className="grid gap-1.5">
          {data.lines.map((l) => (
            <li key={l.line} className="flex flex-wrap items-baseline gap-2">
              <Tag tone={TONE[l.grade] ?? "mute"}>{l.judge != null ? `${l.grade} ${l.judge}/10` : l.grade}</Tag>
              <span className="text-ink">{tv`Câu ${l.line}: ${l.text}`}</span>
              {l.found ? <span className="text-faint">{`${l.found.name} ${timecode(l.found.t_in)}–${timecode(l.found.t_out)}`}{l.short ? tr(" (ngắn hơn cần)") : ""}{l.found.picture && l.found.picture !== "dùng được" ? ` · ${l.found.picture}: ${l.found.picture_why.join(", ")}` : ""}</span>
                : <span className="text-cue">{tr("chưa có hình")}</span>}
            </li>
          ))}
        </ol>
        {data.clips.length > 0 && <div><p className="eyebrow">{tr("Theo clip")}</p>
          <ul className="mt-1 grid gap-1">{data.clips.map((c) => <li key={c.asset_id} className="text-faint"><span className="text-ink">{c.name}</span>{" "}
            {tv`chọn cho câu ${c.lines.join(", ") || "–"}`}{c.alternate_for.length > 0 ? tv`; dự phòng cho câu ${c.alternate_for.join(", ")}` : ""}</li>)}</ul></div>}
        {data.unused.length > 0 && <p className="text-faint">{tv`Không được dùng: ${data.unused.join(", ")}`}</p>}
      </div>
    </Section>
  );
}
