# Associative illustration: narration that says something, pictures that evoke it

Date: 2026-10-18. Raised by the operator on the first real mission ("Buổi sáng dạo biển"): its narration read as a description of
the footage ("Cảnh hoa vàng cam rực rỡ…", "Cốc cà phê trên bàn gỗ…"). Narration is not a caption of the picture; in associative
illustration the words carry an idea and the picture evokes it. Default chosen by the operator: **mixed** (the writer picks the
way for each line).

## Why it happens now

- The draft prompt asks for "mỗi câu nói về một hình ảnh CÓ trong kho footage": the writer describes footage.
- Matching searches with the line itself (plus the brief when there is one, and the producer leaves the brief empty).
- The judge asks whether the frames show what the line says: a literal test.

The data already separates the two: a line has its words (`text`) and what should be seen (`brief`); a storyboard shot has its
`line` and its `intent`/`query`. Only the three steps above treat them as one.

## 1. Three ways to illustrate a line

- `direct` (trực tiếp): the picture shows what is said. Right for places, products, facts, steps, people named.
- `associative` (liên tưởng): the picture evokes the idea through a metaphor, a symbol, a mood or a rhythm ("chậm lại" → a
  wave drawing back slowly, an empty frame).
- `contrast` (tương phản): the picture runs against the words to make a point ("thành phố không bao giờ ngủ" → an empty street
  at dawn).
- The way is a property of a line: `illustration = {mode, evokes, feel}`.
  - `evokes`: one phrase, what the picture must call up (associative and contrast).
  - `feel`: wanted measurable qualities (see 3).
- **Defaults:** a template and a channel have `illustration: direct | associative | mixed` (default `mixed`); a project takes its
  template's, then its channel's. In `mixed` the writer chooses per line; in the others every line is written that way. The
  operator changes any line's way in the script editor or the storyboard.

## 2. Writing

- The draft prompt changes from "every line about something in the footage" to: the narration tells (a story, an idea, a feeling)
  and does not describe the picture; the footage inventory is given as material to illustrate with.
- **For every line** the writer returns:
  - `cau`: the words;
  - `kieu`: direct | associative | contrast;
  - `hinh`: what is seen, written as a shot, which goes to the `brief`;
  - `goi`: what it evokes (not for direct);
  - `cam_giac`: the wanted feel, from a fixed vocabulary.
- **In `mixed`** the prompt states the rule:
  - concrete things (places, objects, facts, steps) are direct;
  - ideas, feelings and transitions are associative;
  - contrast is used rarely, for a point.
- **In `direct`** the old instruction stays: every line about something the footage has.
- **Critique and revision** keep each line's illustration with the line, as they already keep its notes. A new critique note
  catches a line that only describes its picture ("câu này chỉ tả lại hình") when the way is not direct.
- **The producer and a mission** write this way too; the structure of a template is unchanged.

## 3. Finding the picture

- **The query:**
  - direct: the words plus the brief (as now);
  - associative and contrast: the brief and the evoked phrase, **never the words**.
- **Feel, measured, not asked:** each candidate's measured qualities from the canonical model (through the `vi` read interface):
  - motion: still, slow, fast;
  - light: bright, dim, golden, night;
  - colour temperature: warm, cool;
  - framing: wide and empty, close, crowded;
  - time of day, number of people;
  - emotion (where it was labelled).
- **Ranking:**
  - direct: unchanged;
  - associative: the meaning of the brief, scaled by the feel (meaning × (0.7 + 0.3 × feel)), so the feel chooses among
    stretches that mean the right thing and never lifts one that does not (see the real run below);
  - contrast: meaning of the brief, with feel as asked (contrast is in the brief, not inverted by code).
  - Each candidate keeps its feel match, said in words ("chậm, sáng ấm, khung trống: khớp 3/3").
- **The judge:** for associative and contrast lines, the frames are judged against `evokes` and `hinh`: "does this picture call
  up '<evokes>' for the line '<text>'"; a picture that does not show the line literally is not marked down for it. The reason
  is shown, as now.

## 4. Storyboard and Director

- A storyboard shot's spec gains `illustration`. When a storyboard is made from a script, each line's illustration comes with
  it. The Director's query and criteria use it the same way as matching.
- The shot panel shows a three-way switch (Trực tiếp / Liên tưởng / Tương phản), the evoked phrase and the feel. Changing it
  marks the shot to be found again.
- The script editor shows each line's way as a small tag beside "hình cần có", editable.

## 5. Not in this change

- Music by section, transitions between shots, quoted speech lines (a soundbite from a transcript as a line of the script):
  listed in the conversation as missing, each its own change.

## Tests

The fake model returns ways, briefs, evoked phrases and feels:
- **Writing:**
  - a mixed draft keeps each line's illustration;
  - a direct template keeps the old prompt;
  - the critique flags a describing line;
  - illustration survives critique, revision and reordering.
- **Matching:**
  - an associative line is searched with its brief, not its words;
  - the feel re-ranks two equally meaningful candidates towards the measured slow, empty one;
  - the judge prompt for associative lines names what is evoked.
- **Storyboard:** a storyboard from a script carries illustration; changing the way marks the shot stale.
- **Defaults:** template and channel defaults; a project inherits them.

Then one real run with the local model: the same goal as "Buổi sáng dạo biển" written mixed, its narration and picks compared
with the first run's.

## Measured on the library (qwen local model, 2026-10-18)

- **The narration now tells instead of describing.** The first run of "Buổi sáng dạo biển" had lines like "Cảnh hoa vàng cam
  rực rỡ…"; the mixed draft has lines like "Một ngày mới bắt đầu không phải bằng tốc độ, mà bằng sự trân trọng từng khoảnh
  khắc." It chose five associative lines and one direct line (the cup of coffee, a concrete object), as the rule says.
- **Three corrections from that run:**
  - The model repeated one brief for three lines, so the prompt now asks for a different picture for each line.
  - It wrote whole sentences as what a line evokes, so the prompt now asks for two to five words ("chậm lại", "bắt đầu lại").
  - It filled all five feel keys for every line, so the prompt asks for one to three and the code keeps the first three.
- **Feel added to meaning chose the wrong picture.** With feel added (0.6 meaning + 0.4 feel), "a quiet garden with orange
  flowers / chữa lành" went to "a man stirring soil in a bucket", because the bucket shot matched the feel 4/5. Multiplied, the
  same line goes to the garden. A test keeps that.
- **After the corrections:** six lines, six different pictures, each meaning the right thing.
