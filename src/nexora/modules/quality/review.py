"""Whole-cut review: measurable checks on a cut as a viewer would meet it (design v4.0, section 20.2).

Findings are advisory. Each has the shot it concerns, a severity and a suggested fix.
"""
MIN_SHOT, MAX_SHOT = 1.5, 9.0


def review_cut(shots: list[dict]) -> list[dict]:
    """`shots`: one dict per shot in order, with keys text, duration, gap, asset_id, t_in."""
    findings = []
    def add(check, index, severity, text, fix):
        findings.append({"check": check, "shot": index + 1, "severity": severity, "text": text, "fix": fix})
    total = sum(s["duration"] for s in shots) or 1.0
    for i, s in enumerate(shots):
        if s["gap"]:
            add("Thiếu hình", i, "cao", "Câu này không có clip nên video hiện nền trơn.", "Thêm footage, đổi sang phương án khác, hoặc sửa câu.")
        check = (s.get("fact_check") or {}).get("verdict") if s.get("is_fact") else None
        if check == "contradicted":
            add("Dữ kiện", i, "cao", f"Câu này trái với nguồn “{s['fact_check'].get('source')}”.", "Sửa câu cho đúng với nguồn, hoặc tìm nguồn khác.")
        elif s.get("is_fact") and not s.get("source"):
            add("Dữ kiện", i, "cao", "Câu này nêu một dữ kiện nhưng chưa gắn nguồn nào.", "Gắn một nguồn trong phần Nguồn tham khảo của dự án, hoặc sửa câu.")
        if s["duration"] > MAX_SHOT:
            add("Nhịp", i, "vừa", f"Cảnh dài {s['duration']:.1f} giây, dễ làm người xem chán.", "Tách câu thành hai câu ngắn hơn.")
        if s["duration"] < MIN_SHOT:
            add("Nhịp", i, "thấp", f"Cảnh chỉ dài {s['duration']:.1f} giây, có thể lướt qua quá nhanh.", "Gộp với câu bên cạnh.")
        if i and not s["gap"] and not shots[i - 1]["gap"] and s["asset_id"] == shots[i - 1]["asset_id"] and abs(s["t_in"] - shots[i - 1]["t_in"]) < 6:
            add("Lặp hình", i, "vừa", "Cảnh này gần như trùng với cảnh ngay trước nó.", "Đổi một trong hai cảnh sang phương án khác.")
    if shots and shots[0]["gap"]:
        add("Mở đầu", 0, "cao", "Video mở đầu bằng nền trơn.", "Bắt đầu bằng một câu có hình mạnh.")
    gap_share = sum(s["duration"] for s in shots if s["gap"]) / total
    if gap_share > 0.3:
        add("Thiếu hình", 0, "cao", f"{gap_share:.0%} thời lượng video là nền trơn.", "Bổ sung footage trước khi dựng lại.")
    return findings
