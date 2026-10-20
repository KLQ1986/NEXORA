"""Distil OpenMontage's pipelines into NEXORA knowledge (research 2026-10-19, way B).

For each pipeline, one read-only `claude -p` run (the operator's Claude Code login, never the API key) reads its manifest and
director skills in ~/openmontage and writes a Vietnamese spec: the genre's rules, its review checklist, its success criteria,
the prompts worth keeping, and how they map onto NEXORA. The output is research for people and for later code, not code.

Usage: python scripts/distill_openmontage.py [pipeline ...]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("~/openmontage").expanduser()
OUT = Path(__file__).resolve().parents[1] / "docs" / "research" / "openmontage-distilled"
DEFAULT = ["documentary-montage", "animated-explainer", "talking-head", "clip-factory"]
NEXORA = """NEXORA (dự án đích) là nền tảng làm video cá nhân, tiếng Việt, chạy trên Mac:
- Orchestrator có run/stage, lane, lease, timeout, kill switch, gate duyệt người trong DB; privacy mode chặn mọi adapter cloud.
- Thư viện footage tự quay được phân tích (mô tả cảnh, lời nói, cú máy, hồ sơ hình); tìm kiếm theo nội dung.
- Kịch bản: viết theo chủ đề bằng Claude Code (topic), phản biện, kiểm chứng dữ kiện có nguồn; mẫu cấu trúc (template).
- Chọn clip (sourcing.match) có giám khảo mô hình nhìn; Storyboard với shot spec (khung, ống kính, chuyển động, nghiệm thu),
  Director, Copilot (nhận xét), mối nối giữa shot; stock chấm qua ảnh xem trước rồi mới tải.
- Dựng (FilmCraft/ffmpeg), QC tự động (hình, tiếng, phụ đề, nhịp), cổng bản quyền khi đăng, tự duyệt có công tắc.
- Không có: chấm nguy cơ "slideshow", delivery promise, chấm điểm nhà cung cấp, lọc giấy phép theo loại."""
PROMPT = """Đọc pipeline `{p}` của OpenMontage trong thư mục hiện tại: `pipeline_defs/{p}.yaml`, mọi file trong
`skills/pipelines/{p}/`, cùng `skills/meta/reviewer.md` và `skills/meta/checkpoint-protocol.md` khi cần. Chỉ đọc, không sửa gì.

Bối cảnh dự án sẽ dùng kết quả:
{nexora}

Viết một bản spec TIẾNG VIỆT, dạng Markdown, ngắn gọn mà đủ (khoảng 120-220 dòng), gồm đúng các mục:
1. `# {p}`: thể loại này làm gì, cho ai, khi nào nên chọn (1 đoạn).
2. `## Các bước`: mỗi stage: mục đích, đầu vào, đầu ra, có cần người duyệt không.
3. `## Quy tắc dựng của thể loại`: các luật cụ thể, có số (thời lượng, nhịp, tỉ lệ, số cảnh, nhạc, chữ trên hình, câu kết...).
   Mỗi luật một dòng, kèm nguồn `file:dòng`.
4. `## Checklist duyệt`: gộp review_focus và success_criteria thành các mục kiểm được (đo được hoặc trả lời có/không).
5. `## Lỗi hay gặp`: những anti-pattern skill cảnh báo.
6. `## Prompt đáng giữ`: tối đa 3 đoạn hướng dẫn cho mô hình đáng mượn nguyên ý (viết lại tiếng Việt, ngắn).
7. `## Đối chiếu NEXORA`: bảng | Điều OpenMontage làm | NEXORA đã có | Còn thiếu | Đề xuất cụ thể |.
8. `## Đề xuất ưu tiên`: tối đa 5 việc, mỗi việc nói rõ nên là code có test (luật đo được) hay prompt.

Chỉ dựa trên file đã đọc; điều gì suy ra thì ghi "(suy ra)". Trả về DUY NHẤT nội dung Markdown, không lời dẫn."""


def distil(p: str) -> Path:
    argv = ["claude", "-p", "--output-format", "json", "--model", "opus", "--effort", "high",
            "--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob",
            "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence",
            "--system-prompt", "Bạn là kỹ sư phân tích phần mềm, viết spec tiếng Việt chính xác, có dẫn nguồn file:dòng."]
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    started = time.time()
    done = subprocess.run(argv, input=PROMPT.format(p=p, nexora=NEXORA), capture_output=True, text=True, cwd=REPO, env=env, timeout=1800)
    answer = json.loads(done.stdout or "{}")
    text = (answer.get("result") or "").strip()
    if done.returncode != 0 or answer.get("is_error") or not text.startswith("#"):
        raise RuntimeError(f"{p}: {(done.stderr or done.stdout)[-400:]}")
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{p}.md"
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    out.write_text(f"<!-- Chưng cất từ OpenMontage {commit} bằng claude -p (Opus), {time.strftime('%Y-%m-%d')}; "
                   f"{time.time() - started:.0f}s; chi phí theo gói: {answer.get('total_cost_usd')} -->\n\n{text}\n")
    return out


if __name__ == "__main__":
    for p in sys.argv[1:] or DEFAULT:
        try:
            print("ok", distil(p), flush=True)
        except Exception as err:                       # one pipeline failing leaves the others
            print("fail", p, err, flush=True)
