"""Step 5: understanding footage and searching it (design v4.0, section 17.2)."""
import pytest

from nexora.app import build
from nexora.core.states import RunStatus

from tests.conftest import make_video
from tests.fakes import FakeModel


@pytest.fixture
def system(tmp_path):
    return build(tmp_path / "data", model=FakeModel(), segment_seconds=2.0)


def drain(system):
    while system.worker.run_once():
        pass


@pytest.fixture
def ingested(system, tmp_path):
    clip = make_video(tmp_path / "long.mp4", picture=6, black=2)
    asset_id, _ = system.library.ingest(clip)
    drain(system)
    return asset_id


def test_understanding_starts_by_itself_after_ingest_and_describes_only_usable_footage(system, ingested):
    runs = [system.orch.run_info(r) for r in system.orch.runs_for_subject(ingested)]
    assert {r["pipeline_id"] for r in runs} == {"library.ingest", "library.profile", "library.understand"}      # measured and recognised, then described
    assert all(system.orch.run_status(r["run_id"]) is RunStatus.SUCCEEDED for r in runs)
    segments = system.index.moments(ingested, level="segment")
    assert len(segments) == 3                                           # 6 usable seconds in 2-second segments; the black tail is skipped
    assert [(m.t_start, m.t_end) for m in segments] == [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]
    assert all(m.text and m.data["frame"] for m in segments)
    video = system.index.moments(ingested, level="video")
    assert len(video) == 1 and video[0].text == "Video thử nghiệm."


def test_search_finds_a_moment_by_its_words_and_without_diacritics(system, ingested):
    hits = system.index.search("cá tươi")
    assert hits and hits[0].moment.asset_id == ingested and "cá tươi" in hits[0].moment.text
    assert (hits[0].moment.t_start, hits[0].moment.t_end) == (2.0, 4.0)
    assert system.index.search("ca tuoi")[0].moment.moment_id == hits[0].moment.moment_id


def test_search_for_something_absent_returns_nothing_relevant(system, ingested):
    assert system.index.search("thuyền đánh cá", min_score=0.5) == []


def test_running_understanding_again_makes_no_model_calls(system, ingested):
    model = system.adapters._adapters["model"]
    before = dict(model.calls)
    system.library.understand(ingested, force=True)
    drain(system)
    assert model.calls["describe"] == before["describe"]                # descriptions are cached per segment


def test_a_correction_by_the_operator_survives_re_analysis(system, ingested):
    first = system.index.moments(ingested, level="segment")[0]
    system.index.correct(first.moment_id, "Cận cảnh bàn tay rót trà.")
    system.library.understand(ingested, force=True)
    drain(system)
    again = system.index.moments(ingested, level="segment")[0]
    assert again.text == "Cận cảnh bàn tay rót trà." and again.source == "human"
    assert system.index.search("rót trà")[0].moment.moment_id == first.moment_id


def test_rank_fusion_is_an_option_that_reorders_results_without_changing_their_scores(system, ingested):
    plain = system.index.search("chợ rau củ cá tươi", limit=5)
    system.index.fusion = "rrf"
    fused = system.index.search("chợ rau củ cá tươi", limit=5)
    assert {h.moment.moment_id: h.score for h in fused} == {h.moment.moment_id: h.score for h in plain} and len(fused) == len(plain) > 0


def test_footage_deleted_while_it_is_described_gets_nothing_more_written(tmp_path):
    from nexora.app import build, remove_asset
    from tests.conftest import make_video
    from tests.fakes import FakeModel

    class DeletesMidway(FakeModel):
        def submit(self, request):
            if request.operation == "describe" and request.params.get("index") == 1 and system.assets.asset(asset):
                remove_asset(system, asset)              # the operator deletes the clip while its second beat is being described
            return super().submit(request)
    system = build(tmp_path / "data", model=DeletesMidway(), segment_seconds=2.0)
    asset, _ = system.library.ingest(make_video(tmp_path / "f.mp4", picture=8))
    while system.worker.run_once():
        pass
    assert system.assets.asset(asset) is None and system.index.moments(asset) == []
