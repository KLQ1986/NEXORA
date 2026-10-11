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
