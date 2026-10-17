# Director & Storyboard: design (2026-10-17)

From an idea to a cut through a structured storyboard whose every shot is a contract: what it must show, how long, where its
picture comes from, how it is made when it is made, what it must stay consistent with, and how it is accepted. The operator
shapes the storyboard by talking to the Director; the Director carries each shot to its acceptance on its own where it can,
and brings to the operator only what needs a person.

    Idea → Script → Storyboard → Shot Plan → Asset Assignment → Timeline Draft (animatic) → Render

The way of working is learnt from tools like OpenArt's storyboard; nothing here claims how they work inside.

## Assumptions (to correct)

- Content is mixed: the operator's own footage and generated pictures in about equal measure (answer (c)). Footage is tried
  first where a shot allows it; generation fills the rest.
- Personal use, local first: models run on the Mac where they can; RunPod and hosted APIs (fal) when the operator allows and
  pays. Privacy mode and the budget always win.
- UI first: the screen is built and agreed on fixture data before the backend described here is written.

## What NEXORA has and this builds on

| Need | Already | Added here |
|---|---|---|
| script lines, scenes, brief, on-screen text, minimum length, fact checks | `planning/scripts.py`, `Shot` | idea → scenes; shots no longer one per line |
| keyframe first, providers, prompts and seeds kept | `sourcing/generate.py` | provider/model/workflow per shot; fal, ComfyUI |
| footage matched per line, alternates, gaps reported | `sourcing/match.py`, `report.py` | assignment by each shot's source policy and criteria |
| characters, LoRA training | Bible, `RunPodTrainer` | locations, props, wardrobe, looks, time of day as entities |
| edit by word: a fixed set of operations, applied after review | `agents/commands.py` | operations on the Shot Spec, with scope and diff |
| measured checks | VI fields (released), VQ defects and QA, `quality/watch`, colour gap, SigLIP | each shot's criteria point at them |
| autonomy levels, kill switch, budget, privacy | `agents/autonomy.py` | which shots the Director may accept alone |
| render, preview, captions, music, voice | `edit/render.py` | the animatic as a render of stills and temp sound |

No parallel pipeline: the Shot Spec extends the existing shot, the Director sits above the modules like the Producer.

## The Shot Spec

One per shot, versioned (a change makes a new version; the old one is kept and can be returned to).

```
shot:
  id, scene_id, order, version
  intent:        what the shot must make the viewer understand or feel (one sentence), and the script line(s) it carries
  duration:      target, min, max (s); "follow the line" when tied to narration
  framing:       shot size, angle, camera movement, lens feel (from the controlled vocabulary)
  source:        policy  footage | generate | stock | any        (with order of preference)
                 footage_query (when footage is tried), allowed sessions/collections
  generation:    provider (fal | comfyui | runpod | pollinations | local), model, workflow template (id + hash)
                 prompt as fields: subject, action, setting, light, style, camera (compiled deterministically)
                 negative, seed, references (entity images, the previous shot's last frame), strength
                 keyframe first: still approved before any video is paid for
  continuity:    entities present  (character, location, prop, wardrobe, look, time of day: Bible references)
                 screen direction  (looking/moving left or right; the 180° line with the shot before)
                 match_previous    (colour, light, position of the subject)
  criteria:      list of { check, op, value, verifier: auto | human, required }
  assignment:    chosen asset (footage t_in/t_out, or generated file), candidates with their scores
  state:         per stage: draft → planned → assigned → accepted | needs_you ; stale when something it rests on changed
  cost:          estimate before, actual after
```

### Criteria catalogue (each an existing measure)

| check | measured by | example |
|---|---|---|
| `shot_size`, `people`, `place`, `angle`, `text_on_screen` | VI fields, only while *released* | shot_size = close |
| `shows_line` | `quality/watch` (does the picture show what is said) | ≥ 0.7 |
| `no_defect` | VQ defects / QA verdict | shake < 0.3, QA ≠ fail |
| `duration` | the assignment | within min..max |
| `character_match` | SigLIP similarity to the Bible's references | ≥ 0.82 |
| `colour_continuity` | VQ colour gap to the shot before (look mode) | ≤ 4 |
| `screen_direction` | subject motion/gaze from VI tracks | = right |
| `human` | the operator | "the smile reads as relief" |

A criterion that cannot be measured is a human one; it is never guessed. A field not yet released cannot be an automatic
criterion (the Director says so and offers it as human).

## The Director loop

For each shot not accepted, in story order:

1. **Source** by its policy: footage (match against `footage_query` and the intent, filtered by sessions/collections), else
   stock, else generation (keyframe → approval gate per autonomy → video).
2. **Check** every automatic criterion on each candidate; score = required all pass, then weighted rest.
3. **Accept** the best that passes all required criteria when the autonomy level allows, else propose it.
4. **Retry** a failing generation with a bounded change (seed, then prompt field the failing criterion points to, then
   strength/reference), at most N=3 times and within the shot's budget.
5. **Escalate** to the operator with what failed and why ("needs you"), never accept silently.

A shot is *stale* when its spec, an entity it references, or the shot before (for continuity) changes; only stale shots are
redone (the same rule as VQ recipes and the orchestrator's runs).

## Conversation with the Director

The operator writes; the Director answers with a **proposal**: a list of typed operations with a scope, shown as a diff.

- Scope: one shot, a scene, the whole storyboard, or "shots like this".
- Operations: `set(field, value)`, `split(shot, at)`, `merge(a, b)`, `insert(after, spec)`, `delete`, `move`, `retime`,
  `set_source`, `add_criterion`, `remove_criterion`, `link_entity`, `regenerate(shot, keep=…)`, `rewrite_line`.
- Nothing changes until the operator applies; applying makes new versions; every proposal stays in the shot's history.
- A model that produces nothing valid changes nothing (as `commands.py`).

Idea → scenes uses the same mechanism: the first proposal is a whole storyboard (scenes with their purpose, shots with intent,
duration and source policy) from the idea, a length and a format; the story structure follows VI's beats (hook, setup,
development, peak, close) and the target length.

## Seeing continuity

Continuity is shown where the eye cannot keep it on a long storyboard, from the measures above:

- **A seam at every cut** of the project's storyboard (between two neighbouring shots, across scenes too), green / amber /
  red. Opening it shows the last frame of the shot before beside the first of the shot after, and each dimension: colour and
  light step (VQ colour gap; a new scene may change it), screen direction (180° line), character and wardrobe (SigLIP against
  the Bible), jump-cut risk (same size, angle and place). Each failing dimension comes with the Director's fix, which becomes
  a proposal in the conversation.
- **Continuity lanes** on the timeline draft: one lane per Bible entity, a bar where it is present, a gap where it is not; a
  direction lane (→ ←); the warmth and brightness of the light as curves across the shots, so an intended drift (dawn to dusk)
  reads as a line and an accident as a spike; the seams as marks at the cuts.
- A seam's verdict is part of the Director loop: a red seam keeps the shot after it from being accepted alone.

## Animatic (Timeline Draft)

Every shot as its keyframe (a generated still, or a frame of its matched footage) held for its duration, with temp voice
(the narration by the machine voice or the operator's take) and temp music: the story and the pacing reviewed for nearly
nothing before video is generated or cut. Render follows the same timeline with the real pictures.

## Generation backends

A `GenerationBackend` per provider, behind the existing adapter registry:

- **fal** (hosted API): quick access to current image and video models; cost per call; keys in nexora.toml.
- **ComfyUI on RunPod** (serverless worker): workflow templates as JSON, pinned by hash, parameterised from the Shot Spec
  (text→image, image→video, inpaint, character swap, upscale); LoRA from the Bible; the graph and seed stored with the shot.
  ComfyUI is the execution engine, never the source of truth: the Shot Spec is.
- **ComfyUI local** (Mac, MPS) for stills when wanted.
- Existing: RunPod endpoints, Pollinations, StillMotion.

Each backend reports what it can make (kinds, max length, sizes) and its price; the Director estimates cost before a shot is
generated and keeps to the project's budget. Footage leaves the Mac only for a backend the operator allowed.

## The screen

`/du-an/<id>/director` (a tab of the project). Top: the stages as steps with their counts. Left: scenes and shots as an outline.
Centre: the storyboard (cards per shot, by scene) or the timeline (animatic). Right: the chosen shot's inspector, in tabs
(Mục tiêu, Nguồn, Tạo sinh, Liên tục, Nghiệm thu, Lịch sử), and the conversation with the Director, its proposals as diffs to
apply. Every card says the shot's state, its source, its duration, its criteria passed/failed and its cost.

## Phases

1. **UI on fixture data**: the Director screen, agreed with the operator (with their additions: the look shared by every
   shot, the camera plan seen from above, the scene's script, the shot's line on its card and the timeline). Done.
2. **Shot Spec, versions, staleness; idea → storyboard; conversation; animatic.** Done (2026-10-17): `core/storyboard.py`,
   `modules/planning/storyboard.py`, `/api/v1/projects/{id}/storyboard…`, `web/src/Storyboard.tsx` at `/du-an/<id>/storyboard`.
   The writer model is the local one (Qwen3 through Ollama): a proposal of operations in about 20 s, a whole storyboard from an
   idea in about 70 s.
3. **Director loop on footage.** Done: `agents/director.py`; candidates from the library's search, measured against the
   automatic criteria (search score, duration, VI fields only while released, VQ defects, colour gap to the shot before),
   accepted alone at level 2+, else brought to the operator; the colour gap is kept with the picture for the seam.
4. **Generation.** Through the project's existing generation (keyframe first), reached by writing the storyboard to the
   script; the shot chooses its keyframe and video providers among those configured. **Not done:** a fal backend and the
   continuity checks that need it (character likeness by SigLIP against the Bible).
5. **Not done:** ComfyUI on RunPod with pinned workflow templates.

## Testing

Each operation of the conversation on hand-written specs; the Director loop with fake backends and fixed measures (accept,
retry, escalate, budget); staleness after an edit; criteria refused for unreleased fields; the animatic's timing.

## Open

- Content mix (assumed (c)); target lengths and formats most used.
- Which fal models first (image, video), and the budget per project.
