"""The storyboard read as a whole for what makes a video feel like a slideshow (OpenMontage's slideshow risk, research
2026-10-19), from what is measured on the shots."""
from nexora.core.storyboard import Shot
from nexora.modules.planning import storyboard as SB


def shot(i, *, size="trung", angle="ngang mắt", move="đứng yên", seconds=4.0, asset=None, scene="sc1"):
    spec = SB.normalise({"intent": f"shot {i}", "duration": seconds, "framing": {"size": size, "angle": angle, "move": move}})
    return Shot(f"s{i}", "p", scene, float(i), 1, spec, "needs", assignment={"asset_id": asset} if asset else None)


def dims(r):
    return {d["key"]: d for d in r["dimensions"]}


def test_a_varied_board_reads_strong_and_a_monotonous_one_of_stills_reads_as_a_slideshow():
    sizes, moves = ["toàn cảnh", "trung", "cận", "đặc tả"], ["đứng yên", "lia ngang", "đẩy tới", "theo sau"]
    varied = [shot(i, size=sizes[i % 4], move=moves[i % 4], asset=f"a{i}", scene=f"sc{i // 4}") for i in range(8)]
    good = SB.rhythm(varied, {s.shot_id: f"SC{i + 1}" for i, s in enumerate(varied)})
    assert good["verdict"] == "strong" and good["score"] < 2

    flat = [shot(i, angle="cao", asset="same" if i < 6 else f"b{i}", seconds=12.0 if i % 2 else 4.0) for i in range(8)]   # planned, all alike
    codes = {s.shot_id: f"SC{i + 1}" for i, s in enumerate(flat)}
    bad = SB.rhythm(flat, codes, still=lambda s: True)
    d = dims(bad)
    assert bad["verdict"] == "fail" and bad["score"] >= 4
    assert d["repetition"]["score"] == 5 and d["stills"]["score"] == 5 and d["motion"]["score"] == 5
    assert d["reuse"]["count"] == 4 and d["reuse"]["shots"][0] == "SC3"            # the third use of one clip onwards
    assert d["holds"]["count"] == 4 and d["variety"]["score"] == 5
    assert "SC2" in d["holds"]["shots"]


def test_a_shot_heard_with_its_own_sound_may_hold_long_and_a_short_board_is_not_judged():
    long_talk = shot(1, seconds=20.0, asset="t")
    long_talk.assignment["treat"] = {"live_sound": True}
    r = SB.rhythm([shot(0, size="toàn cảnh", asset="x"), long_talk], {"s0": "SC1", "s1": "SC2"})
    assert dims(r)["holds"]["count"] == 0
    assert SB.rhythm([shot(0)], {"s0": "SC1"})["verdict"] == "strong"


def test_a_board_laid_out_without_framing_is_not_charged_for_sizes_and_movement_it_never_planned():
    board = [shot(i, asset=f"a{i}") for i in range(8)]                 # every shot at the default framing
    r = SB.rhythm(board, {s.shot_id: f"SC{i + 1}" for i, s in enumerate(board)})
    d = dims(r)
    assert not r["framed"] and d["variety"]["score"] is None and d["motion"]["score"] is None and "chưa đo" in d["motion"]["detail"]
    assert d["repetition"]["score"] == 0 and r["verdict"] == "strong"


def test_one_grave_fault_is_not_averaged_away():
    board = [shot(i, asset=f"a{i}", seconds=15.0) for i in range(8)]   # varied pictures, every hold far too long
    r = SB.rhythm(board, {s.shot_id: f"SC{i + 1}" for i, s in enumerate(board)})
    assert dims(r)["holds"]["score"] == 5 and r["score"] < 2 and r["verdict"] == "revise"
