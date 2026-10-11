import { STAGE_NAMES, STATUS_NAMES, timecode, type Asset, type Stage } from "./api";

/** The time bar of a clip: what can be used, what is black, what is frozen. The one loud element of the interface. */
export function RangeStrip({ asset, playhead, onSeek, tall = false }: { asset: Asset; playhead?: number; onSeek?: (t: number) => void; tall?: boolean }) {
  const d = asset.duration ?? 0;
  if (!d) return <div className="h-2 rounded-sm bg-raised" />;
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / d) * 100))}%`;
  const span = ([a, b]: number[]) => ({ left: pct(a), width: `${Math.max(0.4, ((b - a) / d) * 100)}%` });
  const minutes = Array.from({ length: Math.floor(d / 60) }, (_, i) => (i + 1) * 60);
  return (
    <div>
      <div
        className={`relative overflow-hidden rounded-sm bg-raised ${tall ? "h-7" : "h-2"} ${onSeek ? "cursor-pointer" : ""}`}
        onClick={(e) => { if (!onSeek) return; const r = e.currentTarget.getBoundingClientRect(); onSeek(((e.clientX - r.left) / r.width) * d); }}
        role={onSeek ? "slider" : "img"} aria-label="Thanh thời gian của video" aria-valuemin={0} aria-valuemax={d} aria-valuenow={playhead ?? 0}
      >
        {asset.usable_ranges.map((r, i) => <div key={`u${i}`} className="absolute inset-y-0 bg-ink/80" style={span(r)} />)}
        {asset.black_ranges.map((r, i) => <div key={`b${i}`} className="hatch absolute inset-y-0 bg-canvas" style={span(r)} title="Khung đen, không dùng được" />)}
        {asset.frozen_ranges.map((r, i) => <div key={`f${i}`} className="dots absolute inset-y-0 bg-raised/90" style={span(r)} title="Hình đứng yên" />)}
        {tall && minutes.map((m) => <div key={m} className="absolute inset-y-0 w-px bg-canvas/60" style={{ left: pct(m) }} />)}
        {playhead != null && <div className="absolute inset-y-0 w-0.5 bg-cue" style={{ left: pct(playhead) }} />}
      </div>
      {tall && (
        <div className="tc relative mt-1 h-4 text-[11px] text-mute">
          <span className="absolute left-0">0:00</span>
          {minutes.filter((m) => m / d < 0.93).map((m) => <span key={m} className="absolute -translate-x-1/2" style={{ left: pct(m) }}>{timecode(m)}</span>)}
          <span className="absolute right-0">{timecode(d)}</span>
        </div>
      )}
    </div>
  );
}

const TONE: Record<string, string> = {
  succeeded: "bg-proof", skipped: "bg-line", running: "bg-ink animate-pulse", ready: "bg-mute", pending: "bg-line",
  retry_wait: "bg-mute", waiting_review: "bg-cue", blocked: "bg-cue", failed: "bg-tally", cancelled: "bg-line",
};

/** One segment per stage, in the order the pipeline declared them. */
export function StageRail({ stages }: { stages: Stage[] }) {
  return (
    <div className="flex gap-0.5" role="list" aria-label="Các bước">
      {stages.map((s) => (
        <div key={s.stage_id} role="listitem" title={`${STAGE_NAMES[s.stage_key] ?? s.stage_key}: ${STATUS_NAMES[s.status] ?? s.status}`}
             className={`h-1.5 flex-1 rounded-full ${TONE[s.status] ?? "bg-line"}`} />
      ))}
    </div>
  );
}

export function StatusText({ status }: { status: string }) {
  const tone = status === "succeeded" ? "text-proof" : status === "failed" ? "text-tally"
    : status === "blocked" || status === "waiting_review" ? "text-cue" : "text-mute";
  return <span className={tone}>{STATUS_NAMES[status] ?? status}</span>;
}

export function Button({ children, onClick, kind = "plain", disabled }: { children: React.ReactNode; onClick?: () => void; kind?: "plain" | "primary" | "danger"; disabled?: boolean }) {
  const look = kind === "primary" ? "bg-ink text-canvas hover:bg-white" : kind === "danger" ? "border border-tally text-tally hover:bg-tally hover:text-canvas" : "border border-line hover:border-mute";
  return <button type="button" onClick={onClick} disabled={disabled} className={`rounded px-3 py-1.5 text-sm font-medium transition-colors disabled:opacity-40 ${look}`}>{children}</button>;
}
