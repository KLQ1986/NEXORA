# Video Intelligence: một domain nền tảng riêng

Bản thiết kế, 2026-10-15. Trạng thái: **chờ người vận hành duyệt**, chưa có code. Đề xuất của người vận hành ngày 2026-10-15; bản này nói cách làm trong NEXORA.

## 1. Ý tưởng

Video Intelligence (VI) là một domain độc lập của Video Factory. Nó nhận một video, phân tích một lần, và giữ kết quả trong một **mô hình chuẩn** có phiên bản. Mọi việc khác dùng kết quả đó mà không phân tích lại: tìm footage, chọn clip cho kịch bản, chọn highlight, cắt clip ngắn, học phong cách dựng, phân tích video đối thủ, báo cáo chất lượng, và các agent. Editor là một bên dùng như các bên khác; VI không biết editor nào đang được chọn.

```
Nhập video ─► Phân tích hình ─┐
(file, tiếng,  Phân tích tiếng ─┼─► Ghép đa phương thức ─► Mô hình chuẩn VI ─► Tìm kiếm · Chọn clip · Highlight
 metadata,    Cảm biến máy ────┘   (thực thể, sự việc,      (dữ liệu có cấu trúc,    Clip ngắn · Phong cách · Đối thủ
 nguồn gốc)                         bằng chứng, độ tin cậy)  file thô, vector,         Báo cáo & QA · Agent
                                                             phiên bản)
```

## 2. NEXORA đang ở đâu so với ý tưởng này

| Tầng | Đang có | Còn thiếu |
|---|---|---|
| Nhập video | `library/ingest.py`: checksum, thông số kỹ thuật đầy đủ, proxy, nguồn gốc, quyền | nằm chung domain với quản lý file, thùng rác, nhạc |
| Phân tích hình | `library/signals.py`, `structure.py`, Vision (`adapters/apple*`), mô tả (`understand.py`) | |
| Phân tích tiếng | `transcribe.py` (VAD, lọc câu bịa, người nói), SoundAnalysis, R 128 | |
| Cảm biến máy | `library/telemetry.py` (DJI) | |
| Ghép đa phương thức | `profile.profile_beat`, `cross_checks`, `events_of`, `scenes_of`, sổ người | nhận diện thực thể còn mỏng (chỉ khuôn mặt); chưa có dòng thời gian sự việc chung cho cả buổi quay |
| Mô hình chuẩn | rải ở `moments.data` (JSON tự do), `_profile.json`, `_look.json`, `_listen.json`, `_telemetry.json`, `.npz`, `asset_versions.metadata`, bảng `golden_labels` | **không có một lược đồ chung có phiên bản**; mỗi nơi một kiểu |
| Bên dùng | `sourcing/match.py`, tìm kiếm ở API, `quality/fields.py`, khâu dựng, agent | **đọc thẳng dữ liệu thô** (`moment.data["profile"]["shot_size"]["value"]`) |

Ranh giới đã có: quy tắc lớp cấm các domain import lẫn nhau, nên editor không gọi vào phân tích. Phân tích một lần đã có ở mức tệp (lưu theo checksum) và mức nhịp (mô tả khoá theo khung, prompt, số đo).

## 3. Domain `intelligence`

Một gói `nexora/modules/intelligence/`, gồm ba phần:

**3.1 Bộ phân tích là plugin có khai báo.** Mỗi bộ phân tích khai báo tên, phiên bản, đầu vào nó cần (file gốc, khung hình, âm thanh, kết quả của bộ khác), các trường nó ghi, và nó có tốn tiền hay gửi dữ liệu ra ngoài không. Ví dụ: `signals@2` cần file và ghi chuyển động, độ nét; `vision@3` cần khung và ghi người, chữ, nhãn cảnh; `telemetry@1` cần luồng dữ liệu của máy và ghi góc máy. Từ các khai báo, hệ thống dựng đồ thị phụ thuộc. Khi một bộ đổi phiên bản, chỉ bộ đó và những bộ phụ thuộc vào nó chạy lại. Các stage hiện có (`probe`, `look`, `listen`, `profile`, `describe`) được bọc thành plugin, không viết lại.

**3.2 Mô hình chuẩn.** Một lược đồ có phiên bản, khoá theo checksum của file:

- `Recording`: định danh, thông số kỹ thuật, nguồn gốc, quyền.
- `Segment` theo các cấp: cú máy, nhịp, phân cảnh, sự việc, khoảnh (một dòng chữ, một âm thanh).
- `Observation`: một giá trị của một trường trên một khoảng thời gian. Gồm `field`, `value`, `source` (measured, recognized, model, human), `confidence`, `evidence` (khung, khoảng thời gian, câu trả lời gốc), `analyzer@version`, `at`.
- `Entity`: người, nơi, vật, cùng các lần xuất hiện của nó.
- `Artifact`: các file thô (khung hình, số đo, vector), đánh địa chỉ theo nội dung.
- `Embedding`: vector văn bản và hình, kèm tên và phiên bản mô hình.

Một trường có thể có nhiều quan sát từ nhiều nguồn. Một **luật hợp nhất** chọn giá trị dùng được: người vận hành, rồi tới số đo đã phát hành, rồi nhận diện đã phát hành, rồi mô hình đã phát hành. Luật này dựa trên cổng phát hành đã có (`quality/fields.py`).

Lưu trữ: các bảng SQLite `vi_recordings`, `vi_segments`, `vi_observations`, `vi_entities`, `vi_appearances`. File thô vẫn nằm cạnh footage như hiện nay. Bảng `moments` vẫn là chỉ mục tìm kiếm, nhưng được sinh ra từ mô hình chuẩn, không còn là nơi lưu chính.

**3.3 Giao diện đọc trong code.** Đây là một lớp Python chạy trong cùng tiến trình, không phải HTTP. Mọi bên dùng chỉ đọc qua lớp này:

```python
vi.recording(asset_id)
vi.segments(asset_id, level="beat", between=(t0, t1))
vi.value(asset_id, t, "shot_size")          # giá trị đã hợp nhất, nguồn, độ tin cậy, bằng chứng
vi.observations(asset_id, field, between)   # mọi quan sát, kể cả chưa phát hành
vi.find(query, filters={"shot_size": "cận"})
vi.alike(asset_id, t0, t1)
vi.entities(kind="person")
vi.changed_since(version)                   # cho bên dùng biết cần làm mới gì
```

## 4. Bên dùng

- `sourcing` (chọn clip), tìm kiếm, `quality` (báo cáo, độ chính xác) và `edit` chỉ đọc qua `vi`.
- Việc mới (chọn highlight, cắt clip ngắn, phân tích đối thủ, học phong cách, tái tạo quy trình sản xuất) là các module đọc qua `vi`, không có bộ phân tích riêng.
- Video của người khác (research, đối thủ) được nhập với cờ quyền (chỉ để tham khảo). `vi` vẫn phân tích đầy đủ, nhưng luật hợp nhất không bao giờ đưa video đó vào kết quả chọn clip.

## 5. Kế hoạch chuyển dần

Không viết lại một lần cả khối. Mỗi bước giữ hệ thống chạy được và test đạt:

1. Tạo `intelligence/model.py` với lược đồ và luật hợp nhất, đặt lên trên các kho hiện có (đọc từ `moments.data` và các file JSON). Test cho lược đồ.
2. Chuyển `sourcing/match.py`, tìm kiếm và `quality/fields.py` sang đọc qua `vi`.
3. Chuyển chỗ ghi: các stage ghi `Observation` vào bảng mới. `moments` được sinh lại từ đó. Viết bước chuyển dữ liệu cho kho hiện có.
4. Dời `ingest`, `signals`, `structure`, `profile`, `transcribe`, `understand`, `telemetry` sang `intelligence/`. `library` chỉ còn quản lý file, thùng rác và nhạc.
5. Bọc các stage thành plugin có khai báo, dựng đồ thị phụ thuộc, tính lại theo phiên bản.
6. Thêm quy tắc lớp mới: chỉ `intelligence` được ghi vào mô hình chuẩn; các domain khác chỉ đọc qua `vi`.

## 6. Điều cần người vận hành quyết

- Duyệt hướng này và tên domain (`intelligence`).
- Thứ tự: làm ngay, hay sau khi xác nhận nhãn mẫu và chọn mô hình nhìn.
