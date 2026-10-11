import { STAGE_NAMES, STATUS_NAMES, timecode, type Asset, type Shot, type Stage } from "./api";

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

export function Button({ children, onClick, kind = "plain", disabled, size = "md" }: { children: React.ReactNode; onClick?: () => void; kind?: "plain" | "primary" | "danger" | "quiet"; disabled?: boolean; size?: "sm" | "md" }) {
  const look = kind === "primary" ? "bg-ink text-canvas hover:bg-white disabled:bg-raised disabled:text-faint"
    : kind === "danger" ? "border border-tally/70 text-tally hover:bg-tally hover:text-canvas disabled:opacity-40"
    : kind === "quiet" ? "text-mute hover:bg-raised hover:text-ink disabled:opacity-40"
    : "border border-line bg-surface hover:border-faint hover:bg-raised disabled:text-faint disabled:hover:border-line disabled:hover:bg-surface";
  return <button type="button" onClick={onClick} disabled={disabled} className={`inline-flex shrink-0 items-center justify-center gap-2 rounded-md font-medium transition-colors ${size === "sm" ? "h-7 px-2.5 text-[13px]" : "h-9 px-3.5 text-sm"} ${look}`}>{children}</button>;
}

const ICONS: Record<string, string> = {
  home: "M3 9.5 10 4l7 5.5V16a1 1 0 0 1-1 1h-3.5v-4.5h-5V17H4a1 1 0 0 1-1-1V9.5Z",
  film: "M4 4h12a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1Zm2.5 0v12m7-12v12M3 8h3.5M3 12h3.5m7-4H17m-3.5 4H17",
  clapper: "M3 8.5h14V16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8.5Zm0 0 .6-3.2a1 1 0 0 1 1.2-.8L16.5 6.6l.5 1.9M7 5l1.6 3.5M11.2 5.8l1.6 2.7",
  pulse: "M2.5 10h3.2l2-5 3.4 10 2.2-5h4.2",
  gauge: "M4.2 14.5a7 7 0 1 1 11.6 0M10 11l3.2-3.6M10 11.4a.4.4 0 1 0 0-.8.4.4 0 0 0 0 .8Z",
  bell: "M5.5 8.5a4.5 4.5 0 0 1 9 0c0 3.5 1.5 4.5 1.5 5.5H4c0-1 1.5-2 1.5-5.5ZM8.3 16.5a1.8 1.8 0 0 0 3.4 0",
  sliders: "M4 6h7m3 0h2M4 10h2m3 0h7M4 14h8m3 0h1M12.5 4.5v3m-5 1v3m6 1v3",
  plus: "M10 4.5v11M4.5 10h11",
  search: "M8.8 14.1a5.3 5.3 0 1 0 0-10.6 5.3 5.3 0 0 0 0 10.6Zm3.9-1.4 3.8 3.8",
  back: "M11.5 5 6.5 10l5 5",
  wave: "M3 10v0m2.8-3v6m2.8-9v12m2.8-8.5v5m2.8-8v11M17 9v2",
  spark: "M10 3.5 11.6 8l4.9 1.9-4.9 1.9L10 16.5l-1.6-4.7L3.5 9.9 8.4 8 10 3.5Z",
};

/** Line icons drawn for this interface: 20 units square, one stroke weight. */
export function Icon({ name, size = 16 }: { name: keyof typeof ICONS | string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="shrink-0"><path d={ICONS[name] ?? ""} /></svg>;
}

/** Every screen: a fixed bar with its name, what it is for and its main action; the content scrolls beneath it. */
export function Page({ title, note, actions, back, children, wide = false, flush = false }: { title: React.ReactNode; note?: React.ReactNode; actions?: React.ReactNode;
  back?: { label: string; onClick: () => void }; children: React.ReactNode; wide?: boolean; flush?: boolean }) {
  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex min-h-[64px] shrink-0 flex-wrap items-center gap-x-6 gap-y-2 border-b border-line px-4 py-3 md:px-8">
        <div className="min-w-0 flex-1">
          {back && <button type="button" onClick={back.onClick} className="-ml-1 mb-0.5 flex items-center gap-1 text-[13px] text-mute hover:text-ink"><Icon name="back" size={14} />{back.label}</button>}
          <h1 className="truncate text-xl font-semibold">{title}</h1>
          {note && <p className="truncate text-[13px] text-mute">{note}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </header>
      <div className={`min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden ${flush ? "" : "px-4 py-6 md:px-8 md:py-7"}`}><div className={`rise min-w-0 ${flush ? "h-full" : wide ? "max-w-[1800px]" : "max-w-[1400px]"}`}>{children}</div></div>
    </section>
  );
}

/** A titled block of a screen. */
export function Section({ title, note, actions, children }: { title: string; note?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
        <div className="min-w-0"><h2 className="text-[15px] font-semibold">{title}</h2>{note && <p className="max-w-2xl text-[13px] text-mute">{note}</p>}</div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

/** A small label for a state. Amber only ever means: this waits for the operator. */
export function Tag({ tone = "mute", children }: { tone?: "mute" | "cue" | "proof" | "tally"; children: React.ReactNode }) {
  const look = { mute: "bg-raised text-mute", cue: "bg-cue/15 text-cue", proof: "bg-proof/15 text-proof", tally: "bg-tally/15 text-tally" }[tone];
  return <span className={`inline-flex h-6 items-center whitespace-nowrap rounded-full px-2.5 text-[12px] font-medium ${look}`}>{children}</span>;
}

/** A cut at a glance: one frame per shot, each as wide as it lasts. The signature of this interface. */
export function Filmstrip({ shots, height = 56, numbered = false }: { shots: Shot[]; height?: number; numbered?: boolean }) {
  const items = shots.map((s) => {
    const sel = s.selection;
    const d = sel && sel.t_in != null && sel.t_out != null && sel.t_out > sel.t_in ? sel.t_out - sel.t_in : Math.max(2.5, s.text.split(/\s+/).length / 2.6);
    const src = sel && sel.status !== "gap" ? sel.frame_url ?? sel.asset?.thumbnail_url ?? s.keyframe_url : s.keyframe_url;
    return { s, d, src, gap: !sel || sel.status === "gap" };
  });
  const total = items.reduce((sum, i) => sum + i.d, 0) || 1;
  if (!items.length) return <div className="hatch rounded bg-raised/60" style={{ height }} />;
  return (
    <div className="filmstrip" style={{ height }} role="img" aria-label={`Dải phim ${items.length} cảnh`}>
      {items.map(({ s, d, src, gap }, i) => (
        <div key={s.shot_id} title={`${i + 1}. ${s.text}`} style={{ width: `${(d / total) * 100}%` }} className={`relative ${gap && !src ? "hatch bg-raised" : "bg-black"}`}>
          {src && <img src={src} alt="" loading="lazy" className="h-full w-full object-cover" />}
          {numbered && <span className="tc absolute left-1 top-1 rounded-sm bg-canvas/80 px-1 text-[11px] leading-4">{i + 1}</span>}
        </div>
      ))}
    </div>
  );
}

/** The five stages of a video, filled up to where the project stands. */
export function Steps({ step, tone }: { step: number; tone: string }) {
  return <div className="flex gap-1" role="img" aria-label={`Đã qua ${Math.min(step, 5)} trên 5 công đoạn`}>{[0, 1, 2, 3, 4].map((i) => <span key={i} className={`h-1 w-5 rounded-full ${i < step ? "bg-proof" : i === step ? (tone === "cue" ? "bg-cue" : tone === "tally" ? "bg-tally" : "bg-ink") : "bg-line"}`} />)}</div>;
}
