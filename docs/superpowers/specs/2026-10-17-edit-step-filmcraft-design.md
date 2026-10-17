# The Edit step on FilmCraft: design (2026-10-17)

A project's steps are Script → Storyboard → **Edit** → Publish. Edit is a full timeline editor: FilmCraft's engine
(storytold/filmcraft, MIT OR Apache-2.0), first with its own interface inside NEXORA, then with NEXORA's interface over the
same engine, panel by panel. The engine is kept; only the interface is written again. The Semantic Editing Copilot is a mode
of the Storyboard and applies its decisions to the cut through the engine's commands.

## Why FilmCraft (the audit, 2026-10-17)

The repositories of `AI_Video_Factory_Video_Editing_Feature_Design_v1.0` (ADR-VE-008: no native editing core before an
audit) and the ones found since were held against the design's criteria. FilmCraft is the only one that is at once
embeddable in NEXORA's web interface (a WebAssembly build), drivable by an agent (701 commands with undo), deep enough to
finish a cut (Premiere-style trims, Lumetri with scopes, a mixer with loudness, multicam, captions, FCPXML / AAF / OTIO / EDL)
and ready for the Copilot (`transcript.set / extract / lift / removeFillers / removePauses / createCaptions`). Runner-up:
OpenReel (MIT, React/TypeScript, shallower, one main author). OpenTake, Cutlass and Dawn Cut are sources of ideas (context
signals, a capability ledger, dry-run by default, a deterministic edit core). CapCut and DaVinci Resolve Free are hand-off
targets by file only: CapCut has no editing API, and Resolve Free 21.0.2 (installed) runs scripts only from inside it
(21.1 removes Python from the Free edition altogether).

Risks taken with it: the repository is young (created 2026-09-30) and releases every two days, so one version is pinned by
SHA-256 and upgraded only on purpose; the web build is single-threaded and reads an imported URL whole into memory.

## Spike results (FilmCraft 0.8.0 web, Chrome on the M4, project "Thử ghép A-G")

| Check | Result | Status |
|---|---|---|
| Release integrity | zip SHA-256 equal in `SHA256SUMS.txt`, recomputed, and GitHub's digest; no address fetched by the page on its own | verified |
| Served by NEXORA at `/filmcraft/` | each file of code checked against its pin before it is handed out; COOP/COEP; cross-origin isolated; WebGPU compositor; WebCodecs for H.264, HEVC, VP9, AV1; ready in 0.22 s | verified (test `tests/api/test_filmcraft.py`) |
| Storyboard → sequence by commands | 6 proxies imported by URL (5–13 MB each); 7 SC on V1 at their `t_in`/`t_out`, frame-exact (SC1 90 frames from 4.67 s); markers SC1–SC7 with each shot's line; a Vietnamese caption track | verified |
| Vietnamese text | captions drawn with every diacritic | verified |
| Playback | 8 s at Half and at Full (1080p): 239 frames shown, 0 dropped; render p95 0.26 ms, decode p95 0.17 ms | verified |
| Ripple trim and undo | SC2 out −15 frames: SC2 105 → 90, SC3 moved 195 → 180; undo restores it | verified |
| Ripple and the caption track | FilmCraft moves sync-locked captions on insert and extract, not on a ripple trim (its `edit` crate) | worked around: before each save the bridge lays each caption over its shot again while the cut keeps one line a shot (SC2 −15 frames: SC3 at 180, its caption at 181) |
| Export in the browser | H.264 1080p, 668 frames, AAC, plays clean in ffmpeg; **160 s for 22 s (4.2 fps)** | verified, too slow for the final render |
| Native export (`filmcraft-cli` 0.8.0, signed and notarized), originals (4K HEVC 10-bit 4:2:0) | 22 s of 1080p in **10–11 s** with VideoToolbox (19 s from the proxies in software); 4K fitted to the frame; captions burned in; loudness −16.1 LUFS | verified |
| Saving into NEXORA and reopening | saved to the browser's private storage (`/opfs/`, never a download), sent to NEXORA as a version; reopened with its media brought in again | verified |
| Inside the project page | the Edit step shows the editor; first visit builds v1 from the storyboard; Save version; Render the cut → a render waiting for review (QC passed, 14 s in all) | verified on "Thử ghép A-G" |
| Narration, music and sound effects on A1–A3 | not built yet | open |

## Who holds what

- **The Storyboard is the plan**: shots, pictures, treatments, seams. "Approve storyboard → Edit" builds a new sequence from it.
- **The cut is the `.fcproj`**, and NEXORA holds it: every save is a version of the project's cut (a checkpoint), listed,
  diffed and restorable. Nothing else holds the cut: FilmCraft's own recovery in the browser (OPFS) is turned off
  (`?norecover&fresh`) so a stale copy never comes back over NEXORA's.
- Building again from the storyboard makes a **new sequence**; it never overwrites one edited by hand.
- The Copilot proposes decisions with their evidence (the spec of 2026-10-17); applied, they run as engine commands on the
  open sequence and the result is saved as a new version.

## The bridge: storyboard to sequence

| Storyboard | FilmCraft |
|---|---|
| Format (16:9, 9:16, 1:1), length | `file.newSequence {width, height, fps}` |
| Each SC with a picture | `timeline.place {item, track: V1, seconds, sourceIn, duration}`; the picture's VQ version when it has one |
| SC code and line | `markers.add {name: SCn, comment: line}` |
| Narration (machine voice or the operator's take) | A1 |
| Music, with ducking | A2; `essentialSound.setType` dialogue / music and `essentialSound.generateDucking` |
| Sound effect of a shot | A3 at the shot |
| Speed | `clip.speedDuration {speed}` |
| Stabilise | Warp Stabilizer on the clip (or the VQ version, already stabilised) |
| Own sound | keep the clip's audio, the narration lane empty there |
| Lip-sync, upscale | made on NEXORA's side first (RunPod), the result placed instead |
| Lines as captions | `captions.newTrack` + `captions.add`, each one frame clear of the next (two touching captions are refused) |
| Spoken clips | `transcript.set` with NEXORA's own transcript (word times, speakers), for the Copilot |

Media go in as proxies (H.264 8-bit 1080p, what FilmCraft decodes fastest). Above about 200 MB a file goes as the stretch the
shot uses plus handles, cut on NEXORA's side, so the browser never holds a whole long recording.

## Export

The final render is native, never the browser's: `filmcraft-cli` (its signed macOS build, pinned like the web build) renders
the saved `.fcproj` relinked to the originals, on all cores and VideoToolbox; NEXORA's QC then reads it as today. Until that
is verified, NEXORA's own FFmpeg render stays the export path, from the storyboard. Hand-offs: FCPXML / OTIO to Resolve,
a draft to CapCut.

## Phases

1. **Use FilmCraft** (a–c done 2026-10-18: `core/cuts.py`, `modules/edit/cut.py`, `adapters/filmcraft.py`, `web/src/EditStep.tsx`)
   a. The Edit step shows FilmCraft (same origin, pinned), the tree's "Cut and review" becoming "Edit".
   b. The bridge above; save and reopen through NEXORA's versions; captions kept in step with ripples.
   c. Native export with `filmcraft-cli`; QC; Screening room as today.
   d. The Copilot: `transcript.set`, decisions as command batches, each applied as a version.
2. **NEXORA's interface over FilmCraft's engine**, panel by panel: a WebAssembly build of the engine without its egui
   interface (needs the Rust toolchain on this Mac), exposing commands, inspection and frames to a canvas; then NEXORA panels
   in this order: bins (NEXORA's Library), inspector and Copilot / transcript, timeline, monitors last.
3. **Rewrite only with a reason**, for example where NEXORA already does better (VQ before creative grading).

## Testing

The route (pins, isolation, paths) is tested; the bridge gets a test per mapping row against a headless session
(`filmcraft-cli`) once it is pinned; every phase ends with the spike's checks run again on one real project.

## Open

- Whether the caption track should follow ripples by sync lock or by the bridge.
- `filmcraft-cli` on originals: speed, HEVC 10-bit D-Log M, VideoToolbox.
- The Rust toolchain for phase 2 (the operator's word before it is installed).
