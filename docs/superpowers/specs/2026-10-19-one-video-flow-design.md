# Một luồng cho một video

Ngày: 2026-10-19 · Trạng thái: người vận hành yêu cầu triển khai ngay ("triển khai luôn đi").

## Vấn đề

Người vận hành phải bấm qua lại nhiều chỗ để làm xong một video:

- **Bắt đầu ở hai nơi.** Có thể bấm "Làm video mới" ở Dự án (chỉ nhập tên), hoặc vào Mission Control ở mục Vận hành để giao trợ lý làm video theo chủ đề. Muốn có kịch bản theo chủ đề thì phải mở dự án, tìm nút "Từ chủ đề…" trong bước Kịch bản.
- **Storyboard nằm ngoài các bước.** Nó là một link phụ dưới "Kịch bản", không có số thứ tự, và mở sang một trang có phần đầu riêng.
- **Hai thanh bước.** Trang Storyboard có thêm một thanh 6 bước riêng đánh số 1–6 (Kịch bản, Storyboard, Shot plan, Gán asset, Timeline nháp, Render). Thanh này trùng tên với các bước chính nhưng đánh số khác.
- **Thanh bước ngang chỉ có trên màn hình nhỏ** (`lg:hidden`). Trên máy tính, các bước chỉ nằm trong menu bên trái.
- **Việc của trợ lý chỉ thấy ở trang dự án.** Sang Storyboard, nơi trợ lý để lại ứng viên clip chờ chọn, thì không còn thấy trợ lý đang làm gì.

Người vận hành dùng cả hai cách: tự làm từng bước, và giao trợ lý làm rồi chỉ vào duyệt. Cả hai cách phải đi chung một luồng.

## Thiết kế

### 1. Một chỗ bắt đầu, ba cách bắt đầu

Bấm "Video mới" (ở Dự án, ở thanh trên, hoặc ở Tổng quan) mở cùng một form. Form có thêm lựa chọn **Cách bắt đầu**:

| Cách | Việc xảy ra |
|---|---|
| **Tự làm** | Như hiện nay: tạo video, mở bước Kịch bản. |
| **Theo chủ đề** | Tạo video, mở bước Kịch bản với bảng "Kịch bản từ chủ đề" (Claude Code viết) đã mở sẵn, chủ đề lấy từ tên video. |
| **Giao trợ lý** | Gửi tên làm mục tiêu cho trợ lý sản xuất (`POST /api/v1/agent/tasks`, có tìm stock), rồi mở ngay video trợ lý vừa tạo. |

Mission Control giữ nguyên, nhưng chỉ dùng cho nhiệm vụ **nhiều video**.

### 2. Bốn bước, giống nhau ở mọi trang của một video

```
① Kịch bản  →  ② Hình & Storyboard  →  ③ Dựng & duyệt  →  ④ Xuất bản      ·  Dòng thời gian · Bảng theo dõi
```

- **Storyboard thành bước ②**, có đèn trạng thái như các bước khác:
  - chờ người duyệt (vàng) khi có clip hay ứng viên chờ chọn;
  - xong (xanh) khi đã duyệt chọn clip.
- **Thanh bước ngang hiện trên mọi kích thước màn hình**, ở cả trang dự án lẫn trang Storyboard. Hai trang có cùng thanh, cùng thứ tự, cùng đèn.
- **Thanh 6 bước riêng của Storyboard không còn cạnh tranh với các bước chính.** Bỏ "Kịch bản" và "Render" (đã là bước ① và ③), không đánh số nữa. Thanh chỉ còn là tiến độ *bên trong* bước ②: Storyboard · Shot plan · Gán asset · Timeline nháp.

### 3. Trợ lý đi theo video

Thẻ "Trợ lý sản xuất" (trợ lý đang làm gì, đang chờ gì) hiện ở **cả trang Storyboard**, ngay dưới thanh bước, không chỉ ở trang dự án.

## Ngoài phạm vi

- Không gộp Phòng chiếu, Thư viện hay Mission Control vào trang dự án; chúng vẫn là kho và hộp thư chung.
- Không đổi đường dẫn (`/du-an/<id>`, `/du-an/<id>/storyboard`), để link cũ vẫn chạy.

## Kiểm tra

- Chạy typecheck và build giao diện.
- Kiểm tra trên trang thật bằng Playwright:
  - thanh 4 bước giống nhau trên trang dự án và trang Storyboard;
  - Storyboard là bước ②;
  - form "Video mới" có ba cách bắt đầu, và "Theo chủ đề" mở sẵn bảng chủ đề.
- Không tạo video thật cho cách "Giao trợ lý" trong lúc kiểm tra, vì cách đó gọi Claude Code của người vận hành.
