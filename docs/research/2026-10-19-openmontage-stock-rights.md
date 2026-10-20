# OpenMontage: cách lấy clip stock và cách xử lý giấy phép

Ngày: 2026-10-19 · Đối tượng: `~/openmontage` (commit `a2652b4`) · Cách làm: đọc mã nguồn, đối chiếu với giấy phép mà các kho trả về thật qua NEXORA.

REA không được dùng ở đây. OpenMontage là một repo mã nguồn Python đầy đủ, và skill REA nói rõ: với repo mã nguồn thì dùng công cụ đọc repo thông thường. REA dành cho binary, gói, app Electron và website.

Quy ước: **[QS]** là quan sát trực tiếp (mã nguồn hoặc dữ liệu thật); **[SR]** là suy ra; **[?]** là chưa biết.

## 1. Câu hỏi

| # | Câu hỏi | Trạng thái |
|---|---|---|
| 1 | OpenMontage tìm và chọn clip thế nào? | Đã trả lời |
| 2 | Nó xếp hạng bằng thuật toán gì? | Đã trả lời |
| 3 | Nó ghi và kiểm soát giấy phép ra sao? | Đã trả lời |
| 4 | Giấy phép thật mà các kho trả về trông thế nào? | Đã trả lời (mẫu nhỏ, xem mục 5) |
| 5 | Có cơ chế ghi công hay chống Content ID không? | Đã trả lời, phạm vi tìm có giới hạn |

## 2. Hai cách lấy clip

**Cách nhanh, `tools/video/direct_clip_search.py`** [QS]
1. Tìm trên mọi kho đang dùng được (`available_sources()`).
2. Tải tối đa `clips_per_query` clip cho mỗi từ khoá và cắt 1 ảnh xem trước.
3. Không có mô hình, không có embedding, không xếp hạng.

Mô tả trong code ghi rõ cách này dành cho trường hợp người hoặc agent tự xem ảnh xem trước.

**Cách chuẩn, `corpus_builder` → `clip_search`** [QS]

1. Với mỗi từ khoá và mỗi kho, `search()` trả về `Candidate`. Mỗi candidate có `source`, `source_id`, `source_url`, `download_url`, `license`, `creator`, `source_tags` và `thumbnail_url`.
2. Clip đã có trong corpus thì bỏ qua (`skip_existing`). Corpus chỉ ghi thêm, không xoá. Có giới hạn `max_new_clips`.
3. Tải file, cắt N khung hình đều nhau, đo kích thước và thời lượng thật.
4. Tính **motion score** từ chênh lệch tuyệt đối trung bình giữa khung đầu và khung giữa (`lib/corpus.py:65`).
5. Đưa các khung vào **CLIP `openai/clip-vit-base-patch32`** (`lib/clip_embedder.py:38`) và gộp thành một vector hình 512 chiều. `source_tags` (nếu không có thì dùng từ khoá) được đưa vào CLIP để thành vector tag.
6. Lưu một `ClipRecord` đầy đủ nguồn gốc vào corpus.

## 3. Thuật toán xếp hạng [QS]

- **Điểm trộn** (`lib/corpus.py:234-245`): `score = (1 − w) · cos(query, hình) + w · cos(query, tag)`, với `w = 0.3` mặc định. Tức là 70% dựa vào hình, 30% dựa vào chữ.
- **Lọc chuyển động**: clip có `motion_score < motion_min` bị loại.
- **Bộ clip cùng chủ đề** (`find_similar_set`, MMR): `(1 − λ) · sim(c, mẫu) − λ · max sim(c, đã chọn)`, với `λ = diversity`.
- **`diversify`**: giữ lại các clip khác nhau nhiều nhất, để hai cảnh liền nhau không quá giống.
- Hướng dẫn cho agent (`skills/pipelines/documentary-montage/asset-director.md:465-468`): xếp hạng theo *mô tả cảnh*, không theo từ khoá tìm kiếm.

## 4. Giấy phép: chỉ ghi lại, không lọc

**Tầng 1: chỉ nối với kho có giấy phép mở** [QS]. Mỗi adapter gán một chuỗi giấy phép:

| Kho | Giấy phép gán | Cách lấy |
|---|---|---|
| Pexels, Pixabay, Coverr, Mixkit | Giấy phép riêng của kho, không cần ghi công | chuỗi cố định |
| Pond5 PD, NARA, NOAA | Phạm vi công cộng | chuỗi cố định |
| NASA | Phạm vi công cộng, có ghi chú ngoại lệ | chuỗi cố định |
| Videvo, Dareful | CC BY (phải ghi công) | chuỗi cố định; Videvo chỉ lấy `license_type=free` |
| ESA | CC BY-SA 3.0 IGO | chuỗi cố định |
| JAXA | "educational/informational use, verify per item" | chuỗi cố định |
| Wikimedia | `LicenseShortName` thật của từng file | đọc từ `extmetadata` (`wikimedia.py:228-252`) |
| Archive.org | `licenseurl` của item; nếu không có thì đoán theo bộ sưu tập | `archive_org.py:388-401, 538-549` |

Archive.org mặc định tìm trong ba bộ sưu tập `prelinger`, `opensource_movies` và `home_movies` (`archive_org.py:51`). Khi item không có `licenseurl`:
- Prelinger được coi là phạm vi công cộng;
- home movies cũng được coi là phạm vi công cộng;
- mọi item còn lại nhận chuỗi **"Public Domain / CC (archive.org — verify per item)"**.

**Tầng 2: ghi nguồn gốc (provenance)** [QS]. Đây là quy tắc "không được thương lượng" (`asset-director.md:470-472`): mỗi clip trong manifest phải có `provider`, `original_url` và `license` để khâu đăng dùng.

**Những gì không có**, trong phạm vi đã tìm là `tools/` và `lib/` [QS]:
- Không có nhánh code nào lọc theo giấy phép: không loại NC (phi thương mại), ND (không phái sinh), SA (share-alike) hay "verify". Lệnh `grep` theo các mẫu `if … licen`, `noncommercial` và `nc-` không trả về gì.
- Không thấy bộ sinh dòng ghi công.
- Không có gì liên quan tới Content ID.

[SR] Tính hợp pháp phụ thuộc vào việc chọn kho và vào người hoặc agent đọc manifest trước khi đăng.

## 5. Giấy phép thật, quan sát qua NEXORA [QS]

**12 ứng viên cho SC1** (video miền Tây, hôm nay, tìm qua OpenMontage):
- Hai ứng viên được chấm cao nhất (10/10 và 8/10) đều là **CC BY-SA 3.0**: phải ghi công, và theo cách hiểu thông thường thì bản phái sinh cũng phải cùng giấy phép.
- 4 ứng viên Archive.org đều mang chuỗi "verify per item". Trong đó có `abcdefu-viet-hoa`, theo tên thì là một **bản cover bài hát có bản quyền** [SR], và các item `dhamma-in-photo-*` do người dùng tự tải lên.

**33 clip stock đã tải về NEXORA trước đây**, đếm theo giấy phép ghi trong `rights`:

| Số clip | Giấy phép | Đánh giá cho kênh YouTube có kiếm tiền [SR] |
|---|---|---|
| 24 | Archive.org "verify per item" (item không có `licenseurl`) | **Chưa rõ**: không có bằng chứng giấy phép |
| 2 | CC BY-SA 4.0 | Phải ghi công; share-alike là rủi ro |
| 1 | CC BY-NC-ND 4.0 | **Không được dùng** (phi thương mại, không phái sinh) |
| 1 | CC BY-NC-SA 3.0 | **Không được dùng** (phi thương mại) |
| 3 | Public Domain Mark / CC0 | An toàn |
| 1 | CC BY 3.0 (Wikimedia) | Được dùng nếu ghi công |
| 1 | CC BY-SA 4.0 (đã tính ở trên) | — |

Chỉ khoảng **4 trên 33** clip có giấy phép thật sự an toàn để đăng. **2 clip mang giấy phép cấm dùng thương mại.** Clip "bản tin tiền mã hoá" trước đây ở SC1 nằm trong nhóm 24 clip "verify per item".

## 6. Điều chưa biết [?]

- Giấy phép thật của các item Archive.org không có `licenseurl`. Phải mở trang của từng item mới biết; OpenMontage không làm việc này.
- Một clip phạm vi công cộng (NASA, Prelinger) có bị người khác đăng ký Content ID sai hay không. Không thể biết trước từ dữ liệu của kho.
- Mẫu chỉ gồm một video và một lần tìm, toàn bộ qua 3 kho không cần key. Chưa quan sát Pexels hay Pixabay.

## 7. Bài học cho NEXORA

1. **Phân loại giấy phép ngay khi tìm**, thành các nhóm `tự do` / `cần ghi công` / `share-alike` / `phi thương mại · không phái sinh` / `chưa rõ`.
   - Loại hẳn nhóm phi thương mại và không phái sinh.
   - Không tự tải nhóm `chưa rõ`.
2. **Thu hẹp Archive.org** về Prelinger và home movies, hoặc chỉ nhận item có `licenseurl` là PD/CC0/CC BY. Bỏ JAXA.
3. **Cổng bản quyền lúc đăng** (`modules/quality/rights.py`) hiện chỉ kiểm tra *có* chuỗi giấy phép. Nó cần dùng cùng cách phân loại ở mục 1:
   - `chưa rõ`, `share-alike` và `phi thương mại` thì chặn, trừ khi người vận hành ghi lý do;
   - `cần ghi công` thì bắt buộc có dòng ghi công (dòng này đã được tự sinh).
4. **Lưu bằng chứng** khi tải: URL trang, giấy phép đọc được, ngày tải và mã băm file, để kháng nghị khi bị claim sai.
5. **Ưu tiên Pexels và Pixabay** khi đã có key: giấy phép rõ, được dùng thương mại, không cần ghi công.
