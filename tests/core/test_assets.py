"""The asset store: logical assets, immutable versions, volumes and lineage (design v4.0, sections 8 and 17.1)."""
import pytest

from nexora.core.assets import AssetStore, sha256_file


@pytest.fixture
def store(tmp_path):
    return AssetStore(tmp_path / "n.db")


def test_a_location_is_a_volume_plus_a_relative_path(store, tmp_path):
    drive = tmp_path / "drive"; (drive / "shoot1").mkdir(parents=True)
    f = drive / "shoot1" / "a.mp4"; f.write_bytes(b"x" * 10)
    vol = store.add_volume("drive", drive, kind="external")
    asset_id, version_id = store.create_asset(f, kind="video", origin="self_shot")
    v = store.version(version_id)
    assert (v.volume_id, v.relative_path, v.role, v.size) == (vol, "shoot1/a.mp4", "original", 10)
    assert store.path_of(v) == f


def test_a_file_outside_every_volume_gets_a_volume_for_its_folder(store, tmp_path):
    f = tmp_path / "loose" / "b.mp4"; f.parent.mkdir(); f.write_bytes(b"y")
    _, version_id = store.create_asset(f, kind="video", origin="self_shot")
    assert store.path_of(store.version(version_id)) == f


def test_registering_the_same_file_twice_returns_the_same_asset(store, tmp_path):
    f = tmp_path / "c.mp4"; f.write_bytes(b"z")
    assert store.create_asset(f, kind="video", origin="self_shot") == store.create_asset(f, kind="video", origin="self_shot")


def test_a_moved_volume_is_relinked_without_touching_assets(store, tmp_path):
    old = tmp_path / "old"; old.mkdir(); (old / "a.mp4").write_bytes(b"data")
    vol = store.add_volume("drive", old, kind="external")
    _, version_id = store.create_asset(old / "a.mp4", kind="video", origin="self_shot")
    new = tmp_path / "new"; old.rename(new)
    assert not store.volume_online(vol)
    store.relink_volume(vol, new)
    assert store.volume_online(vol) and store.path_of(store.version(version_id)) == new / "a.mp4"


def test_derived_versions_record_their_parents_and_the_attempt_that_made_them(store, tmp_path):
    f = tmp_path / "a.mp4"; f.write_bytes(b"orig")
    asset_id, original = store.create_asset(f, kind="video", origin="self_shot")
    proxy = tmp_path / "proxy.mp4"; proxy.write_bytes(b"proxy")
    pid = store.add_version(asset_id, proxy, role="proxy", parents=[original], attempt_id="att_1", metadata={"height": 720})
    v = store.version(pid)
    assert v.parents == (original,) and v.created_by_attempt_id == "att_1" and v.metadata == {"height": 720}
    assert v.checksum == sha256_file(proxy)
    assert [x.role for x in store.versions(asset_id)] == ["original", "proxy"]


def test_metadata_is_merged_and_duplicates_are_found_by_checksum(store, tmp_path):
    a = tmp_path / "a.mp4"; a.write_bytes(b"same")
    b = tmp_path / "b.mp4"; b.write_bytes(b"same")
    aid, av = store.create_asset(a, kind="video", origin="self_shot")
    bid, bv = store.create_asset(b, kind="video", origin="self_shot")
    store.set_checksum(av, sha256_file(a))
    store.update_metadata(av, probe={"width": 1}); store.update_metadata(av, usable=[[0, 2]])
    assert store.version(av).metadata == {"probe": {"width": 1}, "usable": [[0, 2]]}
    assert store.find_original_by_checksum(sha256_file(b), exclude_asset=bid) == aid
