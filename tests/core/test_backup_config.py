"""Backups, lanes and settings."""
import pytest

from nexora.config import Config
from nexora.core.backup import backup, backups, restore
from nexora.core.orchestrator import Orchestrator
from nexora.core.pipeline import PipelineDefinition, StageDef

TWO_LANES = PipelineDefinition("t.lanes", "1", [StageDef("slow", lane="background"), StageDef("quick")])


def test_a_backup_restores_the_database_and_the_replaced_one_is_kept(tmp_path):
    db = tmp_path / "nexora.db"
    orch = Orchestrator(db)
    first = orch.submit_run(TWO_LANES)
    copy = backup(db, tmp_path / "backups", now=1_000_000)
    orch.submit_run(TWO_LANES)
    assert len(orch.runs()) == 2
    kept = restore(copy, db)
    assert Orchestrator(db).runs() == [first] and kept.is_file()


def test_only_the_newest_backups_are_kept(tmp_path):
    db = tmp_path / "nexora.db"
    Orchestrator(db)
    for i in range(5):
        backup(db, tmp_path / "b", keep=3, now=1_000_000 + i * 60)
    assert len(backups(tmp_path / "b")) == 3


def test_a_worker_bound_to_a_lane_leaves_other_work_for_other_workers(tmp_path):
    orch = Orchestrator(tmp_path / "nexora.db")
    orch.submit_run(TWO_LANES)
    assert orch.claim_next("fast", lanes=frozenset({"interactive"})).stage_key == "quick"
    assert orch.claim_next("fast", lanes=frozenset({"interactive"})) is None        # the slow stage is not its business
    assert orch.claim_next("batch", lanes=frozenset({"background"})).stage_key == "slow"


def test_settings_come_from_the_file_and_a_misspelt_one_is_refused(tmp_path):
    assert Config.load(tmp_path / "none.toml").port == 8600
    good = tmp_path / "nexora.toml"; good.write_text('port = 9000\nvoice = "Linh"\n')
    assert Config.load(good).port == 9000
    bad = tmp_path / "bad.toml"; bad.write_text("prot = 9000\n")
    with pytest.raises(ValueError, match="prot"):
        Config.load(bad)
