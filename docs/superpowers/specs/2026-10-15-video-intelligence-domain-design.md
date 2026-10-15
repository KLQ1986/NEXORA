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

## 7. Tìm theo hình (SigLIP 2), đo ngày 2026-10-15

Bộ phân tích `pictures@1` tính vector cho mỗi khung đã xem (2 khung mỗi giây) bằng SigLIP 2 base (`google/siglip2-base-patch16-256`). Vector được lưu thành `{checksum}_pictures.npz` và ghi nhận là artifact `pictures` trong mô hình chuẩn. `vi.search` lấy các ứng viên theo mô tả và từ khoá như trước, rồi sắp lại bằng cách kết hợp thứ hạng (RRF, k = 10) giữa mô tả và khung khớp nhất trong đoạn. Điểm trả về vẫn là điểm mô tả, phát lại theo thứ tự mới, nên các ngưỡng giữ nguyên nghĩa. Xác suất của SigLIP 2 với câu tiếng Việt không đáng tin (có đáp án đúng chỉ được 0,001), nên chỉ dùng thứ hạng. Đoạn chưa có vector hình giữ thứ hạng mô tả ở cả hai bảng. Khâu chọn clip tìm qua `vi.search`.

Mô hình chạy trong một môi trường riêng (`scripts/setup-pictures.sh`, khoảng 760 MB trong `data/tools/siglip`), qua `adapters/siglip.py` và `siglip_helper.py`. Dự án chính không cần PyTorch. Không có môi trường đó thì tìm kiếm chạy theo mô tả như cũ.

Đo trên 18 câu tiếng Việt (đáp án do Claude đặt từ khung hình):

| Cách | Đúng vị trí đầu | Trong 3 đầu | MRR |
|---|---|---|---|
| Thử riêng, 20 nhịp của 0050 và 0038: mô tả | 11/18 | 15/18 | 0,74 |
| Thử riêng: SigLIP 2 base | 12/18 | 17/18 | 0,81 |
| Thử riêng: kết hợp | 13/18 | 17/18 | 0,82 |
| Hệ thống thật, cả kho (chỉ 0050, 0038 có hình): mô tả | 10/18 | 14/18 | 0,68 |
| Hệ thống thật: kết hợp | 10/18 | 16/18 | 0,72 |

SigLIP 2 so400m kém hơn bản base trên 0050 (đúng vị trí đầu 4/10) và chậm gấp 10 lần. Trên cả kho, đáp án chưa đủ: các nhịp ở clip khác cũng đúng (ví dụ cây dừa ở clip khác) nhưng bị tính là sai. Muốn đo đúng cần đáp án cho cả kho.

## 8. Mô tả nhịp v4 và độ phân giải khung, đo ngày 2026-10-15 trên 0038

Ollama đưa mọi ảnh về khoảng 1 megapixel trước khi qwen3-vl xem. Một khung 448 px và một khung 960 px tốn cùng số token (7796 cho 7 khung). Khung 448 px cắt từ proxy chỉ bị phóng to, nên thuyền ngoài khơi, hoa tím và rau muống biển không thấy được. Từ v4, khung của nhịp được trích từ file gốc, chất lượng JPEG 2. Lúc đầu dùng rộng 960 px; sau đó thống nhất dùng **1280 px** (tốn hơn khoảng 4% token: 8097 so với 7796 cho 7 khung), để giữ nhiều chi tiết của file gốc hơn.

Prompt v4: mô hình không còn đặt cỡ cảnh và góc máy, vì máy đo và cảm biến làm tốt hơn. Mô hình được hỏi theo lớp (chủ thể và vị trí, gần máy, giữa, xa), có danh mục tên vật hay gặp ở Việt Nam (chỉ dùng khi thấy rõ), và không được dùng câu mở đầu, câu phủ định hay câu cảm xúc. Bộ lọc bỏ thêm câu mở đầu ("Hình ảnh cho thấy"), câu phủ định và câu nói về chuyển động máy. Văn bản dùng để tìm không còn chứa nhãn âm thanh.

| 0038, 3 nhịp | Vật đúng / 22 | Giống nhau liền kề | Tìm 8 câu: đúng đầu | MRR |
|---|---|---|---|---|
| v3, 448 px proxy | 14 | 0,92 | 5/8 | 0,73 |
| v4, 448 px proxy | 15 | 0,94 | 5/8 | 0,76 |
| **v4, 960 px gốc** | **18** | **0,89** | **7/8** | **0,94** |
| v4, 1280 px gốc | 18 | 0,88 | 4/8 | 0,73 |

Mới đo trên 3 nhịp, nên chênh lệch giữa 960 px và 1280 px phần lớn là ngẫu nhiên: hai cỡ nêu đúng cùng 18 vật. Cần đo thêm trên một clip có người và chữ. Lần chạy thật ở dưới dùng 960 px; từ commit sau, nhịp được mô tả ở 1280 px.

Sau khi chạy thật cho 0038, đo qua tìm kiếm của cả kho với 8 câu của 0038: chỉ dùng mô tả, đúng vị trí đầu giảm từ 5/8 xuống 4/8 (MRR 0,71 xuống 0,68). Kết hợp với hình thì đúng vị trí đầu tăng từ 5/8 lên 6/8, đúng trong 3 kết quả đầu 8/8, MRR từ 0,76 lên 0,83. Mô tả mới nêu đúng nhiều vật hơn, nhưng trên cả kho, mô tả một mình chưa tìm tốt hơn. Câu "đường chân trời trên mặt biển" tụt từ #8 xuống #9, vì v4 không còn nhắc đường chân trời.

### 8.1 Thử v4 ở 1280 px trên 0059 (phòng tắm, có người), 2026-10-15

So với đáp án 18 vật đặt từ khung của file gốc: bản cũ nêu đúng khoảng 5 vật và sai "quay từ trên cao", "tủ", "cảnh cực toàn". Bản v4 ở 1280 px nêu đúng 13 vật bằng tiếng Việt, thêm 2 vật đúng nhưng ghi bằng tiếng Anh, và không bịa vật nào. Vẫn sót cốc thuỷ tinh, kệ, thùng rác, vòi xịt, và không nhận ra người chỉ hiện trong gương. Tìm kiếm trên cả kho: 6/8 câu ra 0059 ở vị trí đầu; "thùng rác" và "cốc thuỷ tinh" trượt vì mô tả không nhắc và vật quá nhỏ để hình cứu được.

Clip này để lộ ba lỗi của bước dọn mô tả, nay đã sửa:
- Từ tiếng Anh ("towel rack", "towel") được dịch theo cụm, trước khi dịch từng từ. Mục nào còn tiếng Anh thì bị bỏ khỏi danh sách vật.
- Chuyển động máy ("máy đẩy vào") bị bỏ khỏi danh sách vật, câu mô tả và các lớp cảnh. Máy quay xuất hiện trong hình vẫn là một vật.
- Chủ thể hay lớp cảnh chỉ nêu vị trí ("phía trái") bị bỏ.
- "Điểm mới" so theo tên chuẩn hoá, nên không lặp lại danh sách "Thấy" khi hai bên chỉ khác "một chiếc".

`retell` (POST `/api/v1/assets/{id}/retell`) dựng lại văn bản của các nhịp từ câu trả lời đã lưu, không gọi lại mô hình mô tả, rồi nhúng lại văn bản. Đã chạy cho 0059 và 0038.

## 9. Kế hoạch A–G (2026-10-15)

Thứ tự đã thống nhất: A nền đúng → B Dossier → C Match Report → D Level 2 phần yếu → E entity xuyên shot → F trích xuất asset → G storytelling và đề xuất dựng lại. Mỗi phần chỉ thử trên **một video test: 0059** (phòng tắm, có người, có lời nói, 2 nhịp). Không chạy lại cả kho.

### A. Nền đúng

- Bước `describe` khai phiên bản `v4`. Một clip được tính là mô tả ở prompt cũ nhất trong các nhịp của nó, nên clip mô tả bằng v3 bị báo là cũ, kể cả khi văn bản đã được dựng lại bằng `retell`.
- Ở 1280 px mỗi khung tốn khoảng 1150 token. Nhịp 7 khung của 0034 vượt 8192 token, nên ngữ cảnh Ollama được nâng lên 16384 cho mọi lệnh gọi. Nếu vẫn vượt, nhịp được hỏi lại với ít khung hơn.
- Câu mô tả chỉ nói về máy quay thì vẫn được giữ, nếu không còn câu nào khác. Một nhịp v4 không có câu mô tả thì được hỏi lại, không lấy từ bộ nhớ đệm.
- Một lớp cảnh lặp nguyên văn lớp trước bị bỏ. Thêm "hoa mỏ két" vào danh mục tên.

Đã mô tả lại 0090, 0026, 0034, 0040 trước khi dừng việc chạy cả kho:

| Clip | Vật đúng | Ghi chú |
|---|---|---|
| 0090 | 5/8 | Sót trời và mây, bụi cây, cỏ. Máy đo "đứng yên" trong khi khung hình có trôi chậm. |
| 0026 | 5/6 | Bịa "mặt trời". |
| 0034 | khoảng 11/13 | Sót người đi xe máy (nhỏ, đang chạy) và bụi cây xén. |
| 0040 | | Nêu đúng rau muống biển hoa tím, thuyền thúng, công trình mái cong. |
