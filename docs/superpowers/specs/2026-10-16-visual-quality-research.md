# Visual Quality Engine: nghiên cứu các repo phục hồi hình ảnh (2026-10-16)

Đánh giá 17 repo người dùng đề xuất, cộng các công cụ khác tìm được khi nghiên cứu. Tiêu chí: giấy phép (của code *và* trọng số mô hình), còn được duy trì không, chạy được trên Mac Apple Silicon không (máy: Apple M4, 24 GB, macOS 27), có hợp footage thật của người dùng không (DJI Osmo Action 6, 4K, 10-bit, D-Log M), và dùng cho mục nào trong 18 tính năng của Quality Engine.

Dữ liệu giấy phép và hoạt động lấy từ GitHub API ngày 2026-10-16. Hai phép đo chạy trên máy này, với khung thật của clip 0002 (vườn dừa).

## Kết luận theo repo

| # | Repo | Giấy phép | Cập nhật cuối | Mac | Kết luận |
|---|---|---|---|---|---|
| 21 | REAL Video Enhancer | AGPL-3.0 | 2026-09 | có app arm64, backend NCNN | **Tham khảo / benchmark.** Không nhúng (AGPL). Danh sách mô hình (RIFE, SPAN 2×, OpenProteus) là gợi ý để chọn mô hình |
| 22 | Real-ESRGAN | BSD-3 (bản ncnn MIT) | 2024-08 | ncnn có bản macOS | **Có điều kiện.** Đo `x4plus` trên M4: 13,8 s cho 960×540, khoảng 3–4 phút một khung 4K. Hình bị "vẽ lại": lá thành kiểu sơn dầu, xoá vân gạch. Không dùng cho footage 4K; chỉ cho ảnh hoặc nguồn nhỏ |
| 23 | BasicSR | Apache-2.0 | 2024-07 | PyTorch | **Không dùng trực tiếp.** Là framework huấn luyện; NEXORA không huấn luyện mô hình |
| 24 | MMagic | Apache-2.0 | 2024-08 | khó (mmcv thiên về CUDA) | **Không dùng.** Ngừng phát triển, phụ thuộc nặng |
| 25 | VRT | **CC BY-NC 4.0** | 2026-09 | PyTorch, nặng | **Không dùng**: chỉ cho phi thương mại. Đọc paper để tham khảo |
| 26 | RVRT | **CC BY-NC 4.0** | 2022-10 | PyTorch | **Không dùng**: phi thương mại, ngừng phát triển |
| 27 | EDVR | không có file giấy phép | 2021-08 | — | **Không dùng.** Đã gộp vào BasicSR |
| 28 | SwinIR | Apache-2.0 | 2024-05 | PyTorch/MPS | **Có điều kiện, chỉ cho ảnh tĩnh** (khử nhiễu, artifact JPEG). Xử lý từng khung riêng nên dễ nhấp nháy trên video, lại chậm |
| 29 | VapourSynth | LGPL-2.1 | 2026-10 | có bottle Homebrew | **Tuỳ chọn về sau.** FFmpeg trên máy đã đủ bộ lọc cho P0/P1; nhiều plugin VapourSynth không có cho Mac |
| 30 | Vapourkit | GPL-3.0 | 2026-10 | **chỉ Windows/Linux** | **Không dùng** |
| 31 | OpenColorIO | BSD-3 | 2026-10 | Homebrew 2.6, pip | **Dùng được (P1)** khi cần quản lý màu đúng chuẩn (nhiều máy quay, ACES). Không có sẵn D-Log M vì DJI không công bố đường cong; LUT của DJI được bọc trong OCIO bằng `FileTransform` |
| 32 | ProPainter | **S-Lab, phi thương mại** | 2025-02 | PyTorch | **Không dùng** cho sản phẩm. Tham khảo cho mục 16 |
| 33 | VEnhancer | không có giấy phép | 2024-09 | cần GPU lớn | **Không dùng.** Sinh lại nội dung, không hợp footage thật |
| 34 | Enhance-A-Video | Apache-2.0 | 2025-03 | chạy trong mô hình diffusion | **Không cho footage thật.** Dành cho dây chuyền A (video sinh bằng AI, chạy trên RunPod) |
| 35 | Anime4K | MIT | 2024-08 | shader | **Chỉ cho dây chuyền A** nếu ra hình kiểu anime |
| 36 | waifu2x-ncnn-vulkan | MIT | 2026-04 | có bản macOS | **Không mặc định** cho footage thật (dành cho tranh, anime) |
| 37 | Video2X | AGPL-3.0 | 2026-03 | **không có bản Mac** | **Không dùng** |

## Những gì nên dùng (không có trong danh sách ban đầu)

| Công cụ | Giấy phép | Cho mục | Bằng chứng |
|---|---|---|---|
| **Apple VideoToolbox `VTFrameProcessor`** | có sẵn trên macOS | 7 khử nhiễu theo thời gian; 13 nội suy khung (`hasDiscontinuity` báo điểm cắt); 10 siêu phân giải ×4 (cho nguồn nhỏ); motion blur; optical flow | Đo trên máy: cả 4 bộ đều `isSupported`. Lọc nhiễu theo thời gian chạy **45 khung/s trên 4K 10-bit** (`&xv0`), nhanh hơn thời gian thực. Cường độ 1,0 làm mềm lá và vỏ cây, nên phải chọn cường độ theo từng shot và có kiểm tra (mục 17). Cần một helper Swift nhỏ, như helper SigLIP |
| **LUT chính thức của DJI (D-Log M → Rec.709)** + FFmpeg `lut3d` | của DJI | 4 | DJI không công bố đường cong D-Log M, nên LUT của chính hãng là cách đúng. `lut3d` có sẵn trong FFmpeg trên máy. Tên máy đọc được từ `encoder=DJI OsmoAction6` |
| **Gyroflow** | GPL-3.0, chạy như chương trình riêng | 11 | README hiện tại có Osmo Action 6 trong danh sách hỗ trợ. File DJI có quaternion theo từng khung (đã đọc được trong `_telemetry.json`). Lưu ý: ổn định hình trong máy (RockSteady) có thể làm mất dữ liệu cần dùng |
| **RIFE (rife-ncnn-vulkan)** | MIT, có bản macOS | 13 (phương án thứ hai) | Nếu bộ nội suy của Apple không đủ tốt |
| **Bộ lọc FFmpeg trên máy** | LGPL/GPL | 5, 7, 9, 12, 14 | Có: `nlmeans`, `bm3d`, `hqdn3d`, `atadenoise`, `cas`, `unsharp`, `deflicker`, `deband`, `gradfun`, `deblock`, `lut3d`, `colortemperature`, `vibrance`, `curves`, `eq`, `minterpolate`. **Thiếu** `zscale` (tone mapping HDR) và `vidstab` |

## Hệ quả cho thiết kế

- P0 và P1 làm được hoàn toàn trên máy, không cần mô hình AI tải về: LUT DJI + bộ lọc FFmpeg + Apple VTFrameProcessor + Gyroflow.
- Mô hình AI phục hồi (Real-ESRGAN, SwinIR…) chỉ dùng có điều kiện: cho ảnh tĩnh và nguồn nhỏ, không cho 4K, và sau khi kiểm tra mô hình không "vẽ lại" hình.
- Ba repo có giấy phép phi thương mại (VRT, RVRT, ProPainter) và hai repo AGPL hoặc không có giấy phép, không có bản Mac (Video2X, VEnhancer) bị loại khỏi phần chạy thật.
- Mọi bộ lọc làm thay đổi texture (khử nhiễu, làm nét) cần cường độ theo từng shot và phép kiểm temporal QA (mục 17) trước khi áp vào cả clip.

## Đánh giá lại khi không xét giấy phép (2026-10-16)

NEXORA chỉ dùng cá nhân, nên giấy phép không còn là lý do loại một repo. Những repo trước bị loại vì giấy phép được xét lại chỉ theo kỹ thuật:

| Repo | Chạy trên máy này | Kết luận mới |
|---|---|---|
| **ProPainter** | Có: `get_device()` chọn **MPS** của Apple. Có sẵn `resize_ratio` và `subvideo_length` để chạy clip dài ở độ phân giải thấp hơn | **Dùng cho mục 16** (xoá vật, inpainting) ngay trên máy, ở 720p–1080p. 4K quá nặng |
| **VRT / RVRT** | Kém: phép deformable convolution/attention viết cho CUDA (`deform_attn_cuda_kernel.cu`), trên MPS phải chạy bằng CPU; mô hình rất tốn bộ nhớ | **Dùng trên RunPod** cho vài shot quan trọng: deblur do chuyển động (mục 8, VRT có mô hình huấn luyện trên DVD/GoPro), siêu phân giải video, khử nhiễu theo thời gian. Không chạy trên máy |
| **REAL Video Enhancer** | Có bản arm64; backend Python (NCNN qua Vulkan, PyTorch) | **Lấy backend** (RIFE 4.x, các mô hình phóng to gọn như SPAN, phát hiện điểm cắt, đọc ghi khung qua FFmpeg). Đo RIFE với bộ nội suy của Apple, rồi chọn cái tốt hơn cho mục 13 |
| **Gyroflow** | Có bản macOS và CLI | **Dùng cho mục 11**: gọi CLI, hoặc nhúng `gyroflow-core` (Rust) |
| **VEnhancer** | Cần GPU rất lớn | Dây chuyền A trên RunPod |
| **Video2X** | Không có bản Mac; các engine bên trong (Real-ESRGAN, RIFE bản ncnn) thì có | Dùng thẳng các engine đó, không cần Video2X |
| **Vapourkit** | Chỉ Windows/Linux | Không dùng. Bản thân VapourSynth vẫn cài được trên Mac bằng Homebrew |

Bộ công cụ đề xuất sau khi đánh giá lại:
- **Mặc định, chạy trên máy:** LUT DJI + bộ lọc FFmpeg + Apple VTFrameProcessor + Gyroflow, đo bằng NIQE/PSNR/SSIM và bộ tạo lỗi giả lập của BasicSR.
- **AI chạy trên máy, có điều kiện:** ProPainter (mục 16); RIFE/SPAN từ REAL Video Enhancer, nếu thắng bản của Apple.
- **AI trên RunPod:** VRT/RVRT cho deblur và phục hồi shot quan trọng; VEnhancer và Enhance-A-Video cho dây chuyền A.

## Không chỉ DJI: Quality Engine nhận mọi nguồn (2026-10-16)

Người dùng xác nhận engine không chỉ xử lý video và ảnh gốc của Osmo Action 6, mà cả từ nhiều nguồn khác. Mỗi loại nguồn có cách mã hoá màu, mức nén, tốc độ khung và kiểu lỗi riêng, nên engine phải nhận ra loại nguồn trước khi chọn cách xử lý.

| Loại nguồn | Đặc điểm | Engine cần |
|---|---|---|
| Máy quay quay log / HDR | DJI D-Log M, Apple Log, Sony S-Log3, Canon C-Log2/3, Panasonic V-Log, ARRI LogC, RED; HLG/PQ, Dolby Vision từ iPhone | **Sổ đăng ký máy quay và profile màu**. OpenColorIO 2.6 có sẵn chuyển đổi cho Apple Log, ARRI LogC3/4, Canon C-Log2/3, Panasonic V-Log, RED Log3G10/RedLogFilm, Sony S-Log3 (các gamut), HLG, PQ. Không có: DJI D-Log/D-Log M, GoPro, Fuji, Nikon, nên dùng LUT của hãng. HDR → SDR cần `zscale`/`libplacebo` (gói `ffmpeg-full`) hoặc tone mapping của Apple |
| Điện thoại | Tốc độ khung thay đổi (VFR), HDR HLG/Dolby Vision, xoay khung, HEVC | Đổi về tốc độ khung cố định (`fps`), tone mapping, sửa xoay |
| Stock, video tải từ mạng, mạng xã hội | 8-bit, nén nặng, thường 720p–1080p, bị nén nhiều lần nên có khối và dải màu, có khi là "4K giả" (phóng to từ nguồn nhỏ) | Phát hiện độ phân giải thật bằng phân tích tần số; deblock/deband; siêu phân giải cho nguồn ≤1080p (Apple ×4, SPAN/Real-ESRGAN) |
| Video do AI sinh | Nhấp nháy, texture "bơi", vật biến dạng, thường 720p/24 khung/s | Temporal QA nặng tay hơn; nội suy khung; siêu phân giải; Enhance-A-Video ngay khi sinh |
| Footage cũ, lưu trữ | Xen kẽ dòng (interlaced), telecine, SD 4:3, hạt, phai màu | Deinterlace (`bwdif`, `nnedi`), IVTC (`fieldmatch` + `decimate`), giữ đúng tỉ lệ khung, khử hạt |
| Quay màn hình, đồ hoạ | Chữ sắc nét, mảng màu phẳng, VFR | **Không** khử nhiễu, **không** làm nét; chỉ đổi định dạng và tốc độ khung |
| Ảnh tĩnh | HEIC, JPEG, RAW/DNG, hướng xoay EXIF, ICC (Display P3) | Giải mã RAW bằng CoreImage/libraw, quản lý màu theo ICC; khử artifact JPEG (SwinIR/FBCNN); phóng to (Real-ESRGAN hợp với ảnh); phục hồi mặt cho ảnh (GFPGAN/CodeFormer) |

Những khả năng làm engine vượt trội, áp dụng cho mọi nguồn:
1. **Hồ sơ nguồn có độ tin cậy:** đọc metadata (thẻ màu, `encoder`, EXIF, tag riêng của từng hãng) và đo trên hình (độ phẳng log, phân bố sáng, phổ tần số, nhịp khung). Báo khi thẻ mâu thuẫn với hình (DJI D-Log M gắn thẻ `bt709`). Không nhận ra profile thì nói không nhận ra.
2. **Phân loại nội dung:** footage máy quay, quay màn hình, hoạt hình/đồ hoạ, video AI sinh, ảnh. Mỗi loại có một công thức khác nhau; làm nét quay màn hình hay khử nhiễu hoạt hình sẽ làm hỏng hình.
3. **Thước đo khách quan:** VMAF (`libvmaf` đã có trong FFmpeg trên máy), NIQE, PSNR/SSIM, và thước đo theo thời gian (chỉ số nhấp nháy, sai số khi dời khung theo optical flow của Apple).
4. **Định tuyến theo tầng:** bộ lọc cổ điển → bộ xử lý của Apple → AI trên máy → AI trên RunPod. Mỗi tầng chỉ dùng khi tầng trước không đủ, và kết quả phải qua thước đo.
5. **Bộ đo chuẩn bằng lỗi giả lập** cho từng loại nguồn, để biết bộ lọc nào hợp nguồn nào trước khi áp lên file thật.

Công cụ cần thêm vào máy: `ffmpeg-full` (Homebrew) cho `zscale`, `libplacebo` và `vidstab`.
