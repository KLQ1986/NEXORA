"""The canonical model of Video Intelligence: written once by the analysis domain, read by everything else."""
from nexora.core.intelligence import Analyzer, VideoIntelligence, fuse, gate_key
from nexora.core.intelligence_store import IntelligenceStore


def make(tmp_path, released=()):
    db = tmp_path / "vi.db"
    return IntelligenceStore(db), VideoIntelligence(db, released=lambda: set(released))


def test_the_operators_word_wins_then_a_released_measure_then_a_released_model_then_the_most_trusted():
    store, vi = make(tmp_path := __import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    store.observe("a", 0, 5, "shot_size", "toàn", source="measured", confidence="medium", analyzer="profile@3")
    store.observe("a", 0, 5, "shot_size", "cận", source="model", confidence="medium", analyzer="describe@v3")
    assert vi.value("a", 2.0, "shot_size").value == "toàn" and not vi.value("a", 2.0, "shot_size").released
    assert vi.value("a", 2.0, "shot_size", released_only=True) is None
    _, gated = make(tmp_path, released={"model.shot_size"})
    v = gated.value("a", 2.0, "shot_size")
    assert (v.value, v.source, v.released) == ("cận", "model", True) and v.others[0].source == "measured"
    _, both = make(tmp_path, released={"shot_size", "model.shot_size"})
    assert both.value("a", 2.0, "shot_size").source == "measured"
    store.observe("a", 0, 5, "shot_size", "trung", source="human", confidence="high", analyzer="operator")
    assert both.value("a", 2.0, "shot_size").value == "trung"


def test_a_stretch_takes_the_observation_covering_most_of_it(tmp_path):
    store, vi = make(tmp_path, released={"people"})
    store.observe_many("a", [(0, 3, "people", "không", "recognized", "high", {}), (3, 10, "people", "một", "recognized", "high", {})], analyzer="profile@3")
    assert vi.value("a", (2.0, 8.0), "people").value == "một" and vi.value("a", 1.0, "people").value == "không"
    assert vi.fit("a", (2.0, 8.0), {"people": "một"})[0] > 0 > vi.fit("a", (2.0, 8.0), {"people": "không"})[0]


def test_a_new_division_replaces_what_an_analyzer_said_but_never_the_operator(tmp_path):
    store, vi = make(tmp_path)
    store.observe("a", 0, 5, "place", "ngoài trời", source="recognized", analyzer="profile@3")
    store.observe("a", 0, 5, "place", "trong nhà", source="human", analyzer="operator")
    store.observe_many("a", [(0, 2, "place", "ngoài trời", "recognized", "high", {})], analyzer="profile@4", replace=("place",))
    assert {(o.t_start, o.t_end, o.source) for o in vi.observations("a", "place")} == {(0, 2, "recognized"), (0, 5, "human")}


def test_segments_entities_and_what_is_stale(tmp_path):
    store, vi = make(tmp_path)
    store.replace_segments("a", "beat", [(0, 4, {"shot": 0}), (4, 9, {"shot": 0})], analyzer="structure@2")
    store.replace_segments("a", "beat", [(0, 9, {"shot": 0})], analyzer="structure@3")
    assert [(s.t_start, s.t_end) for s in vi.segments("a")] == [(0, 9)]
    store.entity("person", "a@1#0", name="Bà Tư", appearances=[("a", 1, 3, {"face": 0})])
    assert vi.entities("person")[0]["name"] == "Bà Tư" and vi.entities("person")[0]["appearances"][0]["asset_id"] == "a"
    look, profile = Analyzer("look", "2", ("file",), ("people",)), Analyzer("profile", "3", ("look",), ("shot_size",))
    store.declare(look); store.declare(profile); store.ran("a", Analyzer("look", "1")); store.ran("a", profile)
    assert vi.stale("a") == ["look", "profile"]                    # look changed, and profile needs look
    store.ran("a", look)
    assert vi.stale("a") == [] and vi.analysed("a") == {"look": "2", "profile": "3"}


def test_a_deleted_recording_is_not_read_and_forgetting_removes_it(tmp_path):
    store = IntelligenceStore(tmp_path / "vi.db")
    store.recording("a", technical={"width": 3840})
    store.observe("a", 0, 1, "people", "một", source="recognized", analyzer="x")
    gone = VideoIntelligence(tmp_path / "vi.db", exists=lambda asset_id: False)
    assert gone.recording("a") is None and gone.observations("a") == []
    assert store.forget("a") == 1 and VideoIntelligence(tmp_path / "vi.db").recording("a") is None


def test_gate_names():
    assert gate_key("shot_size", "measured") == "shot_size" and gate_key("shot_size", "model") == "model.shot_size"
