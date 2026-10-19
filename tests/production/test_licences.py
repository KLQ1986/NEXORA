"""Licence strings as the stock libraries really returned them (research 2026-10-19) sorted into what they allow."""
import pytest

from nexora.modules.quality.licences import classify


@pytest.mark.parametrize("licence, cls", [
    ("Pexels License (free, no attribution required)", "free"),
    ("Pixabay Content License (free, no attribution required)", "free"),
    ("Public domain", "free"),
    ("https://creativecommons.org/publicdomain/zero/1.0/", "free"),
    ("http://creativecommons.org/publicdomain/mark/1.0/", "free"),
    ("Public domain (U.S. federal government work, NOAA)", "free"),
    ("Public Domain (Prelinger Archives)", "free"),
    ("CC BY 3.0", "attribution"),
    ("Creative Commons Attribution 4.0 (CC BY 4.0, attribution required)", "attribution"),
    ("https://creativecommons.org/licenses/by/4.0/", "attribution"),
    ("CC BY-SA 3.0", "share_alike"),
    ("https://creativecommons.org/licenses/by-sa/4.0/", "share_alike"),
    ("CC BY-SA 3.0 IGO (ESA, attribution required)", "share_alike"),
    ("https://creativecommons.org/licenses/by-nc-nd/4.0/", "restricted"),
    ("http://creativecommons.org/licenses/by-nc-sa/3.0/", "restricted"),
    ("JAXA Digital Archives License (educational/informational use, verify per item)", "restricted"),
    ("Public Domain / CC (archive.org — verify per item)", "unknown"),
    ("Creative Commons (check individual sound license)", "unknown"),
    ("Rights status varies — verify per item (Library of Congress)", "unknown"),
    ("", "unknown"),
    (None, "unknown"),
])
def test_each_licence_the_libraries_returned_is_sorted_into_what_it_allows(licence, cls):
    assert classify(licence) == cls


def test_the_publishing_gate_stops_what_the_licence_does_not_allow_and_credits_what_needs_a_credit():
    from nexora.modules.quality.rights import rights_report
    def clip(aid, licence):
        return {"name": f"{aid}.mp4", "origin": "licensed", "rights": {"license": licence, "source_url": f"https://x/{aid}", "creator": "An"}}
    assets = {"a": clip("a", "Pexels License (free, no attribution required)"), "b": clip("b", "CC BY 3.0"), "c": clip("c", "CC BY-SA 3.0"),
              "d": clip("d", "https://creativecommons.org/licenses/by-nc-nd/4.0/"), "e": clip("e", "Public Domain / CC (archive.org — verify per item)")}
    shots = [{"asset_id": k, "text": f"câu {k}"} for k in "abcde"]
    report = rights_report(shots, assets)
    ok = {i["asset_id"]: i["ok"] for i in report["items"]}
    assert ok == {"a": True, "b": True, "c": False, "d": False, "e": False} and not report["clear"]
    assert len(report["blockers"]) == 3 and any("share-alike" in b for b in report["blockers"]) and any("cấm dùng thương mại" in b for b in report["blockers"])
    assert any("An, CC BY 3.0, https://x/b" in d for d in report["disclosures"])          # the credit the licence asks for


def test_the_scout_never_offers_what_may_not_be_used_and_never_takes_an_unclear_or_share_alike_clip(tmp_path):
    from tests.production.test_stock_scout import Model, Stock, cand, scout
    stock = Stock({"floating market boats": [{**cand("wikimedia", "1"), "license": "CC BY-SA 3.0"}, {**cand("archive_org", "2"), "license": "https://creativecommons.org/licenses/by-nc-nd/4.0/"},
                                             {**cand("nasa", "3"), "license": "Public domain"}]})
    s, _ = scout(tmp_path, stock=stock, model=Model(marks={"wikimedia": 10, "nasa": 6}))
    found = s.find("prj_1", "shot_1", "Chợ nổi.", seconds=4)
    assert {c["source"] for c in found} == {"wikimedia", "nasa"}                     # the non-commercial one is never offered
    assert {c["source"]: c["licence_class"] for c in found} == {"wikimedia": "share_alike", "nasa": "free"}
    assert s.best("prj_1", "shot_1")["source"] == "nasa"                            # 10/10 but share-alike is only offered
