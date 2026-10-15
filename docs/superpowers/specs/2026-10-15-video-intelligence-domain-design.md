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

### B. Hồ sơ nguyên liệu (Asset Intelligence Dossier)

`modules/intelligence/dossier.py` gom về một chỗ mọi thứ Video Intelligence biết về một clip, chỉ đọc qua `VideoIntelligence`, không phân tích lại. Hồ sơ gồm:
- thông số kỹ thuật, tiêu đề, tóm tắt, chủ đề, cấu trúc;
- phiên bản của từng bộ phân tích và phần nào đã cũ;
- người, nơi, lời nói, chữ trên hình, sự kiện, cảnh;
- từng nhịp: mô tả, vật thấy, hành động, đặc điểm (ghi rõ giá trị nào chỉ do mô hình nói), điểm hình, điểm tiếng, gợi ý cách dùng, lời, chữ, cờ cần xem;
- kết luận: số giây dùng được, dùng tạm, lỗi, và nhịp đẹp nhất.

Điểm hình chỉ tính từ giá trị đo: rung, nét, phơi sáng, chất lượng ở mức "poor" là lỗi; mức "fair", đường chân trời nghiêng, ngược sáng, nhiễu là dùng tạm. Điểm tiếng: méo là lỗi; gió và tiếng rất nhỏ (dưới -45 LUFS) là dùng tạm. Gợi ý cách dùng (cảnh thiết lập, dẫn vào, kết, chèn chi tiết, đoạn nói trước máy, lời dẫn ngoài khung) chỉ dựa trên giá trị đo hoặc nhận diện, không dựa trên điều mô hình nói.

API: `GET /api/v1/assets/{id}/dossier` (JSON) và `?format=md` (trang Markdown để tải). Trong thư viện, mục "Hồ sơ nguyên liệu" nằm dưới hồ sơ video.

Đi kèm: `retell` tự đóng cờ "ngôn ngữ" khi từ tiếng Anh đã được dịch. `telemetry` được ghi là đã chạy cả khi máy quay không ghi dữ liệu cảm biến, nên footage không phải DJI không còn bị báo là phân tích cũ.

Trên 0059: 9,1 giây dùng được, phân tích ở phiên bản mới nhất. Cỡ cảnh của cả hai nhịp chỉ do mô hình nói, vì không có người để đo cỡ cảnh từ thân người. Đây là việc của D.

### C. Báo cáo ghép nguyên liệu (Script-to-Asset Match Report)

`modules/sourcing/report.py` đọc kết quả ghép, không tìm hay chấm lại:
- **Theo câu:** đoạn được chọn, điểm chấm 0–10 của mô hình, điểm hình (theo `core/usability.py`), có ngắn hơn số giây cần không, lý do, các phương án dự phòng.
- **Theo clip:** clip nào được chọn cho câu nào, dự phòng cho câu nào, dùng bao nhiêu giây, và clip nào không được dùng.
- **Tổng:** số câu tốt, tạm, thiếu; số giây cần và số giây có hình; điểm chấm trung bình.

Một câu là **tốt** khi người dùng đã duyệt, hoặc mô hình chấm từ `AUTO_ACCEPT` (8) trở lên và hình không lỗi. Câu có hình lỗi thì tối đa là **tạm**. Câu không có hình là **thiếu**. Điểm chấm của lựa chọn chính nay được lưu trong `extras.judge` của lựa chọn. Luật chấm hình và tiếng chuyển từ dossier sang `core/usability.py`, vì các module không được import lẫn nhau.

API: `GET /api/v1/projects/{id}/match/report` (JSON) và `?format=md`. Trên bảng dự án, mục "Báo cáo ghép nguyên liệu" nằm dưới các cảnh.

Chạy thật với kịch bản thử 7 câu trên kho hiện có (2026-10-15):

| Câu | Đáp án | Chọn |
|---|---|---|
| Một người quay video trong phòng tắm | 0059, 0–5,2 | 0059, 0–2,7 ✓ |
| Phòng tắm có cửa sổ gỗ và bồn cầu trắng | 0059, 5,2–9,1 | 0059, 5,2–9,1 ✓ |
| Thuyền thúng xanh nằm trên bãi cát | 0038 | 0038, 6,0–8,7 ✓ |
| Vòng quay khổng lồ trong công viên giải trí | 0034 | 0034, 0–3,5 ✓ |
| Hoa mỏ két màu cam trong vườn | 0090 | 0090, 1,7–4,4 ✓ |
| Sóng biển vỗ vào bờ cát | 0026 | 0038, 15,9–18,4 ✓ (có sóng và bờ cát; 0026 ở phương án dự phòng) |
| Tên lửa phóng lên quỹ đạo | thiếu | thiếu ✓ |

7/7 đúng, 87% số giây cần đã có hình. Mô hình chấm 10/10 cho mọi lựa chọn, nên điểm chấm chưa phân biệt được lựa chọn tốt với lựa chọn vừa đủ. Các phương án dự phòng sai ngữ cảnh được chấm 5/10.

### D. Level 2: phần còn yếu

- **Pha của sự kiện** được tính theo chuyển động đo được, không theo nhịp (`profile.phases_of`): cao trào là khoảng một giây quanh lúc chủ thể chuyển động mạnh nhất, bắt đầu và kết thúc là hai phần trước và sau đó. Trước đây một sự kiện chỉ gồm một nhịp có ba pha trùng nhau. Khung "trước / sau" được lấy từ nhịp chứa thời điểm của pha.
- **Cỡ cảnh trong phòng:** khi Apple Vision nhận ra phòng (`interior_room`, `bathroom`, `kitchen`…) và không có vật nào chiếm từ 75% khung trở lên, cỡ cảnh đo được là "trung", độ tin thấp. Vision không phân biệt được cả căn phòng với một góc phòng. Bộ `look` lên phiên bản 4.
- **Người nói** (`profile.voices_of`): một câu thuộc về một người khi lúc nói, người nói được đo là trong khung và mặt người đó là mặt duy nhất thấy được trong phần lớn câu. Giọng nghe lúc đó được coi là của người ấy trong file đó, nên các câu khác cùng giọng (kể cả nói ngoài khung) cũng thuộc về họ. Mỗi người trong thư viện mang theo `speaks`; hồ sơ ghi tên người nói trước mỗi câu.
- **Sửa lỗi mô hình chuẩn:** khi mô tả lại, mọi trường mà bước mô tả có thể ghi đều được xoá trước. Trước đây cỡ cảnh và góc máy do v3 nói vẫn còn và được đọc như hiện hành. Khi một trường không có trong lần ghi mới, `observe_many` nay chỉ xoá những gì cùng bộ phân tích đã ghi trước đó; trước đây nó xoá cả giá trị máy đo của trường đó.

Đo trên 0059:

| | Đáp án | Kết quả |
|---|---|---|
| Hành động | một người quay video (trong gương) | "người đàn ông đang quay video" ✓ |
| Sự kiện | 0–5,2 giây | 0–5,23; chuyển động 0,2–4,0; cao trào 2,7–3,7 ✓ |
| Người nói | người cầm máy, ngoài khung | "ngoài khung" ✓ |
| Cỡ cảnh nhịp 2 | toàn hoặc trung (cả phòng tắm) | đo được "trung" (trước là mô hình nói "cực toàn") |
| Cỡ cảnh nhịp 1 | trung | không đo: có người trong gương nhưng không thấy mặt, nên luật chủ ý không đoán |

Kho hiện chưa có clip nào có người nói trước máy, nên việc gắn người nói mới chỉ được kiểm bằng test, chưa có số đo trên footage thật.

### E. Entity xuyên shot và liên kết âm thanh–hình

`modules/intelligence/entities.py` (hàm thuần) và bộ phân tích mới `follow` (chạy sau mỗi lần mô tả, hoặc `POST /api/v1/assets/{id}/follow`):
- **Vật** (`thing`): vật cùng tên chuẩn hoá, sau khi bỏ số lượng và màu sắc ("thuyền thúng màu xanh lá" → "thuyền thúng"), được nối qua các nhịp liền nhau thành một lần xuất hiện. `across_cut` ghi khi lần xuất hiện đó kéo qua điểm cắt shot. Vật cùng tên ở các clip khác là cùng một thực thể của thư viện. Những cụm không phải vật ("không người", "không gian yên tĩnh") bị bỏ. Mỗi lần xuất hiện được kiểm bằng hình (`seen`): tỉ lệ khung *ngoài* đoạn đó có điểm SigLIP 2 thấp hơn trung vị của đoạn. 0,5 nghĩa là không hơn phần còn lại; chỉ dùng thứ hạng, không dùng xác suất.
- **Chủ thể** (`subject`): bước `look` cắt vùng người và động vật ở mỗi khung (độ tin từ 0,4, diện tích từ 0,4% khung) và lưu vector SigLIP 2 vào `_subjects.npz`. Mỗi track trong một shot được biểu diễn bằng vector trung bình của các vùng cắt. Các track được nối qua điểm cắt và qua các clip khi cosine từ 0,88; hai track cùng lúc trong một clip, hoặc một người với một con vật, không bao giờ được nối. Chỉ giữ chủ thể có từ 2 track.
- **Nguồn âm** (`sound_source`): mỗi âm thanh nghe được gắn với vật trong hình có thể phát ra nó (bảng `SOURCES`: sóng biển → biển, sóng, bãi biển…). Âm thanh từ người (lời nói, tiếng cười…) là trong khung khi người nói được đo là trong khung. Không thấy nguồn thì ghi "ngoài khung"; âm không có trong bảng thì ghi "chưa rõ", không đoán.

Hồ sơ có thêm "Vật theo dõi được", "Chủ thể xuyên shot", và âm thanh của từng nhịp.

Trên 0059:
- 13 vật. Gương, bồn rửa, khăn, giá treo khăn được xác nhận 1,0 ở nhịp 1, đèn trần và gạch tường 1,0 ở nhịp 2, đúng với khung hình.
- Bồn cầu, vòi sen, cửa sổ có mặt cả clip, nên được 0,5.
- Lời "Mì" có nguồn là người, ngoài khung (đúng).
- Không có chủ thể xuyên shot: clip chỉ có một shot và Vision không nhận ra thân người.

Trên cả thư viện có 83 vật. Ví dụ: "thuyền thúng" có ở 0038 và 0040, "cây dừa" ở 0090 và 0094.

### F. Trích xuất asset

`modules/library/extract.py` và thao tác `extract` của adapter ffmpeg lấy một phần của clip ra để dùng ở nơi khác, lấy từ file gốc, giữ nguyên cỡ và độ sâu màu:
- **clip**: HEVC, 10-bit khi file gốc 10-bit, có tiếng (AAC 256k), có track timecode. Footage log vẫn là log, HDR vẫn là HDR. Mô tả màu (primaries, transfer, matrix) được ghi thẳng vào luồng bằng `hevc_metadata`, vì VideoToolbox bỏ qua cờ primaries. Không có media engine thì dùng libx265.
- **ảnh still**: một khung đủ cỡ ở **khung đẹp nhất** của đoạn. Bước `look` nay ghi `best_frame` cho mỗi nhịp: điểm thẩm mỹ của Vision, trừ điểm khung bị đánh dấu là ảnh tiện ích. Footage HDR được đưa về SDR, vì JPEG không chứa được HDR.
- **tiếng**: WAV 24-bit 48 kHz.
- **card.json** đi kèm: nguồn (file, checksum, thời điểm), mô tả, vật, nơi, cỡ cảnh, máy, số người, điểm hình và tiếng, định dạng, log hay không, thời điểm của ảnh still.

API:
- `POST /api/v1/assets/{id}/extract`: `{t_in, t_out}` cho một đoạn, hoặc `{usable: true}` cho mọi nhịp có hình "dùng được"; `kinds` gồm clip, still, audio.
- `GET /api/v1/assets/{id}/extracts`: danh sách đã trích xuất, kèm link tải.

Mỗi yêu cầu tối đa 120 giây footage và chạy đồng bộ. Trong hồ sơ nguyên liệu có nút trích xuất cho từng nhịp và cho mọi đoạn dùng được.

Trên 0059: 2 nhịp dùng được, trích xuất trong khoảng 15 giây. Kết quả là 2 clip 3840×2160 HEVC 10-bit 29,97 khung/giây bt709, ảnh still ở giây 4,5 và 6,5, cùng 2 file WAV.

### G. Kể chuyện và đề xuất dựng lại

`modules/intelligence/story.py`:
- **Câu chuyện của một clip**: mỗi nhịp có một mức năng lượng, đọc từ những gì đo được: chuyển động của chủ thể 0,35, độ to 0,2, lời nói 0,15, vật mới thấy 0,15, máy di chuyển 0,15. Mỗi thành phần được chuẩn hoá trong clip.
  - Vai trò: nhịp đầu là mở đầu, hoặc thiết lập khi là cảnh rộng và máy đứng yên; nhịp nhiều năng lượng nhất là cao trào (khi clip có từ 3 nhịp); nhịp cuối là kết; còn lại là phát triển. Mỗi nhịp ghi lý do.
  - Có nhận xét về 3 giây đầu và về độ dài cú máy. Cấu trúc do mô hình đọc trong tóm tắt (`cau_truc`) được đối chiếu với cao trào đo được.
- **Đề xuất dựng lại** cho một hoặc nhiều clip, theo độ dài đích:
  - Bỏ nhịp có hình lỗi và nhịp quá ngắn.
  - Cắt mỗi nhịp về đoạn có chuyển động, hoặc quanh khung đẹp nhất. Cú máy dài tối đa 3, 4 hoặc 6 giây, tuỳ độ dài đích (đến 20 giây, đến 45 giây, dài hơn).
  - Xếp thứ tự: đoạn nhiều năng lượng nhất lên đầu làm hook (tối đa 3 giây), rồi cảnh thiết lập, rồi các đoạn khác theo thứ tự quay, rồi cảnh kết.
  - Ghi đoạn nào bị bỏ và vì sao. Nếu hình dùng được ít hơn độ dài cần, đề xuất nói rõ.
- **EDL (CMX 3600)** theo timecode gốc của từng file, drop-frame ở 29,97 và 59,94 (`core/timebase.py`), mở được trong Premiere, Resolve và Avid. Không render gì; người dùng hoặc người dựng làm tiếp.

API:
- `GET /api/v1/assets/{id}/story?seconds=30&format=json|md|edl`
- `POST /api/v1/recut {assets, seconds, format}` cho nhiều clip.

Trong thư viện, mục "Kể chuyện và dựng lại" có đường năng lượng, vai trò, chọn độ dài 15/30/60 giây, và nút tải EDL.

Trên 0059:
- Nhịp 1 là mở đầu (năng lượng 0,50: chủ thể chuyển động, có lời), nhịp 2 là kết (0,35).
- Nhận xét: cú máy dài 9 giây, nên cắt còn 2–4 giây cho mạng xã hội.
- Đề xuất 8 giây: hook 0,6–3,6 giây, kết 5,2–8,2 giây, và báo chỉ có 6 giây dùng được.
- EDL: timecode nguồn `01:59:54;09`–`01:59:57;09` và `01:59:58;28`–`02:00:01;28`, drop-frame.

Giới hạn: năng lượng chỉ đọc từ những gì đo được, nên nó không biết ý nghĩa câu chuyện (ai làm gì, vì sao). Đề xuất dựng lại cho clip ngắn ít nhịp (như 0059) gần như chỉ còn chọn và cắt. Cách xếp thứ tự có ích nhất với clip dài hoặc nhiều clip của cùng một buổi quay.

### Kiểm chứng thêm sau khi xong A–G (2026-10-16)

**C. Điểm chấm của bước ghép.** Bộ đo 6 câu, mỗi câu có 3 ứng viên thật trong kho: đúng, vừa đủ (cùng bối cảnh, thiếu ý chính), sai.

| Prompt chấm | Đúng > vừa đủ | Điểm TB: đúng / vừa đủ / sai |
|---|---|---|
| Cũ (chỉ hỏi một con số) | 3/6 | 10 / 6,7 / 0 |
| Mới (nêu chủ thể chính trước, thang có mốc 10/8/6/4/0–2) | 4/6 | 9,7 / 5,3 / 0 |

Hai câu còn hoà là do đáp án chưa chặt: nhịp 1 của 0059 thật ra có cả cửa sổ gỗ và bồn cầu, nhịp 3 của 0038 có sóng vỗ bờ cát. Chạy lại bước ghép thật với kịch bản 7 câu: câu "thuyền thúng xanh nằm trên bãi cát" đổi từ nhịp có rau muống là chủ thể chính (nay 8/10) sang nhịp có hai thuyền nằm ngay trên bờ (10/10). Vẫn đúng 7/7.

**E. Ngưỡng nhận lại chủ thể (0,88) trên vùng cắt thật** (SigLIP 2, cắt như bước `look`):

| Cặp | Cosine |
|---|---|
| Cùng người trong gương ở 0059, giây 2,5 và 3,0 | 0,902, được nối |
| Người ở 0059 với vùng Vision gọi là người ở 0050 (thật ra là cột đèn) | 0,75–0,77 |
| Người với vật (bồn cầu, cửa sổ) | 0,69–0,79 |

Ngưỡng tách được cặp cùng người với mọi cặp khác, nhưng mới có một cặp dương thật và chưa có cặp hai người khác nhau. Kho không có clip nào có hai người, có nhiều shot, hay có người nói trong khung.

**Chưa đo được trên footage thật:** gắn câu nói với người nói (D), nối chủ thể qua điểm cắt trong một clip nhiều shot (E), và kể chuyện cho clip dài (G). Cần một clip có người nói trước máy, quay qua nhiều shot.

**G trên clip dài (0050, vlog đi bộ 144 giây, 17 nhịp).** Lần chạy đầu cho thấy 4 lỗi mà 0059 (2 nhịp) không thể lộ ra:
- hook lấy từ nhịp cuối, nơi có câu chào "ok cảm ơn nhiều";
- vì thế bản dựng không còn cảnh kết;
- điểm cắt rơi vào giữa câu nói;
- danh sách đoạn bị bỏ in mã asset.

Đã sửa:
- Hook là đoạn mạnh nhất trong các nhịp *không phải* nhịp cuối (khi có từ 3 nhịp).
- Nhịp cuối luôn được giữ làm cảnh kết.
- Mọi điểm cắt được đẩy ra khỏi giữa một từ, theo thời gian từng từ của bản phiên âm: lấy trọn từ nếu không quá dài, nếu không thì cắt trước từ đó.

Sau khi sửa, bản 30 giây (thực tế 32,1 giây):
- hook là lúc reo "Ê điện gió" (101,9 giây);
- tiếp theo là cảnh nhà tranh ở đầu clip, rồi các đoạn theo thứ tự quay;
- kết ở quảng trường với câu "ok cảm ơn nhiều";
- không điểm cắt nào nằm trong một từ.

Giới hạn còn lại: bản phiên âm của 0050 có từ kéo dài bất thường (ví dụ "luôn" kéo dài 1,5 giây), nên vài đoạn chỉ còn 1,7 giây sau khi né từ.

**D và E trên footage thật có người nói trước máy (2026-10-16).** Kho không có clip loại này, nên tôi dùng một video phạm vi công cộng: "Nigel Short Interview With VOA Persian" (Wikimedia Commons, 116 giây, 1080p). Video được chạy trong một NEXORA riêng (thư mục dữ liệu ở scratchpad), dùng đúng các mô hình của máy, và không đưa vào thư viện.

Đáp án: một người nói suốt clip, luôn trong khung; có đoạn hoà hình quanh giây 54–64 và thẻ kết từ giây 110,5.

- Hệ thống chia ra 3 shot (cắt ở 64,7 và 110,5), đo người nói "trong khung" ở mọi nhịp có ông, "ngoài khung" ở thẻ kết. Phiên âm tiếng Anh có 20 câu, một giọng.
- **E ✓**: các track người ở shot 0 và shot 1 được nối thành **một chủ thể** (6 track, `across_cut`).
- **D, lần đầu**: cả 20 câu được gán, nhưng bước gom mặt tách một người thành 3 nhóm (198, 21, 1 lần thấy), và 2 câu bị gán cho hai nhóm.
- **Đã sửa:**
  - Một câu chỉ thuộc về một người.
  - Các nhóm mặt mà mỗi nhóm đều được thấy một mình đang nói bằng cùng một giọng trong cùng một file được nối thành một người (`profile.joined_by_voice`).
- **D, sau khi sửa ✓**: một người (219 lần thấy mặt) nói 20/20 câu, không câu nào bị gán hai lần. 19 câu gán theo mặt. Câu còn lại (50,9–55,7 giây) rơi vào lúc lớp hoà hình che mặt, nên được gán theo giọng, đúng người.
- Còn một nhóm 1 mặt lạc, không có câu nào.

**D và E với hai người khác nhau (2026-10-16).** Clip thứ hai: "Trial of Hamid Noury - VOA interview with Kenneth Lewis and Göran Hjalmarsson" (Commons, phạm vi công cộng, 48 giây), chạy trong cùng NEXORA riêng với clip Nigel Short. Như vậy có 3 người, 2 file, 25 câu nói. Hệ thống chia đúng 4 shot: giới thiệu, Lewis (2–12,7 giây), Hjalmarsson (12,7–42,3 giây), thẻ kết.

Lần chạy đầu lộ ra 3 lỗi:
- Bước phân biệt giọng nghe hai người đàn ông thành **một giọng**, nên giọng mang câu của Lewis sang Hjalmarsson.
- Gom mặt xếp mặt Hjalmarsson ở khung đầu sau điểm cắt vào nhóm của Lewis. Dấu vân mặt của Vision không đủ xác định danh tính: Lewis và Hjalmarsson giống nhau 0,88, trong khi hai nhóm của cùng Nigel Short chỉ 0,67.
- Vì vậy track của Lewis bị nối với Hjalmarsson thành một chủ thể.

Đã sửa bằng các ràng buộc cấu trúc, không dùng ngưỡng độ giống mặt:
- Giọng không mang câu sang người g khi lúc đó người nói được đo là trong khung, đang thấy mặt người khác và không thấy mặt g.
- Hai nhóm mặt chỉ được nối nhờ giọng khi cùng có ít nhất 1/4 số lần thấy mặt trong một shot chung, và không bao giờ xuất hiện cùng lúc.
- Một track thuộc về người có mặt xuất hiện nhiều nhất trong nó. Hai track của hai người khác nhau không bao giờ là một chủ thể.
- Khi nhiều mặt cùng xuất hiện, mặt cao gấp từ 2 lần mọi mặt khác được coi là người nói.
- Mảnh câu ngắn được xét trên ít nhất một lần nhìn (0,5 giây).
- Nhóm mặt chỉ thấy một lần, không nói và chưa được đặt tên, bị bỏ như một lần nhận diện lạc.

Kết quả:
- **D:** 24/24 câu được gán đều đúng người (độ chính xác 100%), phủ 24/25 câu (96%): Nigel Short 20/20, Hjalmarsson 3/3, Lewis 1. Câu bỏ trống là một mảnh 0,1 giây.
- **E:** Nigel Short được nối qua điểm cắt; Hjalmarsson là một chủ thể gồm 3 track; Lewis để riêng. Không có lần nối sai nào.

**C với đáp án đã siết.** Các ứng viên "vừa đủ" được thay bằng ứng viên thật sự chỉ vừa đủ: 0034 nhịp 2 cho "nhà mái tranh", 0040 nhịp 2 cho "sóng biển". Kết quả:
- Prompt cũ: đúng > vừa đủ 6/6, vừa đủ > sai 4/6, điểm TB 10 / 3,8 / 0.
- Prompt mới: đúng > vừa đủ 6/6, vừa đủ > sai 3/6, điểm TB 10 / 2,7 / 0.

Các ca hoà trước đây đến từ đáp án lỏng. Prompt mới được giữ vì nó mở rộng khoảng cách giữa "đúng" và "vừa đủ"; đó là điều quyết định một câu là "tốt" hay "tạm".
