import { t as tr, tv, locale } from "./i18n";
import { useState } from "react";
import { post, usePoll, type TrashView } from "./api";
import { ask, Button, Empty, Icon, OpsSide, Page, Tag, toast } from "./parts";

/** NEXORA's own Trash: what was deleted waits here, out of every list and search, until it is restored or deleted for good. */
export default function Trash() {
  const { data, reload } = usePoll<TrashView>("/api/v1/trash", 5000);
  const [files, setFiles] = useState(false);
  const [busy, setBusy] = useState(false);
  const total = (data?.assets.length ?? 0) + (data?.projects.length ?? 0);
  const act = async (fn: () => Promise<unknown>) => { setBusy(true); try { await fn(); } catch (e) { toast((e as Error).message, { tone: "tally" }); } setBusy(false); reload(); };
  const restore = (body: { assets?: string[]; projects?: string[] }, name: string) => act(async () => { await post("/api/v1/trash/restore", body); toast(tv`Đã khôi phục “${name}”.`); });
  const purge = (body: { assets?: string[]; projects?: string[]; discard_files?: boolean }, title: string, detail: string) => act(async () => {
    if (!(await ask(title, { body: detail, confirm: tr("Xoá vĩnh viễn"), danger: true }))) return;
    const r = await post<{ assets: number; projects: number; kept: { title: string; reason: string }[] }>("/api/v1/trash/purge", body);
    r.kept.forEach((k) => toast(`${k.title}: ${k.reason}`, { tone: "tally", seconds: 8 }));
    if (r.assets + r.projects) toast(tv`Đã xoá vĩnh viễn ${r.assets + r.projects} mục.`);
  });
  const when = (t: number) => new Date(t * 1000).toLocaleDateString(locale, { day: "numeric", month: "numeric", year: "numeric" });
  const fileNote = files ? tr(" File gốc của footage cũng được chuyển vào Thùng rác của máy.") : tr(" File gốc của footage vẫn nằm nguyên chỗ cũ.");
  const row = (key: string, icon: string, name: string, kind: string, at: number, left: number, onRestore: () => void, onPurge: () => void, warn?: string) => (
    <li key={key} className="grid items-center gap-x-3.5 gap-y-2 px-4 py-3 sm:grid-cols-[32px_minmax(0,1fr)_auto_auto]">
      <span className="hidden h-8 w-8 place-items-center rounded-lg bg-raised text-mute sm:grid"><Icon name={icon} size={15} /></span>
      <span className="min-w-0"><span className="block truncate font-medium">{name}</span>
        <span className="block text-[12.5px] text-mute">{kind}, {tv`xoá ngày ${when(at)}`}, <span className={left <= 3 ? "text-cue" : ""}>{tv`tự xoá vĩnh viễn sau ${left} ngày`}</span>{warn && <span className="text-cue">. {warn}</span>}</span></span>
      <Button size="sm" disabled={busy} onClick={onRestore}><Icon name="undo" size={14} />{tr("Khôi phục")}</Button>
      <Button size="sm" disabled={busy} onClick={onPurge}>{tr("Xoá vĩnh viễn")}</Button>
    </li>
  );
  const KIND: Record<string, string> = { video: tr("Video"), image: tr("Ảnh"), audio: tr("Âm thanh") };
  return (
    <Page side={<OpsSide />} eyebrow={tr("Vận hành")} title={tr("Thùng rác")}
          note={data ? tv`Dự án và footage đã xoá nằm đây ${data.days} ngày rồi mới bị xoá vĩnh viễn. Trong lúc ở đây chúng không hiện ở đâu cả và không được dùng cho kịch bản nào.` : null}
          actions={total > 0 && <Button disabled={busy} onClick={() => purge({ discard_files: files }, tr("Dọn sạch thùng rác?"), tv`${total} mục sẽ bị xoá vĩnh viễn, không khôi phục được nữa.` + fileNote)}><Icon name="trash" size={15} />{tr("Dọn thùng rác")}</Button>}>
      {data && total === 0 && <div className="max-w-xl"><Empty icon="trash" title={tr("Thùng rác trống")}>{tr("Dự án và footage bạn xoá sẽ nằm ở đây một thời gian, để lấy lại được nếu xoá nhầm.")}</Empty></div>}
      {total > 0 && (
        <div className="grid max-w-4xl gap-7">
          {data!.assets.length > 0 && <label className="flex items-start gap-2.5 rounded-lg border border-line bg-raised/50 p-3 text-[13px]"><input type="checkbox" className="mt-0.5" checked={files} onChange={(e) => setFiles(e.target.checked)} />
            <span>{tr("Khi xoá vĩnh viễn footage, chuyển luôn file gốc vào Thùng rác của máy")}<span className="block text-[12px] text-faint">{tr("Tắt thì chỉ xoá khỏi NEXORA (mô tả, bản xem, số đo); file video của bạn vẫn nằm nguyên chỗ cũ.")}</span></span></label>}
          {data!.projects.length > 0 && <section>
            <h2 className="eyebrow mb-2.5 flex items-center gap-3">{tr("Dự án")}<span className="h-px flex-1 bg-line" /><span className="mono normal-case tracking-normal">{data!.projects.length}</span></h2>
            <ul className="panel rows overflow-hidden">{data!.projects.map((p) => row(p.project_id, "clapper", p.title, tr("Dự án"), p.trashed_at, p.days_left,
              () => restore({ projects: [p.project_id] }, p.title),
              () => purge({ projects: [p.project_id] }, tr("Xoá vĩnh viễn dự án này?"), tv`${p.title}. Kịch bản, lựa chọn clip và các bản dựng bị xoá; file bản dựng vào Thùng rác của máy.`),
              p.published ? tr("Có video đã đăng nên không xoá vĩnh viễn được") : undefined))}</ul>
          </section>}
          {data!.assets.length > 0 && <section>
            <h2 className="eyebrow mb-2.5 flex items-center gap-3">{tr("Footage")}<span className="h-px flex-1 bg-line" /><span className="mono normal-case tracking-normal">{data!.assets.length}</span></h2>
            <ul className="panel rows overflow-hidden">{data!.assets.map((a) => row(a.asset_id, a.kind === "audio" ? "music" : a.kind === "image" ? "image" : "film", a.name, KIND[a.kind] ?? a.kind, a.trashed_at, a.days_left,
              () => restore({ assets: [a.asset_id] }, a.name),
              () => purge({ assets: [a.asset_id], discard_files: files }, tr("Xoá vĩnh viễn footage này?"), a.name + "." + fileNote)))}</ul>
          </section>}
          <p className="text-[12.5px] text-faint"><Tag tone="mute">{tr("Lưu ý")}</Tag> {tr("Khôi phục footage trả lại hình cho những câu kịch bản đã mất nó, trừ câu đã được chọn clip khác trong lúc đó.")}</p>
        </div>
      )}
    </Page>
  );
}
