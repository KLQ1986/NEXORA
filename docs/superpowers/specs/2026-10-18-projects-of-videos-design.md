# Projects of videos

Date: 2026-10-18. Raised by the operator: "a project can have many videos; one video = one script = one storyboard". Approved
in conversation the same day, with the proposal below (shared settings as listed; each existing project becomes a project of
one video).

## The model

```
Dự án (a production: a series, a subject, a campaign)          productions
 ├─ Video 1 = its script (versions) = its storyboard → cut → publish   projects (unchanged)
 ├─ Video 2 …
Mission "make 3 videos about the market" → one production of 3 videos
```

- What the code calls a project stays exactly what it is: one video with its script, storyboard, cuts, renders, publications,
  spending. Nothing about a video's data changes. The interface calls it a **video**.
- A new **production** (`productions`) holds several videos (`projects.production_id`) and what they share:
  - channel, template, narration voice, music;
  - characters (the Bible), research sources;
  - a total budget.
- **Shared, not locked:**
  - A video takes its production's values when it is made.
  - A change on the production reaches every video that still has the production's previous value.
  - A video given its own value keeps it.
  - Readers of a video's settings (render, writing, matching) therefore need no change.
- **The total budget** is checked with each video's own cap. Generating for a video is refused when the production's videos
  together would pass it.
- **Ids say what they are:** a production is `prd_…`, a video `prj_…`, so `/du-an/<id>` opens either.
- **Existing data:** each existing project becomes a production of the same title, holding that one video, its shared values
  taken from the video. This runs once, as a migration, and it is idempotent.

## Navigation

- **Dự án** lists productions: each with its videos (a frame each), how many are in progress, waiting for the operator or done,
  its channel and template.
- **A production's page** shows:
  - its videos, as the project list showed projects;
  - its shared settings;
  - "Thêm video" (a blank video in it);
  - "Giao việc", the mission composer, whose videos are added to this production.
- **A video's page and steps** (Kịch bản, Storyboard, Dựng, Xuất bản) are as before, with the production named in its header,
  leading back.
- **The side menu** is a tree: productions → videos → steps.
- **"Làm video mới"** asks which production; a new production is the default.
- **Accepting an idea** makes a new production of one video, as before.
- **One way to hand work to the machine:** "Giao cho trợ lý" (the producer, started directly) is replaced by "Giao việc" (a
  mission). Mission Control keeps watching missions and approvals; its composer stays for work that is not a video (describe,
  listen).
- **A mission for videos** makes a production of N videos, or adds them to one named. Its plan carries `production_id` when it
  was given from a production's page.

## Trash

A production lists only its videos not in the Trash. A production with no videos can be removed. Videos are trashed and
restored one by one, as before.

## Tests

- The migration: one production per existing project, values taken, run twice without change.
- Shared values:
  - a new video takes them;
  - a change reaches the videos still on the old value and not the one changed by hand.
- The total budget refuses a generation that would pass it.
- A mission makes one production of N videos, or adds to the one named.
- `/du-an/<prd>` and `/du-an/<prj>` both open; the side tree; a video moved to another production.
