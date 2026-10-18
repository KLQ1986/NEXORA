import { t as tr, tv, lang, setLang, type Lang } from "./i18n";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { STAGE_NAMES, STATUS_NAMES, timecode, type Asset, type Shot, type Stage } from "./api";

/** The time bar of a clip: what can be used, what is black, what is frozen. */
export function RangeStrip({ asset, playhead, onSeek, tall = false }: { asset: Asset; playhead?: number; onSeek?: (t: number) => void; tall?: boolean }) {
  const d = asset.duration ?? 0;
  if (!d) return <div className="h-1.5 rounded-full bg-raised" />;
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / d) * 100))}%`;
  const span = ([a, b]: number[]) => ({ left: pct(a), width: `${Math.max(0.4, ((b - a) / d) * 100)}%` });
  const step = d > 600 ? 120 : 60;
  const minutes = Array.from({ length: Math.floor(d / step) }, (_, i) => (i + 1) * step);
  return (
    <div>
      <div
        className={`relative overflow-hidden rounded-full bg-raised ${tall ? "h-8 rounded-md" : "h-1.5"} ${onSeek ? "cursor-pointer" : ""}`}
        onClick={(e) => { if (!onSeek) return; const r = e.currentTarget.getBoundingClientRect(); onSeek(((e.clientX - r.left) / r.width) * d); }}
        role={onSeek ? "slider" : "img"} aria-label={tr("Thanh thời gian của video")} aria-valuemin={0} aria-valuemax={d} aria-valuenow={playhead ?? 0}
      >
        {asset.usable_ranges.map((r, i) => <div key={`u${i}`} className={`absolute inset-y-0 ${tall ? "bg-accent/40" : "bg-accent/75"}`} style={span(r)} />)}
        {asset.black_ranges.map((r, i) => <div key={`b${i}`} className="hatch absolute inset-y-0 bg-canvas" style={span(r)} title={tr("Khung đen, không dùng được")} />)}
        {asset.frozen_ranges.map((r, i) => <div key={`f${i}`} className="dots absolute inset-y-0 bg-raised/90" style={span(r)} title={tr("Hình đứng yên")} />)}
        {tall && minutes.map((m) => <div key={m} className="absolute inset-y-0 w-px bg-canvas/70" style={{ left: pct(m) }} />)}
        {tall && (asset.scene_cuts ?? []).map((c) => <div key={`c${c}`} className="absolute inset-y-1 w-[2px] rounded-full bg-ink/70" style={{ left: pct(c) }} title={tv`Chuyển cảnh ở ${timecode(c)}`} />)}
        {playhead != null && <div className="absolute inset-y-0 w-0.5 bg-cue shadow-[0_0_8px_var(--color-cue)]" style={{ left: pct(playhead) }} />}
      </div>
      {tall && (
        <div className="mono relative mt-1.5 h-4 text-[10.5px] text-faint">
          <span className="absolute left-0">0:00</span>
          {minutes.filter((m) => m / d < 0.92 && m / d > 0.06).map((m) => <span key={m} className="absolute -translate-x-1/2" style={{ left: pct(m) }}>{timecode(m)}</span>)}
          <span className="absolute right-0">{timecode(d)}</span>
        </div>
      )}
    </div>
  );
}

const TONE: Record<string, string> = {
  succeeded: "bg-proof", skipped: "bg-edge", running: "working", ready: "bg-mute", pending: "bg-overlay",
  retry_wait: "bg-mute", waiting_review: "bg-cue", blocked: "bg-cue", failed: "bg-tally", cancelled: "bg-edge", queued: "bg-overlay",
};

/** One segment per stage, in the order the pipeline declared them. With `labels`, each segment is named underneath. */
export function StageRail({ stages, labels = false, name }: { stages: Stage[]; labels?: boolean; name?: (key: string) => string }) {
  return (
    <div className={`flex ${labels ? "gap-1.5" : "gap-[3px]"}`} role="list" aria-label={tr("Các bước")}>
      {stages.map((s) => {
        const label = name ? name(s.stage_key) : STAGE_NAMES[s.stage_key] ?? s.stage_key;
        return (
          <div key={s.stage_id} role="listitem" className="min-w-0 flex-1" title={`${label}: ${STATUS_NAMES[s.status] ?? s.status}`}>
            <div className={`h-1.5 rounded-full ${TONE[s.status] ?? "bg-overlay"}`} />
            {labels && <p className={`mt-1.5 truncate text-[11px] ${s.status === "running" ? "text-ink" : s.status === "failed" ? "text-tally" : s.status === "blocked" || s.status === "waiting_review" ? "text-cue" : "text-faint"}`}>{label}</p>}
          </div>
        );
      })}
    </div>
  );
}

export function StatusText({ status }: { status: string }) {
  const tone = status === "succeeded" ? "text-proof" : status === "failed" ? "text-tally"
    : status === "blocked" || status === "waiting_review" ? "text-cue" : "text-mute";
  return <span className={tone}>{STATUS_NAMES[status] ?? status}</span>;
}

type Kind = "plain" | "primary" | "danger" | "quiet" | "ai";
export function Button({ children, onClick, kind = "plain", disabled, busy, size = "md", title, type = "button" }: { children: React.ReactNode; onClick?: () => void; kind?: Kind; disabled?: boolean; busy?: boolean; size?: "sm" | "md"; title?: string; type?: "button" | "submit" }) {
  const look = kind === "primary" ? "brand-button"
    : kind === "danger" ? "border border-tally/50 bg-tally/10 text-tally hover:bg-tally hover:text-ink disabled:opacity-40"
    : kind === "quiet" ? "text-mute hover:bg-raised hover:text-ink disabled:opacity-40"
    : kind === "ai" ? "border border-ai/35 bg-ai/10 text-ai hover:bg-ai/20 disabled:opacity-40"
    : "border border-edge bg-raised text-ink hover:border-[#454c5c] hover:bg-overlay disabled:border-line disabled:text-faint disabled:hover:bg-raised";
  return <button type={type} title={title} onClick={onClick} disabled={disabled || busy} aria-busy={busy || undefined} className={`btn inline-flex shrink-0 items-center justify-center gap-2 rounded-lg font-medium ${size === "sm" ? "h-7 px-2.5 text-[12.5px]" : "h-9 px-3.5 text-[13.5px]"} ${look}`}>{busy && <Spinner size={size === "sm" ? 12 : 14} />}{children}</button>;
}

const ICONS: Record<string, string> = {
  screen: "M3.5 4.5h13a.5.5 0 0 1 .5.5v8.5a.5.5 0 0 1-.5.5h-13a.5.5 0 0 1-.5-.5V5a.5.5 0 0 1 .5-.5ZM7 17h6M10 14v3M8.5 7.3v4.4L12 9.5 8.5 7.3Z",
  pause: "M7 4.5v11M13 4.5v11",
  skipback: "M5 4.5v11M15 4.5 8 10l7 5.5v-11Z",
  skipfwd: "M15 4.5v11M5 4.5 12 10l-7 5.5v-11Z",
  loop: "M4 9.5V8.5a3 3 0 0 1 3-3h8.5m0 0-2-2m2 2-2 2M16 10.5v1a3 3 0 0 1-3 3H4.5m0 0 2 2m-2-2 2-2",
  volume: "M3.5 8h2.8l4.2-3.5v11L6.3 12H3.5a.5.5 0 0 1-.5-.5v-3a.5.5 0 0 1 .5-.5Zm9.5-.8a3.6 3.6 0 0 1 0 5.6m2-7.6a6.4 6.4 0 0 1 0 9.6",
  mute: "M3.5 8h2.8l4.2-3.5v11L6.3 12H3.5a.5.5 0 0 1-.5-.5v-3a.5.5 0 0 1 .5-.5Zm10 .2 3.4 3.6m0-3.6-3.4 3.6",
  expand: "M3.5 7.5v-4h4m5 0h4v4m0 5v4h-4m-5 0h-4v-4",
  copy: "M7 7h9v9.5H7zM4 13V3.5h9",
  comment: "M4 4.5h12a.5.5 0 0 1 .5.5v8a.5.5 0 0 1-.5.5H9.5L6 16.5v-3H4a.5.5 0 0 1-.5-.5V5a.5.5 0 0 1 .5-.5Z",
  calendar: "M4 5.5h12a.8.8 0 0 1 .8.8v9.4a.8.8 0 0 1-.8.8H4a.8.8 0 0 1-.8-.8V6.3a.8.8 0 0 1 .8-.8Zm-.8 3.6h13.6M6.8 3.5v3.2m6.4-3.2v3.2",
  radar: "M10 10 15 5.2M10 3.2a6.8 6.8 0 1 0 6.8 6.8M10 6.4A3.6 3.6 0 1 0 13.6 10",
  home: "M3.5 9 10 3.8 16.5 9v6.7a.8.8 0 0 1-.8.8H12.3v-4.3H7.7v4.3H4.3a.8.8 0 0 1-.8-.8V9Z",
  film: "M4 3.5h12a.5.5 0 0 1 .5.5v12a.5.5 0 0 1-.5.5H4a.5.5 0 0 1-.5-.5V4a.5.5 0 0 1 .5-.5Zm2.5 0v13m7-13v13M3.5 7.5h3m-3 5h3m7-5h3m-3 5h3",
  clapper: "M3.5 8.5h13V16a.5.5 0 0 1-.5.5H4a.5.5 0 0 1-.5-.5V8.5Zm0 0 .7-3.4a.8.8 0 0 1 1-.6l11 2.6.3 1.4M7.3 5l1.5 3.4m2.9-2.7 1.5 2.8",
  pulse: "M2.5 10h3.2l2-5 3.4 10 2.2-5h4.2",
  gauge: "M4.2 14.5a7 7 0 1 1 11.6 0M10 11l3.2-3.6M10 11.4a.4.4 0 1 0 0-.8.4.4 0 0 0 0 .8Z",
  bell: "M5.5 8.5a4.5 4.5 0 0 1 9 0c0 3.5 1.5 4.5 1.5 5.5H4c0-1 1.5-2 1.5-5.5ZM8.3 16.5a1.8 1.8 0 0 0 3.4 0",
  sliders: "M4 6h7m3 0h2M4 10h2m3 0h7M4 14h8m3 0h1M12.5 4.5v3m-5 1v3m6 1v3",
  plus: "M10 4.5v11M4.5 10h11",
  search: "M8.8 14.1a5.3 5.3 0 1 0 0-10.6 5.3 5.3 0 0 0 0 10.6Zm3.9-1.4 3.8 3.8",
  back: "M11.5 5 6.5 10l5 5",
  next: "m8.5 5 5 5-5 5",
  down: "m5 8 5 5 5-5",
  wave: "M3 10v0m2.8-3v6m2.8-9v12m2.8-8.5v5m2.8-8v11M17 9v2",
  spark: "M10 3 11.7 8.3 17 10l-5.3 1.7L10 17l-1.7-5.3L3 10l5.3-1.7L10 3Z",
  sparkles: "M8 3.5 9.3 7.7 13.5 9 9.3 10.3 8 14.5 6.7 10.3 2.5 9l4.2-1.3L8 3.5Zm7 8 .7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7.7-2Z",
  grid: "M4 4h5v5H4zM11 4h5v5h-5zM4 11h5v5H4zM11 11h5v5h-5z",
  list: "M7 5.5h9.5M7 10h9.5M7 14.5h9.5M3.5 5.5h.01M3.5 10h.01M3.5 14.5h.01",
  play: "M6.5 4.5v11l9-5.5-9-5.5Z",
  check: "m4.5 10.5 3.5 3.5 7.5-8",
  info: "M10 9v5m0-7.6v.1M17.5 10a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Z",
  alert: "M10 7.5v3.5m0 2.6v.1M8.7 3.6 2.9 14a1.5 1.5 0 0 0 1.3 2.2h11.6a1.5 1.5 0 0 0 1.3-2.2L11.3 3.6a1.5 1.5 0 0 0-2.6 0Z",
  x: "m5.5 5.5 9 9m0-9-9 9",
  undo: "M7.5 5 4 8.5 7.5 12M4 8.5h7.5a4 4 0 0 1 0 8H9",
  trash: "M4 6h12M8 6V4.5h4V6M5.5 6l.7 9.5h7.6l.7-9.5M8.5 9v4m3-4v4",
  folder: "M3 6a1 1 0 0 1 1-1h3.6l1.6 1.8H16a1 1 0 0 1 1 1V15a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6Z",
  star: "m10 3.3 2 4.3 4.6.5-3.4 3.2.9 4.6L10 13.6l-4.1 2.3.9-4.6-3.4-3.2 4.6-.5 2-4.3Z",
  clock: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm0-10.5V10l2.5 1.6",
  cpu: "M6 6h8v8H6zM8 2.5V6m4-3.5V6M8 14v3.5m4-3.5v3.5M2.5 8H6m-3.5 4H6m8-4h3.5M14 12h3.5",
  mic: "M10 12.5a2.5 2.5 0 0 0 2.5-2.5V5.5a2.5 2.5 0 1 0-5 0V10a2.5 2.5 0 0 0 2.5 2.5Zm-5-3a5 5 0 0 0 10 0M10 14.5v2.5",
  captions: "M3.5 5h13a.5.5 0 0 1 .5.5v9a.5.5 0 0 1-.5.5h-13a.5.5 0 0 1-.5-.5v-9a.5.5 0 0 1 .5-.5Zm2.5 7h3m2 0h3M6 9.5h8",
  music: "M7.5 14.5V5l9-1.5V13M7.5 14.5a2 2 0 1 1-4 0 2 2 0 0 1 4 0Zm9-1.5a2 2 0 1 1-4 0 2 2 0 0 1 4 0Z",
  image: "M4 4h12a.5.5 0 0 1 .5.5v11a.5.5 0 0 1-.5.5H4a.5.5 0 0 1-.5-.5v-11A.5.5 0 0 1 4 4Zm-.5 9 4-4 4.5 4.5 2-2 3 3M12.5 7.5h.01",
  layers: "m10 3 7 3.8-7 3.8-7-3.8L10 3Zm-7 7 7 3.8 7-3.8M3 13.3 10 17l7-3.7",
  bolt: "M11 2.5 4.5 11h5l-1 6.5L15.5 9h-5l.5-6.5Z",
  shield: "M10 2.8 16 5v4.7c0 3.6-2.6 6.4-6 7.5-3.4-1.1-6-3.9-6-7.5V5l6-2.2Z",
  disk: "M3.5 12V6a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v6m-13 0v2a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-2m-13 0h13M13.5 14h.01",
  download: "M10 3.5v9m-3.5-3.5L10 12.5 13.5 9M4 16.5h12",
  external: "M11.5 3.5h5v5m0-5-7 7M14 12v3.5a1 1 0 0 1-1 1H4.5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1H8",
  refresh: "M16 10a6 6 0 1 1-1.8-4.3M16 3.5V6.5h-3",
  scissors: "M6 8a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm0 0 10 7.5M6 12a2 2 0 1 0 0 4 2 2 0 0 0 0-4Zm0 0 10-7.5",
  timeline: "M3 5h7m3 0h4M3 10h3m3 0h8M3 15h9m3 0h2M10 3v4m-4 1v4m6 1v4",
  board: "M3.5 4h13a.5.5 0 0 1 .5.5v11a.5.5 0 0 1-.5.5h-13a.5.5 0 0 1-.5-.5v-11a.5.5 0 0 1 .5-.5ZM8 4v12m4.5-12v12",
  edit: "M12.5 4.5 15.5 7.5M4 16l.8-3.4 8.9-8.9a1.5 1.5 0 0 1 2.1 0l.5.5a1.5 1.5 0 0 1 0 2.1L7.4 15.2 4 16Z",
  power: "M10 3v6.5M6 5.6a6 6 0 1 0 8 0",
  collapse: "M3.5 4h13v12h-13zM8 4v12m4-7.5L10.5 10 12 11.5",
  command: "M7 7V5.5A1.5 1.5 0 1 0 5.5 7H7Zm0 0h6M7 7v6m6-6V5.5A1.5 1.5 0 1 1 14.5 7H13Zm0 0v6m0 0v1.5a1.5 1.5 0 1 0 1.5-1.5H13Zm0 0H7m0 0v1.5A1.5 1.5 0 1 1 5.5 13H7Z",
  eye: "M2.5 10s2.8-5.5 7.5-5.5 7.5 5.5 7.5 5.5-2.8 5.5-7.5 5.5S2.5 10 2.5 10Zm7.5 2.2a2.2 2.2 0 1 0 0-4.4 2.2 2.2 0 0 0 0 4.4Z",
  link: "M8.5 11.5a3 3 0 0 0 4.2 0l2.6-2.6a3 3 0 0 0-4.2-4.2l-.8.8m1.2 3a3 3 0 0 0-4.2 0l-2.6 2.6a3 3 0 0 0 4.2 4.2l.8-.8",
  globe: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm-7-7h14M10 3c-2 2-2.8 4.4-2.8 7s.8 5 2.8 7c2-2 2.8-4.4 2.8-7S12 5 10 3Z",
  user: "M10 10a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Zm-5.5 6.5a5.5 5.5 0 0 1 11 0",
  coins: "M8 8.5c2.8 0 5-1 5-2.2S10.8 4 8 4 3 5 3 6.3s2.2 2.2 5 2.2Zm-5-2.2v3c0 1.2 2.2 2.2 5 2.2s5-1 5-2.2v-3M7 14.2c.3 1 2.4 1.8 5 1.8 2.8 0 5-1 5-2.2v-3c0-1.1-1.8-2-4.2-2.2",
};

/** Line icons drawn for this interface: 20 units square, one stroke weight. */
export function Icon({ name, size = 16, className = "" }: { name: keyof typeof ICONS | string; size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`shrink-0 ${className}`}><path d={ICONS[name] ?? ""} /></svg>;
}

/** The operations section's side menu: the four screens that look after the machine. The open one may hang its own places beneath. */
export function OpsSide({ children }: { children?: React.ReactNode }) {
  const path = window.location.pathname;
  const items: [string, string, string][] = [["/phong-may", tr("Mission Control"), "gauge"], ["/tien-trinh", tr("Tiến trình"), "pulse"], ["/chi-phi", tr("Chi phí"), "coins"], ["/thong-bao", tr("Thông báo"), "bell"], ["/thung-rac", tr("Thùng rác"), "trash"], ["/he-thong", tr("Hệ thống"), "sliders"]];
  return (
    <SideGroup label={tr("Vận hành")}>
      {items.map(([to, label, icon]) => { const on = path.startsWith(to); return <SideLink key={to} label={label} icon={icon} on={on && !children} onClick={() => goTo(to)}>{on ? children : null}</SideLink>; })}
    </SideGroup>
  );
}

const scrolled = new Map<string, number>();

/* Where the screens move to. The shell hands its own router in, so a side menu built in a page can navigate like the top bar does. */
let navigate: (to: string) => void = (to) => { window.location.assign(to); };
export function setNavigator(f: (to: string) => void) { navigate = f; }
export const goTo = (to: string) => navigate(to);

/* The side menu can be folded away with "[" or its button; the choice is remembered on this machine. */
let sideHidden = (() => { try { return localStorage.getItem("nx.side") === "1"; } catch { return false; } })();
const sideListeners = new Set<() => void>();
export function toggleSide() { sideHidden = !sideHidden; try { localStorage.setItem("nx.side", sideHidden ? "1" : "0"); } catch { /* private window */ } sideListeners.forEach((l) => l()); }
export function useSideHidden() {
  const [, bump] = useState(0);
  useEffect(() => { const l = () => bump((n) => n + 1); sideListeners.add(l); return () => { sideListeners.delete(l); }; }, []);
  return sideHidden;
}

/** A heading inside the side menu, with an optional count or action at its end. */
export function SideGroup({ label, end, children }: { label?: React.ReactNode; end?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="mb-5 last:mb-0">
      {label && <p className="flex items-center justify-between gap-2 px-2.5 pb-1.5 text-[12px] text-faint">{label}{end}</p>}
      <div className="grid gap-0.5">{children}</div>
    </div>
  );
}

/** One place in the side menu. The current one is lit; a count sits at the end; places within it hang beneath on a thread. */
export function SideLink({ label, icon, lead, on, onClick, count, tone, small, title, children }: { label: React.ReactNode; icon?: string; lead?: React.ReactNode; on?: boolean; onClick: () => void;
  count?: number; tone?: "cue" | "ai" | "tally" | "proof"; small?: boolean; title?: string; children?: React.ReactNode }) {
  const badge = tone === "cue" ? "bg-cue/15 text-cue" : tone === "ai" ? "bg-ai/15 text-ai" : tone === "tally" ? "bg-tally/15 text-tally" : tone === "proof" ? "bg-proof/15 text-proof" : "bg-white/[0.06] text-mute";
  return (
    <>
      <button type="button" onClick={onClick} aria-current={on ? "page" : undefined} title={title}
              className={`flex w-full min-w-0 items-center gap-2.5 rounded-lg px-2.5 text-left transition-colors ${small ? "h-8 text-[13px]" : "h-9 text-[13.5px]"} ${on ? "bg-accent/10 font-medium text-accent shadow-[inset_0_0_0_1px_rgba(70,200,224,0.18)]" : "text-mute hover:bg-raised/60 hover:text-ink"}`}>
        {lead ?? (icon && <Icon name={icon} size={small ? 15 : 16} />)}<span className="min-w-0 flex-1 truncate">{label}</span>
        {count != null && count > 0 && <span className={`mono shrink-0 rounded-md px-1.5 text-[11px] font-medium leading-[18px] ${badge}`}>{count}</span>}
      </button>
      {children && <div className="mb-1 ml-[18px] grid gap-0.5 border-l border-line pl-2">{children}</div>}
    </>
  );
}

/** Every screen: the menu of its section down the side (when it has one), a slim bar with its facts and actions, and the content
 *  scrolling beneath. The section itself is named in the top bar, so the screen does not repeat its own name unless it is a
 *  single item (a project, a render) reached from a list. */
/** The section's side menu beside a screen that draws its own header (the storyboard): the same column as Page's, folded with it. */
export function SideFrame({ side, children }: { side: React.ReactNode; children: React.ReactNode }) {
  const hidden = useSideHidden();
  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      {!hidden && <aside aria-label={tr("Menu của mục này")} className="hidden w-[248px] shrink-0 overflow-y-auto overflow-x-hidden border-r border-line bg-surface/40 px-3 py-4 lg:block">{side}</aside>}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}

export function Page({ title, note, actions, back, tabs, side, children, wide = false, full = false, flush = false }: { title: React.ReactNode; eyebrow?: React.ReactNode; note?: React.ReactNode; actions?: React.ReactNode;
  back?: { label: string; onClick: () => void }; tabs?: React.ReactNode; side?: React.ReactNode; children: React.ReactNode; wide?: boolean; full?: boolean; flush?: boolean }) {
  // How wide the content may run: a reading measure, a wide one for work surfaces, or the whole window for the overview.
  const measure = full ? "max-w-none" : wide ? "max-w-[1600px]" : "max-w-[1240px]";
  // Coming back to a screen finds it where it was left.
  const scroller = useRef<HTMLDivElement>(null);
  const place = window.location.pathname + window.location.search;
  useEffect(() => {
    const el = scroller.current, y = scrolled.get(place);
    if (!el || !y) return;
    // Content often arrives a moment later, so wait until the screen is tall enough to land where it was.
    let n = 0, timer = 0;
    const land = () => { if (el.scrollHeight - el.clientHeight >= y || n++ > 30) el.scrollTop = y; else timer = window.setTimeout(land, 50); };
    land();
    return () => window.clearTimeout(timer);
  }, [place]);
  const hidden = useSideHidden();
  const [drawer, setDrawer] = useState(false);
  useEffect(() => { setDrawer(false); }, [place]);
  useEffect(() => { if (!drawer) return; const key = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawer(false); }; window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key); }, [drawer]);
  // A sentence about what the screen is for waits behind an (i); short facts stay in view.
  const explain = typeof note === "string" && note.length > 40;
  const facts = note && !explain ? note : null;
  // A bar with nothing but the (i) is not worth its height: then the screen starts straight with its content.
  const bar = !!(back || facts || actions);
  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      {side && !hidden && <aside aria-label={tr("Menu của mục này")} className="hidden w-[248px] shrink-0 overflow-y-auto overflow-x-hidden border-r border-line bg-surface/40 px-3 py-4 lg:block">{side}</aside>}
      {side && drawer && createPortal(
        <div className="fixed inset-0 z-50 lg:hidden" onClick={() => setDrawer(false)}><div className="scrim absolute inset-0" />
          <aside aria-label={tr("Menu của mục này")} className="drawer relative h-full w-[288px] max-w-[85vw] overflow-y-auto border-r border-line bg-surface px-3 py-4" onClick={(e) => e.stopPropagation()}>{side}</aside></div>, document.body)}
      <section className="flex min-h-0 min-w-0 flex-1 flex-col">
        <h1 className="sr-only">{title}</h1>
        {(bar || side) && (
          <header className={`h-12 shrink-0 items-center gap-3 border-b border-line px-4 md:px-8 ${bar ? (side || back ? "flex" : "hidden md:flex") : "flex lg:hidden"}`}>
            {side && <button type="button" onClick={() => setDrawer(true)} className="flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-line px-2.5 text-[12.5px] text-mute hover:bg-raised hover:text-ink lg:hidden" aria-label={tr("Mở menu của mục này")}><Icon name="sliders" size={14} />{tr("Menu mục")}</button>}
            {side && <button type="button" onClick={toggleSide} className="hidden h-8 w-8 shrink-0 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink lg:grid" title={hidden ? tr("Hiện menu bên (phím [)") : tr("Ẩn menu bên (phím [)")} aria-label={hidden ? tr("Hiện menu bên (phím [)") : tr("Ẩn menu bên (phím [)")}><Icon name="collapse" size={16} className={hidden ? "rotate-180" : ""} /></button>}
            {back && <button type="button" onClick={back.onClick} title={back.label} className="flex shrink-0 items-center gap-1 rounded-md text-[13px] text-mute transition-colors hover:text-ink"><Icon name="back" size={16} /><span className="hidden sm:inline">{back.label}</span></button>}
            {back && <><span className="hidden text-edge sm:inline">/</span><span className="display min-w-0 truncate text-[16px] leading-tight sm:max-w-[45%] sm:shrink-0">{title}</span></>}
            {explain && <Hint text={note as string}><span className="sr-only">{title}</span></Hint>}
            {facts && <div className="hidden min-w-0 items-center overflow-hidden whitespace-nowrap text-[13px] text-faint md:flex [&>*]:flex-nowrap">{facts}</div>}
            {actions && <div className="ml-auto hidden shrink-0 items-center gap-2 md:flex">{actions}</div>}
          </header>
        )}
        {tabs && <div className="shrink-0 border-b border-line px-4 md:px-8"><div className={`mx-auto ${measure}`}>{tabs}</div></div>}
        <div ref={scroller} onScroll={(e) => { scrolled.set(place, e.currentTarget.scrollTop); }} className={`min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden ${flush ? "" : "px-4 pb-12 pt-5 md:px-8 md:pt-6"}`}><div className={`min-w-0 ${flush ? "h-full" : `mx-auto ${measure}`}`}>
          {!flush && (facts || actions) && <div className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-3 md:hidden">{facts && <div className="min-w-0 text-[13px] text-mute">{facts}</div>}{actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}</div>}
          {children}</div></div>
      </section>
    </div>
  );
}

/** Underlined tabs under a page title. */
export function Tabs<T extends string>({ items, value, onChange }: { items: { key: T; label: string; icon?: string; count?: number }[]; value: T; onChange: (k: T) => void }) {
  // The chosen tab is brought into the row's view: a narrow row scrolls, and a tab chosen from elsewhere (a link, a key) may
  // sit past its end.
  const row = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = row.current;
    if (!el) return;
    const show = () => {                                  // the row alone scrolls, never the page around it
      const on = el.querySelector<HTMLElement>('[aria-selected="true"]');
      if (!on) return;
      const left = on.offsetLeft - el.offsetLeft, right = left + on.offsetWidth;
      if (left < el.scrollLeft) el.scrollLeft = left;
      else if (right > el.scrollLeft + el.clientWidth) el.scrollLeft = right - el.clientWidth;
    };
    show();
    const watch = new ResizeObserver(show);                // and again when the row is resized (a viewer going to theatre)
    watch.observe(el);
    return () => watch.disconnect();
  }, [value, items.length]);
  return (
    <div ref={row} className="scroll-x -mb-px flex gap-1" role="tablist">
      {items.map((t) => (
        <button key={t.key} type="button" role="tab" aria-selected={value === t.key} onClick={() => onChange(t.key)}
                className={`flex h-10 items-center gap-2 whitespace-nowrap border-b-2 px-3 text-[13.5px] transition-colors ${value === t.key ? "border-accent font-medium text-ink" : "border-transparent text-mute hover:text-ink"}`}>
          {t.icon && <Icon name={t.icon} size={15} />}{t.label}{t.count ? <span className="mono rounded bg-overlay px-1.5 text-[11px] leading-[18px] text-mute">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

/** A titled block of a screen. */
export function Section({ title, icon, note, actions, children }: { title: string; icon?: string; note?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode }) {
  // A sentence explaining what the section is for is read once, so it waits behind the title; short facts (counts, versions) stay in view.
  const explain = typeof note === "string" && note.length > 40;
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-1.5">
        <div className="min-w-0">
          {explain ? (
            <Hint text={note as string}><h2 className="flex cursor-default items-center gap-2 text-[15px] font-semibold">{icon && <Icon name={icon} size={16} className="text-mute" />}{title}</h2></Hint>
          ) : (
            <><h2 className="flex items-center gap-2 text-[15px] font-semibold">{icon && <Icon name={icon} size={16} className="text-accent" />}{title}</h2>{note && <div className="mt-0.5 max-w-2xl text-[13px] text-mute">{note}</div>}</>
          )}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}

/** Guidance that appears when the pointer rests on its label (or on tap / keyboard focus), instead of sitting on the page. */
export function Hint({ text, children }: { text: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="relative inline-flex items-center gap-1.5" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      {children}
      <button type="button" aria-label={tr("Giải thích")} aria-expanded={open} onClick={() => setOpen((o) => !o)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
              className={`grid h-5 w-5 place-items-center rounded-full transition-colors ${open ? "text-ink" : "text-faint hover:text-ink"}`}><Icon name="info" size={14} /></button>
      {open && <span role="tooltip" className="rise absolute left-0 top-full z-30 mt-2 w-80 max-w-[calc(100vw-2rem)] rounded-lg border border-edge bg-overlay px-3 py-2 text-[12.5px] font-normal leading-relaxed text-mute shadow-xl shadow-black/40">{text}</span>}
    </span>
  );
}

/** A small label for a state. Amber only ever means: this waits for the operator. */
export function Tag({ tone = "mute", children, dot = true }: { tone?: "mute" | "cue" | "proof" | "tally" | "ai" | "accent"; children: React.ReactNode; dot?: boolean }) {
  const look = { mute: "bg-overlay text-mute", cue: "bg-cue/12 text-cue", proof: "bg-proof/12 text-proof", tally: "bg-tally/12 text-tally", ai: "bg-ai/12 text-ai", accent: "bg-accent/15 text-accent" }[tone];
  const dotc = { mute: "bg-faint", cue: "bg-cue", proof: "bg-proof", tally: "bg-tally", ai: "bg-ai", accent: "bg-accent" }[tone];
  return <span className={`inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 text-[12px] font-medium ${look}`}>{dot && <span className={`h-1.5 w-1.5 rounded-full ${dotc}`} />}{children}</span>;
}

/** A cut at a glance: one frame per shot, each as wide as it lasts. */
export function Filmstrip({ shots, height = 56, numbered = false, className = "" }: { shots: Shot[]; height?: number | string; numbered?: boolean; className?: string }) {
  const items = shots.map((s) => {
    const sel = s.selection;
    const d = sel && sel.t_in != null && sel.t_out != null && sel.t_out > sel.t_in ? sel.t_out - sel.t_in : Math.max(2.5, s.text.split(/\s+/).length / 2.6);
    const src = sel && sel.status !== "gap" ? sel.frame_url ?? sel.asset?.thumbnail_url ?? s.keyframe_url : s.keyframe_url;
    return { s, d, src, gap: !sel || sel.status === "gap" };
  });
  const total = items.reduce((sum, i) => sum + i.d, 0) || 1;
  if (!items.length) return <div className={`grid place-items-center bg-raised text-faint ${className}`} style={{ height }}><Icon name="clapper" size={26} /></div>;
  return (
    <div className={`filmstrip ${className}`} style={{ height }} role="img" aria-label={tv`Dải phim ${items.length} cảnh`}>
      {items.map(({ s, d, src, gap }, i) => (
        <div key={s.shot_id} title={`${i + 1}. ${s.text}`} style={{ width: `${(d / total) * 100}%` }} className={`relative ${gap && !src ? "hatch bg-raised" : "bg-black"}`}>
          {src && <img src={src} alt="" loading="lazy" className="h-full w-full object-cover" />}
          {numbered && <span className="mono absolute left-1 top-1 rounded bg-black/70 px-1 text-[10px] leading-4">{i + 1}</span>}
        </div>
      ))}
    </div>
  );
}

/** The five stages of a video, filled up to where the project stands. */
export function Steps({ step, tone }: { step: number; tone: string }) {
  return <div className="flex gap-1" role="img" aria-label={tv`Đã qua ${Math.min(step, 5)} trên 5 công đoạn`}>{[0, 1, 2, 3, 4].map((i) => <span key={i} className={`h-1 w-5 rounded-full ${i < step ? "bg-proof" : i === step ? (tone === "cue" ? "bg-cue" : tone === "tally" ? "bg-tally" : "bg-accent") : "bg-overlay"}`} />)}</div>;
}

/** A key figure: a label, a big number and one line of context. */
export function Stat({ label, value, sub, icon, tone, children }: { label: string; value: React.ReactNode; sub?: React.ReactNode; icon?: string; tone?: "cue" | "ai" | "accent" | "proof"; children?: React.ReactNode }) {
  const c = { cue: "text-cue", ai: "text-ai", accent: "text-accent", proof: "text-proof" }[tone ?? "accent"];
  return (
    <div className="panel flex min-w-0 flex-col p-4">
      <div className="flex items-start justify-between gap-2"><span className="truncate text-[13px] text-mute">{label}</span>{icon && <Icon name={icon} size={17} className={`shrink-0 ${c}`} />}</div>
      <div className="mono mt-2 truncate text-[26px] font-semibold leading-none tracking-tight">{value}</div>
      {sub && <div className="mt-2 truncate text-[12px] text-faint">{sub}</div>}
      {children && <div className="mt-3">{children}</div>}
    </div>
  );
}

/** A reading that is also a filter: its count large, its name small, its lamp colour in the corner; the chosen one stays lit. */
export function Readout({ label, value, icon, tone = "accent", on, onClick }: { label: string; value: React.ReactNode; icon: string; tone?: "cue" | "ai" | "accent" | "proof" | "tally" | "ink"; on?: boolean; onClick: () => void }) {
  const c = { cue: "text-cue", ai: "text-ai", accent: "text-accent", proof: "text-proof", tally: "text-tally", ink: "text-ink" }[tone];
  return (
    <button type="button" role="radio" aria-checked={!!on} onClick={onClick} className="tile flex min-w-0 flex-col p-3.5 text-left">
      <span className="flex items-start justify-between gap-2"><span className="truncate text-[13px] text-mute">{label}</span><Icon name={icon} size={16} className={`shrink-0 ${c}`} /></span>
      <span className="mono mt-2 text-[24px] font-semibold leading-none tracking-tight">{value}</span>
    </button>
  );
}

/** A thin bar of a share. */
export function Meter({ share, tone = "accent" }: { share: number; tone?: "accent" | "cue" | "proof" | "ai" }) {
  // Each bar runs from its colour into a neighbouring one, as the gauges on the overview do.
  const c = { accent: "from-accent-deep to-accent", cue: "from-[#c98f2c] to-cue", proof: "from-[#2f9e6d] to-proof", ai: "from-[#6f5fd6] to-ai" }[tone];
  return <div className="h-1.5 overflow-hidden rounded-full bg-white/[0.06]"><div className={`h-full rounded-full bg-gradient-to-r ${c}`} style={{ width: `${Math.max(0, Math.min(1, share)) * 100}%` }} /></div>;
}

/** What a screen shows when it has nothing yet. */
export function Empty({ icon = "sparkles", title, children, action }: { icon?: string; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="panel flex flex-col items-center px-6 py-10 text-center">
      <span className="mb-3 grid h-11 w-11 place-items-center rounded-xl bg-accent/12 text-accent"><Icon name={icon} size={20} /></span>
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 max-w-md text-[13px] text-mute">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** A segmented choice. */
export function Seg<T extends string | number | boolean>({ items, value, onChange, label, disabled }: { items: readonly (readonly [T, string])[]; value: T; onChange: (v: T) => void; label: string; disabled?: boolean }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {items.map(([v, name]) => <button key={String(v)} type="button" role="radio" disabled={disabled} aria-checked={value === v} onClick={() => onChange(v)}>{name}</button>)}
    </div>
  );
}

/** A timecode chip laid over a picture. */
export function TimeChip({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`chip mono ${className}`}>{children}</span>;
}


/** A small turning ring, for a button or a line that is waiting on the server. */
/** The interface language, as two side-by-side options. Picking one reloads the page, so every screen comes back in
    that language; the choice lives in this browser (see `i18n.ts`). */
export function LangSwitch({ size = "md" }: { size?: "sm" | "md" }) {
  const options: [Lang, string][] = [["vi", "Tiếng Việt"], ["en", "English"]];
  return (
    <div role="group" aria-label={tr("Ngôn ngữ giao diện")} className={`flex shrink-0 overflow-hidden rounded-lg border border-line bg-surface ${size === "sm" ? "h-8" : "h-9"}`}>
      {options.map(([code, name]) => (
        <button key={code} type="button" aria-pressed={lang === code} title={name} onClick={() => { if (lang !== code) setLang(code); }}
                className={`px-2.5 text-[12px] font-semibold uppercase tracking-wide transition-colors ${lang === code ? "bg-raised text-ink" : "text-faint hover:text-mute"}`}>
          {code}
        </button>
      ))}
    </div>
  );
}

export function Spinner({ size = 14, className = "" }: { size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 20 20" fill="none" aria-hidden="true" className={`spin shrink-0 ${className}`}><circle cx="10" cy="10" r="7" stroke="currentColor" strokeOpacity=".25" strokeWidth="2.5" /><path d="M17 10a7 7 0 0 0-7-7" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" /></svg>;
}

/** The shape of content that has not arrived: lines of text, or a block of the given height. */
export function Skeleton({ lines = 0, height, className = "" }: { lines?: number; height?: number | string; className?: string }) {
  if (lines > 0) return <div className={`grid gap-2 ${className}`} aria-hidden="true">{Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton h-3.5" style={{ width: `${[92, 70, 84, 60, 78][i % 5]}%` }} />)}</div>;
  return <div className={`skeleton ${className}`} style={{ height }} aria-hidden="true" />;
}

/** Cards of the same shape as the ones to come. */
export function SkeletonCards({ count = 3, height = 180, className = "" }: { count?: number; height?: number; className?: string }) {
  return <div className={className} aria-busy="true" aria-label={tr("Đang tải…")}>{Array.from({ length: count }, (_, i) => <div key={i} className="panel overflow-hidden"><Skeleton height={height * 0.55} className="!rounded-none" /><div className="p-3"><Skeleton lines={2} /></div></div>)}</div>;
}

// ---------------------------------------------------------------- toasts: a word about what just happened, with a way back
type Toast = { id: number; text: string; tone: "plain" | "proof" | "tally"; action?: { label: string; run: () => void }; until: number };
const toasts: Toast[] = [];
const toastListeners = new Set<() => void>();
let toastSeq = 0;
const notifyToasts = () => toastListeners.forEach((l) => l());
/** Show a short message at the bottom of the screen. With `undo`, the message carries a button that calls it back. */
export function toast(text: string, options: { tone?: Toast["tone"]; undo?: () => void; seconds?: number } = {}) {
  const t: Toast = { id: ++toastSeq, text, tone: options.tone ?? "plain", until: Date.now() + (options.seconds ?? (options.undo ? 8 : 4)) * 1000,
    action: options.undo ? { label: tr("Hoàn tác"), run: options.undo } : undefined };
  toasts.push(t); if (toasts.length > 4) toasts.shift();
  notifyToasts();
  setTimeout(() => { const i = toasts.indexOf(t); if (i >= 0) { toasts.splice(i, 1); notifyToasts(); } }, t.until - Date.now());
}
const dismiss = (t: Toast) => { const i = toasts.indexOf(t); if (i >= 0) { toasts.splice(i, 1); notifyToasts(); } };
export function Toaster() {
  const [, tick] = useState(0);
  useEffect(() => { const l = () => tick((n) => n + 1); toastListeners.add(l); return () => { toastListeners.delete(l); }; }, []);
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-[calc(16px+env(safe-area-inset-bottom))] z-50 flex flex-col items-center gap-2 px-4 md:bottom-10" aria-live="polite" aria-atomic="false">
      {toasts.map((t) => (
        <div key={t.id} className="toast pointer-events-auto flex max-w-[520px] items-center gap-3 py-2.5 pl-4 pr-2 text-[13px]" role="status">
          {t.tone !== "plain" && <Icon name={t.tone === "proof" ? "check" : "alert"} size={15} className={t.tone === "proof" ? "text-proof" : "text-tally"} />}
          <span className="min-w-0">{t.text}</span>
          {t.action && <button type="button" className="btn shrink-0 rounded-md px-2.5 py-1 font-medium text-accent hover:bg-accent/12" onClick={() => { t.action!.run(); dismiss(t); }}>{t.action.label}</button>}
          <button type="button" className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-faint hover:bg-raised hover:text-ink" onClick={() => dismiss(t)} aria-label={tr("Đóng")}><Icon name="x" size={14} /></button>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- the one dialog: a question before something that cannot be undone
type Question = { title: string; body?: React.ReactNode; confirm: string; danger?: boolean; resolve: (yes: boolean) => void };
let question: Question | null = null;
const dialogListeners = new Set<() => void>();
/** Ask before a destructive step. Resolves true only when the operator pressed the confirming button. */
export function ask(title: string, options: { body?: React.ReactNode; confirm?: string; danger?: boolean } = {}): Promise<boolean> {
  return new Promise((resolve) => {
    question = { title, body: options.body, confirm: options.confirm ?? tr("Xoá"), danger: options.danger ?? true, resolve: (yes) => { question = null; dialogListeners.forEach((l) => l()); resolve(yes); } };
    dialogListeners.forEach((l) => l());
  });
}
export function Dialogs() {
  const [, tick] = useState(0);
  const yes = useRef<HTMLButtonElement>(null);
  useEffect(() => { const l = () => tick((n) => n + 1); dialogListeners.add(l); return () => { dialogListeners.delete(l); }; }, []);
  const q = question;
  useEffect(() => {
    if (!q) return;
    const before = document.activeElement as HTMLElement | null;
    yes.current?.focus();
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") q.resolve(false); };
    window.addEventListener("keydown", key);
    return () => { window.removeEventListener("keydown", key); before?.focus(); };
  }, [q]);
  if (!q) return null;
  return (
    <div className="scrim fixed inset-0 z-50 grid place-items-center px-4" onMouseDown={() => q.resolve(false)}>
      <div role="dialog" aria-modal="true" aria-labelledby="ask-title" className="dialog w-full max-w-sm p-5" onMouseDown={(e) => e.stopPropagation()}>
        <h2 id="ask-title" className="text-[15px] font-semibold">{q.title}</h2>
        {q.body && <div className="mt-1.5 text-[13px] text-mute">{q.body}</div>}
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={() => q.resolve(false)}>{tr("Thôi")}</Button>
          <button ref={yes} type="button" onClick={() => q.resolve(true)} className={`btn inline-flex h-9 items-center rounded-lg px-3.5 text-[13.5px] font-medium ${q.danger ? "bg-tally text-white hover:bg-tally/85" : "brand-button"}`}>{q.confirm}</button>
        </div>
      </div>
    </div>
  );
}
