"""The rights and provenance gate: where every picture and sound in a cut came from, and whether it may be published
(design v4.0, sections 20.3 and 18.7).

The report lists each source once. A blocker is something that must not go out as it stands: licensed material with no
licence on record, music nobody has vouched for, a line that contradicts its source. The operator may still publish
over a blocker, but only by saying why, and the reason is kept with the package.
"""
from pathlib import Path


from nexora.modules.quality.licences import LABELS, SAFE, classify, why_not


def rights_report(shots: list[dict], assets: dict[str, dict], *, music: str | None = None, music_cleared: bool = False) -> dict:
    """`shots`: the cut's shots (asset_id, is_fact, source, fact_check, text). `assets`: by asset id, with origin, name and rights.
    Returns {items, blockers, disclosures}."""
    items, blockers, disclosures, seen = [], [], [], set()
    for n, shot in enumerate(shots, 1):
        asset_id = shot.get("asset_id")
        if asset_id and asset_id not in seen and asset_id in assets:
            seen.add(asset_id)
            a = assets[asset_id]
            rights = a.get("rights") or {}
            item = {"asset_id": asset_id, "name": a["name"], "origin": a["origin"], "first_line": n, "license": rights.get("license"), "source_url": rights.get("source_url"),
                    "creator": rights.get("creator"), "ok": True, "note": "Footage của bạn."}
            if a["origin"] == "licensed":
                # What the licence allows, not only that one is written down: a non-commercial, share-alike or unclear licence
                # stops the video as surely as a missing one (research 2026-10-19).
                item["licence_class"] = cls = classify(rights.get("license"))
                item["ok"] = bool(rights.get("license") and rights.get("source_url")) and cls in SAFE
                if not (rights.get("license") and rights.get("source_url")):
                    item["note"] = "Clip lấy từ bên ngoài nhưng không có giấy phép hoặc nguồn trong hồ sơ."
                    blockers.append(f"“{a['name']}” (câu {n}) là clip lấy từ bên ngoài mà chưa có giấy phép và nguồn.")
                elif cls not in SAFE:
                    item["note"] = f"{LABELS[cls]}: {rights.get('license')}. Nguồn: {rights.get('source_url')}"
                    blockers.append(f"“{a['name']}” (câu {n}): {why_not(cls)} ({rights.get('license')}).")
                else:
                    item["note"] = f"{LABELS[cls]}. Giấy phép: {rights.get('license')}. Nguồn: {rights.get('source_url')}"
            elif a["origin"] == "generated":
                item["note"] = "Hình sinh bằng AI. Cần ghi rõ khi đăng."
            if a.get("people") and a.get("consent") not in ("given", "not_needed"):
                # People recognised in footage that goes out: the operator says they agreed, or that none need to (design group 16).
                item["ok"] = False
                item["note"] = (item["note"] + " " if item["note"] else "") + f"Có người xuất hiện ({a['people']} nhịp) mà chưa xác nhận họ đồng ý."
                blockers.append(f"“{a['name']}” (câu {n}) có người xuất hiện mà chưa xác nhận họ đồng ý xuất hiện trong video.")
            items.append(item)
        verdict = (shot.get("fact_check") or {}).get("verdict") if shot.get("is_fact") else None
        if verdict == "contradicted":
            blockers.append(f"Câu {n} trái với nguồn “{shot['fact_check'].get('source')}”.")
        elif shot.get("is_fact") and not shot.get("source"):
            blockers.append(f"Câu {n} nêu một dữ kiện chưa gắn nguồn.")
    if any(i["origin"] == "generated" for i in items):
        disclosures.append("Video có hình sinh bằng AI: bật nhãn nội dung tổng hợp khi đăng.")
    credits = sorted({f"{i['creator'] or 'không rõ tác giả'}, {i['license']}, {i['source_url']}" for i in items if i["origin"] == "licensed" and i["ok"]})
    if credits:
        disclosures.append("Ghi công trong phần mô tả: " + "; ".join(credits))
    if music:
        items.append({"asset_id": None, "name": Path(music).name, "origin": "music", "first_line": 0, "ok": music_cleared, "license": None, "source_url": None, "creator": None,
                      "note": "Bạn đã xác nhận có quyền dùng bản nhạc này." if music_cleared else "Chưa ai xác nhận quyền dùng bản nhạc này."})
        if not music_cleared:
            blockers.append(f"Nhạc nền “{Path(music).name}” chưa được xác nhận quyền sử dụng.")
    return {"items": items, "blockers": blockers, "disclosures": disclosures, "clear": not blockers}
