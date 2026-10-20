# Stock theo ảnh xem trước: chấm trước, tải sau

Ngày: 2026-10-19 · Trạng thái: chờ duyệt

## Vấn đề

Video "Nhịp sống dân dã miền Tây" là lần đầu lấp mọi chỗ thiếu hình bằng stock. Hệ thống tải về khoảng 60 clip, kéo theo hơn 200 bước phân tích. Nhiều clip lạc đề: SC1 là một bản tin về tiền mã hoá đặt cho câu "mặt sông lúc rạng sáng", SC3 là một tấm bia đá. Máy nghẽn, và web đơ tới mức người vận hành phải dừng mọi thứ.

Nguyên nhân nằm ở đường đi hiện tại (`fill_gap_from_stock`, `storyboard_stock` trong `app.py`; bước `gaps` trong `agents/producer.py`):

1. Mỗi câu có đúng một cụm 2–5 từ tiếng Anh (`QUERY_PROMPT`), và cụm này không có phương án dự phòng.
2. `direct_clip_search` của OpenMontage chỉ tìm trên ba kho không cần key: archive_org, nasa và wikimedia. Nó **tải clip đầu tiên** (`clips_per_query=1`) mà không xếp hạng gì.
3. Clip được `library.ingest` nhập vào Thư viện với origin `licensed`, rồi chạy đủ các bước nghe lời nói, tìm chỗ chuyển cảnh, chia cú máy, hồ sơ hình/tiếng và hiểu nội dung. Chỉ sau tất cả các bước đó, clip mới được xem có đúng câu không, và bị rút lại nếu sai.

Bản thân OpenMontage nói rõ `direct_clip_search` là để dùng khi "bạn tự xem ảnh xem trước, hoặc giao cho một agent xem". NEXORA bỏ qua bước xem đó. Đường nặng của OpenMontage (`corpus_builder` → `clip_search`) có xếp hạng CLIP và chống trùng, nhưng vẫn tải hết rồi mới xếp.

## Mục tiêu

- Clip chỉ được tải khi đã được chấm là đúng câu. Ứng viên không bao giờ được tải chỉ để thử.
- Người vận hành xem được từng ứng viên ngay trong NEXORA, phát trực tiếp từ nguồn mà không tải về.
- Clip stock đã chọn nằm trong Thư viện như mọi footage khác, nhưng không kéo theo chuỗi phân tích nặng.
- Sau khi storyboard được duyệt, những gì chỉ phục vụ việc lựa chọn sẽ được dọn đi.
- Tìm được nhiều ứng viên đúng hơn: tìm song ngữ theo từng nguồn, có từ khoá dự phòng, và dùng thêm Pexels/Pixabay khi đã có key.

Ngoài phạm vi: tìm video trên YouTube/Vimeo, cắt một đoạn trong clip dài trước khi tải, sinh hình bằng AI, và đổi cách chọn clip từ footage của chính người vận hành.

## Thiết kế

### 1. Tìm ứng viên mà không tải

Mỗi ứng viên là một `Candidate` đã chuẩn hoá. Nó có `download_url`, `thumbnail_url`, `source_url`, `width`, `height`, `duration`, `license`, `creator` và `source_tags`. Bộ tìm của mọi nguồn trong OpenMontage (`stock_sources/*.search`) trả về các trường này **trước khi tải**.

`OpenMontageStock` có thêm thao tác `candidates`. Thao tác này gọi `search()` của từng nguồn trong tiến trình riêng như hiện nay, rồi trả về danh sách ứng viên mà không tải file nào. Thao tác `search` cũ vẫn giữ, để tương thích.

**Tìm song ngữ theo nguồn.** Một lớp mỏng mới, `adapters/stock_api.py`, gọi trực tiếp API của Pexels và Pixabay, vì chỉ hai API này nhận tham số ngôn ngữ (`locale=vi-VN` cho Pexels, `lang=vi` cho Pixabay). OpenMontage không truyền hai tham số này. Lớp mới chỉ chạy khi có key (`pexels_api_key`, `pixabay_api_key`) và trả về cùng dạng `Candidate`. Ba nguồn kia vẫn đi qua OpenMontage.

| Nguồn | Từ khoá gửi đi |
|---|---|
| Pexels, Pixabay | tiếng Việt (kèm locale/lang) và tiếng Anh |
| Wikimedia | tên riêng tiếng Việt và từ khoá tiếng Anh |
| Archive.org, NASA | tiếng Anh |

**Từ khoá.** `QUERY_PROMPT` được thay bằng một lời nhắc trả về JSON `{"en": [...], "vi": [...], "names": [...]}`. Trong đó `en` có 2–3 cụm tiếng Anh, đi từ cụ thể tới chung. `vi` có 1–2 cụm tiếng Việt. `names` là tên riêng, giữ nguyên dấu.

Lượt tìm đầu dùng cụm cụ thể nhất. Nếu sau khi chấm không có ứng viên nào đạt, hệ thống thử cụm tiếp theo, tối đa 3 lượt mỗi câu.

Ứng viên được gộp và khử trùng theo `source:source_id`. Mỗi câu giữ tối đa 12 ứng viên. Clip quá ngắn so với độ dài của shot thì bị loại, nếu nguồn có cho biết `duration`.

### 2. Chấm theo ảnh xem trước

Hệ thống chỉ tải `thumbnail_url`, mỗi ảnh vài KB, vào `data/tmp/stock/<project_id>/<shot_id>/`. Việc chấm có hai tầng:

1. **SigLIP** (adapter `picture_text` đã có) đo độ giống giữa ảnh và câu. Câu dùng để đo là cụm tiếng Anh cụ thể nhất cộng `source_tags`. Tầng này lọc nhanh, nên rẻ cho cả 12 ứng viên.
2. **Mô hình nhìn** (`judge_model`, mặc định Qwen3-VL) xem kỹ 3 ảnh đứng đầu so với câu lời dẫn. Điểm 0–10 kèm một câu lý do, cùng cách chấm mà `Director.look` đang dùng (`LOOK_PASS = 5`).

Mỗi ứng viên giữ lại điểm SigLIP, điểm mô hình nhìn (nếu đã chấm) và lý do. Một ứng viên **đạt** khi điểm mô hình nhìn ≥ `LOOK_PASS`.

Tầng 2 cần ollama. Khi không có mô hình nhìn, chỉ còn điểm SigLIP. Lúc đó không có ứng viên nào được coi là đạt để tự tải; tất cả chỉ được đề xuất.

### 3. Hai chế độ: tự chọn, hoặc để người vận hành chọn

Chế độ được chọn bằng một công tắc mới trong `auto_approve` (System → Mức tự chủ → Tự duyệt): **"Tự tải clip stock tốt nhất"**. Công tắc này mặc định **tắt**. Như mọi công tắc Tự duyệt, chỉ người vận hành được bật hoặc tắt nó.

- **Tắt (để tôi chọn):** không tải gì. Shot nhận các ứng viên đã chấm làm phương án, và nằm ở trạng thái chờ người vận hành.
- **Bật (tự chọn):** ứng viên đạt có điểm cao nhất được tải và gán cho shot. Các ứng viên còn lại vẫn là phương án. Nếu không ứng viên nào đạt, hệ thống không tải gì.

Nút "Tìm clip stock" trên Storyboard luôn chạy theo chế độ "để tôi chọn": nó hiện ứng viên ngay, không tải.

### 4. Xem trực tiếp từ nguồn

Ứng viên stock hiện trong mục "Phương án khác" của tab Hình, cạnh các phương án từ Thư viện. Mỗi ứng viên được đánh dấu bằng `kind: "stock_candidate"`, và không có `asset_id`. Mỗi ô gồm:

- ảnh xem trước, lấy từ `data/tmp/stock/...` qua một endpoint của NEXORA;
- **phát khi rê chuột hoặc bấm**: một thẻ `<video>` trỏ thẳng tới link xem trước của nguồn. Pexels và Pixabay có bản SD trong `extra`; với các nguồn khác thì dùng `download_url`. Trình duyệt lấy video trực tiếp từ nguồn, NEXORA không lưu gì. Nếu trình duyệt không phát được định dạng đó (`.webm`/`.ogv` trên Safari), ô chỉ hiện ảnh;
- nguồn, giấy phép, thời lượng, điểm và lý do chấm;
- **"Dùng cho shot"**: lúc này NEXORA mới tải bản tốt nhất, nhập vào Thư viện (mục 5) và gán cho shot;
- **"Mở trang gốc"**, mở `source_url` trong tab mới.

Một endpoint mới làm việc này: `POST /storyboard/shots/{id}/use-stock {candidate}`. Director thêm `use_stock_candidate`. Hàm này tải, nhập, rồi gọi `use_asset`. Ứng viên đó được ghi nhớ là `accepted` cho câu.

Ảnh xem trước của nguồn không được dùng làm hình của shot. Hình chỉ có sau khi đã tải.

### 5. Clip stock trong Thư viện: nhãn và phân tích nhẹ

Clip đã tải vào Thư viện với `origin = "licensed"`. Phần `rights` mang `source`, `source_url`, `license`, `creator`, `query`, `stock_id` và điểm chấm. Thư viện có thêm bộ lọc **"Stock"** (origin licensed), và thẻ của clip hiện nhãn nhỏ "Stock".

**Phân tích nhẹ.** Với asset `licensed`, các luồng theo sau việc nhập chỉ chạy những gì cần cho tìm kiếm và dựng:

- `library.ingest`: checksum, proxy, ảnh xem trước, đo `usable`;
- `library.understand`: mô tả hình để tìm được trong Thư viện.

Các luồng `library.transcribe`, `library.cuts`, `library.structure` và `library.profile` không tự chạy cho clip stock. Người vận hành vẫn có thể chạy tay từng clip.

Nơi áp quy tắc này là chỗ các luồng đó được gửi cho một asset mới. Khi lập kế hoạch, sẽ xác định từng chỗ gửi trong `intelligence/service.py` và `library/ingest.py`.

Clip stock vẫn tìm được trong Thư viện, nên dùng lại được cho các video sau.

### 6. Dọn dẹp sau khi duyệt storyboard

Khi `Director.approve(project_id)` thành công:

1. Xoá thư mục `data/tmp/stock/<project_id>/`, nơi chứa ảnh xem trước của ứng viên. Bỏ các ứng viên `stock_candidate` khỏi phương án của các shot. Việc này an toàn vì chưa ứng viên nào được tải.
2. Clip `licensed` được tải cho dự án này (`rights.project_id`) mà **không được dùng trong storyboard vừa duyệt** sẽ được chuyển vào **Thùng rác** bằng `trash_items`, và khôi phục được trong 30 ngày. Clip đang được dùng ở dự án khác hoặc được đánh dấu yêu thích thì giữ nguyên.

Một sự kiện ghi số ảnh xem trước đã xoá và số clip đã chuyển vào Thùng rác. Một thông báo báo kết quả cho người vận hành.

### 7. Không chọn trùng

Khi chọn tự động, ứng viên đã là hình của shot liền trước hoặc liền sau thì bị đẩy xuống. Cụ thể, điểm SigLIP giữa hai ảnh xem trước so với ngưỡng trùng, khoảng 0,92; ứng viên cùng `source_id` thì bị loại hẳn. Khi người vận hành tự chọn, hệ thống không chặn.

## Luồng dữ liệu

```
câu lời dẫn
  → từ khoá {en, vi, names}
  → ứng viên (OpenMontage candidates + Pexels/Pixabay API), chưa tải gì
  → ảnh xem trước → SigLIP (12) → mô hình nhìn (3) → điểm + lý do
  → [Tự chọn bật và có ứng viên đạt] tải bản tốt nhất → Thư viện (licensed, nhẹ) → hình của shot
  → [còn lại] các ứng viên hiện trong "Phương án khác": xem trực tiếp, "Dùng cho shot" thì tải
  → duyệt storyboard → xoá ảnh tạm; clip stock không dùng vào Thùng rác
```

## Lỗi và giới hạn

- Một nguồn lỗi hoặc hết hạn mức không làm hỏng cả lượt tìm. Lỗi được ghi theo nguồn, các nguồn khác vẫn trả về ứng viên.
- Ảnh xem trước không tải được: ứng viên giữ điểm SigLIP 0 và không được tự chọn.
- Mô hình nhìn không chạy được: không tự tải. Ứng viên vẫn được đề xuất theo SigLIP, với nhãn "chưa chấm kỹ".
- Tải bản tốt nhất thất bại khi bấm "Dùng cho shot": shot giữ nguyên, báo lỗi, và ứng viên vẫn còn để thử lại.
- Dừng khẩn cấp đang bật: không tìm và không tải. Việc tìm stock gửi từ khoá ra ngoài, nên bị tính là việc có tác động ra ngoài.
- Từ khoá rời máy giống như hiện nay. Ảnh xem trước và video xem trực tiếp được tải từ nguồn về máy và trình duyệt của người vận hành.

## Kiểm thử

- **Ứng viên:** nguồn được giả lập (fake) trả về `Candidate` thì không có file nào được tải. Từ khoá song ngữ được gửi tới đúng nguồn. Pexels nhận `locale=vi-VN`, Pixabay nhận `lang=vi`.
- **Chấm:** dùng SigLIP và mô hình nhìn giả. Thứ tự đúng, ngưỡng đạt đúng. Khi không có mô hình nhìn thì không tự tải.
- **Hai chế độ:**
  - Công tắc tắt: không tải gì, shot có các ứng viên.
  - Công tắc bật: chỉ tải ứng viên đạt cao nhất.
  - Không ứng viên nào đạt: không tải.
  - Từ khoá dự phòng được thử khi lượt đầu không có ứng viên đạt.
- **Dùng ứng viên:** endpoint `use-stock` tải, nhập `licensed` kèm rights, gán cho shot, và ghi nhớ `accepted`.
- **Phân tích nhẹ:** nhập một clip `licensed` thì không tạo các run transcribe, cuts, structure hay profile, nhưng vẫn có ingest và understand.
- **Dọn dẹp:** sau khi duyệt, thư mục tạm của dự án biến mất. Clip stock không dùng vào Thùng rác. Clip đang dùng ở dự án khác hoặc được đánh dấu yêu thích thì giữ.
- **Không trùng:** hai shot liền nhau không tự chọn cùng một clip.
- **Giao diện:** typecheck và build. Kiểm tra trên trang thật rằng ô ứng viên phát video trực tiếp và nút "Dùng cho shot" hoạt động.

## Những gì giữ nguyên

- Nút "Bỏ clip", ô "Tìm trong Thư viện" và việc ghi nhớ đánh giá của người vận hành theo câu.
- Cách chọn clip từ footage của chính người vận hành (`sourcing.match`).
- `stock_sources`, setting chọn nguồn của người vận hành, vẫn áp dụng cho cả hai đường tìm.
