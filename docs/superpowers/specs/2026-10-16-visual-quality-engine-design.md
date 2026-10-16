# Visual Quality (VQ): thiết kế (2026-10-16)

Nghiên cứu nền: `2026-10-16-visual-quality-research.md`. Danh sách 18 tính năng (A–F) là của người dùng.

## 1. Mục tiêu

Ảnh và video, **từ bất kỳ nguồn nào**, ra khỏi NEXORA với màu, độ sáng, độ nét, độ ổn định và độ sạch đúng mức tốt nhất mà nguồn cho phép, không bịa nội dung. Mọi thay đổi đều đo được trước và sau, và hoàn tác được.

Nguồn gồm: máy quay ghi log/HDR (DJI, iPhone, Sony, Canon, Panasonic, ARRI, RED…), điện thoại, stock và video tải từ mạng, video do AI sinh, footage cũ, quay màn hình, ảnh (HEIC, JPEG, RAW).

Thành công nghĩa là:
- Footage log (D-Log M của kho hiện có) ra màu Rec.709 đúng, không còn xám phẳng, trong mọi bản dựng và mọi lần trích xuất.
- Mỗi bộ lọc đã qua bộ đo lỗi giả lập, và chỉ được áp khi cải thiện thước đo mà không làm hỏng theo thời gian.
- Không đoán: nguồn không nhận ra profile thì được báo, không bị chuyển màu theo phỏng đoán.

## 2. Nguyên tắc

1. **Không phá file gốc.** Engine sinh ra **công thức** (recipe), không sửa file. Công thức được áp khi dựng, khi trích xuất, khi xem trước, và bỏ hoặc đổi lúc nào cũng được.
2. **Đọc trước, xử lý sau.** Engine đọc Video Intelligence (nhiễu, phơi sáng, rung, log, shot, chuyển động đã được đo), chỉ đo thêm phần còn thiếu.
3. **Theo tầng:** bộ lọc FFmpeg → bộ xử lý của Apple (VTFrameProcessor) → AI trên máy → AI trên RunPod. Chỉ lên tầng tiếp khi tầng trước không đủ, và tầng nào cũng qua thước đo.
4. **Đo được, không cảm tính.** Mỗi bước có thước đo: VMAF, PSNR/SSIM so với nguồn (độ trung thành), NIQE (độ tự nhiên), và thước đo theo thời gian.
5. **Theo từng shot.** Tham số (cường độ khử nhiễu, phơi sáng…) đặt theo từng shot, không đặt một lần cho cả clip.

## 3. Kiến trúc

**Tên:** domain **Visual Quality (VQ)**. Code ở `nexora.modules.visual_quality`, bộ đọc chung ở `nexora.core.visual_quality`, bảng `vq_*`, lệnh `nexora vq <file>`, API `/api/v1/vq/...` (file bất kỳ) và `/api/v1/assets/{id}/vq` (asset trong thư viện). Mục "Chất lượng hình" trên giao diện.

**Độc lập hoàn toàn** (người dùng duyệt 2026-10-16):
- Không import module nào khác, và không module nào import nó (luật phân lớp).
- Dữ liệu riêng (`vq_*`).
- **Video Intelligence là tuỳ chọn.** Có kết quả đo sẵn thì dùng cho nhanh, không có thì VQ tự đo phần cần thiết (shot, chuyển động, nhiễu, phơi sáng, rung).
- **Chạy trên mọi file, không cần nhập vào thư viện**, qua CLI hoặc API. Đầu vào là một file hoặc một asset; đầu ra là hồ sơ nguồn, công thức, và file đã xử lý hoặc bản xem trước.
- Thư viện, khâu dựng (`edit`), khâu trích xuất (`library/extract.py`) và sau này dây chuyền A chỉ là bên gọi. Chúng đọc công thức đã duyệt qua `core/visual_quality.py`.

```
nguồn ─▶ SourceProfiler ─▶ ContentClassifier ─▶ Assessor + DefectMapper
                                   │                      │
                                   ▼                      ▼
                         ColorRegistry ──▶ RecipePlanner (theo shot) ──▶ Preview + TemporalQA ──▶ Recipe (đã duyệt)
                                                                                                        │
                                       render (edit) / extract (library) / export ◀─────────────────────┘
```

### 3.1 Thành phần

| Thành phần | Mục | Việc |
|---|---|---|
| `SourceProfiler` | A1 | Đọc metadata (codec, bit depth, fps, VFR, độ phân giải, xen kẽ dòng, thẻ màu, HDR/Dolby Vision, rotation, `encoder`, EXIF/ICC của ảnh, dữ liệu cảm biến DJI) và đo trên hình (độ phẳng log, histogram, phổ tần số để biết độ phân giải thật, nhịp khung). Ra **Source Profile** có độ tin cậy, kèm cảnh báo khi thẻ và hình mâu thuẫn, và thông tin tương thích |
| `ContentClassifier` | — | Footage máy quay / quay màn hình / hoạt hình–đồ hoạ / video AI sinh / ảnh. Dùng nhãn Vision có sẵn, độ phẳng của mảng màu, mật độ cạnh, và metadata. Mỗi loại có cách xử lý riêng (quay màn hình thì không khử nhiễu, không làm nét) |
| `Assessor` | A2 | Điểm từng chiều theo shot: nét, nhiễu (luma/chroma), tương phản, cháy/thiếu sáng, bão hoà, khối nén, dải màu, NIQE. Dùng lại các giá trị đã đo của Video Intelligence, thêm phần thiếu |
| `DefectMapper` | A3 | Bản đồ lỗi theo khung/shot, với mức nghiêm trọng: thiếu sáng, nhiễu, motion blur vs mất nét, khối, dải màu, nhấp nháy, rung, kèm vùng cần xử lý cục bộ (lưới ô trên khung) |
| `ColorRegistry` | B4 | Sổ đăng ký profile màu: các chuyển đổi có sẵn của OpenColorIO 2.6 (Apple Log, S-Log3, C-Log2/3, V-Log, ARRI LogC3/4, RED, HLG, PQ), LUT của hãng (DJI D-Log M, GoPro…) đặt trong `data/luts/`, và bước tone mapping HDR → SDR (`zscale`/`libplacebo`). Mỗi profile có điều kiện nhận diện (máy + đặc điểm đo được). Chỉ áp khi khớp |
| `ExposureBalance` | B5 | Tự đề xuất phơi sáng, highlight, shadow, tương phản, cân bằng trắng và tint theo từng shot, giữ màu da (vùng da nhận từ khuôn mặt Vision), không cho cháy. Người dùng chỉnh tay đè lên được |
| `RecipePlanner` | F18 | Từ hồ sơ nguồn + bản đồ lỗi + loại nội dung ra công thức cho từng shot: các bước theo đúng thứ tự (khử xen kẽ → tốc độ khung cố định → khử khối/dải → khử nhiễu → chuyển màu → phơi sáng/WB → ổn định → làm nét → phóng to → nội suy), mỗi bước có tầng xử lý, tham số và lý do |
| Bộ xử lý (processors) | C, D | Mỗi bước là một bộ cắm chung một giao diện: `ffmpeg` (chuỗi bộ lọc), `apple_vt` (helper Swift: lọc nhiễu theo thời gian, nội suy khung, siêu phân giải ×4, optical flow), `gyroflow` (CLI), về sau `local_ai` (ProPainter, RIFE, SPAN) và `runpod` (VRT/RVRT) |
| `TemporalQA` | F17 | Trên bản xem trước: chỉ số nhấp nháy (độ sáng trung bình theo khung), sai số dời khung theo optical flow (texture "bơi", ghosting), lệch màu theo thời gian, viền giả. So trước và sau; bước nào làm xấu thì bị loại |
| `Benchmark` | — | Lấy khung sạch từ kho, tạo lỗi đã biết bằng `degradations.py` của BasicSR (nhiễu, mờ, nén, thu nhỏ), chạy từng bộ lọc, đo khôi phục bằng PSNR/SSIM/NIQE. Dùng để chọn tầng và tham số mặc định cho từng loại nguồn |

### 3.2 Công thức (recipe)

```json
{"recipe_id": "rcp_…", "asset_id": "…", "version": 3, "source_profile": "dji_osmo_action6_dlogm",
 "shots": [{"t_start": 0.0, "t_end": 5.23, "content": "camera",
            "steps": [{"op": "color_transform", "tier": "ffmpeg", "params": {"lut": "dji_dlogm_rec709.cube"}, "why": "D-Log M (máy + độ phẳng đo được)"},
                      {"op": "denoise", "tier": "apple_vt", "params": {"strength": 0.35}, "why": "nhiễu luma mức trung bình"}],
            "metrics": {"vmaf": 94.1, "niqe_before": 5.8, "niqe_after": 4.9, "flicker": 0.4}}],
 "status": "proposed | approved | rejected", "decided_by": "policy | operator"}
```

- Kết quả của tầng không phải FFmpeg (Apple, Gyroflow, AI) được lưu đệm thành file trung gian, khoá bằng `(checksum nguồn, đoạn, công thức của bước)`. Đổi một bước thì chỉ bước đó và các bước sau chạy lại.
- `edit/render.py` và `library/extract.py` hỏi `core/visual_quality.py` công thức đã duyệt của đoạn cần dùng, rồi áp: bước FFmpeg ghép vào chuỗi bộ lọc của segment, bước khác dùng file trung gian.

### 3.3 Dữ liệu

- `vq_profiles(asset_id, data, confidence, analyzer, at)`: hồ sơ nguồn và loại nội dung.
- `vq_defects(asset_id, t_start, t_end, kind, severity, region, analyzer)`: bản đồ lỗi.
- `vq_recipes(recipe_id, asset_id, version, data, status, decided_by, at)`: công thức theo phiên bản.
- `vq_metrics(recipe_id, t_start, t_end, metric, before, after)`: thước đo.
- Bộ phân tích được khai báo phiên bản như Video Intelligence, nên đổi cách tính thì biết phần nào đã cũ.

### 3.4 API và màn hình

- Asset trong thư viện: `GET /api/v1/assets/{id}/vq` (hồ sơ nguồn, điểm từng chiều, bản đồ lỗi, công thức hiện hành); `POST …/vq/plan`; `POST …/vq/preview {t, seconds}` (ảnh và video trước/sau, kèm thước đo); `POST …/vq/recipe/approve`, `…/reject`; sửa tham số từng bước.
- File bất kỳ: `POST /api/v1/vq/jobs {path}` cùng các bước như trên, kết quả để ở `data/vq/<job>/`. CLI: `nexora vq <file> [--plan] [--preview T] [--apply] [--out file]`.
- Thư viện có thêm mục **"Chất lượng hình"**: hồ sơ nguồn, cảnh báo, công thức đề xuất, thanh kéo trước/sau và các thước đo.

## 4. Các đợt

| Đợt | Gồm | Đo trên |
|---|---|---|
| **1 (P0)** | SourceProfiler + ContentClassifier; Assessor/DefectMapper (phần còn thiếu, cùng NIQE); ColorRegistry (OCIO + LUT DJI + tone mapping HDR); ExposureBalance; RecipePlanner; TemporalQA cơ bản (nhấp nháy, lệch màu); xem trước trước/sau; áp công thức vào dựng và trích xuất, giữ đúng thông tin màu; Benchmark | 0059 (D-Log M); một nguồn khác loại (video iPhone HLG hoặc một clip stock) |
| **2 (P1)** | Khử nhiễu (Apple theo thời gian, `nlmeans`/`bm3d`), làm nét (`cas`), deflicker, deband/deblock, khử xen kẽ và IVTC, nội suy khung biết điểm cắt (Apple, so với RIFE), ổn định (Gyroflow cho nguồn có dữ liệu con quay, `vidstab` cho nguồn khác), phóng to cho nguồn nhỏ (Apple ×4, SPAN), TemporalQA đầy đủ (optical flow) | 0002 (nhiễu, nghiêng, rung khi đi bộ); một clip tải từ mạng |
| **3 (P1/P2)** | Deblur (VRT/RVRT trên RunPod), xoá vật (ProPainter trên máy), relight/HDR cục bộ, phục hồi mặt (ảnh: GFPGAN/CodeFormer), ảnh tĩnh (khử lỗi JPEG, phóng to Real-ESRGAN) | Một shot có vật cần xoá; một ảnh nén nặng |

Mỗi đợt: test tự động, chạy thật trên **một** nguồn mỗi loại, commit, ghi số đo vào tài liệu này.

## 5. Kiểm thử

- Test đơn vị cho từng thành phần, với ảnh và video tổng hợp (lỗi đã biết).
- Bộ đo lỗi giả lập (`Benchmark`) chạy như một test chậm, cho mỗi bộ lọc và mỗi loại nguồn: phải cải thiện PSNR/SSIM so với bản bị lỗi, và không làm NIQE xấu đi.
- Đầu–cuối: lập công thức → xem trước → duyệt → dựng/trích xuất. Kiểm thông tin màu và VMAF của file ra.

## 6. Rủi ro và cách giữ

| Rủi ro | Cách giữ |
|---|---|
| Chuyển màu sai profile | Chỉ áp khi máy và đặc điểm đo được cùng khớp. Không chắc thì cảnh báo, chờ người dùng chọn |
| Khử nhiễu làm bệt texture (đã thấy ở cường độ 1,0) | Cường độ theo shot, giới hạn bởi PSNR/SSIM so với nguồn, cộng TemporalQA |
| AI bịa chi tiết (đã thấy với Real-ESRGAN) | AI không phải mặc định. Chỉ dùng khi bộ đo cho thấy hơn tầng cổ điển, và được đánh dấu rõ là có sinh nội dung |
| Chậm trên clip dài | Xem trước vài giây, lưu đệm theo bước, xử lý theo shot, chạy nền theo hàng đợi |
| Một nguồn chưa từng gặp | Hồ sơ nguồn nói rõ phần không nhận ra; công thức chỉ gồm các bước an toàn (đổi định dạng, không đổi màu) |

## 7. Cần từ người dùng

- File LUT D-Log M → Rec.709 chính thức của DJI cho Osmo Action 6, đặt ở `data/luts/`.
- Khi tới đợt 1: một video iPhone (HLG) hoặc một clip stock, để thử nguồn thứ hai.

Đã sẵn sàng: `ffmpeg-full` (`zscale`, `libplacebo`, `vidstab`, `libvmaf`) được NEXORA dùng qua `ffmpeg_binary`.

## 8. Khớp với kiến trúc NEXORA (đối chiếu với code, 2026-10-16)

1. **Công cụ ngoài là adapter.** Helper Swift cho Apple `VTFrameProcessor` (giống `adapters/apple_see.swift`), Gyroflow (CLI), OpenColorIO, về sau ProPainter/RIFE/SPAN và RunPod (adapter `RunPodUpscale` đã có) đều nằm ở lớp `adapters`, đăng ký trong `AdapterRegistry` với tên năng lực: `ffmpeg`, `apple_frames`, `gyroflow`, `color`, `restore_local`, `restore_remote`. `modules/visual_quality` chỉ gọi theo tên năng lực; adapter nào vắng thì bước đó báo không làm được, không làm hỏng cả công thức.
2. **Việc dài chạy bằng pipeline của orchestrator**: `vq.profile` (hồ sơ nguồn, phân loại, đánh giá, bản đồ lỗi), `vq.plan`, `vq.preview`, `vq.apply`, có stage, lane nền, thử lại, huỷ, và hiện trên màn hình Tiến trình. CLI `nexora vq` và API chỉ gửi việc. Asset trong thư viện dùng `asset_id` làm `subject_ref`; file ngoài thư viện dùng mã job `vqj_…`.
3. **Đọc và ghi tách nhau, như Video Intelligence**:
   - `core/visual_quality.py` là bộ đọc: các module khác (`edit`, `library`) đọc công thức đã duyệt từ đây.
   - `core/visual_quality_store.py` là bộ ghi.
   - Import-linter: thêm `nexora.modules.visual_quality` vào luật "module domain không import nhau"; thêm luật cấm mọi module khác import `core.visual_quality_store`.
4. **Một mối cho chất lượng hình.** Hai chỗ đang làm việc này sẽ chuyển về VQ:
   - Pipeline `library.enhance` (phóng to lanczos, làm mượt khung bằng `minterpolate`) thành công thức của VQ. Nút trên giao diện giữ nguyên, chỉ gọi sang VQ.
   - Trong "treat" của khâu dựng, phần chuyển HDR → SDR (`color_transfer`) và ổn định (`stabilise`) được thay bằng công thức đã duyệt của VQ cho đoạn đó. Khi chưa có công thức, khâu dựng giữ cách cũ, để không có gì hỏng trong lúc chuyển.
5. **Bổ sung cho thiết kế v4.0.**
   - v4.0 đặt "enhancement" (LUT, khử nhiễu, phóng to, ổn định) trong nhóm công cụ dựng, gọi qua OpenMontage.
   - Nay đó là một domain riêng, vì nó nhận mọi nguồn, chạy cả ngoài thư viện, và có thước đo riêng.
   - Ranh giới với `modules/quality`: `quality` kiểm tra **bản dựng** (QC, review, quyền, độ đúng của các trường), còn `visual_quality` lo **chất lượng hình của nguồn**.
