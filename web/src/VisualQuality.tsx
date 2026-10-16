import { t as tr, tv } from "./i18n";
import { useState } from "react";
import { call, post, timecode, usePoll } from "./api";
import { Button, Tag } from "./parts";

/* Visual Quality on screen (design 2026-10-16): what the source is, what is wrong with it shot by shot, the recipe that puts
   it right (each step with why, and a switch), a preview before and after with its temporal checks, and approval. Nothing
   is applied to a cut or an extract until the recipe is approved. */

type Step = { op: string; tier?: string; params: Record<string, unknown>; why?: string; off?: boolean; generative?: boolean;
  checked?: { niqe_without?: number; niqe_with?: number; niqe_classic?: number; niqe_ai?: number } };
type Shot = { t_start: number; t_end: number; steps: Step[]; defects: { kind: string; severity: number }[]; dropped?: { op: string; why: string }[] };
type Preview = { preview_id: string; t: number; seconds: number; qa: { verdict: string; reasons: string[]; metrics: Record<string, [number | null, number | null]> }; urls: Record<string, string> };
type View = {
  profile: { encoding_name: string | null; encoding_confidence: string; content: string; warnings: string[]; technical: Record<string, unknown> } | null;
  recipe: { recipe_id: string; version: number; status: string; decided_by: string | null; shots: Shot[]; notes: string[] } | null;
  approved: string | null; previews: Preview[];
};

const OP: Record<string, string> = {
  color_transform: tr("chuyển màu"), tonemap: tr("HDR về SDR"), levels: tr("phơi sáng, cân bằng trắng"), denoise: tr("khử nhiễu"), sharpen: tr("làm nét"),
  deblock: tr("giảm khối nén"), deband: tr("giảm dải màu"), deflicker: tr("giảm nhấp nháy"), stabilise: tr("ổn định hình"), deinterlace: tr("khử xen kẽ dòng"),
  constant_rate: tr("tốc độ khung cố định"), upscale: tr("phóng to"), interpolate: tr("nội suy khung"), ivtc: tr("bỏ telecine"), restore: tr("phục hồi ảnh nén"), faces: tr("phục hồi khuôn mặt"),
};
const DEFECT: Record<string, string> = {
  noise: tr("nhiễu"), soft: tr("mềm"), blocking: tr("khối nén"), banding: tr("dải màu"), underexposed: tr("thiếu sáng"), overexposed: tr("cháy sáng"),
  crushed: tr("mất chi tiết tối"), flicker: tr("nhấp nháy"), shake: tr("rung"), cast: tr("ám màu"), dull: tr("màu nhạt"), flat: tr("phẳng"),
};
const VERDICT: Record<string, "proof" | "cue" | "tally"> = { pass: "proof", warn: "cue", fail: "tally" };
const CONTENT: Record<string, string> = { camera: tr("footage máy quay"), screen: tr("quay màn hình"), graphics: tr("đồ hoạ"), ai: tr("video AI sinh"), still: tr("ảnh tĩnh") };

export function AssetVQ({ assetId, seek }: { assetId: string; seek?: (t: number) => void }) {
  const { data, reload } = usePoll<View>(`/api/v1/assets/${assetId}/vq`, 5000);
  const [note, setNote] = useState<string | null>(null);
  const act = async (url: string, body?: object, done?: string) => {
    setNote(null);
    try { await post(url, body ?? {}); if (done) setNote(done); reload?.(); } catch (e) { setNote((e as Error).message); }
  };
  const toggle = async (shot: number, step: number, off: boolean) => {
    if (!data?.recipe) return;
    try {
      await call(`/api/v1/vq/recipes/${data.recipe.recipe_id}/shots/${shot}/steps/${step}`, { method: "PATCH", body: JSON.stringify({ off }) });
      reload?.();
    } catch (e) { setNote((e as Error).message); }
  };
  if (!data) return null;
  const p = data.profile, r = data.recipe, shown = data.previews[0];
  return (
    <details className="rounded-lg border border-line bg-raised/30 p-2.5 text-[12.5px]">
      <summary className="cursor-pointer list-none"><span className="eyebrow">{tr("Chất lượng hình")}</span>
        <span className="ml-2 text-faint">{p ? `${p.encoding_name ?? tr("profile màu chưa rõ")} · ${CONTENT[p.content] ?? p.content}` : tr("chưa phân tích")}
          {r ? ` · ${tv`công thức v${r.version}`} ${r.status === "approved" ? tr("đã duyệt") : r.status === "rejected" ? tr("đã bỏ") : tr("chờ duyệt")}` : ""}</span></summary>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={() => act(`/api/v1/assets/${assetId}/vq/plan`, {}, tr("Đã xếp việc phân tích chất lượng hình."))}>{p ? tr("Phân tích lại") : tr("Phân tích chất lượng hình")}</Button>
        {r && <Button size="sm" kind="quiet" onClick={() => act(`/api/v1/assets/${assetId}/vq/preview`, { recipe_id: r.recipe_id }, tr("Đã xếp việc xem trước."))}>{tr("Xem trước")}</Button>}
        {r && r.status !== "approved" && <Button size="sm" kind="primary" onClick={() => act(`/api/v1/vq/recipes/${r.recipe_id}/approve`)}>{tr("Duyệt công thức")}</Button>}
        {r && r.status !== "rejected" && <Button size="sm" kind="quiet" onClick={() => act(`/api/v1/vq/recipes/${r.recipe_id}/reject`)}>{tr("Bỏ")}</Button>}
        {note && <span className="text-faint">{note}</span>}
      </div>
      {p && p.warnings.length > 0 && <ul className="mt-2 grid gap-0.5">{p.warnings.map((w) => <li key={w} className="text-cue">{w}</li>)}</ul>}
      {r && <ol className="mt-2 grid gap-2">{r.shots.map((s, k) => (
        <li key={k} className="rounded-md border border-line/60 p-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <button className="mono text-ink underline" onClick={() => seek?.(s.t_start)}>{`${timecode(s.t_start)}–${timecode(s.t_end)}`}</button>
            {s.defects.map((d) => <Tag key={d.kind} tone={d.severity > 0.6 ? "tally" : "cue"}>{`${DEFECT[d.kind] ?? d.kind} ${Math.round(d.severity * 100)}%`}</Tag>)}
          </div>
          {s.steps.length === 0 && <p className="mt-1 text-faint">{tr("Không cần xử lý.")}</p>}
          <ul className="mt-1 grid gap-0.5">{s.steps.map((st, j) => (
            <li key={j} className="flex flex-wrap items-baseline gap-2">
              <label className="flex items-center gap-1"><input type="checkbox" checked={!st.off} onChange={(e) => toggle(k, j, !e.target.checked)} />
                <span className={st.off ? "text-faint line-through" : "text-ink"}>{OP[st.op] ?? st.op}</span></label>
              {st.generative && <Tag tone="cue">{tr("AI sinh chi tiết")}</Tag>}
              <span className="text-faint">{st.why}
                {st.checked?.niqe_with != null ? tv` · NIQE ${st.checked.niqe_without} → ${st.checked.niqe_with}` : ""}
                {st.checked?.niqe_ai != null ? tv` · NIQE cổ điển ${st.checked.niqe_classic}, AI ${st.checked.niqe_ai}` : ""}</span>
            </li>))}</ul>
          {(s.dropped ?? []).map((d) => <p key={d.op} className="text-faint">{tv`Đã bỏ ${OP[d.op] ?? d.op}: ${d.why}`}</p>)}
        </li>))}</ol>}
      {shown && (
        <div className="mt-2 grid gap-1">
          <div className="flex flex-wrap items-center gap-2"><Tag tone={VERDICT[shown.qa.verdict] ?? "mute"}>{tv`kiểm tra: ${shown.qa.verdict}`}</Tag>
            <span className="text-faint">{shown.qa.reasons.join("; ") || tr("không thấy vấn đề theo thời gian")}</span></div>
          <div className="grid grid-cols-2 gap-1">
            {shown.urls.before_video ? <video src={shown.urls.before_video} controls muted loop className="w-full rounded" /> : <img src={shown.urls.before_still} alt="" className="w-full rounded" />}
            {shown.urls.after_video ? <video src={shown.urls.after_video} controls muted loop className="w-full rounded" /> : <img src={shown.urls.after_still} alt="" className="w-full rounded" />}
            <span className="text-center text-faint">{tr("trước")}</span><span className="text-center text-faint">{tr("sau")}</span>
          </div>
          <p className="text-faint">{Object.entries(shown.qa.metrics).filter(([, v]) => v[1] != null).map(([k, [b, a]]) => `${k} ${b ?? "–"}→${a}`).join(" · ")}</p>
        </div>
      )}
    </details>
  );
}
