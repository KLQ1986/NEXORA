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

## Bổ sung: Mission Control là nhà chung (cùng ngày)

Người vận hành yêu cầu:

> "Trang vận hành đổi lên thành Mission Control luôn… gom luôn menu dự án… sơ đồ workflow theo style hitech… click vào node nào thì màn hình chức năng của node đó hiện ra bên dưới."

**Điều hướng**
- Mục "Vận hành" trên thanh trên cùng đổi tên thành **Mission Control**.
- Mục **Dự án được gộp vào** Mission Control. Các đường dẫn `/du-an/...` vẫn giữ.

**Một menu trái** (`OpsSide`), dùng giống nhau ở mọi trang của Mission Control, dự án và vận hành. Menu có bốn nhóm:

1. **Mission Control:** Board, Nhiệm vụ, Phê duyệt, Agents, Chất lượng, Artifacts, Ngân sách & tài nguyên, Nhật ký. Phê duyệt và Nhiệm vụ có số đếm.
2. **Vận hành:** Tiến trình, Chi phí, Thông báo, Thùng rác, Hệ thống.
3. **Video:** các bộ lọc.
4. **Dự án:** danh sách video.

Tab của Mission Control lấy từ địa chỉ trang (`?tab=`), nên các mục trong menu trái mở đúng tab.

**Sơ đồ dây chuyền** (`web/src/Pipeline.tsx`) thay cho thanh tab ngang và thanh 4 bước. Có 11 node:

N01 Nhiệm vụ → N02 Nghiên cứu → N03 Kịch bản → N04 Kiểm chứng → N05 Tìm clip → N06 Stock → N07 Storyboard → N08 Dựng → N09 QC → N10 Duyệt → N11 Xuất bản.

- **Trạng thái node:** xong, đang chạy, chờ bạn, lỗi hoặc chưa tới.
  - Khi có trợ lý làm video đó, trạng thái lấy từ bước của trợ lý.
  - Khi không có, lấy theo tiến độ của dự án.
  - Node QC báo lỗi khi bản dựng không qua QC.
- **Hình thức:** lưới mờ; node có mã `Nxx` viết bằng chữ đơn cách; đường nối chảy sáng vào node đang chạy; node chờ bạn nhấp nháy.
- **Bấm vào node** mở màn hình của nhóm node đó ngay bên dưới:

  | Node | Màn hình mở ra |
  |---|---|
  | N01–N04 | Kịch bản |
  | N05–N07 | Storyboard |
  | N08–N10 | Dựng |
  | N11 | Xuất bản |

  Nhóm node của màn hình đang mở được khoanh viền.

**Vị trí của sơ đồ**
- Đầu trang Mission Control: pipeline của video đang theo dõi, có ô chọn video. Mặc định là video đang làm.
- Trên Board: bảng **"Dây chuyền đang chạy"**, mỗi video đang làm một hàng pipeline thu gọn, kèm việc trợ lý vừa làm.
- Đầu trang dự án và trang Storyboard, thay cho thanh 4 bước.

## Đổi hướng: node mở trang riêng (2026-10-20)

Người vận hành thấy cách "bấm node thì màn hình hiện ngay bên dưới" không còn đủ chiều cao để xem hết thông tin. Đổi lại:

- **Sơ đồ dây chuyền chỉ còn trên Board** của Mission Control: sơ đồ lớn của video đang theo dõi, và các hàng thu gọn trong "Dây chuyền đang chạy". Các tab khác của Mission Control, trang dự án và trang Storyboard không còn sơ đồ.
- **Bấm một node thì sang hẳn trang của bước đó**: `/du-an/<id>?tab=…&from=board`, hoặc `/du-an/<id>/storyboard?from=board`.
- **Trang mở từ Board có nút "‹ Board"** để quay về `/phong-may?video=<id>`:
  - ở trang dự án, nút nằm chỗ đường dẫn quay lại trên đầu trang;
  - ở trang Storyboard, nút nằm đầu hàng trợ lý.
  - Đổi bước bằng menu trái vẫn giữ nút này.
- Mở thẳng trang dự án (không qua Board) thì nút quay lại như cũ: về sản phẩm hoặc danh sách dự án; từ Storyboard thì về Kịch bản.
