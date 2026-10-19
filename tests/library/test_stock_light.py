"""Stock brought in for a picture is only taken in and described: it was chosen on its preview, so listening to it, finding its
cuts, dividing it into shots and profiling it would be work nobody uses (design 2026-10-19, section 5)."""
from nexora.app import build

from tests.fakes import FakeModel
from tests.library.test_analysis import TWO_SHOTS, drain, film


def pipelines(system, asset_id):
    return sorted({system.orch.pipeline_of(r) for r in system.orch.runs_for_subject(asset_id)})


def test_licensed_footage_is_taken_in_and_described_but_not_listened_to_cut_divided_or_profiled(tmp_path):
    system = build(tmp_path / "data", model=FakeModel(), segment_seconds=15.0)
    stock, _ = system.library.ingest(film(tmp_path / "stock.mp4", TWO_SHOTS), origin="licensed", rights={"source": "pexels"})
    own, _ = system.library.ingest(film(tmp_path / "own.mp4", [("rgbtestsrc", 4), ("testsrc", 4)]))
    drain(system)
    assert pipelines(system, stock) == ["library.ingest", "library.understand"]
    assert system.index.moments(stock, level="segment")                   # found by search like any footage
    assert "library.structure" in pipelines(system, own)                   # the operator's own footage is analysed in full
    # The sweeps that catch up on older footage leave stock alone too.
    original = system.assets.original(stock)
    system.assets.update_metadata(original.version_id, scene_cuts=None)
    assert stock not in [system.orch.run_info(r)["subject_ref"] for r in system.library.find_missing_cuts() + system.intelligence.find_unmeasured()]
