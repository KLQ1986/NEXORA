import { t as tr, tv } from "./i18n";
import { useState } from "react";
import { post, timecode, usePoll, type Asset, type BeatView, type Label, type StructureView } from "./api";
import { Button, Icon } from "./parts";
import { BeatFlags, GoldenLabels, ProfileFacts } from "./Profile";

const CAMERA: Record<string, string> = { static: tr("máy tĩnh"), pan: tr("lia ngang"), tilt: tr("lia dọc"), push_in: tr("đẩy vào"), pull_out: tr("kéo ra"), handheld: tr("cầm tay") };
const GRADE: Record<string, string> = { good: tr("tốt"), fair: tr("chấp nhận được"), poor: tr("kém") };
const DIRECTION: Record<string, string> = { left_to_right: tr("trái sang phải"), right_to_left: tr("phải sang trái") };
const SURE: Record<string, string> = { high: tr("chắc"), medium: tr("khá chắc"), low: tr("chưa chắc") };
const BEAT_TONE: Record<string, string> = { good: "bg-accent/45", fair: "bg-cue/55", poor: "bg-tally/60" };
const TRANSITION: Record<string, string> = { cut: tr("cắt cứng"), dissolve: tr("chuyển mờ"), marked: tr("bạn đặt"), black: tr("sau đoạn đen"), start: tr("đầu video") };

/** One thing measured about a beat, with how sure the measure is. A measure in doubt is shown fainter. */
function Measure({ name, label, text }: { name: string; label?: Label; text?: string }) {
  if (!label || text === undefined) return null;
  return (
    <span className={`inline-flex items-baseline gap-1.5 rounded-md border border-line bg-raised/60 px-2 py-1 ${label.confidence === "low" ? "opacity-60" : ""}`} title={tv`Đo từ hình, ${SURE[label.confidence] ?? label.confidence}`}>
      <span className="text-faint">{name}</span><span>{text}</span>
    </span>
  );
}

function BeatFacts({ beat }: { beat: BeatView }) {
  const l = beat.labels;
  const fault = l.exposure?.fault === "burnt" ? tr("cháy sáng") : l.exposure?.fault === "dark" ? tr("quá tối") : null;
  return (
    <div className="flex flex-wrap gap-1.5 text-mini">
      <Measure name={tr("Máy")} label={l.camera} text={CAMERA[String(l.camera?.value)] ?? String(l.camera?.value ?? "")} />
      <Measure name={tr("Độ rung")} label={l.shake} text={GRADE[String(l.shake?.value)]} />
      <Measure name={tr("Độ nét")} label={l.sharpness} text={l.sharpness ? GRADE[String(l.sharpness.value)] : undefined} />
      <Measure name={tr("Phơi sáng")} label={l.exposure} text={fault ?? GRADE[String(l.exposure?.value)]} />
      <Measure name={tr("Lời nói")} label={l.speech} text={l.speech?.value ? tr("có") : tr("không")} />
      {l.speed?.value === "slow_motion" && <Measure name={tr("Tốc độ")} label={l.speed} text={tr("quay chậm")} />}
      {l.still?.value === true && <Measure name={tr("Hình")} label={l.still} text={tr("đứng yên")} />}
      {DIRECTION[String(l.direction?.value)] && <Measure name={tr("Hướng")} label={l.direction} text={DIRECTION[String(l.direction?.value)]} />}
    </div>
  );
}

/** The shots and beats of a recording along its length, and the operator's hand on them: a boundary can be placed, moved or
    removed where the picture is paused, and the recording kept as an answer the dividing rules are measured against. */
export function StructureStrip({ asset, t, seek }: { asset: Asset; t: number; seek: (s: number) => void }) {
  const { data, reload } = usePoll<StructureView>(`/api/v1/assets/${asset.asset_id}/structure`, 5000);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const d = asset.duration ?? 0;
  if (!data || !d) return null;
  const act = async (url: string, body?: unknown) => { setBusy(true); setFailed(null); try { await post(url, body); } catch (e) { setFailed((e as Error).message); } setBusy(false); reload(); };
  const base = `/api/v1/assets/${asset.asset_id}/structure`;
  if (!data.measured) {
    const working = data.run && ["queued", "running"].includes(data.run.status);
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-dashed border-line px-3 py-2.5 text-meta text-mute">
        <span className="min-w-0 flex-1">{working ? tr("Hệ thống đang đo video này để chia thành cú máy và nhịp.") : tr("Video này chưa được chia thành cú máy và nhịp.")}</span>
        {!working && <Button size="sm" busy={busy} onClick={() => act(`${base}/analyse`)}>{tr("Đo và chia")}</Button>}
        {failed && <p className="w-full text-tally">{failed}</p>}
      </div>
    );
  }
  const pct = (s: number) => `${Math.min(100, Math.max(0, (s / d) * 100))}%`;
  const span = (a: number, b: number) => ({ left: pct(a), width: `${Math.max(0.3, ((b - a) / d) * 100)}%` });
  const beat = data.beats.find((b) => t >= b.t_start && t < b.t_end) ?? null;
  const all = data.boundaries.beat;
  const nearest = all.length ? all.reduce((best, b) => (Math.abs(b - t) < Math.abs(best - t) ? b : best)) : null;
  const isShot = (b: number) => data.boundaries.shot.some((s) => Math.abs(s - b) < 0.02);
  const mark = (kind: "shot" | "beat", op: string, at: number, to?: number) => act(`${base}/marks`, { kind, op, t: at, to });
  const inside = t > 0.2 && t < d - 0.2 && !all.some((b) => Math.abs(b - t) < 0.3);
  const marked = (b: number) => data.marks.some((m) => Math.abs(m.t - b) <= 0.3);
  const seekAt = (e: React.MouseEvent<HTMLDivElement>) => { const r = e.currentTarget.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * d); };
  return (
    <section className="grid gap-2.5" aria-label={tr("Cú máy và nhịp")}>
      <div className="flex items-baseline gap-3 text-mini text-mute">
        <span className="eyebrow">{tr("Cú máy và nhịp")}</span>
        <span>{tv`${data.shots.length} cú máy · ${data.beats.length} nhịp`}</span>
        {data.bars && data.bars.value !== "none" && <span title={tr("Đo từ hình: video có viền đen cố định")}>{data.bars.value === "top_bottom" ? tr("viền đen trên dưới") : tr("viền đen hai bên")}</span>}
      </div>
      <div className="grid gap-1">
        <div className="relative h-3 cursor-pointer overflow-hidden rounded-sm bg-raised" onClick={seekAt} role="img" aria-label={tr("Các cú máy theo thời gian")}>
          {data.shots.map((s, i) => <div key={`s${i}`} className={`absolute inset-y-0 border-l-2 ${s.pinned ? "border-cue" : "border-ink/80"} ${i % 2 ? "bg-overlay" : "bg-edge/60"}`} style={span(s.t_start, s.t_end)} title={tv`Cú máy ${i + 1}: ${timecode(s.t_start)} đến ${timecode(s.t_end)}, ${TRANSITION[s.transition_in] ?? s.transition_in}`} />)}
          {data.transitions.map(([a, b], i) => <div key={`z${i}`} className="hatch-cue absolute inset-y-0" style={span(a, b)} title={tr("Vùng chuyển mờ: không khung hình nào được lấy ở đây")} />)}
        </div>
        <div className="relative h-7 cursor-pointer overflow-hidden rounded-md bg-raised" onClick={seekAt} role="slider" aria-label={tr("Các nhịp theo thời gian")} aria-valuemin={0} aria-valuemax={d} aria-valuenow={t}>
          {data.beats.map((b, i) => <div key={`b${i}`} className={`absolute inset-y-0 border-l ${b.pinned ? "border-cue" : "border-canvas"} ${BEAT_TONE[String(b.labels.quality?.value)] ?? "bg-accent/45"} ${beat === b ? "brightness-150" : ""} ${b.moment ? "" : "opacity-50"}`} style={span(b.t_start, b.t_end)} title={tv`Nhịp ${timecode(b.t_start)} đến ${timecode(b.t_end)}${b.moment ? "" : tr(", chưa mô tả")}`} />)}
          <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-cue shadow-[0_0_8px_var(--color-cue)]" style={{ left: pct(t) }} />
        </div>
      </div>
      {beat && (
        <div className="grid gap-2 rounded-lg border border-line bg-raised/40 p-2.5">
          <p className="flex flex-wrap items-baseline gap-x-2 text-meta"><span className="mono text-ink">{timecode(beat.t_start)} – {timecode(beat.t_end)}</span><span className="text-faint">{tv`cú máy ${beat.shot + 1}`}</span>
            {!beat.moment && <span className="text-faint">{tr("chưa mô tả")}</span>}</p>
          <BeatFacts beat={beat} />
          <ProfileFacts beat={beat} />
          <BeatFlags beat={beat} reload={reload} />
          <GoldenLabels assetId={asset.asset_id} beat={beat} reload={reload} />
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2 text-mini">
        <Button size="sm" disabled={busy || !inside} title={tr("Đặt một ranh giới nhịp ở chỗ đang xem. Mọi lần chia lại sau này đều giữ nó.")} onClick={() => mark("beat", "add", t)}>{tv`Đặt ranh giới nhịp ở ${timecode(t)}`}</Button>
        <Button size="sm" disabled={busy || !inside} title={tr("Đặt một ranh giới cú máy ở chỗ đang xem, khi hệ thống bỏ sót một điểm cắt.")} onClick={() => mark("shot", "add", t)}>{tr("Đặt ranh giới cú máy")}</Button>
        {nearest != null && <>
          <Button size="sm" disabled={busy || Math.abs(nearest - t) < 0.3 || t <= 0.2 || t >= d - 0.2} title={tr("Dời ranh giới gần nhất tới chỗ đang xem")} onClick={() => mark(isShot(nearest) ? "shot" : "beat", "move", nearest, t)}>{tv`Dời ranh giới ở ${timecode(nearest)} tới đây`}</Button>
          <Button size="sm" disabled={busy} title={tr("Bỏ ranh giới gần chỗ đang xem nhất. Hệ thống sẽ không đặt lại nó.")} onClick={() => mark(isShot(nearest) ? "shot" : "beat", "remove", nearest)}>{tv`Bỏ ranh giới ở ${timecode(nearest)}`}</Button>
          {marked(nearest) && <button type="button" className="link" disabled={busy} title={tr("Quên dấu của bạn ở đây và để hệ thống tự quyết")} onClick={() => mark("beat", "clear", nearest)}>{tr("Trả về cho hệ thống")}</button>}
        </>}
      </div>
      <label className="flex items-start gap-2 text-mini text-mute">
        <input type="checkbox" className="mt-0.5" checked={data.reference} disabled={busy} onChange={(e) => act(`${base}/reference`, { on: e.target.checked })} />
        <span>{tr("Dùng video này làm mẫu đo: các ranh giới như đang thấy là đáp án đúng. Chỉ đánh dấu khi bạn đã rà hết video.")}</span>
      </label>
      {data.faults.length > 0 && <p className="flex items-start gap-1.5 text-mini text-tally"><Icon name="alert" size={13} className="mt-0.5 shrink-0" />{tv`Các nhịp chưa phủ kín video: ${data.faults.length} chỗ.`}</p>}
      {failed && <p className="text-mini text-tally">{failed}</p>}
    </section>
  );
}
