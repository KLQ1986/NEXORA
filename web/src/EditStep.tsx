import { t as tr, tv } from "./i18n";
import { useCallback, useEffect, useRef, useState } from "react";
import { call, post, usePoll } from "./api";
import { Button, Icon, toast } from "./parts";

/* The Edit step (design 2026-10-17): FilmCraft's editor, pinned and served by NEXORA, driven through its own command API
   (window.filmcraft, same origin). The storyboard is built into a sequence once; the operator edits; every save is a
   version of the project's cut kept by NEXORA; the final render runs on this Mac with FilmCraft's engine. */

type Cmd = { id: string; params: Record<string, unknown>; tag?: string; as?: string };
type Plan = { media: { version: string | null; name: string; url: string }[]; commands: Cmd[]; missing: { code: string; reason: string }[]; notes: string[];
  seconds: number; shots: number; sound: { voice: number; music: boolean; sfx: number } };
type CutVersion = { cut_id: string; version: number; made_by: string; note: string | null; source: string | null; created_at: number;
  stats: { sequences: { name: string; video_clips: number; captions: number }[]; media: number }; document_url: string; export: { run_id: string; status: string } | null };
type CutView = { editor: { ready: boolean; version: string; url: string; native: boolean; fix: string | null }; versions: CutVersion[]; storyboard: boolean };
type FilmCraftApi = {
  execute: (id: string, params?: unknown) => Promise<any>;
  importUrl: (url: string, name?: string) => Promise<{ items: number[]; errors: unknown[] }>;
  openProject: (fileOrUrl: unknown) => Promise<unknown>;
  readFile: (path: string) => Promise<Uint8Array>;
  files: () => Promise<{ path: string; size: number; kind: string }[]>;
};

const TICKS = 254016000000;                         // FilmCraft's time: ticks a second
const PATH = "/opfs/nexora/cut.fcproj";       // written to the browser's private storage, never offered as a download
const FILES = /"\/files\/([^"/]+)"/g;

export default function EditStep({ projectId, approved, onChanged }: { projectId: string; approved: boolean; onChanged: () => void }) {
  const url = `/api/v1/projects/${projectId}/cut`;
  const { data, reload } = usePoll<CutView>(url, 4000);
  const frame = useRef<HTMLIFrameElement>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);          // the version shown in the editor
  const [dirty, setDirty] = useState(false);
  const [ready, setReady] = useState(false);
  const [height, setHeight] = useState(() => Math.max(560, window.innerHeight - 230));
  const started = useRef(false);

  useEffect(() => { const r = () => setHeight(Math.max(560, window.innerHeight - 230)); window.addEventListener("resize", r); return () => window.removeEventListener("resize", r); }, []);

  /** The editor's command API, once its page has started. */
  const fc = useCallback(async (): Promise<FilmCraftApi> => {
    for (let i = 0; i < 200; i++) {
      const api = (frame.current?.contentWindow as unknown as { filmcraft?: FilmCraftApi } | null)?.filmcraft;
      if (api?.execute) return api;
      await new Promise((r) => setTimeout(r, 100));
    }
    throw new Error(tr("Trình dựng chưa khởi động."));
  }, []);

  const act = async (key: string, fn: () => Promise<unknown>, done?: string) => {
    setBusy(key);
    try { await fn(); if (done) toast(done, { tone: "proof" }); } catch (e) { toast((e as Error).message, { tone: "tally" }); } finally { setBusy(null); reload(); onChanged(); }
  };

  /** Every medium a document names, brought into the editor under the name the document uses. */
  const bring = async (api: FilmCraftApi, media: { name: string; url: string }[]) => {
    const items: Record<string, number> = {};
    const held = new Set((await api.files()).map((f) => f.path));
    for (const m of media) {
      // A file already fetched in this session is only added to the project, so it keeps its one name (`/files/<name>`).
      const r = held.has(`/files/${m.name}`) ? await api.execute("file.import", { paths: [`/files/${m.name}`] }) : await api.importUrl(m.url, m.name);
      items[m.name] = items[m.name.split(".")[0]] = r.items[0];         // by its file name, and by the version id it starts with
    }
    return items;
  };

  /** FilmCraft moves sync-locked captions on insert and extract but not on a ripple trim: while the cut keeps the storyboard's
      shape (one line a shot), each caption is laid again over its own shot, one frame clear of the next. */
  const realign = async (api: FilmCraftApi) => {
    const s = await api.execute("sequence.inspect", {});
    const clips = (s?.video?.[0]?.items ?? []) as { start: number; duration: number }[];
    const track = (await api.execute("captions.list", { track: "C1" }).catch(() => null))?.tracks?.[0];
    const caps = (track?.captions ?? []) as { id: number; start: number; end: number; text: string }[];
    if (!clips.length || caps.length !== clips.length || !s.durationFrames) return;
    const frame = Math.round(s.duration / s.durationFrames);
    const want = clips.map((c, k) => [c.start + (k ? frame : 0), c.start + c.duration - frame]);
    if (caps.every((c, k) => Math.abs(c.start - want[k][0]) <= frame && Math.abs(c.end - want[k][1]) <= frame)) return;
    await api.execute("captions.delete", { captions: caps.map((c) => c.id) });
    for (const [k, c] of caps.entries()) {
      await api.execute("captions.add", { track: "C1", text: c.text, time: want[k][0], durationSeconds: (want[k][1] - want[k][0]) / TICKS });
    }
  };

  /** The Source monitor shows the media of a timeline clip, its In and Out at the stretch the shot uses, the playhead at
      its In: never "No clips", and the stretch around the shot is there to slip, re-cut or insert from. */
  const showInSource = useCallback(async (api: FilmCraftApi, clip?: number) => {
    const s = await api.execute("sequence.inspect", {});
    const items = (s?.video ?? []).flatMap((t: { items: { clip: number; sourceIn: number; sourceOut: number }[] }) => t.items);
    const c = clip == null ? items[0] : items.find((i: { clip: number }) => i.clip === clip);
    if (!c) { if (clip != null) shown.current = clip; return; }       // a sound clip: the Source stays as it is
    await api.execute("source.open", { clip: c.clip });
    await api.execute("source.setPlayhead", { time: c.sourceIn });     // no marks set: looking at a shot changes nothing in the cut
    shown.current = c.clip;
  }, []);
  const shown = useRef<number | null>(null);

  const save = async (note: string, source = "operator") => {
    const api = await fc();
    await realign(api);
    await api.execute("file.saveAs", { path: PATH });
    const text = new TextDecoder().decode(await api.readFile(PATH));
    const r = await post<{ saved: CutVersion }>(url, { document: text, note, source, made_by: "operator" });
    setOpen(r.saved.version);
    setDirty(false);
    return r.saved;
  };

  const build = async () => {
    const api = await fc();
    const plan = await call<Plan>(`${url}/plan`);
    // A fresh project: the cut being edited stays as it was in its own version, and nothing is imported into it twice.
    await api.execute("file.newProject", { name: "cut" });
    const items = await bring(api, plan.media);
    let clips: number[] = [];
    const tags: Record<string, number[]> = {};
    const refs: Record<string, unknown> = {};
    const resolve = (v: unknown): unknown => {
      if (typeof v === "string" && v.startsWith("$item:")) return items[v.slice(6)];
      if (typeof v === "string" && v.startsWith("$ref:")) return refs[v.slice(5)];
      if (typeof v === "string" && v.startsWith("$tag:")) return tags[v.slice(5)] ?? [];
      if (v === "$clip" || (Array.isArray(v) && v.length === 1 && v[0] === "$clip")) return clips;
      if (Array.isArray(v)) return v.map(resolve);
      return v;
    };
    for (const c of plan.commands) {
      const params = Object.fromEntries(Object.entries(c.params).map(([k, v]) => [k, resolve(v)]));
      const r = await api.execute(c.id, params);
      if (c.id === "timeline.place") clips = (r?.clips ?? []) as number[];
      if (c.tag) tags[c.tag] = [...(tags[c.tag] ?? []), ...clips];
      if (c.as) refs[c.as] = r?.bin ?? r?.item ?? r;                  // what this command made, for later commands to name
    }
    await save(tr("lắp từ storyboard"), "storyboard");
    await showInSource(api).catch(() => undefined);
    if (plan.missing.length) toast(tv`${plan.missing.length} shot chưa có hình: để trống trên timeline.`, { tone: "tally" });
    if (plan.notes.length) toast(plan.notes.slice(0, 3).join(" · "), { tone: "tally" });
  };

  const openVersion = async (v: CutVersion) => {
    const api = await fc();
    const text = await (await fetch(v.document_url)).text();
    const media = [...text.matchAll(FILES)].map((m) => ({ name: m[1], url: m[1].startsWith("ver_") ? `/media/${(m[1].match(/^ver_[0-9A-Za-z]+/) ?? [m[1]])[0]}` : `${url}/sound/${encodeURIComponent(m[1])}` }));
    await api.execute("file.newProject", { name: "cut" });
    const held = new Set((await api.files()).map((f) => f.path));
    for (const m of new Map(media.map((m) => [m.name, m])).values()) if (!held.has(`/files/${m.name}`)) await api.importUrl(m.url, m.name);
    await api.openProject(v.document_url);
    await showInSource(api).catch(() => undefined);
    setOpen(v.version);
    setDirty(false);
  };

  // First visit: the newest version opens; with none, the storyboard is built into one.
  useEffect(() => {
    if (!data || !ready || started.current || !data.editor.ready) return;
    started.current = true;
    const newest = data.versions[0];
    if (newest) act("open", () => openVersion(newest));
    else if (data.storyboard && approved) act("build", build, tr("Đã lắp storyboard thành timeline (phiên bản 1)."));
  }, [data, ready]);

  // A clip chosen on the timeline is shown in the Source monitor, at its stretch.
  useEffect(() => {
    if (!ready) return;
    const id = window.setInterval(async () => {
      try {
        const api = await fc();
        const sel = ((await api.execute("state.inspect", {}))?.selection ?? []) as number[];
        if (sel.length === 1 && sel[0] !== shown.current) await showInSource(api, sel[0]);
      } catch { /* not ready, or a sound clip */ }
    }, 900);
    return () => window.clearInterval(id);
  }, [ready, fc, showInSource]);

  // Edits mark the open version as changed, so leaving or exporting asks to save first.
  useEffect(() => {
    if (!ready) return;
    const id = window.setInterval(async () => {
      try { const api = await fc(); const s = await api.execute("project.inspect", {}); setDirty(!!s?.dirty); } catch { /* not ready */ }
    }, 3000);
    return () => window.clearInterval(id);
  }, [ready, fc]);

  if (!data) return <div className="panel h-[560px] animate-pulse" />;
  if (!data.editor.ready) {
    return (
      <div className="panel grid gap-2 p-5">
        <p className="font-semibold">{tr("Trình dựng chưa được cài")}</p>
        <p className="text-mute">{tr("Chạy một lần trong thư mục NEXORA:")} <code className="mono">{data.editor.fix}</code></p>
      </div>
    );
  }
  const current = data.versions.find((v) => v.version === open) ?? data.versions[0];
  const exp = current?.export;
  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{tr("Dựng video")}</span>
        <span className="mono rounded border border-line px-1.5 text-[11px] text-faint">FilmCraft {data.editor.version}</span>
        {current && <span className="text-[12.5px] text-mute">{tv`Phiên bản ${current.version}`}{dirty ? <span className="text-cue">{tr(" · có thay đổi chưa lưu")}</span> : ""}</span>}
        <span className="flex-1" />
        <Button size="sm" busy={busy === "build"} disabled={!data.storyboard} title={tr("Lắp storyboard thành một sequence mới; bản dựng tay đang có vẫn giữ nguyên trong các phiên bản")}
                onClick={() => act("build", build, tr("Đã lắp lại từ storyboard thành phiên bản mới."))}><Icon name="layers" size={14} />{tr("Lắp từ Storyboard")}</Button>
        <Button size="sm" busy={busy === "save"} onClick={() => act("save", () => save(tr("lưu tay")), tr("Đã lưu phiên bản mới."))}><Icon name="check" size={14} />{tr("Lưu phiên bản")}</Button>
        {data.versions.length > 0 && (
          <select aria-label={tr("Phiên bản")} value={current?.version ?? ""} onChange={(e) => { const v = data.versions.find((x) => x.version === Number(e.target.value)); if (v) act("open", () => openVersion(v)); }}
                  className="h-8 rounded-md border border-line bg-canvas px-2 text-[12.5px] text-ink">
            {data.versions.map((v) => <option key={v.cut_id} value={v.version}>{`v${v.version} · ${v.note ?? v.source ?? ""} · ${new Date(v.created_at * 1000).toLocaleString()}`}</option>)}
          </select>)}
        <Button size="sm" kind="primary" busy={busy === "export"} disabled={!data.editor.native || !current}
                title={data.editor.native ? tr("Lưu rồi xuất trên máy này từ file gốc (FilmCraft, encoder phần cứng); bản xuất chờ bạn duyệt như mọi bản dựng") : tr("Chưa cài FilmCraft CLI: sh scripts/setup-filmcraft.sh")}
                onClick={() => act("export", async () => { const v = dirty || !current ? await save(tr("lưu trước khi xuất")) : current; await post(`${url}/${v.cut_id}/export`); }, tr("Đang xuất bản dựng trên máy này."))}>
          <Icon name="scissors" size={14} />{tr("Xuất bản dựng")}</Button>
        {exp && <span className={`text-[12px] ${exp.status === "waiting_review" ? "text-cue" : exp.status === "failed" ? "text-tally" : "text-faint"}`}>
          {({ waiting_review: tr("bản xuất chờ duyệt"), succeeded: tr("đã duyệt"), failed: tr("xuất lỗi"), running: tr("đang xuất…"), queued: tr("đang chờ xuất") } as Record<string, string>)[exp.status] ?? exp.status}</span>}
      </div>
      <iframe ref={frame} src={data.editor.url} title={tr("Trình dựng")} onLoad={() => setReady(true)} allow="cross-origin-isolated; autoplay; fullscreen"
              className="w-full rounded-xl border border-line bg-black" style={{ height }} />
    </div>
  );
}
