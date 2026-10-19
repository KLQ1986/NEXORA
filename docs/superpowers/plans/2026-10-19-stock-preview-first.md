# Stock theo ảnh xem trước: kế hoạch triển khai

> **Dành cho agent thực thi:** chạy native, tức một phiên làm lần lượt từng task theo TDD. Các bước dùng checkbox (`- [ ]`).

**Mục tiêu:** clip stock được chấm qua ảnh xem trước trước khi tải. Người vận hành xem ứng viên trực tiếp từ nguồn, và chỉ clip được chọn mới tải về. Clip stock vào Thư viện với phân tích nhẹ, và được dọn sau khi duyệt storyboard.

**Kiến trúc:** module mới `modules/sourcing/stock.py` (`StockScout`) giữ ứng viên trong bảng `stock_candidates`. Nó gọi hai nguồn tìm: thao tác `candidates` mới của adapter `stock` (OpenMontage), và adapter mới `stock_api` (Pexels/Pixabay song ngữ). Nó chấm bằng `picture_text` (SigLIP) và `model` (mô hình nhìn). `app.py` nối scout với Thư viện, Director và Sourcing. API và Storyboard hiện ứng viên, phát trực tiếp từ nguồn.

**Công nghệ:** Python 3.12 (FastAPI, sqlite), React + TS, OpenMontage chạy trong tiến trình riêng, Pexels API v1, Pixabay API.

**Spec:** `docs/superpowers/specs/2026-10-19-stock-preview-first-design.md`

## Ràng buộc chung

- Không tải video ứng viên khi tìm hoặc chấm. Chỉ tải ảnh xem trước, hoặc một khung ffmpeg đọc từ xa khi nguồn không có ảnh.
- Công tắc mới `stock` trong `auto_approve` mặc định tắt, và chỉ người vận hành bật.
- Dừng khẩn cấp đang bật thì không tìm và không tải stock.
- Mọi URL tải phải là địa chỉ web công khai (`public_address`).
- Không truyền `ANTHROPIC_API_KEY` cho tiến trình con.
- Clip `licensed` mới nhập chỉ chạy ingest và understand.

## Điểm cần chú ý khi review

1. Một nguồn lỗi (mạng, hết hạn mức) thì các nguồn khác vẫn trả về ứng viên. Test bằng nguồn giả ném lỗi.
2. Ứng viên không có `thumbnail_url` vẫn được chấm qua một khung ffmpeg; nếu không lấy được thì chỉ được đề xuất. Test với `thumbnail_url=""`.
3. Không có mô hình nhìn thì không tự tải. Test bằng `model` ném `AdapterError`.
4. Dọn sau khi duyệt không đụng clip stock đang dùng ở dự án khác hoặc được ≥4 sao. Test hai dự án.
5. Shot liền kề không tự chọn cùng `source_id`. Test hai câu có cùng ứng viên tốt nhất.

---

### Task 1: Clip stock chỉ phân tích nhẹ

**Files:** sửa `src/nexora/modules/intelligence/service.py` (`taken_in`, `find_unmeasured`), `src/nexora/modules/library/ingest.py` (`find_missing_cuts`), `src/nexora/app.py` (nhiệm vụ transcribe bỏ qua `licensed`). Test: `tests/library/test_stock_light.py`.

- [ ] Viết test: nhập một video `origin="licensed"` → run understand có; transcribe, structure, cuts và profile không có. Gọi `find_unmeasured` và `find_missing_cuts` cũng không tạo run cho clip này. Video `self_shot` vẫn có đủ các run.
- [ ] Chạy test, xác nhận đang fail.
- [ ] Sửa `taken_in`: nếu `(asset or {}).get("origin") == "licensed"` → `self.understand(asset_id)` rồi return. Hai vòng quét bỏ qua `asset["origin"] == "licensed"`.
- [ ] Chạy test, xác nhận pass. Commit.

### Task 2: Nguồn ứng viên (không tải)

**Files:** sửa `src/nexora/adapters/openmontage.py` (thêm thao tác `candidates` và `download`); tạo `src/nexora/adapters/stock_api.py` (`StockApi`: Pexels/Pixabay, `candidates`/`download`, cùng `fetch_public(url, path, max_bytes)`). Test: `tests/adapters/test_stock_sources.py`.

**Interfaces:**
- `Request("candidates", inputs={"queries": [str]}, params={"sources": [...], "per_query": 8, "lang": "vi"|"en"})` → `outputs["candidates"]: list[dict]`. Mỗi dict có các khoá `source, source_id, source_url, download_url, preview_url, thumbnail_url, width, height, duration, creator, license, tags`.
- `Request("download", inputs={"candidate": dict}, params={"out_dir": str})` → `files=(path,)`.

- [ ] Viết test. Với OpenMontage: giả `run_process`; payload chứa `"op": "candidates"` và không có `output_dir` tải. Với StockApi: giả `urlopen`; Pexels nhận `locale=vi-VN` khi `lang=vi`; Pixabay nhận `lang=vi`; `preview_url` là bản SD/tiny; không có key thì `describe()` báo không dùng được.
- [ ] Sửa runner của OpenMontage để chạy được ba thao tác. `candidates` gọi `available_sources()`, lọc theo `sources`, chạy `search(q, SearchFilters(kind="video", per_page=n))` và trả `asdict`; mỗi nguồn lỗi thì ghi lại rồi bỏ qua. `download` gọi `get_source(c["source"]).download(Candidate(**c), out)`.
- [ ] Viết `StockApi`.
- [ ] Chạy test, xác nhận pass. Commit.

### Task 3: StockScout (từ khoá, ảnh, chấm, lưu)

**Files:** tạo `src/nexora/modules/sourcing/stock.py`. Test: `tests/production/test_stock_scout.py`.

**Interfaces:**
- `StockScout(db_path, adapters, tmp_dir)`.
- `.keywords(line) -> {"en": [...], "vi": [...], "names": [...]}`.
- `.find(project_id, key, line, *, seconds) -> list[dict]`: chạy tối đa 3 lượt, lưu kết quả, xếp theo điểm.
- `.options(project_id, key) -> list[dict]`.
- `.candidate(cid) -> dict | None`.
- `.best(project_id, key, *, avoid=set()) -> dict | None`: ứng viên đạt (`look ≥ LOOK_PASS`) và `source_id` không nằm trong `avoid`.
- `.fetch(cid, out_dir) -> Path`.
- `.forget(project_id) -> int`.

Mỗi ứng viên đã lưu gồm `cid, project_id, key, ...các trường nguồn, thumb (đường dẫn), siglip, look, why, rank`.

- [ ] Viết test với adapter giả `stock`, `stock_api`, `picture_text`, `model`:
  - Gộp ứng viên và khử trùng.
  - Không có file video nào được ghi ra.
  - SigLIP xếp hạng; chỉ 3 ứng viên đầu được mô hình nhìn chấm.
  - Lượt dự phòng chỉ chạy khi lượt đầu không có ứng viên đạt.
  - Một nguồn lỗi thì các nguồn khác vẫn trả về.
  - Ứng viên không có thumbnail thì lấy một khung ffmpeg; nếu ffmpeg lỗi thì `look=None`.
  - Mô hình nhìn lỗi thì `best()` trả None.
  - `forget` xoá cả các hàng trong bảng lẫn thư mục tạm.
- [ ] Viết `StockScout`. Bảng `stock_candidates(cid TEXT PRIMARY KEY, project_id, key, data TEXT, rank REAL, created_at)`. Lời nhắc từ khoá trả JSON. Mô hình nhìn dùng `JUDGE_PROMPT` với `n=1` qua `model.describe`.
- [ ] Chạy test, xác nhận pass. Commit.

### Task 4: Nối vào app: công tắc, dùng ứng viên, producer, nút Storyboard

**Files:**
- sửa `src/nexora/agents/autonomy.py`: thêm `SWITCHES["stock"]`;
- sửa `src/nexora/app.py`:
  - `build()` tạo `system.stock_scout`;
  - `fill_gap_from_stock(system, shot_id, line)` viết lại;
  - thay `storyboard_stock`;
  - thêm `use_stock_candidate(system, cid, *, shot_id, board)`;
- sửa `src/nexora/agents/producer.py`: bỏ `QUERY_PROMPT` khỏi đường dùng, truyền câu lời dẫn;
- sửa `src/nexora/api/app.py`:
  - `/stock` không tải;
  - thêm `/use-stock`;
  - thêm `GET /api/v1/stock/{cid}/thumb`;
  - thêm `stock_options` vào `shot_view`.

Test: `tests/production/test_stock_flow.py`; cập nhật các test stock cũ trong `test_production.py`, `test_topic_script.py` và `test_sourcing_more.py`.

- [ ] Viết test:
  - Công tắc tắt → producer không tải gì, shot có `stock_options`.
  - Công tắc bật → chỉ tải ứng viên đạt cao nhất; asset `licensed` có `rights.project_id`, `stock_id`, `score`.
  - Dừng khẩn cấp đang bật → không gọi tìm.
  - `/use-stock` tải, nhập, gán cho shot.
  - Hai câu liền nhau không cùng `source_id`.
- [ ] Viết code. `use_stock_candidate` gọi `scout.fetch`, rồi `library.ingest(origin="licensed", rights)`. Shot storyboard dùng `director.use_asset`; dòng kịch bản dùng `sourcing.use_asset(pending=understands)`.
- [ ] Chạy test, xác nhận pass. Commit.

### Task 5: Dọn dẹp sau khi duyệt storyboard

**Files:** `src/nexora/app.py` (`after_storyboard_approved`), `src/nexora/api/app.py` (gọi hàm này trong `storyboard_approve`). Test trong `tests/production/test_stock_flow.py`.

- [ ] Viết test sau khi duyệt:
  - `stock_candidates` của dự án và `tmp/stock/<project>` đã bị xoá.
  - Clip `licensed` có `rights.project_id` == dự án mà không có trong storyboard thì vào Thùng rác.
  - Clip đang dùng ở dự án khác hoặc ≥4 sao thì giữ.
  - Có một thông báo kết quả.
- [ ] Viết code, chạy test, xác nhận pass. Commit.

### Task 6: Giao diện

**Files:** `web/src/Storyboard.tsx`, `web/src/Library.tsx`, `web/src/api.ts`, `web/src/en.ts`, `web/src/System.tsx` (công tắc tự hiện qua `switch_names`).

- [ ] Tab Hình có mục "Clip stock · N". Mỗi ô gồm:
  - ảnh, lấy từ `/api/v1/stock/{cid}/thumb`;
  - `<video>` phát `preview_url` khi rê chuột hoặc bấm (muted, loop, preload none);
  - nguồn, giấy phép, thời lượng, điểm và lý do;
  - nút "Dùng cho shot";
  - nút "Mở trang gốc".
- [ ] Đổi nhãn nút "Tìm clip stock" thành "Tìm ứng viên stock". Sau khi tìm, mục ứng viên hiện ra mà chưa tải gì.
- [ ] Thư viện: thẻ của clip `origin === "licensed"` có nhãn "Stock", và có thêm bộ lọc "Stock".
- [ ] Chạy `npx tsc --noEmit` và `npm run build`. Kiểm tra trên trang thật bằng Playwright.
- [ ] Commit.

### Task 7: Hoàn tất

- [ ] Chạy toàn bộ bộ test, sửa chỗ hỏng.
- [ ] Khởi động lại server; chạy một lần tìm thật (chỉ gửi từ khoá, không tải) trên một shot của miền Tây; xem trang.
- [ ] Cập nhật memory `stock-search-deferred`, chạy `graphify update .`. Commit.
