# Xoá và sửa: Thùng rác trong NEXORA, sửa tên và thông tin

Trạng thái: thiết kế đã chốt, người vận hành giao cho tự quyết (2026-10-14).

## 1. Vì sao

Ngày 2026-10-14 NEXORA có hai lệnh xoá (nguyên liệu, dự án), cả hai đều **xoá thẳng**: dữ liệu biến mất khỏi cơ sở dữ
liệu ngay lúc bấm, chỉ khôi phục được bằng bản sao lưu. Một nhà dựng chuyên nghiệp cần xoá được mà không sợ bấm nhầm, và cần
sửa được những gì mình đặt ra (tên dự án, tên clip, buổi quay) mà không phải nhập lại. Hiện còn thiếu:

- không có Thùng rác, không hoàn tác được;
- không xoá được nhiều nguyên liệu một lúc;
- không xoá được một bản dựng riêng lẻ;
- không đổi được tên dự án trên giao diện (API có), không nhân bản được dự án ở cùng khung hình;
- không đổi được tên hiển thị và buổi quay của một nguyên liệu (cả hai đang suy ra từ đường dẫn file).

## 2. Nguyên tắc

1. **Xoá là chuyển vào Thùng rác.** Mục trong Thùng rác biến khỏi mọi danh sách, tìm kiếm, khớp kịch bản và việc nền,
   nhưng không mất gì. Khôi phục trả lại đúng như trước.
2. **Xoá vĩnh viễn chỉ xảy ra ở Thùng rác**: bấm "Xoá vĩnh viễn" một mục, "Dọn thùng rác", hoặc tự động sau 30 ngày.
   Xoá vĩnh viễn dùng đúng hai hàm đã có (`remove_asset`, `remove_project`).
3. **File gốc của người dùng không bao giờ bị xoá ngầm.** Xoá vĩnh viễn nguyên liệu để nguyên file gốc, trừ khi người
   vận hành đánh dấu "cũng chuyển file gốc vào Thùng rác của máy". Bản dựng do NEXORA làm thì vào Thùng rác của máy.
4. **Mỗi lần xoá có hoàn tác ngay** (thông báo nhỏ có nút "Hoàn tác").
5. Dự án đã có video đăng vẫn không xoá được (giữ hồ sơ đăng và số liệu).

## 3. Thùng rác

### Dữ liệu
- Cột mới `assets.trashed_at REAL` và `projects.trashed_at REAL` (NULL là không ở thùng rác).
- `AssetStore.assets()` và `ProjectStore.projects()` mặc định **bỏ qua** mục trong thùng rác; tham số
  `include_trashed=True` cho những chỗ cần thấy cả (chống nhập trùng file, giữ file bản dựng khi dọn bộ nhớ).
  Nhờ vậy mọi danh sách, vòng lặp việc nền, gợi ý kịch bản đều tự bỏ qua mà không phải sửa từng chỗ.
- `AssetStore.rejected()` (tập nguyên liệu không bao giờ được đề xuất hay tìm thấy) gồm cả nguyên liệu trong thùng rác.
- `asset(id)` và `project(id)` vẫn trả về mục trong thùng rác, kèm `trashed_at`.

### Nguyên liệu vào thùng rác
- Dừng việc đang chạy trên nó.
- Các câu kịch bản đang dùng nó trở về **thiếu hình**, lý do "Footage … đang ở Thùng rác". Lựa chọn cũ được cất trong
  `extras.trashed_pick` của câu đó.
- Khôi phục: câu nào vẫn đang thiếu hình và còn giữ `trashed_pick` của đúng nguyên liệu này thì nhận lại lựa chọn cũ.
  Câu đã được chọn clip khác trong lúc đó thì giữ lựa chọn mới.
- Mô tả, khung hình, số đo được giữ nguyên trong lúc ở thùng rác (khôi phục không phải phân tích lại).

### Dự án vào thùng rác
- Dừng việc đang chạy của nó; trợ lý bỏ qua nhiệm vụ của dự án trong thùng rác.
- Biến khỏi danh sách dự án, Tổng quan, chiến dịch, "Đã dùng trong" của nguyên liệu. Bản dựng và file giữ nguyên.
- Khôi phục: hiện lại như cũ.

### Dọn
- `purge_trash(older_than_days=30)` chạy lúc khởi động server; `purge_trash(0)` khi bấm "Dọn thùng rác".
- Một mục không xoá vĩnh viễn được (ví dụ dự án có video đã đăng) thì ở lại thùng rác và báo lý do.

### API
- `POST /api/v1/trash` với `{"assets": [...], "projects": [...]}`: chuyển vào thùng rác (một hoặc nhiều).
- `POST /api/v1/trash/restore` cùng dạng: khôi phục.
- `GET /api/v1/trash`: các mục, ngày xoá, ngày sẽ tự xoá vĩnh viễn.
- `DELETE /api/v1/trash` với `{"assets", "projects", "discard_files"}` hoặc rỗng là dọn hết: xoá vĩnh viễn.
- `DELETE /api/v1/assets/{id}` và `DELETE /api/v1/projects/{id}` giờ **chuyển vào thùng rác** (không còn xoá thẳng).

## 4. Sửa

- **Dự án**: ô "Tên dự án" ở đầu ngăn Thiết lập (dùng `PATCH /projects/{id}` sẵn có); nút **Nhân bản** tạo bản sao
  cùng khung hình (`POST /projects/{id}/duplicate`, dùng `clone` sẵn có).
- **Nguyên liệu**: tên hiển thị và buổi quay sửa được trong tab Thông tin (cột mới `assets.title`, `assets.session`;
  để trống là quay về giá trị suy ra từ file). Tên hiển thị được dùng ở mọi nơi hiện tên clip trong giao diện thư viện.
- **Bản dựng**: xoá một bản dựng riêng lẻ (`DELETE /renders/{id}`), file vào Thùng rác của máy; bản đã đăng không xoá được.

## 5. Giao diện

- Trang **Thùng rác** (`/thung-rac`), có lối vào từ thanh bên của Dự án và Thư viện kèm số mục. Mỗi mục: tên, loại, ngày
  xoá, "còn N ngày"; nút Khôi phục, Xoá vĩnh viễn; đầu trang có "Dọn thùng rác" và ô "cũng chuyển file gốc vào Thùng rác
  của máy".
- **Thư viện**: chế độ chọn nhiều (nút "Chọn"), thanh dưới có "Chuyển vào thùng rác (N)".
- Nút xoá trên thẻ dự án và trong tab Thông tin của nguyên liệu: hỏi lại, rồi thông báo có "Hoàn tác".

## 6. Kiểm thử

- Nguyên liệu vào thùng rác: biến khỏi thư viện, tìm kiếm, khớp; câu dùng nó thành thiếu hình; khôi phục trả lại lựa chọn;
  câu đã đổi clip thì không bị ghi đè.
- Dự án vào thùng rác: biến khỏi danh sách và "Đã dùng trong"; khôi phục; dọn xoá vĩnh viễn và chuyển bản dựng vào Thùng rác.
- Dọn theo tuổi: mục mới hơn 30 ngày ở lại.
- Đổi tên/buổi quay nguyên liệu, đổi tên và nhân bản dự án, xoá một bản dựng.

## 7. Không làm lần này

Thùng rác cho từng câu kịch bản (kịch bản đã có phiên bản), cho chiến dịch, cho mẫu đo; chọn nhiều dự án một lúc.
