import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { call, post, timecode, usePoll, type Finding, type Project, type RenderItem, type Rights } from "./api";
import { locale, t as tr, tv } from "./i18n";
import { Button, Empty, Filmstrip, Icon, Page, Seg, Skeleton, SkeletonCards, Spinner, Tag, TimeChip, toast } from "./parts";

/** 00:01:47.342: the timecode a reviewer quotes back. */
const longTc = (s: number) => {
  const x = Math.max(0, s), h = Math.floor(x / 3600), m = Math.floor((x % 3600) / 60), sec = Math.floor(x % 60), ms = Math.floor((x % 1) * 1000);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}.${String(ms).padStart(3, "0")}`;
};
const FPS = 30;
const SPEEDS = [[0.5, "0.5×"], [1, "1×"], [1.5, "1.5×"], [2, "2×"]] as const;
const FORMATS: Record<string, string> = { landscape: "16:9", portrait: "9:16", square: "1:1" };
const when = (s: number) => new Date(s * 1000).toLocaleString(locale, { hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit" });
const go = (to: string) => { window.history.pushState({}, "", to); window.dispatchEvent(new PopStateEvent("popstate")); };

type Verdict = "waiting" | "approved" | "rejected" | "open";
type Reel = { project: Project; render: RenderItem; version: number; of: number; verdict: Verdict };
const VERDICT: Record<Verdict, { label: string; tone: "cue" | "proof" | "tally" | "mute" }> = {
  waiting: { label: tr("Chờ bạn duyệt"), tone: "cue" }, approved: { label: tr("Đã duyệt"), tone: "proof" }, rejected: { label: tr("Không duyệt"), tone: "tally" }, open: { label: tr("Chưa duyệt"), tone: "mute" },
};
const ORIGIN: Record<string, string> = { self_shot: tr("tự quay"), licensed: tr("có giấy phép"), generated: tr("AI sinh"), music: tr("nhạc") };
const DOT = { cue: "bg-cue", proof: "bg-proof", tally: "bg-tally", mute: "bg-faint" };

/** Every finished cut of every project, newest first, with where its review stands. */
function reels(projects: Project[]): Reel[] {
  const out: Reel[] = [];
  for (const p of projects) {
    p.renders.forEach((r, i) => {
      const verdict: Verdict = i === 0 && p.render?.status === "waiting_review" ? "waiting" : r.review ? (r.review.approved ? "approved" : "rejected") : "open";
      out.push({ project: p, render: r, version: p.renders.length - i, of: p.renders.length, verdict });
    });
  }
  return out.sort((a, b) => b.render.created_at - a.render.created_at);
}

/** Where each shot of a cut starts and ends, its picture and its words, from what the render recorded about itself.
    The recorded durations can fall short of the file (padding, the last caption held); they are stretched to the file's length. */
function scenes(project: Project, render: RenderItem, length: number) {
  const cut = render.qc.shots ?? [];
  const sum = cut.reduce((s, c) => s + c.duration, 0);
  const scale = length > 0 && sum > 0 ? length / sum : 1;
  let at = 0;
  return cut.map((s, i) => {
    const shot = project.shots[i]?.text === s.text ? project.shots[i] : project.shots.find((x) => x.text === s.text) ?? null;
    const sel = shot?.selection ?? null;
    const thumb = s.gap ? null : sel && sel.status !== "gap" ? sel.frame_url ?? sel.asset?.thumbnail_url ?? shot?.keyframe_url ?? null : shot?.keyframe_url ?? null;
    const d = s.duration * scale;
    const item = { n: i + 1, start: at, end: at + d, text: s.text, gap: s.gap, own: !!s.own_voice, thumb, source: s.gap ? null : sel?.asset?.name ?? null, scene: shot?.scene ?? null };
    at += d;
    return item;
  });
}

/** Timecodes written in a note ("0:07 the coffee shot is dark") as points on the cut. */
const marksIn = (text: string | null | undefined) => [...(text ?? "").matchAll(/(?<![\d:])(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?(?![\d:])/g)]
  .map((m) => ({ at: Number(m[1]) * 60 + Number(m[2]) + (m[3] ? Number(`0.${m[3]}`) : 0), text: (text ?? "").slice((m.index ?? 0) + m[0].length).split(/(?=\d{1,2}:\d{2})/)[0].trim() }));

// ---------------------------------------------------------------- the sound of the cut, measured in the browser from the file itself
const peaksCache = new Map<string, number[]>();
function useWaveform(url: string) {
  const [peaks, setPeaks] = useState<number[] | null>(peaksCache.get(url) ?? null);
  useEffect(() => {
    if (peaksCache.has(url)) { setPeaks(peaksCache.get(url)!); return; }
    let gone = false;
    setPeaks(null);
    (async () => {
      try {
        const bytes = await fetch(url).then((r) => r.arrayBuffer());
        const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const ctx = new Ctx();
        const audio = await ctx.decodeAudioData(bytes);
        void ctx.close();
        const data = audio.getChannelData(0), buckets = 600, size = Math.max(1, Math.floor(data.length / buckets)), stride = Math.max(1, Math.floor(size / 64));
        const out: number[] = [];
        for (let b = 0; b < buckets; b++) { let peak = 0; for (let k = b * size; k < (b + 1) * size && k < data.length; k += stride) peak = Math.max(peak, Math.abs(data[k])); out.push(peak); }
        const top = Math.max(...out, 0.0001);
        const shaped = out.map((v) => Math.pow(v / top, 0.7));
        peaksCache.set(url, shaped);
        if (!gone) setPeaks(shaped);
      } catch { if (!gone) { peaksCache.set(url, []); setPeaks([]); } }
    })();
    return () => { gone = true; };
  }, [url]);
  return peaks;
}

function Wave({ peaks, tone }: { peaks: number[]; tone: string }) {
  return (
    <svg className={`absolute inset-0 h-full w-full ${tone}`} viewBox={`0 0 ${peaks.length} 100`} preserveAspectRatio="none" aria-hidden="true">
      {peaks.map((p, i) => <rect key={i} x={i + 0.15} width={0.7} y={50 - Math.max(1.5, p * 46)} height={Math.max(3, p * 92)} rx={0.35} fill="currentColor" />)}
    </svg>
  );
}

// ---------------------------------------------------------------- the gallery: every cut, the ones waiting for a decision first
function Gallery({ projects }: { projects: Project[] | null }) {
  const all = useMemo(() => reels(projects ?? []), [projects]);
  const [picked, setFilter] = useState<"all" | Verdict | null>(null);          // until the operator chooses: the waiting ones if there are any
  const filter = picked ?? (all.some((r) => r.verdict === "waiting") ? "waiting" : "all");
  const [hover, setHover] = useState<string | null>(null);
  const shown = all.filter((r) => filter === "all" || r.verdict === filter);
  const count = (v: Verdict) => all.filter((r) => r.verdict === v).length;
  return (
    <Page eyebrow={tr("Sản xuất")} title={tr("Phòng chiếu")} wide note={tr("Xem lại mọi bản dựng như người xem, rồi duyệt hoặc ghi nhận xét theo mốc thời gian.")}
          actions={<Seg label={tr("Lọc bản dựng")} value={filter} onChange={setFilter}
                        items={[["waiting", tv`Chờ duyệt ${count("waiting")}`], ["approved", tv`Đã duyệt ${count("approved")}`], ["rejected", tv`Không duyệt ${count("rejected")}`], ["open", tv`Bản cũ ${count("open")}`], ["all", tv`Tất cả ${all.length}`]] as const} />}>
      {!projects && <SkeletonCards count={6} height={220} className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" />}
      {projects && all.length === 0 && <Empty icon="screen" title={tr("Chưa có bản dựng nào")}>{tr("Khi một dự án dựng xong, bản dựng sẽ hiện ở đây để bạn xem và duyệt.")}</Empty>}
      {projects && all.length > 0 && shown.length === 0 && <Empty icon="check" title={filter === "waiting" ? tr("Không có bản nào chờ duyệt") : tr("Không có bản dựng nào ở mục này")} action={<Button onClick={() => setFilter("all")}>{tr("Xem tất cả")}</Button>} />}
      <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {shown.map((r) => {
          const v = VERDICT[r.verdict], q = r.render.qc, poster = r.render.package ? `/api/v1/renders/${r.render.render_id}/package/${r.render.package.thumbnail}` : null;
          const notes = (q.findings?.length ?? 0) + (q.viewer?.findings.length ?? 0);
          const id = r.render.render_id;
          return (
            <li key={id}>
              <button type="button" onClick={() => go(`/phong-chieu?r=${id}`)} onMouseEnter={() => setHover(id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(id)} onBlur={() => setHover(null)}
                      className={`panel group block w-full overflow-hidden text-left transition-[border-color,transform] duration-200 hover:-translate-y-0.5 hover:border-edge ${r.verdict === "waiting" ? "!border-cue/45" : ""}`}>
                <span className="relative block aspect-video overflow-hidden bg-black">
                  {poster ? <img src={poster} alt="" loading="lazy" className="h-full w-full object-cover" /> : <Filmstrip shots={r.project.shots} height="100%" className="h-full" />}
                  {hover === id && <video src={r.render.url} muted autoPlay loop playsInline preload="none" className="rise absolute inset-0 h-full w-full bg-black object-contain" />}
                  <span className="pointer-events-none absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent" />
                  <span className="absolute left-2.5 top-2.5 rounded-full bg-black/55 backdrop-blur"><Tag tone={v.tone}>{v.label}</Tag></span>
                  <TimeChip className="absolute right-2.5 top-2.5"><Icon name="play" size={10} />{timecode(q.duration)}</TimeChip>
                  <span className="absolute bottom-2.5 left-2.5 flex gap-1.5">
                    <span className="chip mono">{FORMATS[q.format ?? "landscape"] ?? q.format}</span>
                    {q.draft && <span className="chip !text-cue">{tr("Bản nháp")}</span>}
                    {q.external && <span className="chip">{tr("Hoàn thiện bên ngoài")}</span>}
                  </span>
                  <span className="absolute inset-0 grid place-items-center opacity-0 transition-opacity duration-200 group-hover:opacity-100"><span className="grid h-12 w-12 place-items-center rounded-full bg-white/90 text-canvas shadow-lg"><Icon name="play" size={20} /></span></span>
                </span>
                <span className="block px-4 pb-4 pt-3">
                  <span className="block truncate text-[15px] font-medium">{r.render.package?.title || r.project.title}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-x-2.5 text-[12px] text-faint">
                    <span>{tv`Bản ${r.version}/${r.of}`}</span><span className="mono">{when(r.render.created_at)}</span>
                    <span className={q.passed ? "text-proof" : "text-tally"}>{q.passed ? tr("QC đạt") : tr("QC chưa đạt")}</span>
                    {notes > 0 && <span className="text-cue">{tv`${notes} điểm nên xem`}</span>}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Page>
  );
}

// ---------------------------------------------------------------- the screening: one cut, played and judged
type Panel = "scenes" | "words" | "checks" | "review" | "lineage";
type Lineage = { script: { version: number }; file: string; shots: { line: number; text: string; duration: number; source: { name: string; origin: string; t_in: number | null; rights?: { licence?: string; source?: string } | null } | null; generated: { kind: string; prompt: string; seed: number | null; provider: string; model?: string }[] | null }[] };

function Screening({ reel, siblings }: { reel: Reel; siblings: Reel[] }) {
  const { project: p, render } = reel;
  const video = useRef<HTMLVideoElement>(null);
  const deck = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const [t, setT] = useState(0);
  const [duration, setDuration] = useState(render.qc.duration || 0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [muted, setMuted] = useState(false);
  const [loop, setLoop] = useState(false);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const [panel, setPanel] = useState<Panel>(reel.verdict === "waiting" ? "review" : "scenes");
  const [query, setQuery] = useState("");
  const [grid, setGrid] = useState(false);
  const [follow, setFollow] = useState(true);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [lineage, setLineage] = useState<Lineage | null>(null);
  const peaks = useWaveform(render.url);
  const shots = useMemo(() => scenes(p, render, duration), [p, render, duration]);
  const total = duration || shots[shots.length - 1]?.end || 1;
  const current = shots.find((s) => t >= s.start && t < s.end) ?? shots[shots.length - 1] ?? null;
  const findings: (Finding & { by: string })[] = [...(render.qc.findings ?? []).map((f) => ({ ...f, by: tr("Kiểm tra tự động") })), ...(render.qc.viewer?.findings ?? []).map((f) => ({ ...f, by: tr("AI xem lại") }))];
  const marks = marksIn(render.review?.comment);
  const draftMarks = marksIn(note);
  const { data: rights } = usePoll<Rights>(`/api/v1/renders/${render.render_id}/rights`, 30000);
  const pct = (s: number) => `${Math.min(100, Math.max(0, (s / total) * 100))}%`;

  // The playhead follows the picture every frame while playing, not four times a second.
  useEffect(() => {
    let frame = 0;
    const tick = () => { const v = video.current; if (v) setT(v.currentTime); frame = requestAnimationFrame(tick); };
    if (playing) frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);
  useEffect(() => { if (video.current) video.current.playbackRate = speed; }, [speed]);
  useEffect(() => { if (video.current) video.current.muted = muted; }, [muted]);
  useEffect(() => { if (loop && current && playing && t >= current.end - 0.04 && video.current) video.current.currentTime = current.start; }, [loop, current, playing, t]);
  // Keep the playing shot in view in the list, unless the operator scrolled away to read.
  const playingN = current?.n;
  useEffect(() => {
    if (!follow || !playing || !playingN || !window.matchMedia("(min-width: 1024px)").matches) return;          // on a phone the list is below the picture: moving it would move the page
    list.current?.querySelector(`[data-n="${playingN}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [playingN, follow, playing]);

  const seek = useCallback((s: number) => { const v = video.current; if (!v) return; v.currentTime = Math.max(0, Math.min(s, total - 0.01)); setT(v.currentTime); }, [total]);
  const toggle = useCallback(() => { const v = video.current; if (!v) return; if (v.paused) void v.play(); else v.pause(); }, []);
  const jumpShot = useCallback((by: number) => {
    if (!shots.length) return;
    const i = current ? current.n - 1 : 0;
    const into = current && t - current.start > 0.6 && by < 0 ? i : Math.max(0, Math.min(shots.length - 1, i + by));     // back once returns to the start of this shot, as players do
    seek(shots[into].start + 0.001);
  }, [shots, current, t, seek]);
  const full = useCallback(() => { const v = video.current; if (!v) return; if (document.fullscreenElement) void document.exitFullscreen(); else void v.requestFullscreen?.(); }, []);
  const mark = useCallback(() => { const now = video.current?.currentTime ?? 0; setPanel("review"); setNote((x) => `${x}${x && !x.endsWith("\n") ? "\n" : ""}${timecode(now)} `); }, []);
  useEffect(() => {
    const on = () => { const v = video.current; if (v) v.controls = document.fullscreenElement === v; };
    document.addEventListener("fullscreenchange", on); return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if ((el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable)) || e.metaKey || e.ctrlKey || e.altKey) return;
      const v = video.current; if (!v) return;
      const step = e.shiftKey ? 1 : 1 / FPS;
      const k = e.key.toLowerCase();
      if (e.key === " ") { e.preventDefault(); toggle(); }
      else if (k === "k") v.pause();
      else if (e.key === "ArrowLeft") { e.preventDefault(); v.pause(); seek(v.currentTime - step); }
      else if (e.key === "ArrowRight") { e.preventDefault(); v.pause(); seek(v.currentTime + step); }
      else if (e.key === "ArrowUp") { e.preventDefault(); jumpShot(-1); }
      else if (e.key === "ArrowDown") { e.preventDefault(); jumpShot(1); }
      else if (k === "j") seek(v.currentTime - 5);
      else if (k === "l") seek(v.currentTime + 5);
      else if (k === "m") setMuted((m) => !m);
      else if (k === "f") full();
      else if (e.key === "[") setSpeed((s) => SPEEDS[Math.max(0, SPEEDS.findIndex(([x]) => x === s) - 1)][0]);
      else if (e.key === "]") setSpeed((s) => SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.findIndex(([x]) => x === s) + 1)][0]);
      else if (k === "n") { e.preventDefault(); mark(); }
    };
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, [toggle, seek, jumpShot, full, mark]);
  useEffect(() => { if (panel === "lineage" && !lineage) call<Lineage>(`/api/v1/renders/${render.render_id}/lineage`).then(setLineage).catch(() => setLineage(null)); }, [panel, lineage, render.render_id]);

  const at = (x: number) => { const r = deck.current?.getBoundingClientRect(); return r ? Math.min(1, Math.max(0, (x - r.left) / r.width)) * total : 0; };
  const scrub = (e: React.PointerEvent) => { e.currentTarget.setPointerCapture(e.pointerId); seek(at(e.clientX)); };
  const hoverT = hoverX == null ? null : at(hoverX);
  const hoverShot = hoverT == null ? null : shots.find((s) => hoverT >= s.start && hoverT < s.end) ?? null;

  const decide = async (approve: boolean) => {
    setBusy(approve ? "approve" : "reject");
    try {
      await post(`/api/v1/projects/${p.project_id}/render/decision`, { approve, comment: approve ? undefined : note.trim() || undefined });
      toast(approve ? tr("Đã duyệt bản dựng.") : tr("Đã ghi nhận xét. Hệ thống sẽ dựng lại theo ghi chú."), { tone: approve ? "proof" : "plain" });
      setNote("");
    } catch (e) { toast((e as Error).message, { tone: "tally" }); }
    setBusy(null);
  };
  const watchAgain = async () => { setBusy("watch"); try { await post(`/api/v1/renders/${render.render_id}/watch`); toast(tr("AI đã xem lại bản dựng."), { tone: "proof" }); } catch (e) { toast((e as Error).message, { tone: "tally" }); } setBusy(null); };
  const v = VERDICT[reel.verdict];
  const needle = query.trim().toLowerCase();
  const matching = shots.filter((s) => !needle || s.text.toLowerCase().includes(needle) || (s.source ?? "").toLowerCase().includes(needle));
  const pkg = render.package;
  const title = pkg?.title || p.title;
  const PANELS: { key: Panel; label: string; icon: string; dot?: string }[] = [
    { key: "scenes", label: tr("Cảnh"), icon: "grid" }, { key: "words", label: tr("Lời dẫn"), icon: "captions" },
    { key: "checks", label: tr("Kiểm tra"), icon: "shield", dot: findings.length || !render.qc.passed ? "bg-cue" : "bg-proof" },
    { key: "review", label: tr("Duyệt"), icon: "check", dot: reel.verdict === "waiting" ? "bg-cue" : undefined }, { key: "lineage", label: tr("Nguồn gốc"), icon: "layers" },
  ];
  const btn = "btn grid h-9 w-9 place-items-center rounded-lg text-mute hover:bg-raised hover:text-ink";
  const pill = "btn inline-flex h-8 items-center gap-1.5 rounded-lg border border-edge bg-raised px-3 text-[12.5px] hover:bg-overlay";
  const facts: [string, string, string, string][] = [
    [tr("Thời lượng"), timecode(total), "clock", ""], [tr("Dựng lúc"), when(render.created_at), "scissors", ""],
    [tr("Kiểm tra"), render.qc.passed ? tr("Đạt") : tr("Chưa đạt"), "shield", render.qc.passed ? "text-proof" : "text-tally"],
    [tr("Bản quyền"), rights ? (rights.clear ? tr("Sạch") : tv`${rights.blockers.length} điểm`) : "…", "link", rights ? (rights.clear ? "text-proof" : "text-cue") : ""],
  ];
  const tags = [FORMATS[render.qc.format ?? "landscape"] ?? render.qc.format, tv`${shots.length} cảnh`, render.qc.music ? tr("Có nhạc nền") : tr("Không nhạc"), shots.some((s) => s.own) ? tr("Giọng bạn thu") : tr("Giọng máy"),
    render.qc.draft ? tr("Bản nháp") : null, render.qc.external ? tr("Hoàn thiện bên ngoài") : null, p.channel, p.template].filter(Boolean) as string[];
  const KEYS: [string, string][] = [["Space", tr("phát / dừng")], ["← →", tr("từng khung hình")], ["⇧ ← →", tr("từng giây")], ["↑ ↓", tr("cảnh trước / sau")], ["J L", tr("lùi / tới 5 giây")], ["[ ]", tr("tốc độ")], ["N", tr("ghi mốc nhận xét")], ["F", tr("toàn màn hình")]];

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
      <div className="min-w-0 shrink-0 lg:min-h-0 lg:flex-1 lg:shrink lg:overflow-y-auto">
        <div className="mx-auto w-full max-w-[1500px] px-4 pb-10 pt-4 md:px-8">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button type="button" onClick={() => go("/phong-chieu")} className="flex items-center gap-1 text-[12.5px] text-mute hover:text-ink"><Icon name="back" size={14} />{tr("Phòng chiếu")}</button>
            <span className="text-faint">/</span>
            <button type="button" onClick={() => go(`/du-an/${p.project_id}`)} className="max-w-[40ch] truncate text-[12.5px] text-mute hover:text-ink">{p.title}</button>
            <span className="ml-auto" />
            {siblings.length > 1 && (
              <div className="scroll-x flex max-w-full gap-1 rounded-lg border border-line bg-canvas p-1" role="tablist" aria-label={tr("Các bản dựng của dự án")}>
                {siblings.map((s) => (
                  <button key={s.render.render_id} type="button" role="tab" aria-selected={s.render.render_id === render.render_id} onClick={() => go(`/phong-chieu?r=${s.render.render_id}`)} title={`${VERDICT[s.verdict].label} · ${when(s.render.created_at)}`}
                          className={`flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-[12px] ${s.render.render_id === render.render_id ? "bg-overlay font-medium text-ink" : "text-mute hover:text-ink"}`}>
                    <span className={`h-1.5 w-1.5 rounded-full ${DOT[VERDICT[s.verdict].tone]}`} />{tv`Bản ${s.version}`}
                  </button>
                ))}
              </div>
            )}
            <a href={render.url} download className={`${pill} !h-9 !text-[13px]`}><Icon name="download" size={14} />{tr("Tải video")}</a>
          </div>

          {/* The stage: black, the picture alone. */}
          <div className="relative overflow-hidden rounded-xl bg-black ring-1 ring-line">
            <video ref={video} key={render.url} src={render.url} playsInline preload="auto" onClick={toggle} onDoubleClick={full}
                   onPlay={() => setPlaying(true)} onPause={() => { setPlaying(false); if (video.current) setT(video.current.currentTime); }} onSeeked={() => { if (video.current) setT(video.current.currentTime); }}
                   onLoadedMetadata={(e) => { setDuration(e.currentTarget.duration || render.qc.duration); e.currentTarget.playbackRate = speed; }} onEnded={() => setPlaying(false)}
                   className={`block w-full cursor-pointer bg-black object-contain ${(render.qc.format ?? "landscape") === "landscape" ? "aspect-video lg:aspect-auto lg:h-[min(58vh,640px)]" : "h-[min(58vh,640px)]"}`} />
            {!playing && (
              <button type="button" onClick={toggle} aria-label={tr("Phát")} className="rise absolute left-1/2 top-1/2 grid h-16 w-16 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-white/90 text-canvas shadow-2xl transition-transform hover:scale-105">
                <Icon name="play" size={26} />
              </button>
            )}
            {current && <span className="pointer-events-none absolute left-3 top-3 flex items-center gap-2"><TimeChip>{tv`Cảnh ${String(current.n).padStart(2, "0")}`}</TimeChip>{current.own && <span className="chip">{tr("Giọng bạn")}</span>}{current.gap && <span className="chip !text-cue">{tr("Nền trơn")}</span>}</span>}
            <span className="pointer-events-none absolute right-3 top-3 rounded-full bg-black/55 backdrop-blur"><Tag tone={v.tone}>{v.label}</Tag></span>
          </div>

          {/* The deck: sound, scenes and notes on one ruler, all scrubbable. */}
          <div className="panel mt-3 px-3 pb-2 pt-3">
            <div ref={deck} className="relative cursor-pointer touch-none select-none" onPointerDown={scrub} onPointerMove={(e) => { setHoverX(e.clientX); if (e.buttons === 1) seek(at(e.clientX)); }} onPointerLeave={() => setHoverX(null)}
                 role="slider" aria-label={tr("Vị trí trong bản dựng")} aria-valuemin={0} aria-valuemax={Math.round(total)} aria-valuenow={Math.round(t)} aria-valuetext={longTc(t)} tabIndex={0}>
              <div className="relative h-14 overflow-hidden rounded-md bg-canvas">
                {peaks === null && <Skeleton className="absolute inset-0 !rounded-md" />}
                {peaks && peaks.length > 0 && <>
                  <Wave peaks={peaks} tone="text-edge" />
                  <div className="absolute inset-0" style={{ clipPath: `inset(0 ${100 - Math.min(100, (t / total) * 100)}% 0 0)` }}><Wave peaks={peaks} tone="text-accent" /></div>
                </>}
                {peaks && peaks.length === 0 && <span className="absolute inset-0 grid place-items-center text-[11.5px] text-faint">{tr("Bản dựng này không có tiếng")}</span>}
              </div>
              <div className="relative mt-1.5 h-9">
                {shots.map((s) => (
                  <div key={s.n} className={`absolute inset-y-0 overflow-hidden rounded-[5px] border-x border-surface transition-colors ${s.gap ? "hatch-cue bg-raised" : current?.n === s.n ? "bg-accent/35" : s.n % 2 ? "bg-overlay" : "bg-raised"}`} style={{ left: pct(s.start), width: pct(s.end - s.start) }}>
                    <span className={`mono absolute left-1.5 top-1/2 -translate-y-1/2 text-[10px] ${current?.n === s.n ? "text-ink" : "text-faint"}`}>{s.n}</span>
                  </div>
                ))}
                {findings.map((f, i) => { const s = shots[f.shot - 1]; return s ? <span key={`f${i}`} title={`${f.check}: ${f.text}`} className={`absolute top-0 h-2 w-2 -translate-x-1/2 rotate-45 rounded-[2px] ${f.severity === "cao" ? "bg-cue" : "bg-ai"}`} style={{ left: pct(s.start + Math.min(0.3, (s.end - s.start) / 2)) }} /> : null; })}
                {[...marks, ...draftMarks].map((m, i) => <span key={`m${i}`} title={m.text || tr("Mốc nhận xét")} className="absolute bottom-0 h-2.5 w-2.5 -translate-x-1/2 rounded-full border-2 border-surface bg-tally" style={{ left: pct(m.at) }} />)}
              </div>
              <div className="pointer-events-none absolute -top-1 bottom-0 z-10 w-0.5 -translate-x-1/2 rounded-full bg-ink shadow-[0_0_0_1px_rgba(0,0,0,0.4)]" style={{ left: pct(t) }}><span className="absolute -left-[5px] -top-0.5 h-3 w-3 rounded-full bg-ink" /></div>
              {hoverT != null && (
                <div className="pointer-events-none absolute bottom-full z-20 mb-2 -translate-x-1/2" style={{ left: `clamp(80px, ${pct(hoverT)}, calc(100% - 80px))` }}>
                  <div className="dialog w-40 overflow-hidden !animate-none">
                    {hoverShot?.thumb ? <img src={hoverShot.thumb} alt="" className="aspect-video w-full object-cover" /> : <div className="hatch aspect-video bg-raised" />}
                    <p className="flex items-center justify-between px-2 py-1 text-[11px]"><span className="mono">{timecode(hoverT)}</span>{hoverShot && <span className="text-faint">{tv`Cảnh ${hoverShot.n}`}</span>}</p>
                  </div>
                </div>
              )}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-faint">
              <span className="flex items-center gap-1.5"><span className="h-0.5 w-3 rounded bg-accent" />{tr("Âm thanh")}</span>
              <span className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-sm bg-overlay" />{tr("Cảnh")}</span>
              {findings.length > 0 && <span className="flex items-center gap-1.5"><span className="h-2 w-2 rotate-45 rounded-[2px] bg-cue" />{tr("Nên xem lại")}</span>}
              {(marks.length > 0 || draftMarks.length > 0) && <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-tally" />{tr("Mốc nhận xét")}</span>}
              <span className="mono ml-auto">{timecode(0)} – {timecode(total)}</span>
            </div>
          </div>

          {/* Transport */}
          <div className="mt-3 flex flex-wrap items-center gap-x-2.5 gap-y-3">
            <div className="flex items-center gap-0.5">
              <button type="button" className={btn} onClick={() => jumpShot(-1)} title={tr("Cảnh trước (↑)")} aria-label={tr("Cảnh trước")}><Icon name="skipback" size={17} /></button>
              <button type="button" className={btn} onClick={() => { video.current?.pause(); seek(t - 1 / FPS); }} title={tr("Lùi một khung hình (←)")} aria-label={tr("Lùi một khung hình")}><Icon name="back" size={16} /></button>
              <button type="button" onClick={toggle} className="btn mx-1 grid h-11 w-11 place-items-center rounded-xl bg-raised text-ink ring-1 ring-edge hover:bg-overlay" title={tr("Phát / dừng (Space)")} aria-label={playing ? tr("Dừng") : tr("Phát")}><Icon name={playing ? "pause" : "play"} size={19} /></button>
              <button type="button" className={btn} onClick={() => { video.current?.pause(); seek(t + 1 / FPS); }} title={tr("Tới một khung hình (→)")} aria-label={tr("Tới một khung hình")}><Icon name="next" size={16} /></button>
              <button type="button" className={btn} onClick={() => jumpShot(1)} title={tr("Cảnh sau (↓)")} aria-label={tr("Cảnh sau")}><Icon name="skipfwd" size={17} /></button>
              <button type="button" className={`${btn} ${loop ? "!bg-accent/15 !text-accent" : ""}`} onClick={() => setLoop(!loop)} aria-pressed={loop} title={tr("Lặp lại cảnh đang xem")} aria-label={tr("Lặp lại cảnh")}><Icon name="loop" size={17} /></button>
            </div>
            <p className="mono whitespace-nowrap text-[16px] font-medium tracking-tight">{total < 3600 ? longTc(t).slice(3) : longTc(t)} <span className="text-faint">/ {total < 3600 ? longTc(total).slice(3) : longTc(total)}</span></p>
            <div className="ml-auto [&_.seg>button]:px-2"><Seg label={tr("Tốc độ phát")} value={speed} onChange={setSpeed} items={SPEEDS} /></div>
            <div className="flex items-center gap-0.5">
              <button type="button" className={btn} onClick={mark} title={tr("Ghi mốc nhận xét (N)")} aria-label={tr("Ghi mốc nhận xét")}><Icon name="comment" size={16} /></button>
              <button type="button" className={btn} onClick={() => setMuted(!muted)} aria-pressed={muted} title={tr("Tắt / bật tiếng (M)")} aria-label={tr("Tắt tiếng")}><Icon name={muted ? "mute" : "volume"} size={17} /></button>
              <button type="button" className={btn} onClick={full} title={tr("Toàn màn hình (F)")} aria-label={tr("Toàn màn hình")}><Icon name="expand" size={16} /></button>
            </div>
          </div>

          {/* What this cut is */}
          <div className="mt-8 grid gap-6 2xl:grid-cols-[minmax(0,1fr)_auto]">
            <div className="min-w-0">
              <h1 className="text-[26px] font-semibold leading-tight tracking-tight md:text-[30px]">{title}</h1>
              <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-mute">{pkg?.description || tv`Bản dựng ${reel.version} của “${p.title}”, ${shots.length} cảnh, dài ${timecode(total)}.`}</p>
              <div className="mt-4 flex flex-wrap gap-2">{tags.map((x) => <span key={x} className="rounded-md border border-line bg-raised px-2.5 py-1 text-[12.5px] text-mute">#{x.toLowerCase().replace(/\s+/g, "-")}</span>)}</div>
            </div>
            <dl className="grid grid-cols-2 gap-2 self-start sm:grid-cols-4 2xl:grid-cols-2">
              {facts.map(([k, val, icon, tone]) => (
                <div key={k} className="panel-raised min-w-[132px] px-3 py-2.5"><dt className="eyebrow flex items-center gap-1.5 !text-[10px]"><Icon name={icon} size={12} />{k}</dt><dd className={`mono mt-1 text-[14px] ${tone}`}>{val}</dd></div>
              ))}
            </dl>
          </div>
          <p className="mt-8 hidden flex-wrap gap-x-4 gap-y-1 text-[11.5px] text-faint md:flex">
            {KEYS.map(([k, w]) => <span key={k}><kbd className="mono rounded border border-line px-1">{k}</kbd> {w}</span>)}
          </p>
        </div>
      </div>

      {/* The inspector */}
      <aside className="flex w-full shrink-0 flex-col border-t border-line bg-surface lg:min-h-0 lg:w-[420px] lg:border-l lg:border-t-0" aria-label={tr("Chi tiết bản dựng")}>
        <div className="grid grid-cols-5 gap-1 border-b border-line p-2" role="tablist">
          {PANELS.map((x) => (
            <button key={x.key} type="button" role="tab" aria-selected={panel === x.key} onClick={() => setPanel(x.key)}
                    className={`relative flex flex-col items-center gap-1 rounded-lg py-2 text-[11.5px] transition-colors ${panel === x.key ? "bg-raised font-medium text-accent" : "text-mute hover:bg-raised/60 hover:text-ink"}`}>
              <Icon name={x.icon} size={17} />{x.label}{x.dot && <span className={`absolute right-[22%] top-1.5 h-1.5 w-1.5 rounded-full ${x.dot}`} />}
            </button>
          ))}
        </div>

        {panel === "scenes" && (
          <div className="flex items-center gap-2 border-b border-line p-3">
            <span className="relative min-w-0 flex-1"><Icon name="search" size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={tr("Tìm trong bản dựng…")} aria-label={tr("Tìm cảnh")} className="h-9 w-full pl-9 pr-3 text-[13px]" /></span>
            <div className="seg" role="radiogroup" aria-label={tr("Cách xem")}>
              <button type="button" role="radio" aria-checked={!grid} onClick={() => setGrid(false)} aria-label={tr("Danh sách")}><Icon name="list" size={14} /></button>
              <button type="button" role="radio" aria-checked={grid} onClick={() => setGrid(true)} aria-label={tr("Lưới")}><Icon name="grid" size={14} /></button>
            </div>
          </div>
        )}

        <div ref={list} className="p-3 lg:min-h-0 lg:flex-1 lg:overflow-y-auto" onWheel={() => { if (playing) setFollow(false); }}>
          {panel === "scenes" && (
            <>
              {!follow && playing && <button type="button" onClick={() => setFollow(true)} className="sticky top-0 z-10 mb-2 flex w-full items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-[12px] font-medium text-canvas shadow-lg"><Icon name="down" size={13} />{tr("Theo cảnh đang phát")}</button>}
              {shots.length === 0 && <p className="px-2 py-6 text-center text-[13px] text-mute">{tr("Bản dựng này được làm trước khi hệ thống ghi lại từng cảnh. Dựng lại để xem theo cảnh.")}</p>}
              <ol className={grid ? "grid grid-cols-2 gap-2" : "grid gap-2"}>
                {matching.map((s) => {
                  const on = current?.n === s.n;
                  return (
                    <li key={s.n} data-n={s.n}>
                      <button type="button" onClick={() => { seek(s.start + 0.001); void video.current?.play(); }}
                              className={`group w-full rounded-xl border p-2 text-left transition-colors ${on ? "border-accent/60 bg-accent/[0.07]" : "border-line bg-raised/40 hover:border-edge hover:bg-raised"} ${grid ? "" : "flex gap-3"}`}>
                        <span className={`relative block shrink-0 overflow-hidden rounded-lg bg-black ${grid ? "w-full" : "w-[128px]"}`}>
                          {s.thumb ? <img src={s.thumb} alt="" loading="lazy" className="aspect-video w-full object-cover transition-transform duration-300 group-hover:scale-[1.04]" /> : <span className={`block aspect-video ${s.gap ? "hatch-cue bg-raised" : "hatch bg-raised"}`} />}
                          <TimeChip className="absolute bottom-1 left-1 !h-[18px] !px-1.5 !text-[10px]">{longTc(s.start).slice(3, 8)}</TimeChip>
                          {on && playing && <span className="absolute right-1 top-1 flex h-[18px] items-end gap-[2px] rounded bg-black/60 px-1 pb-[3px]">{[0, 1, 2].map((k) => <span key={k} className="eq w-[2px] rounded-full bg-accent" style={{ animationDelay: `${k * 0.15}s` }} />)}</span>}
                        </span>
                        <span className={`block min-w-0 ${grid ? "mt-2 px-0.5" : "py-0.5"}`}>
                          <span className={`block truncate text-[13px] font-medium leading-snug ${on ? "text-accent" : ""}`}>{s.scene ? `${s.scene} · ` : ""}{tv`Cảnh ${String(s.n).padStart(2, "0")}`}</span>
                          <span className={`mt-0.5 block text-[12.5px] leading-relaxed text-mute ${grid ? "line-clamp-2" : "line-clamp-3"}`}>{s.text}</span>
                          {!grid && <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10.5px]">
                            <span className="mono rounded bg-overlay px-1.5 py-0.5 text-faint">{(s.end - s.start).toFixed(1)}s</span>
                            {s.gap ? <span className="rounded bg-cue/12 px-1.5 py-0.5 text-cue">{tr("THIẾU HÌNH")}</span> : s.source && <span className="max-w-[160px] truncate rounded bg-overlay px-1.5 py-0.5 text-faint">{s.source}</span>}
                            {findings.some((f) => f.shot === s.n) && <span className="rounded bg-cue/12 px-1.5 py-0.5 text-cue">{tr("NÊN XEM")}</span>}
                          </span>}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              {needle && matching.length === 0 && <p className="px-2 py-6 text-center text-[13px] text-mute">{tv`Không có cảnh nào chứa “${query}”.`}</p>}
            </>
          )}

          {panel === "words" && (
            <div>
              <div className="mb-3 flex items-center gap-2 px-1">
                <p className="eyebrow flex-1">{tr("Lời dẫn theo thời gian")}</p>
                <Button size="sm" kind="quiet" onClick={() => { void navigator.clipboard?.writeText(shots.map((s) => s.text).join("\n")); toast(tr("Đã chép toàn bộ lời dẫn.")); }}><Icon name="copy" size={13} />{tr("Chép")}</Button>
                {pkg && <a className="btn inline-flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] text-mute hover:bg-raised hover:text-ink" href={`/api/v1/renders/${render.render_id}/package/${pkg.captions}`} download><Icon name="download" size={13} />SRT</a>}
              </div>
              <ol className="grid gap-0.5">
                {shots.map((s) => {
                  const on = current?.n === s.n;
                  return (
                    <li key={s.n} data-n={s.n}>
                      <button type="button" onClick={() => seek(s.start + 0.001)} className={`grid w-full grid-cols-[52px_minmax(0,1fr)] gap-3 rounded-lg px-2 py-2 text-left transition-colors ${on ? "bg-accent/[0.08]" : "hover:bg-raised/60"}`}>
                        <span className={`mono pt-0.5 text-[11.5px] ${on ? "text-accent" : "text-faint"}`}>{timecode(s.start)}</span>
                        <span className={`text-[14px] leading-relaxed transition-colors duration-300 ${on ? "text-ink" : t > s.end ? "text-mute" : "text-faint"}`}>
                          {s.scene && s.scene !== shots[s.n - 2]?.scene && <span className="eyebrow mb-1 block !text-accent">{s.scene}</span>}
                          {s.text}{s.own && <span className="ml-2 align-middle text-[10.5px] text-proof">● {tr("giọng bạn")}</span>}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
              {pkg?.translations && Object.keys(pkg.translations).length > 0 && (
                <p className="mt-4 flex flex-wrap gap-2 px-2 text-[12px] text-mute">{tr("Bản dịch phụ đề:")}{Object.entries(pkg.translations).map(([lang, file]) => <a key={lang} className="link" href={`/api/v1/renders/${render.render_id}/package/${file}`} download>{lang}</a>)}</p>
              )}
            </div>
          )}

          {panel === "checks" && (
            <div className="grid gap-4">
              <div className="panel-raised overflow-hidden">
                <p className="flex items-center justify-between border-b border-line px-3.5 py-2.5"><span className="eyebrow">{tr("Kiểm tra tự động")}</span><Tag tone={render.qc.passed ? "proof" : "tally"}>{render.qc.passed ? tr("Đạt") : tr("Chưa đạt")}</Tag></p>
                <ul className="rows">
                  {Object.entries(render.qc.checks).map(([name, ok]) => <li key={name} className="flex items-center justify-between gap-3 px-3.5 py-2 text-[13px]"><span>{name}</span><Icon name={ok ? "check" : "x"} size={15} className={ok ? "text-proof" : "text-tally"} /></li>)}
                  {render.qc.gaps > 0 && <li className="flex items-center justify-between gap-3 px-3.5 py-2 text-[13px]"><span>{tr("Câu dùng nền trơn vì thiếu hình")}</span><span className="mono text-cue">{render.qc.gaps}</span></li>}
                </ul>
              </div>
              <div className="ai-card p-3.5">
                <div className="flex items-center gap-2"><Icon name="sparkles" size={15} className="text-ai" /><span className="flex-1 text-[13px] font-medium">{tr("AI xem như người xem")}</span>
                  <Button size="sm" kind="ai" busy={busy === "watch"} onClick={watchAgain}>{render.qc.viewer ? tr("Xem lại") : tr("Cho AI xem")}</Button></div>
                <p className="mt-1 text-[12px] text-mute">{render.qc.viewer ? tv`Đã xem ${render.qc.viewer.judged} trên ${render.qc.viewer.of} cảnh có hình.` : tr("Mô hình nhìn từng cảnh và so với lời dẫn: mở đầu, nhịp, lặp, hình có khớp lời không.")}</p>
              </div>
              {findings.length === 0 ? <p className="flex items-center gap-2 px-1 text-[13px] text-proof"><Icon name="check" size={15} />{tr("Không có điểm nào cần xem lại.")}</p> : (
                <div>
                  <p className="eyebrow mb-2 px-1">{tv`Nên xem lại · ${findings.length}`}</p>
                  <ul className="grid gap-2">
                    {findings.map((f, i) => { const s = shots[f.shot - 1]; return (
                      <li key={i}><button type="button" onClick={() => { if (s) seek(s.start + 0.001); }} className="w-full rounded-xl border border-line bg-raised/40 p-3 text-left text-[13px] transition-colors hover:border-edge">
                        <span className="mb-1 flex items-center gap-2"><span className={`h-2 w-2 rotate-45 rounded-[2px] ${f.severity === "cao" ? "bg-cue" : "bg-ai"}`} /><span className="font-medium">{f.check}</span>
                          <span className="ml-auto flex items-center gap-1.5 text-[11px] text-faint">{f.by}{s && <TimeChip className="!h-[18px] !text-[10px]">{timecode(s.start)}</TimeChip>}</span></span>
                        <span className="block text-mute">{tv`Cảnh ${f.shot}: ${f.text}`}</span>{f.fix && <span className="mt-1 block text-[12px] text-faint">→ {f.fix}</span>}
                      </button></li>); })}
                  </ul>
                </div>
              )}
            </div>
          )}

          {panel === "review" && (
            <div className="grid gap-4">
              <div className={`rounded-xl border p-4 ${reel.verdict === "waiting" ? "cue-card" : "border-line bg-raised/40"}`}>
                <p className="flex items-center gap-2"><Tag tone={v.tone}>{v.label}</Tag>{render.review && <span className="mono text-[11.5px] text-faint">{when(render.review.at)}</span>}</p>
                {reel.verdict === "open" && <p className="mt-2 text-[12.5px] text-mute">{tr("Đây là bản cũ, đã có bản dựng mới hơn. Chỉ bản mới nhất đang chờ mới duyệt được.")}</p>}
                {render.review?.comment && (
                  <div className="mt-3 text-[13px] leading-relaxed">
                    {render.review.comment.split(/(\d{1,2}:\d{2}(?:\.\d{1,3})?)/).map((part, i) => /^\d{1,2}:\d{2}/.test(part)
                      ? <button key={i} type="button" onClick={() => seek(marksIn(part)[0]?.at ?? 0)} className="mono mx-0.5 rounded bg-tally/15 px-1.5 text-[12px] text-tally hover:bg-tally/25">{part}</button> : <span key={i}>{part}</span>)}
                  </div>
                )}
              </div>
              {reel.verdict === "waiting" && (
                <div className="grid gap-3">
                  <label htmlFor="rv-note" className="field-label !mb-0">{tr("Nhận xét theo mốc thời gian")}</label>
                  <textarea id="rv-note" value={note} onChange={(e) => setNote(e.target.value)} rows={5} placeholder={tr("0:07 cảnh xay cà phê bị tối, đổi cảnh khác\n0:12 lời dẫn đọc nhanh quá")} className="w-full p-3 text-[13px] leading-relaxed" />
                  <div className="flex flex-wrap items-center gap-2">
                    <Button size="sm" onClick={mark}><Icon name="clock" size={13} />{tv`Ghi mốc ${timecode(t)}`}</Button>
                    <span className="text-[11.5px] text-faint">{tr("hoặc bấm N khi đang xem")}</span>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    <Button busy={busy === "reject"} disabled={!!busy} onClick={() => decide(false)}><Icon name="refresh" size={14} />{tr("Chưa được, dựng lại")}</Button>
                    <Button kind="primary" busy={busy === "approve"} disabled={!!busy} onClick={() => decide(true)}><Icon name="check" size={14} />{tr("Duyệt bản dựng")}</Button>
                  </div>
                </div>
              )}
              {reel.verdict !== "waiting" && <Button onClick={() => go(`/du-an/${p.project_id}`)}><Icon name="clapper" size={14} />{tr("Mở dự án để sửa và dựng lại")}</Button>}
              {rights && !rights.clear && (
                <div className="cue-card p-3.5 text-[12.5px]"><p className="mb-1 flex items-center gap-2 font-medium text-cue"><Icon name="alert" size={14} />{tr("Bản quyền cần xử lý trước khi đăng")}</p>
                  <ul className="grid gap-1 text-mute">{rights.blockers.map((b) => <li key={b}>• {b}</li>)}</ul></div>
              )}
            </div>
          )}

          {panel === "lineage" && (
            <div className="grid gap-3">
              <div className="flex flex-wrap gap-2 px-1">
                <a className={pill} href={`/api/v1/renders/${render.render_id}/edl`} download><Icon name="download" size={13} />EDL (Resolve)</a>
                <a className={pill} href={`/api/v1/renders/${render.render_id}/otio`} download><Icon name="download" size={13} />OpenTimelineIO</a>
              </div>
              {!lineage && <div className="grid gap-2 p-1"><Skeleton lines={3} /><Skeleton lines={3} /></div>}
              {lineage && <p className="px-1 text-[12px] text-faint">{tv`Kịch bản phiên bản ${lineage.script.version}`} · <span className="mono break-all">{lineage.file.split("/").slice(-2).join("/")}</span></p>}
              {lineage?.shots.map((s) => (
                <button key={s.line} type="button" onClick={() => { if (shots[s.line - 1]) seek(shots[s.line - 1].start + 0.001); }} className="rounded-xl border border-line bg-raised/40 p-3 text-left text-[12.5px] hover:border-edge">
                  <span className="mb-1 flex items-center gap-2"><span className="mono grid h-5 w-6 place-items-center rounded bg-overlay text-[10.5px] text-mute">{s.line}</span><span className="line-clamp-1 flex-1 text-ink">{s.text}</span><span className="mono text-[11px] text-faint">{s.duration.toFixed(1)}s</span></span>
                  {s.source && <span className="block text-mute"><Icon name="film" size={12} className="mr-1 inline align-[-1px]" />{s.source.name}{s.source.t_in != null && <span className="mono"> @ {timecode(s.source.t_in)}</span>} <span className="text-faint">· {ORIGIN[s.source.origin] ?? s.source.origin}{s.source.rights?.licence ? ` · ${s.source.rights.licence}` : ""}</span></span>}
                  {s.generated?.map((g, k) => <span key={k} className="mt-1 block text-mute"><Icon name="spark" size={12} className="mr-1 inline align-[-1px] text-ai" />{g.provider}{g.model ? ` / ${g.model}` : ""}{g.seed != null && <span className="mono"> · seed {g.seed}</span>}<span className="mt-0.5 line-clamp-2 block text-faint">{g.prompt}</span></span>)}
                  {!s.source && !s.generated && <span className="block text-cue">{tr("Nền trơn, không có hình")}</span>}
                </button>
              ))}
            </div>
          )}
        </div>
      </aside>
    </section>
  );
}

/** Phòng chiếu: the gallery of every finished cut, and the screening of one of them. */
export default function Review() {
  const { data: projects } = usePoll<Project[]>("/api/v1/projects", 5000);
  const id = new URLSearchParams(window.location.search).get("r");
  const all = useMemo(() => reels(projects ?? []), [projects]);
  if (!id) return <Gallery projects={projects} />;
  if (!projects) return <div className="grid flex-1 place-items-center text-mute"><Spinner size={22} /></div>;
  const reel = all.find((r) => r.render.render_id === id);
  if (!reel) return <Page title={tr("Phòng chiếu")}><Empty icon="alert" title={tr("Không tìm thấy bản dựng này")} action={<Button onClick={() => go("/phong-chieu")}>{tr("Về Phòng chiếu")}</Button>} /></Page>;
  const siblings = all.filter((r) => r.project.project_id === reel.project.project_id).sort((a, b) => a.version - b.version);
  return <Screening key={id} reel={reel} siblings={siblings} />;
}
