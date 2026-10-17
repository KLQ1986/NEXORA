# Ideas from the library, channel profiles with structured templates, alternate openings and endings

Date: 2026-10-18. Design v4.0 sections 16.1, 16.2, 16.3, 16.4, 16.6. Approved in conversation the same day.

## Why

The ideas the system proposed were a model's brainstorm over one line per video, three of four scores were the model's own
opinion, a risk only moved an idea down the list, nothing was kept, and an idea led nowhere but to the autonomous producer.
Channels knew their platform and cadence but not how the channel speaks; templates knew captions and voice but not the shape
of a video; a script had one opening and one ending.

## 1. Ideas: the library first, kept

- **Clusters are measured, not asked for.** The understood footage (not trashed, not rejected, not reference-only) is grouped
  two ways: by subject (the video-level `chu_de` tags, lower-cased) and by shooting session (the operator's session name, else
  the capture day from the probe's `created`). A cluster holds its assets, total and unused seconds (unused: in no project),
  sessions, the places its segments name (`boi_canh`) and a few segment descriptions. Clusters with the same assets are one;
  the largest by unused seconds come first.
- **The model only writes the angle**, one small prompt per cluster (so a 7B local model can carry it): a title, an angle, a
  template from the operator's list, five to eight shots the video needs, audience fit, fit with the channel when a channel
  is chosen, and a risk.
- **Coverage is measured per shot.** Each needed shot is searched in the index; a shot is covered when its best moment scores
  at least 0.5 (the radar's threshold). Kept per shot: the moment, asset and range. The idea carries the share covered, the
  gaps (uncovered shots) and an estimated length (covered shots hold their moment's length within 2 to 6 s, a gap 4 s).
- **Scores, 1 to 5:** audience fit (model), channel fit (model, only with a channel), footage (measured share covered),
  freshness (measured: the cluster's unused share), difference (measured: how far from the closest project already made or
  idea already proposed this run; the embedding's similarity mapped from 0.35, two unrelated ideas, to 0.85, the same idea,
  as measured with bge-m3; else word overlap).
- A group sharing 60% of its footage with a group already proposed for in this run is passed over (the first real run gave
  the same resort twice, once by subject "cây cỏ", once by "cảnh quan").
- **A risk that would stop the video blocks** (consent, privacy, a claim that is wrong or unlawful: the model says `chan`);
  any other risk is a note. On the first real run the 7B model wrote a risk for every idea, so blocking on any risk blocked
  them all. A blocked idea is taken only with the operator's reason, which is kept.
- **Kept** in `ideas` (core/ideas.py): status `new | blocked | accepted | dropped`. Proposing again sets aside every undecided
  idea first; accepted and dropped ones stay as history.
- A local model takes about two minutes a group (9.6 minutes for four on the first run), so proposing runs in the background
  and the screen follows it.
- **Accepting** creates a project from the idea's template and channel, keeps the idea on it (`projects.idea`), and opens the
  Storyboard, whose start screen is filled with the idea (title, angle, shots).
- **Triggers:** on request, and in the background when the understood library has changed and at least an hour has passed,
  or a week has passed; a notification says how many ideas are new.

## 2. Channel profiles and structured templates

- A channel gains `tone`, `pacing`, `banned` (phrases never said) and `notes`; every change raises its `version`. A project
  records the channel version it was planned with.
- The channel's profile is written into the prompts of ideas, the draft, the critique and the Copilot's reading. A banned
  phrase found in a script is a measured critique note, not a model's.
- A template gains `structure`: segments with a role (`hook | body | close`), a label, a duration range and what the segment
  must achieve. Defaults: hook 3–8 s, body, close 3–10 s.
- The draft writes one `# <label>` scene per segment (the script's existing scene marker), so a script carries its structure.
- **Structure check:** each scene's length is estimated (a line's own hold time, else its words at 2.6 per second) and compared
  with its segment's range; a scene too short or too long, or a segment missing, is said on the script.

## 3. Alternate openings and endings

- From the current script, the opening (the first scene, or the first line when there are no scenes) or the ending (the last
  scene, or the last line) is written again two or three ways; the rest is not touched.
- Each alternative is kept whole in `script_variants` with its part and a label ("Mở bài B"); "A" is the script as it is.
- Choosing one saves it as the script's next version, labelled; the other alternatives stay to choose later.

## Tests

The fake model answers the cluster and variant prompts; tests cover measured coverage and scores, blocking and its reason,
replacement on proposing again, accepting into a project, the channel profile in prompts and banned phrases, the structure
check, and choosing a variant. Then one real run on the library with the local model.
