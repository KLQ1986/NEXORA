# NEXORA — Kế hoạch triển khai MVP

Cập nhật: 2026-10-11. Thiết kế tham chiếu: `NEXORA_System_Design_v4.0` (các số mục bên dưới là mục của bản này).

## 1. Đích đến của MVP

Một video hoàn chỉnh được làm ra từ footage của chính người vận hành, đi hết dây chuyền B (mục 15.2), không cần gõ lệnh:

> nhập footage → hệ thống hiểu footage → viết kịch bản → hệ thống chọn đúng đoạn cho từng câu → dựng timeline có lời dẫn, phụ đề, nhạc → duyệt → xuất file MP4.

MVP **không** gồm: sinh video bằng AI (dây chuyền A), đăng tự động lên nền tảng, thí nghiệm và phân tích số liệu, các năng lực P1 và P2 ở mục 27.

## 2. Cách làm việc

- **Lát cắt dọc.** Mỗi lát cho ra một thứ chạy thử được từ đầu tới cuối, không xây xong cả một lớp rồi mới tới lớp khác.
- **Test trước.** Viết test, thấy nó thất bại, rồi mới viết code. Tiêu chí nghiệm thu lấy từ mục 26.
- **Giữ quy tắc lớp.** `uv run lint-imports` phải đạt trước khi coi một lát là xong (mục 4.4).
- **Spec viết đúng lúc.** Chỗ nào thiết kế còn mỏng thì viết spec một hai trang ngay trước khi xây phần đó, không viết trước cả loạt.
- **Thiết kế đi theo số đo.** Khi code chạy thật cho thấy thiết kế đoán sai, sửa v4.0 chứ không lách.
- **Mỗi lát một lần commit** (hoặc vài commit nhỏ), sau khi test và lint đều đạt.

Lệnh kiểm tra:

```bash
uv run pytest -q
uv run lint-imports
```

## 3. Các lát cắt

Cỡ là ước lượng tương đối (S nhỏ, M vừa, L lớn), không phải cam kết thời gian.

| # | Lát cắt | Cỡ | Phụ thuộc | Trạng thái |
|---|---|---|---|---|
| 1 | Lõi chạy việc | M | — | Gần xong (42 test đạt); còn lệnh dòng lệnh và bộ kiểm thử adapter dùng chung |
| 2 | Nhập một video | M | 1 | Xong phần chính (63 test đạt); còn phát hiện đứng hình, kiểm tra dung lượng đĩa, chuẩn hoá HDR |
| 3 | Hiểu video và tìm kiếm | L | 2 | Chưa bắt đầu |
| 4 | Khớp kịch bản với footage | L | 3 | Chưa bắt đầu |
| 5 | Dựng và render | L | 4 | Chưa bắt đầu |
| 6 | Web UI lõi | L | 2 (làm song song với 3–5) | Chưa bắt đầu |
| 7 | Video đầu tiên trên footage thật | S | 5, 6 | Chưa bắt đầu |

### Thứ tự thực hiện

Giao diện được làm xen kẽ với phần xử lý, để mỗi năng lực mới đều nhìn thấy và thao tác được ngay.

| Bước | Việc | Thuộc lát | Cần từ người vận hành trước khi bắt đầu | Trạng thái |
|---|---|---|---|---|
| 1 | Lõi chạy việc: trạng thái, worker, adapter, chi phí | 1 | — | Xong |
| 2 | Nhập video: kho tài sản, khung đen, proxy, API, dòng lệnh | 2 | — | Xong |
| 3 | Dọn nợ: hạ dung lượng proxy, phát hiện đứng hình, kiểm tra dung lượng đĩa, bộ kiểm thử chung cho adapter | 1, 2 | Cho phép cài bản FFmpeg đầy đủ hơn | Kế tiếp |
| 4 | Khung Web UI và hai màn hình đầu: Library, Runs | 6 | Chọn công nghệ front-end | |
| 5 | Hiểu video: chia đoạn, mô tả, chỉ mục | 3 | Chấm kết quả thử nghiệm; cho hay không cho dùng model cloud | |
| 6 | Tìm kiếm trong Library và màn hình Asset | 3, 6 | — | |
| 7 | Khớp kịch bản với footage | 4 | — | |
| 8 | Màn hình Project, kịch bản và Match review | 6 | — | |
| 9 | Dựng và render: timeline, lời dẫn, phụ đề, nhạc, QC | 5 | Mẫu định dạng số 1; chọn bộ render đồ hoạ; chọn giọng đọc | |
| 10 | Màn hình Timeline preview, Render review và Board | 6 | Chép giao diện Backlot hay viết lại (ý định thương mại) | |
| 11 | Video đầu tiên trên footage thật, đo và sửa | 7 | Footage thật | |

### Trạng thái sau lượt xây 2026-10-11

Các bước 1–10 của bảng trên đã có bản chạy được; bước 11 đã chạy trên bốn video thử nghiệm (chưa phải footage thật của người vận hành). 84 test đạt.

**Đã thử trọn luồng trên giao diện:** tạo dự án → nhập kịch bản 6 câu → hệ thống chọn clip → đổi một clip sang phương án khác → duyệt → dựng → kiểm tra tự động đạt → duyệt bản dựng. Kết quả là một file MP4 1280×720 dài 19 giây, có lời dẫn giọng Linh của macOS, phụ đề tiếng Việt, và một thẻ nền trơn cho câu không có footage.

**Lựa chọn đã tự quyết thay người vận hành (đổi được):** React + Vite + Tailwind cho giao diện; mô hình cục bộ qua Ollama (qwen2.5vl:7b để nhìn hình, bge-m3 để tìm theo nghĩa), không gửi gì lên cloud; giọng đọc Linh có sẵn của macOS; khung hình 1280×720 ngang; chưa cài bản FFmpeg đầy đủ.

**Số đo với mô hình cục bộ (12 câu của thử nghiệm):** lựa chọn đầu đúng đoạn 2/10 câu; đúng trong ba phương án đầu 7/10; một trong hai câu không có footage bị gán nhầm clip. Kém rõ so với lần Claude tự xem khung hình trong thử nghiệm. Hiểu bốn video (17 phút) mất khoảng 25 phút.

**Đã thêm ở lượt xây thứ hai (97 test đạt):** bước chấm ứng viên bằng khung hình thật và canh clip vào khung hình đúng nhất; video dọc 9:16 và vuông; nhạc nền tự hạ dưới lời dẫn; kiểm tra âm lượng; rà soát bản dựng (thiếu hình, nhịp, lặp, mở đầu); thông báo; gói xuất bản (video, phụ đề SRT, ba ảnh đại diện, tiêu đề, mô tả, ghi công, cờ nội dung tổng hợp); tự duyệt theo độ tin cậy; màn hình Bảng theo dõi có xem lại quá trình, dải timeline, hộp thông báo; dây chuyền sinh hình bằng AI (ảnh tĩnh duyệt trước, bộ dựng prompt, seed, giới hạn độ dài clip, ghi chi phí); lấy clip stock miễn phí qua OpenMontage chạy trong tiến trình riêng; nâng cấp cấu trúc cơ sở dữ liệu cũ.

**Số đo sau khi có bước chấm bằng khung hình:** 7/12 câu đúng (trước đó 2/10 lựa chọn đầu đúng), cả hai câu không có footage đều được báo thiếu; khớp 12 câu mất 7 phút với mô hình cục bộ.

**Chưa có so với thiết kế v4.0, và lý do:**

| Phần | Vì sao chưa |
|---|---|
| Sinh ảnh và video thật bằng AI | Dây chuyền đã có và đã test với nhà cung cấp giả lập; cần khoá API của một nhà cung cấp thật |
| Đăng lên nền tảng, thu số liệu, thí nghiệm | Cần tài khoản, khoá API và audit của nền tảng |
| Chuẩn hoá video HDR | Cần cài bản FFmpeg đầy đủ hơn |
| Dựng thô theo transcript, nhận dạng giọng nói | Cần cài thêm mô hình nhận dạng giọng nói |
| Reframe bám chủ thể, đồng bộ nhiều máy quay | Chưa làm; video dọc hiện cắt giữa khung |
| Canh hình theo từ khoá và phách nhạc | Chưa làm |
| Ảnh tĩnh làm nguyên liệu, hiểu thư viện nhạc, giọng của người vận hành | Chưa làm |
| Khớp khẩu hình, nâng độ phân giải, huấn luyện mô hình nhân vật | Chưa làm; phụ thuộc dây chuyền sinh hình thật |
| Thông báo của macOS, kênh nhắn tin | Chưa làm; hiện chỉ có hộp thông báo trong giao diện |

**Lỗi do thử trên giao diện phát hiện và đã sửa:** bước ghép cuối hỏng khi thư mục dữ liệu là đường dẫn tương đối.

### Lượt xây thứ ba, 2026-10-11

Đã xây, có test tự động (102 test đạt) và đã chạy trên trình duyệt, trừ khi ghi khác:

| Tính năng | Kiểm chứng |
|---|---|
| Màn hình Dòng thời gian trong dự án: các hàng Hình, Lời dẫn, Phụ đề, Nhạc theo đúng tỷ lệ thời gian; đầu phát đi theo video; bấm cảnh để nhảy tới; trượt đoạn lấy sớm hoặc muộn hơn; đổi sang cảnh khác; báo cảnh đã đổi mà chưa dựng lại; dựng lại ngay tại đó | Chạy trên trình duyệt với dự án 6 câu |
| Thông báo của macOS khi có việc chờ duyệt, bị dừng, thất bại, hoặc video dựng xong; bật tắt ở mục Hệ thống | Test tự động. Chưa nhìn tận mắt thông báo hiện lên màn hình |
| Ảnh tĩnh làm nguyên liệu, khi dựng có chuyển động đẩy máy chậm | Test tự động. Chưa thử trên giao diện vì nhập ảnh sẽ gọi mô hình thị giác, đang tạm dừng |
| Lời dẫn tự thu: đặt file `1.wav`, `2.m4a` theo số câu trong một thư mục; câu nào có file thì dùng giọng thu, câu còn lại dùng giọng máy | Test tự động. Ô nhập đã có trên giao diện, chưa thử với bản thu thật |
| Nhạc trong thư viện: nhập file nhạc, đo độ dài và độ lớn, chọn trong dự án | Chạy trên trình duyệt với một file âm thử |
| Sửa lỗi: video ngắn hơn 3 giây trước đây không ghép được | Test tự động |

### Lượt xây thứ tư, 2026-10-11

108 test đạt. Ba tính năng dưới đây và toàn bộ lượt thứ ba đã được chạy trên trình duyệt bằng một server thử riêng (cổng 8601) dùng mô hình giả, vì mô hình thị giác thật đang tạm dừng theo yêu cầu.

| Tính năng | Cách làm | Kiểm chứng |
|---|---|---|
| Cắt khung theo chủ thể cho video dọc và vuông | Mô hình nhìn một khung hình và cho biết chủ thể nằm ở đâu theo chiều ngang; người vận hành ghi đè bằng Bên trái, Chính giữa, Bên phải trên Dòng thời gian | Trình duyệt, mô hình giả. Xem khung hình thật của bản dựng: đúng phần được chọn |
| Chèn hình khác khi nói tới một từ trong câu | Tìm cảnh theo từ đó trong kho; thời điểm chuyển hình tính theo vị trí của từ trong câu | Trình duyệt, mô hình giả. Khung hình trước và sau thời điểm chuyển khác nhau đúng như mong đợi |
| Đồng bộ hai máy quay cùng một sự kiện | So độ lớn âm thanh của hai clip để tìm độ lệch; trên Dòng thời gian đổi sang góc máy khác ở đúng thời điểm đó | Trình duyệt: tìm đúng độ lệch 2,50 giây đã cài sẵn; từ chối hai clip không cùng sự kiện và clip không có tiếng |

Giới hạn cần biết: đồng bộ máy quay cần cả hai clip có âm thanh; thời điểm chèn hình là ước lượng theo vị trí chữ, chưa dựa trên nhận dạng tiếng nói; chất lượng tìm chủ thể của mô hình thật chưa được đo.

Chưa làm được vì đang chờ: chạy các phần cần mô hình thật trên giao diện (mô hình đang tạm dừng), và các mục bị chặn ở bảng trên.

### Chạy thử MVP bằng mô hình thật trên giao diện, 2026-10-11

Một video dọc 5 câu làm trọn trên giao diện với `qwen2.5vl:7b` và `bge-m3`: chọn clip có chấm bằng khung hình (3 câu có clip, 2 câu báo thiếu hình), lấp một chỗ thiếu bằng clip stock có giấy phép, chèn hình theo từ, dựng 720×1280 dài 17 giây, kiểm tra tự động đạt, duyệt, tạo gói xuất bản. Một dự án 2 câu khác được tự duyệt vì cả hai clip đều đạt 10/10. Một ảnh thật được nhập và mô tả.

Ghi nhận về chất lượng, để dành cho giai đoạn tối ưu (người vận hành yêu cầu hoàn thiện nền tảng trước):

- Câu "Những chiếc bánh trứng vàng ruộm vừa ra lò" bị báo thiếu hình dù kho có video làm bánh trứng.
- Hỏi mô hình vị trí chủ thể bằng một con số thì nó luôn trả lời 50. Đã đổi sang hỏi "trái, giữa, phải" (đúng 3 trên 3 ảnh thử). Trong video thật, 4 cảnh thì 1 cảnh lệch trái, 3 cảnh ở giữa; chưa chấm đúng sai.
- Khi nạp, `qwen2.5vl:7b` chiếm 13 GB RAM.

### Nền tảng, lượt 2026-10-11 (113 test đạt)

- [x] File cấu hình `nexora.toml` (`init-config` ghi ra mẫu; thiết lập gõ sai bị từ chối khi khởi động)
- [x] Sao lưu cơ sở dữ liệu mỗi lần khởi động và theo nút bấm; lệnh `restore` giữ lại bản bị thay
- [x] Quản lý dung lượng ở mục Hệ thống: xem từng loại dữ liệu, dọn dữ liệu tạm, trỏ lại nơi chứa footage
- [x] Chi tiết một lần chạy ở mục Tiến trình: từng lần thử, thời gian, lỗi; huỷ lần chạy
- [x] Nhật ký `data/logs/stages.jsonl`: mỗi bước một dòng
- [x] Hai luồng chạy: phân tích footage (nền) tách khỏi chọn clip và dựng video
- [x] Lệnh `doctor` và mục Kiểm tra hệ thống trên giao diện
- [x] `README.md`: cài đặt, lệnh, cấu trúc, cách tự khởi động cùng máy
- [x] Trợ lý sản xuất (lớp `nexora.agents`): nhận một mục tiêu, tự viết kịch bản, tìm clip, lấp chỗ thiếu bằng stock, dựng; dừng ở hai cổng duyệt; ghi lại từng quyết định theo vai
- [x] Giờ phân tích footage: chỉ cho việc nặng chạy trong khung giờ đã chọn
- [x] Ngân sách theo dự án cho việc sinh hình trả tiền

Đã chạy trên trình duyệt bằng server thử dùng mô hình giả: trợ lý làm trọn một video qua hai lần duyệt; giữ việc phân tích ngoài khung giờ trong khi việc nhập vẫn chạy; huỷ một lần chạy; trỏ lại nơi chứa footage sau khi thư mục đổi chỗ; lưu ngân sách. Lệnh `backup` và `restore` đã chạy trên dữ liệu thử. Trợ lý đã chạy một lần với mô hình thật trên giao diện: viết 5 câu, tìm đủ clip cho cả 5, dựng bản 56 giây, kiểm tra tự động đạt, qua hai lần duyệt. Ghi nhận cho giai đoạn tối ưu: câu do mô hình viết quá dài (mỗi cảnh 10 đến 14 giây), phần kiểm tra bản dựng đã cảnh báo cả 5 cảnh.

### Hoàn thiện Core và giao diện theo thiết kế v4.0, 2026-10-11 (121 test đạt)

Core (mục 5 và 23 của thiết kế):

- [x] Ghi lại mọi lần gọi công cụ và mô hình: việc gì, bao lâu, có lỗi không, tốn bao nhiêu
- [x] Ngân sách theo ngày và theo tháng; việc trả tiền không bắt đầu khi đã hết
- [x] Bảng năng lực: mỗi dây chuyền chạy được hay thiếu gì trên máy này
- [x] Lần chạy mới tự rút lại lần cũ cùng loại còn đang chờ duyệt
- [x] Tuỳ chọn thông báo: tắt từng loại, giờ không báo
- [x] Ghi chú khi không duyệt bản dựng, lưu cùng bản dựng đó

Giao diện (mục 22):

- [x] Tổng quan: việc chờ bạn, việc đang chạy, dự án gần đây, hiện trạng kho và máy
- [x] Chi phí: tiền so với ngân sách, thời gian máy theo từng công cụ
- [x] Hệ thống: thêm bảng năng lực và tuỳ chọn thông báo
- [x] Dự án: ô ghi chú khi từ chối bản dựng, danh sách các bản dựng trước

Năm điểm cuối so với thiết kế, đã xây (123 test đạt) và đã thử trên trình duyệt với dữ liệu thật trừ khi ghi khác:

- [x] Thư viện: chấm sao, bộ sưu tập, lọc theo loại, bộ sưu tập và số sao
- [x] Dòng thời gian: đổi vị trí câu; kịch bản lên phiên bản mới, mỗi câu giữ nguyên clip đã chọn
- [x] Danh sách cắt (EDL, CMX 3600) trỏ về file gốc để dựng tiếp trong DaVinci Resolve. Chưa nhập thử vào Resolve; mã thời gian nguồn tính theo 30 khung/giây và bắt đầu từ 0
- [x] Luồng thay đổi trực tiếp: màn hình tự làm mới ngay khi có thay đổi (đo được khoảng 0,1 đến 0,6 giây), vẫn giữ hỏi lại định kỳ làm dự phòng
- [x] Chọn mô hình theo loại việc trong `nexora.toml` (`judge_model`, `writer_model`); mới có test tự động, chưa chạy với hai mô hình khác nhau

### Chạy thử MVP cuối trên hệ thống đã hoàn chỉnh, 2026-10-12

Một video ngang 4 câu làm trọn từ giao diện bằng mô hình thật: chọn clip có chấm bằng khung hình (3 câu có clip, 1 câu báo thiếu hình), lấp chỗ thiếu bằng clip stock thuộc phạm vi công cộng, duyệt clip, dựng 1280×720 dài 13,8 giây, kiểm tra tự động đạt và không có điểm nào cần xem lại, duyệt bản dựng, tạo gói xuất bản, tải được EDL 4 cảnh. Bản dựng xong trong khi việc mô tả clip stock mới nhập vẫn còn chạy nền, tức hai luồng chạy tách nhau đúng như thiết kế. Mục Chi phí ghi lại 15 lần mô hình xem khung hình (121 giây), không lần gọi nào lỗi.

Xem lại khung hình của video này: ba cảnh đầu đúng nội dung (chợ, ấm moka, rừng lúc chạng vạng). Cảnh thứ tư sai: câu nói về đoàn tàu qua cầu sắt nhưng hình là bờ biển. Nguyên nhân: clip stock dài được lấy từ giây đầu tiên mà không xem hình có khớp câu hay không, và kiểm tra tự động không bắt được vì nó không so hình với lời. Việc cần làm đầu tiên của giai đoạn tối ưu: sau khi clip stock được mô tả xong, chấm và chọn đoạn khớp trong clip đó như với footage của người vận hành, hoặc trả lại trạng thái thiếu hình nếu không đoạn nào khớp.

Đã sửa (125 test đạt): clip stock được đề xuất ngay, và khi đã được mô tả xong thì hệ thống chấm, chọn đoạn khớp trong clip, hoặc trả về trạng thái thiếu hình. Thử lại đúng trường hợp trên bằng mô hình thật: thay vì bờ biển ở giây 0, hệ thống chọn giây 137 đến 141 của phim, nơi có cây cầu sắt. Còn chưa chuẩn: khoảng 2 giây đầu của đoạn này vẫn là cảnh đồi cát trước khi tới cây cầu, tức điểm vào còn sớm. Đây là độ chính xác của bước định vị trong đoạn, để dành cho giai đoạn tối ưu.

### Giao diện theo mục 22 của thiết kế, 2026-10-12 (126 test đạt)

Giao diện đã được thiết kế lại toàn bộ (khung chung, dải phim, lưới thư viện, bàn dựng) và bổ sung các tính năng thiết kế nêu mà trước đó chưa có:

- [x] Tiến trình: thử lại một bước đã thất bại; báo lần chạy có vẻ bị treo
- [x] Hệ thống: giọng đọc, mô hình theo từng việc, chế độ riêng tư (chặn mọi thứ gửi ra ngoài máy), thư mục theo dõi tự nhập footage, mẫu định dạng
- [x] Dự án: chọn mẫu định dạng; ghi mốc thời gian đang xem vào ghi chú khi từ chối bản dựng
- [x] Thư viện: ghi chú buổi quay cho từng nguyên liệu; tìm cảnh giống một cảnh đã có
- [x] Bảng theo dõi: trang kịch bản; cảnh báo bước bị treo
- [x] Thông báo: báo khi kịch bản còn câu thiếu hình
- [x] Nút dừng khẩn cấp luôn có ở thanh bên

Làm tiếp cùng ngày (127 test đạt, đã bấm thử trên giao diện với mô hình giả):

- [x] Kịch bản có cấu trúc: dòng bắt đầu bằng # là tên cảnh; mỗi câu có ghi chú "hình cần có" (dùng để tìm clip) và "chữ trên màn hình" (thay cho phụ đề); ghi chú đi theo câu sang phiên bản kịch bản mới
- [x] Hồ sơ thương hiệu trong mẫu định dạng: cỡ và vị trí phụ đề, cách đọc riêng (viết=đọc)
- [x] Gợi ý ý tưởng có thẻ điểm; điểm "có hình" đo từ kho; ý tưởng có rủi ro xếp sau; giao thẳng cho trợ lý
- [x] Bản dựng nháp: khi không thấy file gốc, hệ thống cắt từ bản xem và ghi rõ là bản nháp
- [x] Thông báo khi ổ đĩa sắp đầy hoặc mất nơi chứa footage, mỗi lần đổi trạng thái báo một lần

Làm tiếp (128 test đạt, đã bấm thử trên giao diện với mô hình giả và xem khung hình):

- [x] Nguồn tham khảo của dự án (tên, nơi xuất bản, ngày, đường dẫn, đoạn trích); câu nêu dữ kiện gắn với một nguồn; dữ kiện chưa có nguồn bị nêu ra khi kiểm tra bản dựng
- [x] Mỗi câu có thời lượng giữ hình tối thiểu và ghi chú âm thanh (ghi chú âm thanh đi vào file EDL; hệ thống chưa tự chèn hiệu ứng âm thanh)
- [x] Hồ sơ thương hiệu: kiểu chữ có chân hoặc không chân, màu chữ phụ đề, logo đặt ở góc
- [x] Phụ đề hai dòng được chia đều, không để một chữ lẻ ở dòng cuối

Chưa làm so với thiết kế: hệ thống tự đi tìm nguồn trên mạng (người vận hành hiện tự nhập nguồn); dựng thô theo lời nói (19.1, cần mô hình nhận dạng tiếng nói); đăng bài và số liệu (21, cần tài khoản).

### Hoàn thiện theo từng module, bắt đầu 2026-10-12

Planning (137 test đạt; đã bấm thử trên giao diện với mô hình giả):

- [x] Đọc nguồn từ một địa chỉ web do người vận hành đưa: lấy tên bài, nơi xuất bản, ngày và đoạn mở đầu. Chế độ riêng tư chặn việc này. Hệ thống chưa tự tìm bài trên mạng (cần một dịch vụ tìm kiếm)
- [x] Tìm câu nêu dữ kiện và đối chiếu với nguồn: mỗi câu nhận kết luận (nguồn xác nhận, trái với nguồn, chưa có căn cứ) kèm đoạn trích. Kết luận mà đoạn trích không có thật trong nguồn thì bị coi là chưa có căn cứ. Câu trái nguồn bị nêu ra khi kiểm tra bản dựng
- [x] Phản biện kịch bản và viết lại theo nhận xét thành phiên bản mới
- [x] Lịch biên tập: ngày dự định đăng cho từng dự án, lịch tháng kéo thả, báo video quá ngày
- [x] Radar cơ hội: footage chưa dùng vào video nào theo chủ đề; chủ đề đang theo dõi được đo bằng số cảnh khớp trong kho. Chưa có tín hiệu xu hướng từ nền tảng (cần tài khoản)
- [x] Trợ lý có thêm ba vai có giới hạn: Nghiên cứu (đọc tối đa 5 trang được chỉ định), Phản biện (một vòng, biên kịch trả lời một lần), Kiểm chứng. Việc đi quá 40 bước bị dừng

Library (145 test đạt; đã bấm thử trên giao diện, nhận dạng lời nói chạy bằng công cụ thật):

- [x] Ngữ cảnh cho footage không tiếng: tên file, thư mục (buổi quay), ngày quay và ghi chú của người vận hành đi vào câu hỏi mô tả. Ghi chú đổi thì lần mô tả lại hỏi mới, không dùng kết quả cũ
- [x] Ghi chú của người vận hành tìm được bằng ô tìm kiếm
- [x] Tầng khung hình: xem kỹ một đoạn theo từng khung khi cần (tối đa 8 khung mỗi đoạn)
- [x] Nhận dạng lời nói có mốc từng từ bằng whisper.cpp chạy trên máy (đã cài qua Homebrew, mô hình large-v3-turbo-q5 nằm ở `data/models`). Câu nói vào chung chỉ mục với mô tả hình. Footage không tiếng được bỏ qua
- [x] Buổi quay (cùng thư mục, cùng ngày), lọc theo buổi quay
- [x] Gạt một nguyên liệu ra: không được đề xuất cho kịch bản, không hiện khi tìm
- [x] Mỗi nguyên liệu cho biết đang dùng trong dự án nào; lọc "chưa dùng"

Ghi nhận để tối ưu sau: whisper nghe giọng đọc máy sai vài từ ("sạp" thành "sạc", "rau" thành "dao"); mốc từ liền nhau không có khoảng lặng nên câu được tách theo dấu phẩy và độ dài.

Sourcing (154 test đạt; đã chạy thật một câu chuyện ba cảnh: ảnh từ Pollinations, clip làm trên máy, dựng ra video dọc):

- [x] Nhiều nhà cung cấp cho cùng một loại hình, có định tuyến theo từng cảnh và thứ tự ưu tiên; nhà cung cấp hỏng, hết lượt hoặc bị chế độ riêng tư chặn thì chuyển sang nhà kế tiếp
- [x] Nhà cung cấp ảnh thật không cần khoá (Pollinations). Không có tài khoản thì chỉ được một đến ba ảnh rồi bị từ chối một lúc; hệ thống báo "hết lượt", giữ ảnh đã có và chạy tiếp khi bấm lại. Có token thì đặt `pollinations_token`
- [x] Nhà cung cấp clip chạy trên máy: biến ảnh đã duyệt thành clip có chuyển động máy (đẩy, kéo, lia). Đây không phải mô hình video; trong hình không có gì chuyển động
- [x] Hồ sơ nhân vật, bối cảnh, phong cách của dự án: câu nào nhắc tên thì prompt tả đúng như hồ sơ; ảnh tham chiếu được gửi kèm cho nhà cung cấp nhận ảnh
- [x] Chấm chất lượng ảnh bằng mô hình nhìn và vòng sửa có giới hạn (tối đa 2 lần làm lại), chọn bản tốt nhất, giữ hồ sơ các bản bị loại
- [x] Sửa từng cảnh: hình cần sinh, cỡ cảnh, chuyển động máy, nhà cung cấp, xin ảnh khác (seed mới). Chạy lại chỉ làm lại cảnh đã đổi
- [x] Kế hoạch cho câu thiếu hình: cảnh gần nhất trong kho, các cách xử lý máy này làm được, và danh sách cần quay thêm tải về được

Chưa làm: mô hình video thật (cần khoá của nhà cung cấp), huấn luyện mô hình nhân vật (mục P2, cần công cụ huấn luyện), chọn nguồn stock trên giao diện.

Edit (162 test đạt; đã chạy thật: bản ghi 14 giây có lời nói được cắt còn 9 giây và dựng ra video dùng chính tiếng của nó):

- [x] Dựng thô theo lời nói: bỏ khoảng lặng, tiếng đệm, câu nói lại (giữ lần sau); người vận hành chọn lại từng câu; kết quả là dự án sẵn sàng dựng, dùng âm thanh gốc
- [x] Từng cảnh: tốc độ (0,5 đến 2 lần), chống rung, dùng âm thanh gốc thay lời dẫn, tiếng động lấy từ thư viện
- [x] Cả video: làm sạch âm thanh (giảm ù và xì), cân màu giữa các cảnh
- [x] Bản xem thử nhanh: nửa kích thước, 15 khung/giây, không đọc lời dẫn mới, không cần duyệt clip, không có cổng duyệt
- [x] Chỉnh sửa bằng lời: mô hình chỉ được chọn trong 8 thao tác trên câu có số; danh sách hiện ra trước, áp dụng sau
- [x] Tái sử dụng sang khung hình khác thành dự án mới, giữ nguyên clip đã chọn
- [x] Gói bàn giao để dựng tay (CapCut): mỗi cảnh một clip sạch, phụ đề rời, nhạc, tờ hướng dẫn
- [x] Nhập lại bản hoàn thiện ở phần mềm khác: được đo như mọi bản dựng và tính là đã duyệt
- [x] Lồng tiếng nhân vật: câu viết "Tên: lời thoại" đọc bằng giọng riêng của nhân vật trong hồ sơ dự án
- [x] Phụ đề rời SRT và VTT; dịch phụ đề sang 7 ngôn ngữ với cùng mốc thời gian (bản dịch thiếu dòng bị từ chối)
- [x] Nâng chất lượng clip: phóng to 2 lần (lấy mẫu lại, không sinh chi tiết mới), làm mượt lên 50 hoặc 60 khung/giây; bản dựng cuối lấy từ bản đã nâng

Chưa làm: khớp khẩu hình (cần mô hình lip-sync), chuyển HDR về SDR (FFmpeg trên máy thiếu bộ lọc zscale), phóng to bằng mô hình học máy.

### Lát 1 — Lõi chạy việc

Mục thiết kế: 5, 6, 7.

- [x] Mô hình trạng thái Run → Stage → Attempt trên SQLite, sự kiện, nhận việc độc quyền, thử lại, cổng duyệt, huỷ, nút dừng khẩn cấp, khôi phục.
- [x] Worker: vòng lặp nhận việc → gọi hàm xử lý của stage → báo kết quả; heartbeat; dừng tại điểm an toàn; chạy khôi phục khi khởi động.
- [x] Đăng ký pipeline và hàm xử lý: module khai báo, lõi chạy.
- [x] Hợp đồng adapter: describe, estimate, submit, poll, cancel, reconcile; khuôn request, result, error; bảng mã lỗi chuẩn và phản ứng của lõi.
- [x] Adapter đầu tiên: FFprobe chạy như tiến trình con, có giới hạn thời gian.
- [x] Adapter FFmpeg: phát hiện khung đen, tạo proxy (ghi tên tạm rồi đổi tên khi xong), ảnh thu nhỏ.
- [ ] Bộ kiểm thử chung cho adapter (mục 7.6): mới có test riêng cho FFprobe và cho quy tắc riêng tư; chưa thành bộ dùng lại cho mọi adapter.
- [x] Bản ghi chi phí và chặn theo ngân sách của run.
- [x] Lệnh dòng lệnh: `python -m nexora ingest | worker | runs | assets | env | serve`.

**Xong khi:** một pipeline mẫu hai bước chạy qua worker và gọi FFprobe trên một file thật; dừng worker giữa chừng rồi chạy lại thì việc tiếp tục, không làm lại bước đã xong; adapter FFmpeg qua bộ kiểm thử chung.

### Lát 2 — Nhập một video

Mục thiết kế: 8, 15.1, 17.1, 19.9.1, 23.3.

- [x] Kho tài sản: Asset, AssetVersion bất biến, StorageVolume, nối lại ổ đĩa, phả hệ, tìm trùng theo checksum.
- [x] Các bước nhập: đăng ký và tính checksum, đọc thông số, phát hiện khung đen, tạo proxy 720p, ảnh thu nhỏ; file trùng được liên kết chứ không xử lý lại.
- [ ] Phát hiện đứng hình; chuẩn hoá tốc độ khung hình và HDR khi tạo proxy (cần bản FFmpeg có `zscale`).
- [x] Kiểm tra môi trường bản đầu: bộ lọc và bộ mã hoá của FFmpeg (`python -m nexora env`).
- [ ] Kiểm tra dung lượng trống trước khi nhập và trước khi render.
- [x] API: đăng ký file, xem run, xem danh sách tài sản. Mỗi luồng dùng một kết nối SQLite riêng.

**Xong khi:** nhập được bốn video của thử nghiệm; phần khung đen ở cuối video chợ Hội An được đánh dấu là không dùng được; ngắt giữa lúc tạo proxy rồi chạy lại thì tiếp tục; checksum file gốc không đổi.

**Đã đo (2026-10-11, bốn video thử nghiệm, 17 phút):** nhập hết 82 giây; phần khung đen của video chợ được phát hiện đúng (dùng được 0 → 2:25); checksum bốn file gốc không đổi. Proxy 720p ở 3 Mbps chiếm 325 MB, lớn hơn cả file gốc (205 MB): cần hạ bitrate và không tạo proxy cho phần khung đen.

**Còn cần:** cài bản FFmpeg đầy đủ hơn (bản hiện có thiếu bộ lọc chuyển HDR, mục 12.5).

### Lát 3 — Hiểu video và tìm kiếm

Mục thiết kế: 10, 11, 17.2, 18.2 (phần chỉ mục).

- [ ] Chia đoạn theo đổi cảnh và theo thay đổi hình ảnh.
- [ ] Lấy mẫu khung hình và ghép lưới có mốc thời gian (dùng lại cách của thử nghiệm).
- [ ] Adapter model nhìn hình; đầu ra có cấu trúc; lời nhắc được ghi phiên bản.
- [ ] Mô tả theo đoạn và theo cả video, kèm tham chiếu bằng chứng.
- [ ] Moment, chỉ mục FTS5, embedding văn bản, tìm kiếm lai.
- [ ] Lớp riêng tư: tài sản "chỉ cục bộ" không bao giờ tới adapter cloud.
- [ ] Lưu kết quả theo (checksum, phiên bản bộ phân tích, cấu hình); không phân tích lại khi không có gì đổi.

**Xong khi:** tìm "cá tươi" trả về đoạn mâm cá của video chợ trong ba kết quả đầu; chạy lại trên video không đổi thì không có lời gọi model nào; test âm tính về riêng tư đạt.

**Cần trước:** kết quả chấm thử nghiệm; quyết định có cho dùng model cloud không; spec ngắn về lời nhắc và mật độ lấy mẫu.

### Lát 4 — Khớp kịch bản với footage

Mục thiết kế: 15.2 (bước 1–7), 18.1, 18.2.

- [ ] Bảng dữ liệu: Project, Script có phiên bản, Shot, ShotNeed, Candidate, Selection, Gap.
- [ ] Từ câu kịch bản ra nhu cầu hình; mở rộng truy vấn.
- [ ] Tìm rộng bằng chỉ mục, rồi chấm kỹ bằng keyframe thật.
- [ ] Định vị điểm vào và điểm ra bằng lấy mẫu dày.
- [ ] Chọn trên cả chuỗi: không lặp clip, đa dạng cỡ cảnh.
- [ ] Khoảng trống kèm đề xuất xử lý.
- [ ] Ghi lại quyết định đúng/đổi/sai của người vận hành.

**Xong khi:** chạy 12 câu của thử nghiệm qua hệ thống thật, ra danh sách đoạn chọn có điểm vào, điểm ra, và hai khoảng trống; đo được tỷ lệ lựa chọn đầu tiên trùng với đáp án người vận hành đã chấm.

**Cần trước:** xử lý được câu có hai hành động (phát hiện từ thử nghiệm).

### Lát 5 — Dựng và render

Mục thiết kế: 12, 16.4, 19, 20.1.

- [ ] Timeline có phiên bản và TimelineItem.
- [ ] Mẫu định dạng số 1.
- [ ] Lời dẫn: adapter giọng đọc, mốc thời gian từng từ, thời lượng câu quyết định độ dài clip.
- [ ] Phụ đề qua bộ render đồ hoạ; tiêu đề và logo.
- [ ] Nhạc nền, tự hạ nhạc dưới lời, chuẩn hoá âm lượng.
- [ ] Render theo từng clip có lưu đệm; xem thử bằng proxy; render bản cuối.
- [ ] QC tất định.

**Xong khi:** từ danh sách đoạn đã duyệt ra một file MP4 có lời dẫn, phụ đề, nhạc và qua QC; đổi một clip thì chỉ render lại đúng clip đó.

**Cần trước:** spec mẫu định dạng số 1; chọn bộ render đồ hoạ; nghe thử và chọn giọng đọc tiếng Việt.

### Lát 6 — Web UI lõi

Mục thiết kế: 22.

- [ ] Các màn hình: Home, Library, Asset, Project và kịch bản, Match review, Board, Timeline preview, Render review, Runs, Settings kèm nút dừng khẩn cấp.
- [ ] Luồng sự kiện trực tiếp cho Board và Runs.

**Xong khi:** làm trọn một video từ nhập footage tới xuất file mà không mở terminal.

**Cần trước:** chọn công nghệ front-end; spec bố cục màn hình; quyết định chép giao diện Backlot hay viết lại (phụ thuộc ý định thương mại).

### Lát 7 — Video đầu tiên trên footage thật

- [ ] Chạy trọn dây chuyền trên footage của người vận hành.
- [ ] Đo: số phút thao tác cho mỗi phút thành phẩm, chi phí, tỷ lệ chọn đúng, thời gian xử lý.
- [ ] Lập danh sách lỗi và chỗ thiết kế đoán sai; cập nhật v4.0.
- [ ] Quyết định bước sau: làm P1 của dây chuyền B, hay bắt đầu dây chuyền A.

**Xong khi:** có một video người vận hành chịu đăng, và một bảng số đo.

## 4. Quyết định đang chờ người vận hành

| Quyết định | Chặn lát nào |
|---|---|
| Chấm kết quả thử nghiệm (`spike/report/index.html`) | 3, 4 |
| Có cho dùng model cloud với footage riêng không | 3 |
| NEXORA có thể thành sản phẩm thương mại không | 6 (giao diện Backlot), và việc gọi công cụ OpenMontage |
| Công nghệ front-end và bộ render đồ hoạ | 5, 6 |
| Mẫu định dạng số 1: tỷ lệ khung, độ dài, kiểu phụ đề, giọng | 5 |

## 5. Rủi ro chính

- **Chất lượng hiểu footage thật.** Thử nghiệm mới chạy trên video tải về và do chính model chấm. Lát 7 là phép thử thật; nếu lát 3 và 4 cho kết quả kém thì dừng lại sửa trước khi làm lát 5.
- **Phạm vi.** Lát 5 và 6 lớn. Nếu kéo dài, cắt bớt: bỏ nhạc và tiêu đề khỏi lát 5, bỏ Board và Timeline preview khỏi lát 6.
- **Hành động nhỏ, ngắn trong khung rộng** là chỗ model nhìn kém nhất (kết quả thử nghiệm). Cần lấy mẫu dày và cho người vận hành đổi phương án dễ dàng.

## 6. Sau MVP

Theo mục 27 của v4.0: các mục P1 của dây chuyền B (dựng thô theo transcript, reframe, tự chấp nhận theo độ tin cậy, gợi ý ý tưởng từ kho), rồi dây chuyền A (hoạt hình sinh bằng AI) dùng lại toàn bộ từ bước dựng timeline trở đi.

## 7. Cách cập nhật kế hoạch này

Đánh dấu ô khi một việc xong và test đạt. Khi một lát xong, cập nhật cột Trạng thái và ghi một dòng về điều đã học được nếu nó làm đổi các lát sau.
