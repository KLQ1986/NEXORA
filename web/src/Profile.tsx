import { t as tr, tv, locale } from "./i18n";
import { useState } from "react";
import { post, call, timecode, usePoll, type BeatView, type Label } from "./api";
import { Button, Tag } from "./parts";

/* The footage profile on screen (design 2026-10-14): what was measured and recognised in a beat and what a model said of it,
   each with where it came from and how sure it is; the operator's answers that every field is measured against; the
   flags where a model disagreed with a measurement; and how right each field has been. */

const SOURCE: Record<string, string> = { measured: tr("đo"), recognized: tr("nhận diện"), model: tr("mô hình"), human: tr("bạn") };
const SURE: Record<string, string> = { high: tr("chắc"), medium: tr("khá chắc"), low: tr("chưa chắc") };
const CAMERA: Record<string, string> = { static: tr("máy tĩnh"), pan: tr("lia ngang"), tilt: tr("lia dọc"), push_in: tr("đẩy vào"), pull_out: tr("kéo ra"), handheld: tr("cầm tay") };

type P = Label & Record<string, unknown>;

function Fact({ name, label, text }: { name: string; label?: P; text?: string | null }) {
  if (!label || text == null || text === "") return null;
  const low = label.confidence === "low";
  return (
    <span className={`inline-flex items-baseline gap-1.5 rounded-md border px-2 py-1 ${label.source === "model" ? "border-ai/30 bg-ai/5" : "border-line bg-raised/60"} ${low ? "opacity-60" : ""}`}
          title={tv`Nguồn: ${SOURCE[label.source] ?? label.source}, ${SURE[label.confidence] ?? label.confidence}`}>
      <span className="text-faint">{name}</span><span>{text}</span><span className="text-[10.5px] text-faint">{SOURCE[label.source] ?? label.source}</span>
    </span>
  );
}

const list = (v: unknown) => (Array.isArray(v) ? v.join(", ") : v == null ? "" : String(v));

/** Everything the profile holds about one beat, measured and recognised first, the model's labels after. */
export function ProfileFacts({ beat }: { beat: BeatView }) {
  const p = (beat.profile ?? {}) as Record<string, P>;
  const m = (beat.model_labels ?? {}) as Record<string, P>;
  if (!Object.keys(p).length && !Object.keys(m).length) return null;
  const loud = p.loudness?.value != null ? `${p.loudness.value} LUFS` : null;
  return (
    <div className="grid gap-1.5 text-[12px]">
      <div className="flex flex-wrap gap-1.5">
        <Fact name={tr("Người")} label={p.people} text={p.people ? `${p.people.value}${p.people.count ? ` (${p.people.count})` : ""}` : null} />
        <Fact name={tr("Cỡ cảnh")} label={p.shot_size} text={p.shot_size ? String(p.shot_size.value) : null} />
        <Fact name={tr("Nơi")} label={p.place} text={list(p.place?.value)} />
        <Fact name={tr("Tư thế")} label={p.posture} text={list(p.posture?.value)} />
        <Fact name={tr("Người nói")} label={p.speaker} text={list(p.speaker?.value)} />
        <Fact name={tr("Chủ thể")} label={p.subject_place} text={list(p.subject_place?.value)} />
        <Fact name={tr("Chân trời")} label={p.horizon} text={p.horizon ? `${p.horizon.value} (${p.horizon.degrees}°)` : null} />
        <Fact name={tr("Ánh sáng")} label={p.light} text={list(p.light?.value)} />
        <Fact name={tr("Ngược sáng")} label={p.backlit} text={p.backlit?.value ? tr("có") : null} />
        <Fact name={tr("Màu")} label={p.colour} text={p.colour ? `${p.colour.value}${p.colour.kelvin ? ` ~${p.colour.kelvin}K` : ""}, ${p.colour.look ?? ""}` : null} />
        <Fact name={tr("Độ sâu")} label={p.depth} text={list(p.depth?.value)} />
        <Fact name={tr("Nhiễu hạt")} label={p.noise} text={list(p.noise?.value)} />
        <Fact name={tr("Bố cục")} label={p.composition} text={list(p.composition?.value)} />
        <Fact name={tr("Âm thanh")} label={p.sound} text={list(p.sound?.value)} />
        <Fact name={tr("Độ lớn")} label={p.loudness} text={loud} />
        <Fact name={tr("Cắt đỉnh")} label={p.clipping} text={p.clipping?.value ? tr("có") : null} />
        <Fact name={tr("Gió")} label={p.wind} text={p.wind?.value ? tr("có") : null} />
      </div>
      {Array.isArray(p.colour?.palette) && (
        <div className="flex items-center gap-1" aria-label={tr("Màu chủ đạo")}>
          {(p.colour.palette as [string, number, string][]).map(([hex, share, name]) => (
            <span key={hex} title={`${name} ${Math.round(share * 100)}%`} className="h-3.5 rounded-sm border border-line" style={{ background: hex, width: `${Math.max(8, share * 120)}px` }} />))}
        </div>)}
      {!!p.scene_tags?.value && <p className="text-faint">{tr("Nhận diện thấy:")} {list(p.scene_tags.value)}</p>}
      {!!p.text?.value && <p className="text-faint">{tr("Chữ trên hình:")} <span className="text-ink">{list(p.text.value)}</span></p>}
      {Object.keys(m).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          <Fact name={tr("Cỡ cảnh")} label={m.co_canh} text={list(m.co_canh?.value)} />
          <Fact name={tr("Góc máy")} label={m.goc_may} text={list(m.goc_may?.value)} />
          <Fact name={tr("Số người")} label={m.so_nguoi} text={list(m.so_nguoi?.value)} />
          <Fact name={tr("Nơi")} label={m.noi_chon} text={list(m.noi_chon?.value)} />
        </div>)}
      {!!beat.new_things?.length && <p className="text-faint">{tr("Điểm mới so với nhịp trước:")} <span className="text-ink">{beat.new_things.join(", ")}</span></p>}
    </div>
  );
}

/** The flags on one beat, with the two ways to close them. */
export function BeatFlags({ beat, reload }: { beat: BeatView; reload: () => void }) {
  const flags = beat.flags ?? [];
  if (!beat.moment || !flags.some((f) => f.state === "open")) return null;
  const settle = async (index: number, state: string) => { await post("/api/v1/flags", { moment_id: beat.moment!.moment_id, index, state }).catch(() => {}); reload(); };
  return (
    <ul className="grid gap-1 text-[12px]">
      {flags.map((f, i) => f.state === "open" && (
        <li key={i} className="flex flex-wrap items-center gap-2 rounded-md border border-cue/30 bg-cue/5 px-2 py-1">
          <Tag tone="cue">{f.rule}</Tag><span className="min-w-0 flex-1">{f.message}</span>
          <button type="button" className="link" onClick={() => settle(i, "resolved")}>{tr("Đã xử lý")}</button>
          <button type="button" className="link" onClick={() => settle(i, "ignored")}>{tr("Bỏ qua")}</button>
        </li>))}
    </ul>
  );
}

const GOLDEN: [string, string, string[]][] = [
  ["shot_size", tr("Cỡ cảnh"), ["cực toàn", "toàn", "trung", "cận", "đặc tả"]],
  ["people", tr("Số người"), ["không", "một", "hai", "nhóm", "đám đông"]],
  ["place", tr("Nơi"), ["ngoài trời", "trong nhà"]],
  ["text_present", tr("Có chữ trên hình"), ["có", "không"]],
];

/** The operator says what is true of this beat. Each answer is a golden label every field is measured against. */
export function GoldenLabels({ assetId, beat, reload }: { assetId: string; beat: BeatView; reload: () => void }) {
  const p = (beat.profile ?? {}) as Record<string, P>;
  const held: Record<string, string> = { shot_size: String(p.shot_size?.value ?? ""), people: String(p.people?.value ?? ""), place: String(p.place?.value ?? ""),
                                         text_present: p.text?.value ? "có" : beat.profile && Object.keys(beat.profile).length ? "không" : "" };
  const given = Object.fromEntries((beat.golden ?? []).map((g) => [g.field, g.value]));
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const value = (f: string) => draft[f] ?? given[f] ?? held[f] ?? "";
  const save = async () => {
    setBusy(true);
    const labels = GOLDEN.map(([f]) => ({ t_start: beat.t_start, t_end: beat.t_end, field: f, value: value(f) })).filter((l) => l.value);
    await post(`/api/v1/assets/${assetId}/golden`, { labels }).catch(() => {});
    setDraft({}); setBusy(false); reload();
  };
  return (
    <details className="text-[12px]">
      <summary className="cursor-pointer list-none text-accent">{(beat.golden ?? []).length ? tv`Đáp án của bạn cho nhịp này (${(beat.golden ?? []).length} trường)` : tr("Ghi đáp án đúng cho nhịp này")}</summary>
      <p className="mt-1 text-faint">{tr("Mỗi đáp án dùng để đo độ chính xác của hệ thống. Ô đã điền sẵn giá trị hệ thống đang giữ: sửa ô sai rồi lưu.")}</p>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        {GOLDEN.map(([f, name, values]) => (
          <label key={f} className="grid gap-0.5"><span className="text-faint">{name}{given[f] ? " ✓" : ""}</span>
            <select className="h-8 rounded-md border border-line bg-raised px-1.5" value={value(f)} onChange={(e) => setDraft({ ...draft, [f]: e.target.value })}>
              <option value="">–</option>{values.map((v) => <option key={v} value={v}>{v}</option>)}
            </select></label>))}
        <Button size="sm" busy={busy} onClick={save}>{tr("Lưu đáp án")}</Button>
      </div>
    </details>
  );
}

type FieldRow = { field: string; name: string; source: string; bar: number; status: string; labels?: number; answered?: number; coverage?: number | null; accuracy?: number | null; within_one?: number | null;
  calibration?: Record<string, { right: number; wrong: number; share: number }>; calibrated?: boolean; confusion?: Record<string, number>; mistakes?: { t_start: number; truth: string; held: string }[] };
const STATUS: Record<string, [string, "proof" | "cue" | "tally" | "mute"]> = { released: [tr("Đã phát hành"), "proof"], trial: [tr("Thử nghiệm"), "cue"], withdrawn: [tr("Đã rút"), "tally"] };

/** How right each field has been against the operator's answers, and whether matching may rely on it. */
export function FieldAccuracy() {
  const { data, reload } = usePoll<{ fields: FieldRow[]; labels: number; min_labels: number; runs: { run_id: string; created_at: number }[]; regressions: { field: string; before: number; now: number }[] }>("/api/v1/fields", 20000);
  const [busy, setBusy] = useState(false);
  const pct = (v?: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);
  const measure = async () => { setBusy(true); await post("/api/v1/fields/measure").catch(() => {}); setBusy(false); reload(); };
  return (
    <div className="panel p-5">
      <div className="mb-3 flex flex-wrap items-start gap-3">
        <div className="min-w-0 grow basis-60"><h2 className="text-[15px] font-semibold">{tr("Độ chính xác từng trường")}</h2>
          <p className="mt-0.5 max-w-2xl text-[13px] text-mute">{tv`So từng trường với đáp án bạn ghi ở Thư viện. Một trường chỉ được dùng để chọn clip khi đúng đủ thường xuyên trên ít nhất ${data?.min_labels ?? 10} đáp án. Đang có ${data?.labels ?? 0} đáp án.`}</p></div>
        <Button kind="ai" busy={busy} onClick={measure}>{tr("Đo độ chính xác")}</Button>
      </div>
      {!!data?.regressions.length && <p className="mb-2 text-[13px] text-tally">{tr("Kém đi so với lần đo trước:")} {data.regressions.map((r) => `${r.field} ${pct(r.before)} → ${pct(r.now)}`).join("; ")}</p>}
      <div className="scroll-x">
        <table className="w-full min-w-[640px] text-[12.5px]">
          <thead className="text-left text-faint"><tr><th className="py-1.5 font-normal">{tr("Trường")}</th><th className="font-normal">{tr("Nguồn")}</th><th className="font-normal">{tr("Đáp án")}</th><th className="font-normal">{tr("Đúng")}</th><th className="font-normal">{tr("Ngưỡng")}</th><th className="font-normal">{tr("“Chắc” đúng")}</th><th className="font-normal">{tr("Trạng thái")}</th></tr></thead>
          <tbody className="rows">
            {data?.fields.map((f) => (
              <tr key={f.field} className="align-top">
                <td className="py-1.5 pr-2">{f.name}{f.within_one != null && <span className="block text-faint">{tv`lệch tối đa một bậc: ${pct(f.within_one)}`}</span>}
                  {!!f.mistakes?.length && <details><summary className="cursor-pointer list-none text-accent">{tv`${f.mistakes.length} chỗ sai`}</summary>
                    <ul className="text-faint">{f.mistakes.slice(0, 8).map((x, i) => <li key={i}>{timecode(x.t_start)}: {tv`đúng là ${x.truth}, hệ thống giữ ${x.held}`}</li>)}</ul></details>}</td>
                <td className="pr-2 text-mute">{SOURCE[f.source] ?? f.source}</td>
                <td className="mono pr-2">{f.answered ?? 0}{f.coverage != null && f.coverage < 1 && <span className="block text-faint">{tv`trả lời ${pct(f.coverage)}`}</span>}</td>
                <td className="mono pr-2">{pct(f.accuracy)}</td>
                <td className="mono pr-2 text-faint">{pct(f.bar)}</td>
                <td className="mono pr-2">{f.calibration?.high ? `${pct(f.calibration.high.share)} (${f.calibration.high.right + f.calibration.high.wrong})` : "–"}</td>
                <td><Tag tone={(STATUS[f.status] ?? STATUS.trial)[1]}>{(STATUS[f.status] ?? STATUS.trial)[0]}</Tag></td>
              </tr>))}
          </tbody>
        </table>
      </div>
      {!!data?.runs.length && <p className="mt-2 text-[12px] text-faint">{tr("Lần đo gần nhất:")} {new Date(data.runs[0].created_at * 1000).toLocaleString(locale)}</p>}
    </div>
  );
}

type FlagRow = { moment_id: string; index: number; asset_id: string; name: string; t_start: number; t_end: number; rule: string; message: string; text: string; frame: string | null };

/** The review queue: only the beats where a model's words disagree with what was measured, not the whole library. */
export function ReviewQueue() {
  const { data, reload } = usePoll<{ flags: FlagRow[]; total: number; by_rule: Record<string, number> }>("/api/v1/flags", 15000);
  const settle = async (f: FlagRow, state: string) => { await call("/api/v1/flags", { method: "POST", body: JSON.stringify({ moment_id: f.moment_id, index: f.index, state }) }).catch(() => {}); reload(); };
  return (
    <div className="panel p-5">
      <h2 className="text-[15px] font-semibold">{tr("Hàng chờ xem lại")}</h2>
      <p className="mt-0.5 max-w-2xl text-[13px] text-mute">{tr("Những nhịp mà lời mô hình trái với số đo hoặc nhận diện của máy. Xem khung hình, rồi chọn: đã xử lý (bạn đã sửa, hoặc mô hình đúng) hay bỏ qua.")}</p>
      {data && <p className="mt-2 flex flex-wrap gap-1.5 text-[12px]">{Object.entries(data.by_rule).map(([r, n]) => <Tag key={r} tone="cue">{`${r}: ${n}`}</Tag>)}{data.total === 0 && <span className="text-faint">{tr("Không có cờ nào đang mở.")}</span>}</p>}
      <ul className="rows mt-3">
        {data?.flags.slice(0, 60).map((f) => (
          <li key={`${f.moment_id}-${f.index}`} className="flex flex-wrap items-start gap-3 py-2.5 text-[12.5px]">
            {f.frame && <img src={`/api/v1/moments/${f.moment_id}/frame`} alt="" className="h-16 w-28 shrink-0 rounded-md border border-line object-cover" loading="lazy" />}
            <div className="min-w-0 flex-1 basis-60">
              <p className="flex flex-wrap items-baseline gap-2"><Tag tone="cue">{f.rule}</Tag><span className="truncate">{f.name}</span><span className="mono text-faint">{timecode(f.t_start)}</span></p>
              <p className="mt-0.5">{f.message}</p>
              <p className="mt-0.5 line-clamp-2 text-faint">{f.text}</p>
            </div>
            <div className="flex shrink-0 gap-3"><button type="button" className="link" onClick={() => settle(f, "resolved")}>{tr("Đã xử lý")}</button><button type="button" className="link" onClick={() => settle(f, "ignored")}>{tr("Bỏ qua")}</button></div>
          </li>))}
      </ul>
    </div>
  );
}

type AssetProfileView = { asset: { duration: number; orientation: string; language: string | null; log_profile: boolean;
    pacing: { shots: number; cuts_per_minute: number; shot_median: number | null; transitions: Record<string, number> };
    hook: { first_word_at: number | null; face_in_first_3s: boolean; text_in_first_3s: boolean; strength: string; sound_early: string[] };
    calls_to_action: string[]; platforms: Record<string, { fits: string; reasons: string[] }>;
    style: { shot_sizes: Record<string, number>; camera: Record<string, number>; look: Record<string, number>; palette: Record<string, number>; speech_share: number; music_share: number; loudness_lufs: number | null; captions: unknown };
    loudness: { integrated?: number | null; range?: number | null; true_peak?: number | null }; quality: { beats_with_flaws: number; beats: number; watermark: boolean };
    sound: Record<string, number> };
  text_spans: { text: string; start: number; kind: string }[]; recognised: boolean };
type ScenesView = { scenes: { number: number; name: string; why: string[]; assets: string[]; beats: { asset_id: string; start: number; end: number }[] }[] };

const share = (o: Record<string, number>) => Object.entries(o).map(([k, v]) => `${CAMERA[k] ?? k} ${Math.round(v * 100)}%`).join(", ");
const FIT: Record<string, "proof" | "cue" | "tally"> = { "tốt": "proof", "được, cần sửa": "cue", "kém": "tally" };

/** The profile of the whole recording: how it is cut, how it opens, which platforms it suits, its style, and its scenes. */
export function AssetProfile({ assetId }: { assetId: string }) {
  const { data } = usePoll<AssetProfileView>(`/api/v1/assets/${assetId}/profile`, 30000);
  const { data: scenes } = usePoll<ScenesView>(`/api/v1/assets/${assetId}/scenes`, 60000);
  if (!data?.asset) return null;
  const a = data.asset;
  const mine = scenes?.scenes.filter((s) => s.assets.includes(assetId)) ?? [];
  return (
    <details className="rounded-lg border border-line bg-raised/30 p-2.5 text-[12.5px]">
      <summary className="cursor-pointer list-none"><span className="eyebrow">{tr("Hồ sơ của cả video")}</span>
        <span className="ml-2 text-faint">{tv`${a.orientation}, ${a.pacing.shots} cú máy, mở đầu ${a.hook.strength}`}{a.log_profile ? tr(", quay log") : ""}</span></summary>
      <dl className="mt-2 grid gap-x-4 gap-y-1.5 sm:grid-cols-[9rem_1fr]">
        <dt className="text-faint">{tr("Nhịp dựng")}</dt><dd>{tv`${a.pacing.cuts_per_minute} lần cắt mỗi phút; cú máy dài trung bình ${a.pacing.shot_median ?? "–"} giây`}</dd>
        <dt className="text-faint">{tr("Ba giây đầu")}</dt><dd>{[a.hook.first_word_at != null ? tv`lời đầu ở giây ${a.hook.first_word_at}` : tr("không có lời"), a.hook.face_in_first_3s ? tr("có mặt người") : tr("không có mặt người"), a.hook.text_in_first_3s ? tr("có chữ") : tr("không có chữ")].join("; ")}</dd>
        <dt className="text-faint">{tr("Nền tảng")}</dt><dd className="flex flex-wrap gap-1.5">{Object.entries(a.platforms).map(([name, f]) => <span key={name} title={f.reasons.join("; ")}><Tag tone={FIT[f.fits] ?? "mute"}>{`${name}: ${f.fits}`}</Tag></span>)}</dd>
        <dt className="text-faint">{tr("Phong cách")}</dt><dd>{[share(a.style.shot_sizes), share(a.style.camera), share(a.style.look)].filter(Boolean).join(" · ")}</dd>
        <dt className="text-faint">{tr("Màu")}</dt><dd>{Object.entries(a.style.palette).map(([k, v]) => `${k} ${Math.round(v * 100)}%`).join(", ")}</dd>
        <dt className="text-faint">{tr("Âm thanh")}</dt><dd>{[a.loudness.integrated != null ? `${a.loudness.integrated} LUFS` : null, a.loudness.true_peak != null ? tv`đỉnh ${a.loudness.true_peak} dBTP` : null,
          tv`lời nói ${Math.round(a.style.speech_share * 100)}%`, tv`nhạc ${Math.round(a.style.music_share * 100)}%`, Object.entries(a.sound).filter(([k]) => k !== "lời nói").map(([k, v]) => `${k} ${v}s`).join(", ")].filter(Boolean).join("; ")}</dd>
        {a.calls_to_action.length > 0 && <><dt className="text-faint">{tr("Kêu gọi hành động")}</dt><dd>{a.calls_to_action.join(", ")}</dd></>}
        <dt className="text-faint">{tr("Chất lượng")}</dt><dd>{tv`${a.quality.beats_with_flaws}/${a.quality.beats} nhịp có lỗi kỹ thuật`}{a.quality.watermark ? tr("; có watermark") : ""}</dd>
        {data.text_spans.length > 0 && <><dt className="text-faint">{tr("Chữ trên hình")}</dt><dd>{data.text_spans.slice(0, 6).map((s) => `${timecode(s.start)} ${s.kind}: ${s.text || "(logo)"}`).join(" · ")}</dd></>}
        {mine.length > 0 && <><dt className="text-faint">{tr("Phân cảnh")}</dt><dd>{mine.map((s) => <span key={s.number} className="mr-3 inline-block">{tv`#${s.number} ${s.name}`}{s.assets.length > 1 ? tv` (${s.assets.length} file)` : ""}</span>)}</dd></>}
        {!data.recognised && <><dt /><dd className="text-faint">{tr("Máy này chưa có bộ nhận diện của Apple: người, chữ và âm thanh chưa được nhận diện.")}</dd></>}
      </dl>
    </details>
  );
}
