# Hồ sơ footage: đủ 16 nhóm thông tin, có bảo đảm độ chính xác

Bản thiết kế, 2026-10-14; trạng thái triển khai ở mục 14. Bổ sung cho `2026-10-13-footage-understanding-design.md` (gọi tắt là **thiết kế 10-13**); số mục dạng "10-13 §5" trỏ về bản đó. Phần nào của thiết kế 10-13 không bị nhắc lại ở đây thì vẫn giữ nguyên.

## 1. Mục đích

Người vận hành đặt ra 16 nhóm thông tin mà hệ thống phải nhận diện được trên một footage (danh sách ở mục 5). Ngày 2026-10-14, đối chiếu với code và dữ liệu thật cho thấy: có khá đủ 3 nhóm (01, 14, 16), có một phần 6 nhóm, sơ sài 5 nhóm, chưa có 2 nhóm (12, 13). Thiết kế 10-13 phủ các nhóm 03, 04, 06, 07, 08 một phần; các nhóm 05, 09, 10, 11, 12, 13 và phần lớn 02, 15 chưa nằm trong đợt nào.

Bản này làm ba việc:

1. Đặt mỗi trường của 16 nhóm vào một nguồn bằng chứng cụ thể, với cách kiểm chứng.
2. Đặt cơ chế bảo đảm độ chính xác chung: bộ mẫu do người vận hành gán, cổng phát hành theo từng trường, độ tin cậy được hiệu chỉnh theo số đo.
3. Đề xuất những phần tôi cho là làm hệ thống tốt hơn hẳn (mục 4 và 7), dựa trên những gì đã thử được trên chính máy này.

**Đích của mọi trường là chọn đúng nguyên liệu.** Thứ tự xây (mục 10) xếp theo mức một trường giúp khâu khớp kịch bản chọn đúng đoạn, không theo số thứ tự nhóm.

## 2. Hiện trạng đo được ngày 2026-10-14

Trên clip DJI `0050` (Osmo Action 6, 4K HEVC 10 bit, 144 giây, có lời nói):

| Quan sát | Hệ quả |
|---|---|
| Bảy nhịp liền nhau được tả gần như cùng một câu ("con đường, nhà mái lá, cây cỏ, ánh nắng, khu nghỉ dưỡng") | Khớp kịch bản không phân biệt được các nhịp; chọn gần như ngẫu nhiên trong số đó |
| Khung toàn cảnh một lối đi được mô hình ghi cỡ cảnh là "cận" | Nhãn do mô hình đoán, không có số đo kiểm chéo, sai mà không ai biết |
| Mô tả lẫn tiếng Anh ("countryside"), một vật có bốn cách gọi (cây, cây cỏ, cây cối, cây xanh) | Tìm theo từ khoá và theo nghĩa kém đi |
| Bản chép lời có câu vô nghĩa và câu lặp ("trăng bí bên này" hai lần) | Nguồn nghĩa mạnh nhất của clip có thoại bị nhiễu |
| Ô hành động thường rỗng | Không biết hành động bắt đầu, kết thúc ở đâu |

## 3. Nguyên tắc

Giữ mọi nguyên tắc của 10-13 §1, thêm:

- **Ba bậc nguồn, lấy từ bậc chắc nhất có thể.** *Đo* (FFmpeg, numpy, dữ liệu cảm biến của máy quay), *nhận diện chuyên dụng* (Apple Vision, SoundAnalysis, whisper: mỗi công cụ làm một việc hẹp, có độ tin cậy riêng), *mô hình nhìn và ngôn ngữ* (chỉ cho những gì hai bậc trên không làm được). Một trường có thể đo được thì không hỏi mô hình.
- **Tách quan sát khỏi suy luận.** Mỗi trường thuộc một trong ba hạng: `observed` (thấy hoặc đo được), `recognized` (công cụ nhận diện), `inferred` (suy luận: thông điệp, khán giả, cảm xúc, nhân quả). Trường `inferred` được hiển thị và tìm được, nhưng không bao giờ là bộ lọc cứng và không bao giờ loại một ứng viên khỏi khâu khớp kịch bản.
- **Mỗi giá trị có bằng chứng.** Giá trị kèm khoảng thời gian hoặc khung hình đã sinh ra nó, công cụ và phiên bản, và độ tin cậy. Không có bằng chứng thì không lưu.
- **Một trường chỉ được dùng khi đã qua cổng.** Trường mới được tính và hiển thị ngay, nhưng chỉ được khâu khớp kịch bản và tìm kiếm dùng khi độ chính xác của nó trên bộ mẫu đạt ngưỡng phát hành (mục 8).
- **Hai nguồn độc lập cho mỗi trường quan trọng.** Cỡ cảnh, số người, chuyển động máy, có lời nói, người nói trong khung: mỗi trường có ít nhất một nguồn đo hoặc nhận diện để đối chiếu với lời mô hình.
- **Chạy trong máy là mặc định.** Mọi công cụ mới ở mục 4 chạy trong máy, miễn phí, không gửi dữ liệu đi. Quy tắc riêng tư của 10-13 §19 giữ nguyên.

## 4. Nguồn bằng chứng mới

Đều đã được thử ngày 2026-10-14 trên máy này (Mac mini M4, 24 GB, macOS 27, Swift 6.4, FFmpeg 9.0.2).

### 4.1 Apple Vision, qua một adapter `vision`

Một chương trình Swift nhỏ, biên dịch khi cài đặt, nhận danh sách khung và các yêu cầu, trả JSON. Adapter Python gọi nó như gọi FFmpeg. Không có Swift (máy khác) thì adapter báo không sẵn sàng và các trường của nó mang trạng thái "chưa đo"; không gì khác bị hỏng.

| Yêu cầu của Vision | Cho trường | Thử trên máy này |
|---|---|---|
| Đọc chữ, chế độ chính xác, tiếng Việt và tiếng Anh | Chữ trên hình (nhóm 10) | Khung resort có chèn chữ: đọc đúng từng dấu "Khu nghỉ dưỡng Mũi Né - giảm 30% tháng Mười" và "DJI" ở góc |
| Phân loại hình (1.303 nhãn, có độ tin cậy) | Nơi chốn, vật thể, cảnh vật (nhóm 02, 06) | Khung resort: ngoài trời 0,93, bầu trời 0,93, cây 0,50, lối đi 0,49. Đúng |
| Khung chữ nhật người, khuôn mặt, chất lượng khuôn mặt | Số người, cỡ cảnh khi có người (nhóm 04, 06) | Khung không người: 0 mặt, 0 người. Đúng |
| Tư thế cơ thể (khớp xương), điểm mốc khuôn mặt (môi) | Tư thế, hành động, người đang nói trong khung (nhóm 06, 07, 08) | Có sẵn, chưa thử trên footage có người |
| Đường chân trời (góc nghiêng) | Góc máy nghiêng, bố cục (nhóm 04, 05) | Có sẵn |
| Vùng nổi bật theo chú ý | Vị trí chủ thể, khoảng trống (nhóm 05) | Khung resort: một vùng 0,90 × 0,54, tức không có chủ thể đơn lẻ, khớp với cảnh toàn |
| Điểm thẩm mỹ, ảnh "tiện ích" (chụp giấy tờ, màn hình) | Chất lượng thẩm mỹ (nhóm 14, tách khỏi lỗi kỹ thuật) | Khung resort: -0,07 |
| Dấu vân hình ảnh (vector đặc trưng) | Tìm hình giống hình, cùng nơi chốn, trùng lặp (nhóm 03, 15) | Có sẵn |
| Bám đối tượng qua các khung | Theo dõi một người, một vật (nhóm 06) | Có sẵn |

### 4.2 SoundAnalysis, qua một adapter `sound`

Bộ phân loại có sẵn của Apple, 303 loại âm thanh (lời nói, cười, hét, thì thầm, nhạc, chim, gió, nước, xe cộ, đám đông…), mỗi cửa sổ vài giây một kết quả có độ tin cậy.

Thử trên clip `0050` (cửa sổ 3 giây): lời nói 31/57 cửa sổ, khớp với 119 giây lời nói whisper đếm được; chim 7 cửa sổ, hợp với khu nghỉ ngoài trời; nhưng "báo khói" 9 cửa sổ, nhiều khả năng là nhầm. Bài học được đưa vào thiết kế: mỗi loại âm có ngưỡng riêng, phải xuất hiện ở hai cửa sổ liền nhau, và chỉ khoảng 40 loại được gom về danh sách tiếng Việt (mục 5, nhóm 09) mới được dùng; các loại còn lại được lưu nhưng không dùng.

### 4.3 FFmpeg: các bộ lọc đo có sẵn, chưa dùng

Có trong bản FFmpeg đang cài: `ebur128` (độ lớn theo chuẩn, đỉnh thật), `astats` (đỉnh, nền ồn, số mẫu bị cắt), `silencedetect`, `aspectralstats` (phổ, dùng để nhận ra tiếng gió), `signalstats` (độ sáng, độ bão hoà, sắc độ), `cropdetect`, `idet` (video xen kẽ dòng), `blockdetect` (vỡ khối do nén), `siti` (độ phức tạp không gian và thời gian), `scdet`.

### 4.4 Giải mã bằng phần cứng

Giải mã 30 giây clip 4K HEVC 10 bit của Osmo Action 6 để lấy khung thu nhỏ: **31,4 giây bằng CPU, 5,8 giây với `-hwaccel videotoolbox`**. Clip 8 phút từng mất khoảng 25 phút để nhập (`PLAN.md`), phần lớn là giải mã. Lượt giải mã của 10-13 §3, việc tìm đoạn đen và việc tạo proxy chuyển sang giải mã phần cứng, có đường lùi về CPU khi phần cứng từ chối file. Nhờ đó việc chạy thêm các nguồn bằng chứng ở bản này không làm việc nhập chậm hơn hiện nay.

### 4.5 Dữ liệu cảm biến của máy quay (đề xuất, cần kiểm chứng)

File của Osmo Action 6 có luồng `CAM meta`: 4.309 bản ghi cho 4.309 khung (protobuf của DJI). Nhiều dòng máy DJI, GoPro và điện thoại ghi con quay hồi chuyển, gia tốc, hướng máy, ISO, tốc độ màn trập và hồ sơ màu theo từng khung. Nếu giải được, đây là **sự thật** về chuyển động máy, độ rung, góc ngẩng cúi và độ nghiêng, tốt hơn mọi ước lượng từ hình. Thư viện mã nguồn mở `telemetry-parser` (của Gyroflow, MIT hoặc Apache-2.0) đọc được nhiều định dạng này.

Đề xuất: một bước thử nghiệm riêng ở đợt 2 xác định luồng này giải được tới đâu. Nếu được, nó thành nguồn `measured` cho chuyển động máy và góc máy, và ước lượng từ hình chuyển thành nguồn kiểm chéo. Nếu không, không phần nào của thiết kế phụ thuộc vào nó.

### 4.6 Mô hình mạnh hơn, chọn bằng số đo

`qwen2.5vl:7b` là trần chất lượng hiện nay. Đợt 2 dựng bộ mẫu (mục 8), sau đó mỗi ứng viên được chạy trên cùng bộ mẫu: một mô hình nhìn mới hơn vừa 24 GB RAM, `claude` qua adapter đã có (khi tài khoản có tín dụng, và chỉ cho file người vận hành cho phép). Bộ định tuyến mô hình đã có chọn mô hình **theo từng trường** dựa trên số đo. Ví dụ: mô hình nhỏ cho mô tả thường, mô hình mạnh cho cỡ cảnh khi không có người, hoặc cho bước chấm ứng viên cuối. Code không biết tên mô hình (10-13 §1).

## 5. Mười sáu nhóm thông tin

Ký hiệu cột Nguồn: **Đ** đo, **N** nhận diện chuyên dụng, **M** mô hình nhìn và ngôn ngữ, **H** người vận hành. Cột Cấp: tài sản (file), phân cảnh, cú máy, nhịp, khoảnh (một khoảng thời gian bất kỳ, như một dòng chữ hay một âm thanh), từ. Cột Đợt trỏ tới mục 10.

### Nhóm 01. Định danh và thông số kỹ thuật

| Trường | Cấp | Nguồn | Hiện có | Đợt |
|---|---|---|---|---|
| Tên hiển thị, buổi quay, nguồn gốc, ngày nhập, checksum, kích thước, các phiên bản file | tài sản | Đ, H | có | — |
| Thời lượng, độ phân giải, tốc độ khung, codec, có tiếng | tài sản | Đ | có | — |
| Container, bitrate tổng và từng luồng, profile, độ sâu màu, định dạng điểm ảnh | tài sản | Đ | — | 2 |
| Không gian màu, primaries, transfer, dải màu; HDR (PQ, HLG); hồ sơ log (mục nhóm 05) | tài sản | Đ | một phần | 2 |
| Xoay của điện thoại, tỷ lệ điểm ảnh, tỷ lệ hiển thị thật | tài sản | Đ | — | 2 |
| Tốc độ khung thay đổi (so `r_frame_rate`, `avg_frame_rate` và khoảng cách mốc thời gian thật) | tài sản | Đ | — | 2 |
| Xen kẽ dòng (`idet`) | tài sản | Đ | — | 2 |
| Từng luồng âm thanh: codec, số kênh, bố cục kênh, tần số mẫu, thẻ ngôn ngữ | tài sản | Đ | — | 2 |
| Timecode, hãng và đời máy (`encoder`, thẻ của hãng), GPS nếu có | tài sản | Đ | — | 2 |
| Ngôn ngữ của nội dung (whisper nhận diện, kèm độ tin cậy), khác thẻ ngôn ngữ của container | tài sản | N | — | 4 |
| URL nguồn và giấy phép của clip tải về | tài sản | H | có cho stock | — |

**Kiểm chứng.** Mọi trường là số đo. Kiểm thử bằng file tổng hợp cho từng biến thể (xoay 90°, tốc độ khung thay đổi, xen kẽ dòng, nhiều luồng âm thanh, HDR). Khi khai báo của container mâu thuẫn với số đo (khai 29,97 khung mỗi giây nhưng mốc thời gian không đều), số đo thắng và nhịp mang cờ. GPS là dữ liệu riêng tư: chỉ lưu trong máy, không đưa vào gói xuất bản.

### Nhóm 02. Tóm tắt và phân loại nội dung

| Trường | Cấp | Nguồn | Hạng | Đợt |
|---|---|---|---|---|
| Tóm tắt một dòng và một đoạn | tài sản, phân cảnh | M | observed | 9 (có bản đầu) |
| Chủ đề chính, chủ đề phụ, từ khoá | tài sản, phân cảnh | M + Đ | observed | 9 |
| Thể loại (danh sách: vlog du lịch, ẩm thực, hướng dẫn, phỏng vấn, sự kiện, giới thiệu sản phẩm, phong cảnh, đời sống, cảnh chèn, quay màn hình) | tài sản | M | observed | 9 |
| Bối cảnh (nơi chốn, thời điểm, mùa) | tài sản, phân cảnh | gom từ nhịp | observed | 9 |
| Mục đích, khán giả, thông điệp | tài sản | M | inferred | 9 |
| Ngôn ngữ nói và ngôn ngữ chữ trên hình | tài sản | N | recognized | 4, 6 |
| Độ hợp với từng nền tảng (TikTok, Shorts, Reels, YouTube dài) | tài sản, phân cảnh | Đ (luật) | observed | 9 |

**Cách làm: tóm tắt từ dưới lên.** Mô hình không xem lại hình để tóm tắt. Nó nhận các bản ghi có cấu trúc của nhịp (nhãn, hành động, thực thể, lời nói, chữ trên hình) và phải ghi số nhịp làm chứng cho mỗi ý. Code kiểm: ý không có nhịp làm chứng, hoặc nhịp làm chứng không chứa danh từ chính của ý, thì bị bỏ. Từ khoá lấy từ bộ từ vựng chuẩn (mục 6) và tên trong sổ nhân vật, nơi chốn.

**Độ hợp với nền tảng là luật, không phải ý kiến.** Tính từ tỷ lệ khung, độ dài các khoảng dùng được, có lời nói hay không, chữ trên hình có nằm trong vùng an toàn của từng nền tảng hay không. Kết quả đi kèm lý do ("dọc 9:16, có đoạn 45 giây liền mạch, chữ nằm ngoài vùng bị giao diện che").

### Nhóm 03. Cấu trúc phân cảnh và cú máy

Phần lớn đã có trong 10-13 §4, §5, §8. Bổ sung:

| Trường | Cấp | Nguồn | Đợt |
|---|---|---|---|
| Loại cú máy (tĩnh, chuyển động, cầm tay, gimbal, flycam, timelapse, quay màn hình) | cú máy | Đ + N + metadata máy | 3 |
| Lý do mở phân cảnh: lưu điểm của từng tín hiệu (khoảng cách giờ, độ khác hình, nơi chốn, chủ thể, dấu vân hình ảnh) | ranh giới | Đ | 7 |
| Độ liên tục giữa hai cú máy: cùng thực thể, hướng chuyển động trên màn hình giữ nguyên, nhiệt độ màu lệch bao nhiêu | cặp cú máy | Đ + N | 7 |
| Đổi góc trong cùng cảnh, khi không có tiếng để đồng bộ: nền giống nhau theo dấu vân hình ảnh, cùng nơi chốn, giờ quay sát nhau | cặp cú máy | Đ + N | 7 |

Dấu vân hình ảnh của Vision thay cho lưới 32×18 trong việc so "cùng nơi chốn". Lưới vẫn giữ cho điểm cắt, vì nó nhanh và đã được chỉnh ngưỡng.

### Nhóm 04. Máy quay và ngôn ngữ hình ảnh

| Trường | Nguồn chính | Nguồn kiểm chéo | Đợt |
|---|---|---|---|
| Chuyển động máy: tĩnh, lia ngang, lia dọc, đẩy vào, kéo ra, cầm tay (đã có) | Đ (hình); cảm biến máy nếu giải được | lời mô hình | có, 2 |
| Phân biệt zoom với dolly: zoom phóng đều mọi vùng, dolly làm vùng gần và vùng xa dịch khác nhau (thị sai) | Đ | — | 3 |
| Bám theo chủ thể: chủ thể đứng yên trong khung trong khi nền trôi | Đ | — | 3 |
| Độ rung, gimbal hay cầm tay (đã có độ rung) | Đ; cảm biến máy | — | có |
| **Cỡ cảnh** (cực toàn, toàn, trung, cận, đặc tả) | **khi có người: Đ từ chiều cao mặt và thân người so với khung** (mặt trên một nửa chiều cao khung là đặc tả; mặt 0,2 đến 0,5 là cận; thấy trọn thân người là trung hoặc toàn tuỳ chiều cao thân); khi không có người: M với thẻ định nghĩa có ví dụ | vùng nổi bật của Vision: một vùng lớn lan toả là cảnh rộng, một vật chiếm phần lớn khung là cận | 3 |
| Góc máy: ngang tầm, từ trên xuống, từ dưới lên, trên cao, nghiêng | M; độ nghiêng do Vision đo đường chân trời; góc ngẩng cúi từ cảm biến máy nếu có | vị trí đường chân trời trong khung | 3 |
| Góc nhìn: khách quan, góc nhìn nhân vật (POV), qua vai, tự quay mặt mình | M | Đ: mặt to, gần, chuyển động máy theo mặt là tự quay | 3 |
| Độ sâu trường ảnh: nông hay sâu | Đ: độ nét trong vùng chủ thể so với ngoài vùng | — | 3 |
| Chuyển động tương đối giữa máy và chủ thể | Đ: quỹ đạo tâm chủ thể so với chuyển động máy | — | 3 |

**Kiểm chứng.** Cỡ cảnh là nhãn ảnh hưởng nhất tới việc chọn clip, nên có hai nguồn bắt buộc. Mô hình và số đo khác nhau quá một bậc thì gắn cờ. Khi có người trong khung, số đo thắng.

### Nhóm 05. Bố cục, ánh sáng và màu

| Trường | Cách tính | Nguồn | Đợt |
|---|---|---|---|
| Vị trí chủ thể, quy tắc một phần ba (khoảng cách từ tâm chủ thể tới bốn điểm một phần ba), đặt giữa | tâm và khung của vùng nổi bật | Đ + N | 3 |
| Đối xứng trái phải | tương quan giữa lưới độ sáng và bản soi gương của nó | Đ | 3 |
| Khoảng trống | tỷ lệ diện tích có năng lượng gradient thấp, và phía nào của chủ thể còn trống (để đặt chữ) | Đ | 3 |
| Đường dẫn | hướng gradient trội và các đường hội tụ về phía chủ thể; độ tin cậy vừa | Đ | 3 |
| Đường chân trời thẳng hay nghiêng | Vision | N | 3 |
| Độ sáng, độ tương phản (phân vị 95 trừ phân vị 5), tông sáng hay tông tối | histogram | Đ | 3 |
| Ngược sáng | vùng chủ thể tối hơn nền rõ rệt | Đ | 3 |
| Hướng sáng: trước, bên, sau, trên, không rõ | M; khi có mặt người, Đ từ chênh sáng giữa hai nửa khuôn mặt | M + Đ | 3 |
| Ánh sáng cứng hay mềm | M | M | 3 |
| Năm màu chủ đạo kèm tỷ lệ | gom cụm trong không gian màu Lab | Đ | 3 |
| Nhiệt độ màu (ấm, trung tính, lạnh, kèm ước lượng Kelvin) và độ ám màu | giả định thế giới xám có loại vùng bão hoà | Đ | 3 |
| Độ bão hoà | `signalstats` hoặc sắc độ trung bình | Đ | 3 |
| **Hồ sơ log hoặc phẳng** (D-Log, D-Log M, HLG chưa chỉnh màu) | độ tương phản và độ bão hoà rất thấp trên toàn file, cộng metadata máy | Đ | 3 |
| Kiểu màu: tự nhiên, điện ảnh xanh cam, cổ điển, rực rỡ, đơn sắc, tối giản | luật trên màu chủ đạo và tách màu vùng tối, vùng sáng; M khi luật không chắc | Đ + M | 3 |

Hồ sơ log là trường có giá trị trực tiếp cho dựng: một clip log ghép cạnh một clip thường sẽ lệch màu nặng. Khâu dựng dùng trường này để áp LUT hoặc cảnh báo.

### Nhóm 06. Thực thể, vật thể và quan hệ không gian

| Trường | Nguồn | Đợt |
|---|---|---|
| Người: số người (đếm khung người của Vision), khung toạ độ, khuôn mặt, chất lượng khuôn mặt, tư thế (đứng, ngồi, cúi, nằm, đi, chạy, từ khớp xương) | N | 5 |
| Động vật: chó, mèo do Vision; loài khác do M | N + M | 5 |
| Vật thể, phương tiện, đồ ăn, sản phẩm: tên, thuộc tính (màu, chất liệu, trạng thái), khung toạ độ | M (Qwen2.5-VL trả được khung toạ độ), kiểm bằng nhãn phân loại của Vision và vùng nổi bật | 5 |
| Nơi chốn: tên loại nơi (từ vựng chuẩn), trong nhà hay ngoài trời, cụ thể nếu biết (từ sổ nơi chốn, GPS, ghi chú) | N + M + H | 5 |
| Quan hệ dạng (chủ thể, quan hệ, đối tượng), với danh sách quan hệ cố định: cầm, mặc, đeo, ngồi trên, đứng cạnh, đặt trên, ở trong, đi vào, đi ra, nhìn vào, nói với, đưa cho | M | 5 |
| Bám một thực thể qua các khung trong cú máy | N (bám đối tượng của Vision, nối bằng độ chồng khung và dấu vân hình ảnh) | 5 |
| Cùng một người hay nơi qua nhiều cú máy và phân cảnh | dấu vân hình ảnh của vùng mặt, thân và trang phục, gom cụm; người vận hành xác nhận trong sổ (10-13 §11) | 7 |

**Kiểm chứng.** Số người do mô hình nói và số khung người Vision đếm khác nhau thì gắn cờ; nhãn "số người" trong 10-13 §6 chuyển từ nguồn mô hình sang nguồn nhận diện. Khung toạ độ mô hình đưa phải nằm trong khung hình và chồng ít nhất 30% lên một vùng Vision thấy (người, vùng nổi bật); không thì hạ độ tin cậy.

**Riêng tư.** Đặc trưng khuôn mặt chỉ lưu trong máy, không bao giờ gửi lên cloud, xoá được theo từng người trong sổ.

### Nhóm 07. Hành động, sự kiện và diễn biến

Giữ 10-13 §7 (bản ghi hành động, sự việc, ba pha, trọn vẹn hay bị cụt). Bổ sung:

| Trường | Cách làm | Nguồn | Đợt |
|---|---|---|---|
| Bản ghi đủ năm ý: ai, làm gì, với ai hoặc cái gì, ở đâu, kết quả | M; động từ được chuẩn hoá qua bộ từ vựng | M | 5 |
| Điểm bắt đầu, kết thúc chính xác tới 0,1 giây | lượt quét dày tại chỗ: chỉ trong khoảng của sự việc, lấy 5 khung mỗi giây, đo chuyển động chủ thể và thay đổi tư thế | Đ + N | 5 |
| Trạng thái trước và sau | M so khung đầu và khung cuối của sự việc trong cùng một lời gọi ("trước: bột chưa nhào; sau: bột đã thành khối") | M | 5 |
| Chuỗi sự việc trong phân cảnh | thứ tự theo thời gian | Đ | 7 |
| Điểm chuyển (turning point) | đỉnh trùng nhau của: đổi hành động, đổi chủ thể, độ khác hình lớn, âm thanh bật lên | Đ | 7 |
| Nhân quả | chỉ khi cả hai sự việc đã được nhận ra; M trả lời có hoặc không, kèm khung làm chứng; mặc định độ tin cậy thấp | M | 7 |

### Nhóm 08. Lời nói, bản chép lời và ngôn ngữ

Giữ 10-13 §12 (siết ranh giới từ, phân biệt người nói). Bổ sung, theo thứ tự tác động lên độ chính xác:

1. **Bộ đo lời nói.** Người vận hành sửa tay bản chép lời của khoảng 5 phút footage (một clip trước). Hệ thống tính tỷ lệ lỗi từ (WER) và tỷ lệ lỗi ký tự (CER). Không có bộ đo này thì mọi thay đổi bên dưới chỉ là cảm nhận.
2. **Chỉ chép chỗ có tiếng người.** Lọc trước bằng SoundAnalysis (cửa sổ "lời nói") và mức âm. Whisper hay bịa chữ trong đoạn gió, nhạc hoặc im lặng; các câu như "trăng bí bên này" nhiều khả năng sinh ra như vậy.
3. **Gợi ý từ vựng.** Đưa vào whisper tên người, tên nơi trong sổ, ghi chú của buổi quay và chữ đọc được trên hình. Tên riêng là chỗ whisper sai nhiều nhất.
4. **Lọc câu bịa.** Bỏ câu lặp nguyên văn câu trước, câu nằm trong vùng SoundAnalysis không thấy tiếng người, câu có xác suất từ trung bình quá thấp. Mỗi câu bị bỏ được ghi lại kèm lý do.
5. **So mô hình chép lời.** Trên bộ đo ở bước 1: bản đang dùng `large-v3-turbo` q5, bản `large-v3` đầy đủ, và PhoWhisper (VinAI, tinh chỉnh cho tiếng Việt, chuyển sang định dạng của whisper.cpp). Giữ bản có WER thấp nhất trong giới hạn thời gian.
6. **Sửa chữ có giới hạn.** Chỉ với từ có xác suất thấp: mô hình ngôn ngữ được đề xuất thay bằng từ có âm gần giống và hợp ngữ cảnh. Bản gốc được giữ, từ đã sửa được đánh dấu "sửa bởi mô hình", và người vận hành duyệt được.
7. **Phụ đề có sẵn trên hình làm đáp án.** Khi OCR thấy phụ đề cháy sẵn trùng câu nói (nhóm 10), phụ đề được dùng để sửa bản chép lời.

Các trường còn lại:

| Trường | Nguồn | Đợt |
|---|---|---|
| Mốc từng từ đã siết, độ tin cậy từng từ (đã có độ tin cậy) | Đ + N | 4 |
| Chia câu, dấu câu | N; M khôi phục dấu câu khi whisper bỏ sót | 4 |
| Từ đệm (à, ờ, ừ, thì, kiểu, là): đánh dấu để cắt | Đ (danh sách) | 4 |
| Người nói và lời nói chồng nhau | Đ (10-13 §12); chồng nhau khi hai cụm giọng cùng hoạt động | 4 |
| **Người nói có trong khung hay không** (nói trước máy, lồng tiếng, người ngoài khung) | Đ: tương quan giữa độ mở môi (điểm mốc khuôn mặt của Vision) và mức âm lời nói | 4 |
| Chuyển ngôn ngữ trong câu | N (ngôn ngữ của whisper từng đoạn) + Đ (từ điển) | 4 |
| Giọng: sôi nổi hay đều đều, cười, hét, thì thầm | Đ (độ biến thiên cao độ và mức âm) + N (các loại âm của SoundAnalysis) | 4 |
| Bản dịch | M qua mô-đun dịch đã có, chỉ dịch khi được yêu cầu | 9 |
| Tóm tắt lời nói theo phân cảnh | M | 9 |
| Tách lời nghe được khỏi chữ thấy trên hình | hai trường riêng (đã tách) | có |

### Nhóm 09. Âm thanh và không gian âm

| Trường | Nguồn | Đợt |
|---|---|---|
| Loại âm theo khoảnh: lời nói, nhạc, tiếng nền (gió, nước, chim, xe cộ, đám đông, mưa), hiệu ứng (vỗ tay, tiếng gõ, cửa, máy móc, động cơ) | N: SoundAnalysis gom về khoảng 40 nhóm tiếng Việt | 6 |
| Độ lớn theo chuẩn: tích hợp, ngắn hạn, dải biến thiên, đỉnh thật, cho mỗi nhịp và cả file | Đ (`ebur128`) | 6 |
| Cắt đỉnh âm (clipping), nền ồn, tỷ lệ tín hiệu trên nhiễu của lời nói | Đ (`astats`, phân vị mức âm) | 6 |
| Khoảng lặng | Đ (`silencedetect` và mức âm 10 ms đã có) | 6 |
| Tiếng gió | Đ (năng lượng tần thấp, `aspectralstats`) + N | 6 |
| Nhạc trong footage: có hay không, tempo, năng lượng, đoạn nhạc lên cao | N + Đ (dùng lại `library/music.py` trên đoạn có nhạc) | 6 |
| Nguồn âm trong khung hay ngoài khung | Đ (luật): lời nói và môi cử động là trong khung; chim kêu và Vision thấy chim là trong khung; không có gì tương ứng là ngoài khung | 6 |
| Quan hệ hình và tiếng: cú máy bắt đầu cùng lúc âm thanh bật lên | Đ | 6 |

**Kiểm chứng.** Như mục 4.2: ngưỡng riêng cho từng loại âm, phải có ít nhất hai cửa sổ liền nhau, chỉ gom các loại đã liệt kê. Kiểm chéo: tiếng gió được báo trong khi số đo nói ngoài trời và gió tần thấp mạnh thì độ tin cậy cao; báo trong nhà thì gắn cờ.

### Nhóm 10. Chữ trên hình, phụ đề và đồ hoạ

| Trường | Cách làm | Nguồn | Đợt |
|---|---|---|---|
| Nội dung chữ, khung toạ độ, độ tin cậy | Vision đọc chữ tiếng Việt và tiếng Anh, trên các khung của nhịp và một lượt thưa 1 khung mỗi giây | N | 6 |
| Lúc chữ hiện và tắt | nối các lần đọc qua thời gian (chồng khung toạ độ, chữ giống nhau), rồi tìm mép bằng cách đọc thêm các khung ở giữa | Đ + N | 6 |
| Loại chữ: phụ đề, tiêu đề, dòng chú thích tên (lower third), chữ trong cảnh (biển hiệu, bao bì), giao diện màn hình, watermark | luật: vị trí (đáy, giữa, góc), có đứng yên khi máy chuyển động hay không, có hiện và tắt theo câu nói hay không, có nằm suốt cả file ở một góc hay không | Đ | 6 |
| Chữ có sẵn trong cảnh hay chữ chèn hậu kỳ | chữ chèn đứng yên trong khung khi máy chuyển động; chữ trong cảnh trôi theo cảnh | Đ | 6 |
| Watermark và logo không có chữ | vùng nhỏ có độ biến thiên theo thời gian rất thấp trong khi phần còn lại của hình thay đổi | Đ | 6 |
| Tên thương hiệu của logo | M, tuỳ chọn | M | 6 |
| Cỡ chữ (chiều cao so với khung), màu chữ, màu nền, có viền hay không | Đ trong khung toạ độ của chữ | Đ | 6 |
| Biểu đồ, đồ hoạ thông tin | M (loại nội dung "đồ hoạ hoặc chữ" của 10-13 §6) | M | 6 |
| Lỗi chính tả trong chữ trên hình | từ điển tiếng Việt | Đ | 6 |

**Kiểm chứng.** OCR được đo bằng khung có chèn chữ đã biết trước, như phép thử ngày 2026-10-14: chữ chuẩn, chữ nhỏ, chữ trên nền rối, chữ có dấu chồng. Nhãn "chữ chèn sẵn" và "watermark" trong 10-13 §6 chuyển từ nguồn mô hình sang nguồn đo và nhận diện.

### Nhóm 11. Ngữ pháp dựng và nhịp

Chủ yếu có ích với video đã dựng (video tham khảo, clip tải về); với footage thô tự quay phần lớn trường là rỗng, và đó là đúng.

| Trường | Cách làm | Nguồn | Đợt |
|---|---|---|---|
| Số cắt mỗi phút, phân bố độ dài cú máy (trung vị, phân vị 10 và 90), đường nhịp theo thời gian | từ ranh giới cú máy | Đ | 9 |
| Kiểu chuyển cảnh (đã có) | 10-13 §4 | Đ | có |
| Jump cut: hai cú máy liền nhau có nền gần như trùng và cùng chủ thể | dấu vân hình ảnh | Đ + N | 9 |
| Match cut: bố cục hai bên điểm cắt giống nhau nhưng nội dung khác | tương quan lưới cao, nhãn phân loại khác; độ tin cậy vừa | Đ + N | 9 |
| J-cut và L-cut: lời nói kéo qua điểm cắt, hoặc tiếng của cú sau bắt đầu trước hình | mốc từ so với điểm cắt | Đ | 9 |
| Quay chậm, tua nhanh, đổi tốc độ giữa chừng, khung đứng (đã có quay chậm và đứng hình) | tốc độ khung, khung lặp, độ lớn chuyển động | Đ | 9 |
| Cắt theo phách nhạc | tỷ lệ điểm cắt nằm trong 80 ms quanh một phách | Đ | 9 |
| Cắt theo lời | tỷ lệ điểm cắt rơi vào khe giữa hai câu | Đ | 9 |

### Nhóm 12. Kể chuyện, cảm xúc và tác động lên người xem

Toàn bộ nhóm này mang hạng `inferred`, trừ những trường ghi khác.

| Trường | Cách làm | Hạng | Đợt |
|---|---|---|---|
| Đoạn mở đầu (hook): 3 giây đầu có gì | **đo**: thời điểm câu nói đầu tiên, có mặt người không, mức thay đổi hình, có chữ không, âm thanh bật lên không | observed | 9 |
| Cấu trúc mở đầu, phát triển, cao trào, kết | M trên các bản tóm tắt phân cảnh và lời nói, có trích số phân cảnh làm chứng | inferred | 9 |
| Xung đột, nhịp kể | M | inferred | 9 |
| Cảm xúc thể hiện theo thời gian | kết hợp: biểu cảm khuôn mặt (M trên vùng mặt, danh sách vui, buồn, ngạc nhiên, giận, trung tính), giọng (nhóm 08), cười và hét (nhóm 09) | inferred | 9 |
| Lời kêu gọi hành động | luật trên lời nói và chữ ("đăng ký", "theo dõi", "link", "mua", "inbox"), M xác nhận | observed | 9 |
| Đối tượng người xem, giả thuyết về khả năng giữ chân | M, ghi rõ là giả thuyết | inferred | 9 |

**Khép vòng với số liệu thật (đề xuất).** Mô-đun Phân phối đã thu số liệu của video đã đăng theo các mốc. Khi đủ dữ liệu, hệ thống so những thuộc tính đo được của các clip đã dùng (cỡ cảnh, có mặt người, nhịp cắt, kiểu mở đầu) với độ giữ chân thật. Giả thuyết lúc đó được thay bằng bằng chứng từ chính kênh của người vận hành.

### Nhóm 13. Dấu vân phong cách

Gom từ các nhóm 04, 05, 09, 10, 11 cho một file, một buổi quay hoặc một video tham khảo:

- Hình: phân bố cỡ cảnh, phân bố chuyển động máy, bảng màu, độ tương phản, độ bão hoà, nhiệt độ màu, hồ sơ log, độ hạt, độ nét, tỷ lệ khung.
- Chữ: vị trí, cỡ, màu, nền và viền của phụ đề; kiểu tiêu đề.
- Dựng: số cắt mỗi phút, kiểu chuyển cảnh, cắt theo phách hay theo lời.
- Âm thanh: tempo và năng lượng nhạc, độ lớn, lời dẫn hay lời thoại.

Kết quả có hai dạng: một thẻ phong cách đọc được, và một bộ thông số khớp với mẫu định dạng sẵn có của khâu dựng (kiểu chữ, màu phụ đề, logo, tỷ lệ khung).

**Học phong cách từ video tham khảo (đề xuất).** Người vận hành nhập một video tham khảo với cờ "chỉ để tham khảo". Hệ thống phân tích, xuất thẻ phong cách và bộ thông số dựng, nhưng không bao giờ đưa hình hay tiếng của video đó vào kết quả khớp kịch bản.

### Nhóm 14. Chất lượng và lỗi

Hai vùng tên tách nhau: `defects.*` (lỗi kỹ thuật, đo xác định được) và `aesthetic.*` (đánh giá thẩm mỹ). Một bộ lọc chất lượng không bao giờ dùng trường `aesthetic` để loại clip.

| Trường | Cách làm | Nguồn | Hiện có | Đợt |
|---|---|---|---|---|
| Mất nét, rung, phơi sáng (cháy, bệt), khung đen, đứng hình, chớp sáng, nhấp nháy | 10-13 §3, §4 | Đ | có | — |
| Nhiễu hạt | độ lệch của bộ lọc Laplace trong vùng phẳng | Đ | — | 3 |
| Dải màu (banding) | đếm mức độ sáng rời rạc trong vùng chuyển màu mịn | Đ | — | 3 |
| Vỡ khối do nén | `blockdetect` | Đ | — | 3 |
| Rớt khung | khoảng cách mốc thời gian lệch khỏi độ dài một khung; chuỗi khung lặp trong đoạn có chuyển động | Đ | — | 3 |
| Xen kẽ dòng | `idet` | Đ | — | 2 |
| Lệch tiếng và hình | với người nói trong khung: độ lệch làm tương quan giữa độ mở môi và mức âm lớn nhất | Đ | — | 4 |
| Cắt đỉnh âm, mất tiếng đột ngột, tiếng gió | nhóm 09 | Đ | — | 6 |
| Lỗi chính tả chữ trên hình; phụ đề tràn (đã có ở khâu kiểm tra bản dựng) | nhóm 10 | Đ | một phần | 6 |
| Điểm thẩm mỹ | Vision | N | — | 3 |

### Nhóm 15. Tìm kiếm, truy xuất và dùng lại

| Thành phần | Cách làm | Đợt |
|---|---|---|
| Tìm theo từ khoá và theo nghĩa của văn bản (đã có) | FTS và vector `bge-m3` | có |
| **Đa dạng kết quả** | khi nhiều nhịp gần trùng nhau cùng đứng đầu, chỉ giữ nhịp tốt nhất của mỗi cụm rồi mới xếp tiếp (xếp hạng có phạt trùng lặp) | 3 |
| Tìm theo hình | vector dấu vân hình ảnh của Vision cho khung đại diện; "tìm cảnh giống cảnh này" | 8 |
| Lọc theo nhãn có cấu trúc | cỡ cảnh, chuyển động máy, có mặt người, người nói trong khung, loại âm, có chữ, hồ sơ log, chất lượng; chỉ nhãn đã qua cổng phát hành mới được dùng làm bộ lọc | 8 |
| Câu hỏi tự nhiên thành bộ lọc | mô hình ngôn ngữ đổi câu hỏi thành bộ lọc cộng phần nghĩa; nếu đổi lỗi thì lùi về tìm theo nghĩa thường | 8 |
| Xếp hạng | điểm nghĩa, điểm khớp nhãn, chất lượng kỹ thuật, độ trọn vẹn của hành động, phản hồi ghép cảnh đã có | 8 |
| Thông tin dùng lại | khoảng dùng được, điểm cắt sạch, quyền sử dụng, đánh giá sao, đã dùng trong dự án nào | 8 |
| Vector mang tên và phiên bản mô hình; đổi mô hình thì tính lại | | 2 |

Các câu hỏi mẫu của người vận hành, viết thành bộ lọc:

| Câu hỏi | Bộ lọc |
|---|---|
| Đoạn có người nói trước camera | có lời nói, người nói trong khung, mặt người cỡ trung trở lên, mặt nhìn về máy |
| Close-up sản phẩm | cỡ cảnh cận hoặc đặc tả, vật thể thuộc loại sản phẩm chiếm vùng nổi bật, không có mặt người chiếm khung |
| Cảnh có nhạc tăng cao | có nhạc, độ lớn ngắn hạn tăng đều trong 3 giây trở lên |

**Kiểm chứng.** Bộ mẫu tìm kiếm do người vận hành chọn tay (đã có cơ chế, commit `30df1ee`) đo tỷ lệ tìm đúng trong 1, 3, 10 kết quả đầu, trước và sau mỗi thay đổi.

### Nhóm 16. Nguồn gốc, quyền và bằng chứng

| Trường | Nguồn | Hiện có | Đợt |
|---|---|---|---|
| Nguồn file, nguồn gốc, giấy phép, người tạo, URL của clip tải về | Đ, H | có | — |
| Mỗi nhãn: nguồn đo, mô hình hay người, độ tin cậy | | có | — |
| **Mã bộ phân tích đầy đủ** cho mỗi giá trị: công cụ, phiên bản công cụ, tên và mã băm mô hình, phiên bản prompt, mã băm tham số, thời điểm xử lý | Đ | chỉ có phiên bản prompt | 2 |
| Bằng chứng: khoảng thời gian, khung hình, câu trả lời gốc của mô hình | Đ | có khung hình | 2 |
| Kết quả kiểm chéo (cờ, trạng thái, ai xử lý) | Đ, H | thiết kế 10-13 §10 | 3 |
| Lịch sử sửa: ai, lúc nào, giá trị cũ, giá trị mới | H | nhật ký thao tác chung | 2 |
| Trạng thái xác minh quyền: chưa xác minh, người vận hành xác nhận, có tệp giấy phép | H | một phần | 9 |
| Người xuất hiện trong hình: đã đồng ý cho xuất hiện hay chưa, theo từng người trong sổ | H | — | 9 |
| Thông tin xác thực nội dung (C2PA) nếu file có | Đ | — | 9 |
| Cờ nội dung tổng hợp (đã có ở gói xuất bản) | Đ | có | — |

Người xuất hiện chưa đồng ý không chặn việc dựng, nhưng là một mục chặn ở cổng quyền trước khi xuất bản, giống nhạc chưa được xác nhận.

## 6. Bộ từ vựng chuẩn

Một tệp từ vựng tiếng Việt có phiên bản, gồm: loại nơi chốn, loại vật thể, động từ hành động, quan hệ, loại âm, loại chữ, thể loại, cảm xúc. Mỗi mục có tên chuẩn, các tên gọi khác và tên tiếng Anh tương ứng (để ánh xạ nhãn của Vision và SoundAnalysis).

- Câu trả lời của mô hình được chuẩn hoá: "cây cỏ", "cây cối", "cây xanh" đều về "cây". Từ ngoài từ vựng được giữ nguyên trong mô tả tự do nhưng không vào nhãn.
- **Chặn lẫn ngôn ngữ.** Từ tiếng Anh trong câu trả lời tiếng Việt ("countryside") được ánh xạ qua tên tiếng Anh của từ vựng. Không ánh xạ được thì hỏi lại một lần với nhắc nhở; vẫn lỗi thì gắn cờ.
- Người vận hành thêm mục và tên gọi khác từ giao diện; thay đổi được ghi lịch sử.

## 7. Mô tả phân biệt được

Đây là sửa đổi trực tiếp cho vấn đề lớn nhất ở mục 2.

- Prompt mô tả của một nhịp nhận kèm mô tả và nhãn của **nhịp trước trong cùng cú máy**, và phải nói nhịp này **khác gì**: chủ thể mới, góc nhìn mới, vật mới xuất hiện, hành động đổi. Không có gì khác thì nói thẳng "tiếp diễn" và nhịp được đánh dấu gần trùng.
- Mô tả có hai phần: phần chung (bối cảnh, giữ ngắn) và phần riêng (điều làm nhịp này khác). Chỉ mục tìm kiếm đặt trọng số cao hơn cho phần riêng.
- **Chỉ số đo:** độ giống trung bình giữa vector mô tả của hai nhịp kề nhau trong cùng cú máy. Chỉ số này phải giảm so với hiện nay trên clip `0050`, trong khi bộ mẫu ghép cảnh không được tụt.

## 8. Bảo đảm độ chính xác

### 8.1 Bộ mẫu do người vận hành gán

Mở rộng `quality/evaluation.py` (10-13 §16) từ ranh giới sang mọi trường. Theo cách làm đã thống nhất, mỗi lần làm **một clip**, xong mới sang clip thứ hai:

- Người vận hành gán trên giao diện, ngay ở dải thời gian, các giá trị đúng cho một mẫu nhịp (khoảng 30 nhịp mỗi clip): cỡ cảnh, góc máy, số người, hành động, nơi chốn, loại âm, chữ trên hình.
- Bản chép lời đúng cho khoảng 5 phút có thoại (nhóm 08).
- Các câu kịch bản kèm đoạn đúng cho bộ mẫu ghép cảnh (đã có cơ chế chọn tay).

Để giảm công gán: giao diện đưa sẵn giá trị của hệ thống, người vận hành chỉ bấm "đúng" hoặc chọn giá trị khác.

### 8.2 Số đo theo loại trường

| Loại trường | Số đo |
|---|---|
| Nhãn từ danh sách | tỷ lệ đúng; ma trận nhầm lẫn; với cỡ cảnh, thêm tỷ lệ lệch không quá một bậc |
| Khung toạ độ | độ chồng (IoU) |
| Mốc thời gian (ranh giới, đầu và cuối hành động, chữ hiện và tắt) | sai lệch tuyệt đối, tỷ lệ trong 0,5 giây |
| Lời nói | WER, CER, riêng cho tên riêng |
| Chữ trên hình | CER |
| Loại âm | tỷ lệ bắt đúng và tỷ lệ báo nhầm theo từng loại |
| Tìm kiếm và ghép cảnh | đúng trong 1, 3, 10 kết quả đầu |

### 8.3 Cổng phát hành theo trường

Mỗi trường có một trạng thái: **thử nghiệm** (tính và hiển thị, không dùng), **phát hành** (khâu khớp kịch bản và bộ lọc tìm kiếm được dùng), **ngừng** (số đo tụt dưới ngưỡng ở một lần đo sau). Ngưỡng phát hành mặc định:

| Loại trường | Ngưỡng |
|---|---|
| Đo bằng code | 95% đúng trên bộ mẫu |
| Nhận diện chuyên dụng | 90% |
| Mô hình, hạng observed | 85% |
| Mô hình, hạng inferred | không có cổng; không bao giờ là bộ lọc |
| Lời nói | WER không quá 15% để dùng cho khớp kịch bản |

Ngưỡng là cấu hình, chỉnh được. Trang Hệ thống hiển thị bảng trạng thái từng trường với số đo mới nhất.

### 8.4 Hiệu chỉnh độ tin cậy

Độ tin cậy "cao" phải đúng ít nhất 95% trên bộ mẫu, "vừa" ít nhất 75%. Nếu không đạt, bảng ánh xạ trong 10-13 §6 cho trường đó được hạ xuống một bậc cho tới khi đạt. Nhờ vậy, "cao" có nghĩa giống nhau ở mọi trường.

### 8.5 Mở rộng kiểm tra chéo (bổ sung 10-13 §10)

| Luật | Cờ khi |
|---|---|
| Cỡ cảnh | mô hình và số đo (mặt, thân, vùng nổi bật) lệch nhau quá một bậc |
| Số người | mô hình và số khung người của Vision khác nhau |
| Nơi chốn | nhãn phân loại của Vision (trong nhà, ngoài trời) trái với mô hình |
| Chữ trên hình | mô hình nói có chữ mà OCR không đọc được gì, hoặc ngược lại |
| Âm thanh | mô tả nhắc tiếng nhạc mà SoundAnalysis không thấy nhạc |
| Lời nói | whisper có câu trong vùng SoundAnalysis không thấy tiếng người |
| Ngôn ngữ | câu trả lời có từ ngoài ngôn ngữ mà không ánh xạ được |
| Gần trùng | mô tả của nhịp gần như trùng nhịp trước mà số đo cho thấy hình đã đổi nhiều |

### 8.6 Chống tụt chất lượng

Mỗi lần chạy bộ đo lưu cấu hình (mô hình, prompt, ngưỡng, từ vựng). Một thay đổi làm bất kỳ trường đã phát hành nào tụt quá 3 điểm phần trăm thì bị báo trước khi áp cho cả kho. Kiểm thử tự động vẫn chạy bằng adapter giả, không cần mô hình hay Swift thật.

## 9. Dữ liệu và dây chuyền

### 9.1 Lưu trữ

| Bảng hoặc chỗ lưu | Nội dung | Mới hay đã có |
|---|---|---|
| `asset_versions.metadata.probe` | mở rộng theo nhóm 01 | đã có, mở rộng |
| `moments` cấp `segment` (nhịp), `data.labels` | thêm vùng tên `composition`, `light`, `color`, `people`, `audio`, `text`, `defects`, `aesthetic`; mỗi nhãn có `value`, `source`, `confidence`, `evidence`, `analyzer` | đã có, mở rộng |
| `moments` cấp `video` | hồ sơ tài sản: nhóm 02, 11, 12, 13 | đã có, mở rộng |
| `footage_scenes`, `footage_scene_beats`, `entities`, `entity_mentions` | như 10-13 §8, §11 | mới (theo 10-13) |
| `tracks` | thực thể được bám trong một cú máy: tài sản, khoảng thời gian, chuỗi khung toạ độ, thực thể trong sổ nếu đã nối | mới |
| `text_spans` | chữ trên hình: tài sản, khoảng thời gian, chữ, khung toạ độ, loại, độ tin cậy | mới |
| `audio_events` | âm thanh: tài sản, khoảng thời gian, loại, độ tin cậy, nguồn | mới |
| `image_vectors` | vector dấu vân hình ảnh của khung đại diện, kèm tên và phiên bản mô hình | mới |
| `field_history` | lịch sử sửa từng trường: ai, lúc nào, cũ, mới | mới |
| `golden_labels` | bộ mẫu của người vận hành: trường, tài sản, khoảng thời gian, giá trị đúng | mới |
| `field_status` | trạng thái phát hành và số đo mới nhất của từng trường | mới |

`text_spans` và `audio_events` có dòng tương ứng trong chỉ mục tìm kiếm, như phân cảnh trong 10-13 §8.

### 9.2 Dây chuyền

Bổ sung vào bảng của 10-13 §14:

| Bước | Cần | Làm gì | Chạy sau |
|---|---|---|---|
| `probe` | ffprobe | thông số đầy đủ của nhóm 01 | khi nhập |
| `signals` | ffmpeg (giải mã phần cứng) | như 10-13, thêm màu, bố cục, nhiễu, vỡ khối | `probe` |
| `telemetry` | trình đọc metadata máy (nếu giải được) | chuyển động và góc máy từ cảm biến | `probe` |
| `audio` | ffmpeg, adapter `sound` | loại âm, độ lớn, lặng, gió, cắt đỉnh | `probe` |
| `vision` | adapter `vision` | người, mặt, tư thế, phân loại, chân trời, vùng nổi bật, thẩm mỹ, dấu vân hình ảnh trên khung của nhịp | `frames` |
| `text` | adapter `vision` | lượt đọc chữ thưa, nối thành khoảnh, phân loại chữ | `signals` |
| `speech` | whisper | lọc theo vùng có tiếng người, gợi ý từ vựng, lọc câu bịa | `audio` |
| `describe` | model | như 10-13, thêm mô tả phân biệt, khung toạ độ, quan hệ, trạng thái trước và sau | `vision`, `speech` |
| `tracks` | adapter `vision` | bám thực thể trong cú máy | `vision` |
| `profile` | model (chỉ để viết) | tóm tắt từ dưới lên, phân loại, độ hợp nền tảng, ngữ pháp dựng, phong cách, kể chuyện | `scenes` |
| `checks` | code | toàn bộ luật ở mục 8.5 | mọi bước trên |

Ba bước `probe`, `signals`, `audio` không cần mô hình; `vision` và `text` không cần mô hình ngôn ngữ. Trên máy Mac, như vậy phần lớn các trường đo và nhận diện có ngay sau khi nhập, kể cả khi mô hình đang tắt.

## 10. Thứ tự xây mới

Thay bảng ở 10-13 §18. Đợt 1 giữ nguyên (đã xong và đã nghiệm thu). Thứ tự xếp theo mức giúp chọn đúng nguyên liệu:

| Đợt | Nội dung | Nhóm | Vì sao ở vị trí này |
|---|---|---|---|
| 1 | (đã xong) tín hiệu, cú máy, nhịp, nhãn đo được | 03, 04, 14 | — |
| 2 | **Nền đo lường**: adapter `vision` và `sound`, giải mã phần cứng, `probe` đầy đủ, mã bộ phân tích và lịch sử sửa, bộ mẫu và cổng phát hành, giao diện gán mẫu, thử giải metadata máy, so mô hình nhìn | 01, 16, 8 | mọi đợt sau cần nguồn đo để kiểm chéo và cần bộ mẫu để biết mình có đúng không |
| 3 | **Mô tả phiên bản 2**: nhãn từ danh sách, cỡ cảnh và góc máy có hai nguồn, bố cục, ánh sáng, màu, hồ sơ log, chất lượng mở rộng, từ vựng chuẩn, mô tả phân biệt, đa dạng kết quả, kiểm tra chéo, hàng chờ xem lại | 04, 05, 14, 15 (đa dạng) | sửa trực tiếp hai lỗi lớn nhất đang thấy: các nhịp giống nhau và cỡ cảnh sai |
| 4 | **Lời nói**: bộ đo WER, lọc theo vùng có tiếng người, gợi ý từ vựng, lọc câu bịa, so mô hình chép lời, siết ranh giới từ, phân biệt người nói, người nói trong khung, lệch tiếng và hình | 08 | bản chép lời đang nhiễu, mà nó là nguồn nghĩa mạnh nhất cho clip có thoại |
| 5 | **Hành động và thực thể**: bản ghi năm ý, đầu và cuối chính xác, trạng thái trước và sau, sự việc, pha, trọn vẹn, điểm cắt sạch, người và vật có khung toạ độ, quan hệ, bám trong cú máy | 06, 07 | cần cho câu kịch bản tả việc làm cụ thể |
| 6 | **Âm thanh và chữ trên hình** | 09, 10 | cho thêm hai nguồn kiểm chéo và các bộ lọc mới |
| 7 | **Phân cảnh và sổ đăng ký**: phân cảnh qua nhiều file, góc máy, lần quay lại, độ phủ, liên tục, điểm chuyển, nhân quả, nhận lại người và nơi qua nhiều cú máy | 03, 06, 07 | gộp hai đợt 4 và 5 cũ; cần thực thể của đợt 5 |
| 8 | **Tìm kiếm**: tìm theo hình, lọc theo nhãn đã phát hành, câu hỏi tự nhiên thành bộ lọc, xếp hạng mới | 15 | cần các nhãn của đợt 3 đến 7 đã qua cổng |
| 9 | **Hồ sơ cấp tài sản**: tóm tắt từ dưới lên, phân loại, độ hợp nền tảng, ngữ pháp dựng, kể chuyện, cảm xúc, phong cách, video tham khảo, quyền và sự đồng ý, C2PA, khép vòng với số liệu | 02, 11, 12, 13, 16 | ít ảnh hưởng tới việc chọn đoạn; có ích cho dựng và sáng tạo |

Đợt 4 không phụ thuộc đợt 3 và có thể làm song song nếu footage có thoại là ưu tiên. Mỗi đợt có kế hoạch riêng, chạy trước trên một clip DJI cho tới khi đúng, rồi mới sang clip thứ hai; cả kho chỉ chạy một lần ở cuối đợt.

**Điều kiện xong của mỗi đợt.** Mọi trường của đợt có số đo trên bộ mẫu. Trường đạt ngưỡng thì phát hành; trường chưa đạt thì giữ ở trạng thái thử nghiệm, kèm ghi chú vì sao. Bộ mẫu ghép cảnh không tụt. Đợt 3 còn phải làm giảm chỉ số gần trùng ở mục 7.

## 11. Tình huống kiểm thử bổ sung

Nối tiếp danh sách của 10-13 §15:

| # | Tình huống | Kết quả phải có | Đợt |
|---|---|---|---|
| 39 | Không có Swift hoặc không phải macOS | Các trường của `vision` và `sound` mang trạng thái "chưa đo"; mọi thứ khác chạy | 2 |
| 40 | Phần cứng từ chối giải mã một file | Lùi về giải mã CPU, kết quả giống hệt | 2 |
| 41 | File quay dọc trên điện thoại có cờ xoay | Tỷ lệ hiển thị và khung toạ độ theo hướng đúng | 2 |
| 42 | Tốc độ khung khai báo khác mốc thời gian thật | Số đo thắng, có cờ | 2 |
| 43 | Đổi mô hình nhìn | Chỉ các trường của mô hình hết hạn; số đo và nhận diện giữ nguyên | 2 |
| 44 | Một trường tụt dưới ngưỡng ở lần đo mới | Trường chuyển sang "ngừng", khâu khớp kịch bản thôi dùng nó | 2 |
| 45 | Mặt người chiếm nửa khung, mô hình nói "toàn" | Cỡ cảnh "đặc tả" theo số đo, có cờ | 3 |
| 46 | Cảnh rộng không người, mô hình nói "cận" | Có cờ "cỡ cảnh" (vùng nổi bật lan toả) | 3 |
| 47 | Bảy nhịp liền nhau cùng nội dung | Các nhịp sau được đánh dấu "tiếp diễn"; kết quả tìm kiếm chỉ đưa một nhịp của cụm lên đầu | 3 |
| 48 | Mô hình trả lời có từ tiếng Anh | Từ được ánh xạ về từ vựng; không ánh xạ được thì có cờ | 3 |
| 49 | File quay hồ sơ log | Nhãn "log", độ bão hoà và tương phản thấp không bị coi là lỗi phơi sáng | 3 |
| 50 | Đoạn chỉ có gió, không ai nói | Whisper không được chạy cho đoạn đó; không có câu nào | 4 |
| 51 | Câu lặp nguyên văn câu trước | Câu bị bỏ, có ghi lý do | 4 |
| 52 | Tên riêng có trong sổ | Bản chép lời viết đúng tên | 4 |
| 53 | Người nói trước máy và lồng tiếng trong cùng file | Hai giá trị "trong khung" và "ngoài khung" đúng chỗ | 4 |
| 54 | Tiếng lệch hình 200 ms | Lỗi lệch tiếng được báo kèm độ lệch | 4 |
| 55 | Người cầm cốc rồi đặt xuống bàn | Hai hành động, có trạng thái trước và sau, có quan hệ "cầm" rồi "đặt trên" | 5 |
| 56 | Hai người đi qua nhau trong cú máy | Hai vệt bám riêng, không đổi danh tính khi chồng nhau | 5 |
| 57 | Phụ đề cháy sẵn theo câu nói | `text_spans` loại phụ đề, hiện và tắt theo câu; được dùng để sửa bản chép lời | 6 |
| 58 | Watermark ở góc suốt file | Loại watermark, kể cả khi không có chữ | 6 |
| 59 | Biển hiệu trong cảnh khi máy lia | Loại chữ trong cảnh, không phải chữ chèn | 6 |
| 60 | Âm thanh bị nhận nhầm một cửa sổ đơn lẻ | Không có sự kiện âm thanh (cần hai cửa sổ liền nhau) | 6 |
| 61 | Âm thanh cắt đỉnh | Lỗi cắt đỉnh, kèm khoảng thời gian | 6 |
| 62 | Hai cú máy cùng nơi, khác góc, không có tiếng | Quan hệ "góc khác" trong cùng phân cảnh | 7 |
| 63 | Câu hỏi "close-up sản phẩm" | Bộ lọc đúng như mục 5 nhóm 15; đổi câu hỏi lỗi thì lùi về tìm theo nghĩa | 8 |
| 64 | Tóm tắt có ý không nhịp nào làm chứng | Ý bị bỏ | 9 |
| 65 | Video tham khảo | Có thẻ phong cách; không nhịp nào của nó xuất hiện trong kết quả khớp kịch bản | 9 |
| 66 | Người chưa đồng ý xuất hiện trong bản dựng | Cổng quyền chặn xuất bản, có lý do | 9 |

## 12. Chi phí và thời gian

- Vision và SoundAnalysis chạy trên khung và âm thanh đã có; ước lượng trên giấy là vài phần trăm thời gian của bước mô tả bằng mô hình. Số thật được ghi ở lần chạy đầu của đợt 2.
- Giải mã phần cứng bù lại phần thời gian các bước mới thêm vào (mục 4.4).
- Số lời gọi mô hình mỗi nhịp tăng ít: mô tả, khung toạ độ, quan hệ và trạng thái nằm trong cùng một lời gọi; câu hỏi riêng chỉ dành cho trường mà bộ đo cho thấy hỏi gộp làm sai.
- Lượt quét dày (nhóm 07) chỉ chạy trong khoảng của sự việc, không chạy cả file.

## 13. Điều còn ngoài phạm vi

- Nhận diện danh tính người thật theo khuôn mặt với cơ sở dữ liệu bên ngoài: không làm. Sổ nhân vật chỉ gom người trong kho của người vận hành, và người vận hành đặt tên.
- Đánh giá giá trị nghệ thuật như một con số quyết định: điểm thẩm mỹ chỉ để sắp xếp, không để loại.
- Dự đoán độ giữ chân khi chưa có số liệu thật của kênh: chỉ là giả thuyết có ghi rõ.

## 14. Trạng thái triển khai (2026-10-15)

Đã có code, test tự động và đã chạy trên 10 clip DJI của kho thật:

| Phần | Nằm ở | Ghi chú |
|---|---|---|
| Adapter `vision` và `sound` (Swift, Apple Vision, SoundAnalysis); thêm nhận diện bàn tay | `adapters/apple.py`, `adapters/apple_see.swift` | Biên dịch lúc dùng lần đầu; máy khác không có thì các trường để trống |
| Thông số kỹ thuật đầy đủ (nhóm 01), giải mã phần cứng có đường lùi | `adapters/media.py` | |
| Dây chuyền `library.profile`: người, cỡ cảnh đo được, tư thế, nơi, chân trời, vùng chủ thể, ánh sáng, ngược sáng, màu, nhiệt độ màu, bảng màu, log, nhiễu, bố cục, độ sâu, chữ trên hình theo thời gian và loại, watermark không chữ, loại âm, độ lớn R 128, cắt đỉnh, gió, người nói trong khung | `library/profile.py`, `library/profiler.py` | Chạy trước bước mô tả |
| Hồ sơ cả file: nhịp dựng, ba giây đầu, lời kêu gọi hành động, độ hợp nền tảng, thẻ phong cách, chất lượng | `profile.asset_profile` | Màn hình Thư viện |
| Bộ từ vựng chuẩn, chặn tiếng Anh | `library/vocab.py` | |
| Mô tả phiên bản 3 (phiên bản 2 đã thử và bỏ, xem mục 7 dưới đây) | `library/understand.py` | |
| Kiểm tra chéo, cờ, hàng chờ xem lại | `profile.cross_checks`, API `/flags`, Hệ thống > Độ chính xác | |
| Lời nói: VAD, không mang ngữ cảnh, lọc câu bịa, siết ranh giới từ, gợi ý từ vựng, phân biệt người nói theo giọng | `library/transcribe.py`, `adapters/speech.py` | |
| Sự việc, ba pha, cụt đầu và cụt đuôi | `profile.events_of` | Từ hành động mô hình nêu; đỉnh theo chuyển động đo được |
| Phân cảnh qua nhiều file của một buổi quay | `profile.scenes_of`, `Profiler.publish_scenes` | Tên phân cảnh lấy từ nhãn, không gọi mô hình |
| Tìm cảnh giống cảnh (dấu vân hình ảnh) | API `/moments/{id}/alike` | |
| Bộ mẫu, đo theo trường, độ phủ, hiệu chỉnh độ tin cậy, cổng phát hành, so lần đo | `quality/fields.py` | |
| Khớp kịch bản dùng trường đã phát hành, nhãn mô hình đã phát hành đứng thay khi trường đo trống, phương án thay thế ở chỗ khác nhau | `sourcing/match.py` | |
| Nguồn gốc của mô tả: mô hình, prompt, từ vựng, số đo đã đưa | `moments.data.provenance` | |

**Mục 7, mô tả phân biệt, đã đổi theo số đo.** Phiên bản 2 cho mô hình xem mô tả của nhịp trước: trên clip 0050, mô hình 7B chép lại mô tả cũ và độ giống giữa hai nhịp kề nhau tăng từ 0,79 lên 0,95. Phiên bản 3 không cho xem nữa; "điểm mới" do code tính từ các vật được nêu ở hai nhịp. Độ giống còn 0,78.

**Đã làm sau đó:** giải luồng dữ liệu cảm biến của máy DJI (mục 4.5) theo định dạng protobuf, không cần schema (`library/telemetry.py`): góc máy đúng 55/55; khung để nhận diện lấy từ file gốc thay cho proxy; bám người, mặt, tay trong cú máy; điểm đầu và cuối hành động tới 0,1 giây; trạng thái trước và sau của sự việc; tóm tắt có dẫn chứng (thể loại, mục đích, khán giả, cấu trúc, cảm xúc); video tham khảo và mẫu định dạng từ phong cách; sự đồng ý của người xuất hiện ở cổng quyền; phát hiện C2PA; lịch sử sửa đáp án; sổ người theo khuôn mặt; số liệu kênh so với thuộc tính footage.

**Còn chưa làm:** gom vật và nơi chốn qua nhiều cú máy (sổ chỉ có người theo khuôn mặt, chưa đo trên người thật vì kho gần như không có mặt người); quan hệ không gian có khung toạ độ (mô hình 7B trả sai, cần thử lại với mô hình mạnh hơn); nhân quả; kiểm chữ ký C2PA (mới phát hiện có hay không); so PhoWhisper (cần một bản chép lời do người vận hành sửa tay làm đáp án); độ chính xác của phân biệt người nói và người nói trong khung (chưa có đáp án). Mô hình nhìn mạnh hơn đã so: xem `docs/PLAN.md`.
