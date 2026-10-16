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

## 9. Đưa code từ các repo nghiên cứu về (2026-10-16)

Bốn cách, tuỳ bản chất của thứ cần lấy:

1. **Chép code (vendor)** vào `src/nexora/third_party/<repo>/`, ghi repo và commit gốc ở đầu mỗi file. Chỉ cho code nhỏ chạy được trong môi trường chính (numpy, scipy, OpenCV). Gồm: NIQE, PSNR/SSIM và `degradations.py` của BasicSR; `tile_process` và DNI của Real-ESRGAN. Đợt 1.
2. **Clone repo vào `data/tools/<tên>/`, môi trường Python riêng**, dựng bằng `scripts/setup-<tên>.sh`, gọi qua helper JSON-lines và một adapter, giống SigLIP. Cho code nặng (PyTorch, mô hình lớn): backend của REAL Video Enhancer (RIFE 4.x, SPAN, phát hiện điểm cắt) ở đợt 2; ProPainter, SwinIR ở đợt 3; VRT/RVRT chạy trên RunPod ở đợt 3; VEnhancer, Enhance-A-Video cho dây chuyền A.
3. **Gọi chương trình có sẵn qua adapter**: Gyroflow (CLI), Real-ESRGAN và RIFE bản ncnn cho Mac, VapourSynth nếu cần. Đợt 2.
4. **Học ý tưởng, tự viết lại**:
   - phát hiện điểm cắt trước khi nội suy (REAL Video Enhancer);
   - chép thông tin màu từ bộ giải mã sang bộ mã hoá, và processor factory (Video2X);
   - frame server lười có bộ đệm (VapourSynth);
   - lấy điểm ảnh thật từ khung lân cận trước khi sinh (ProPainter);
   - căn chỉnh theo chuyển động rồi gộp khung (EDVR/VRT/RVRT/BasicVSR).

Lý do không chép thẳng mọi thứ vào môi trường chính:
- mỗi repo nặng cần phiên bản PyTorch và thư viện riêng, để chung sẽ làm hỏng nhau;
- ghi commit gốc thì cập nhật được từng phần;
- đi qua adapter thì thay được khi bộ đo cho thấy có cái tốt hơn.

Mọi thứ đưa về phải qua bộ đo lỗi giả lập trước khi thành mặc định.

## 10. Đã làm và số đo (2026-10-17)

### Đợt 1 (commit f435523, fc2b0f4)

- Hồ sơ nguồn, nhận diện màu (LUT DJI chính thức, OCIO, HDR), đánh giá theo shot, công thức theo shot có phiên bản, xem trước có kiểm tra theo thời gian, áp vào dựng, trích xuất và bản nâng cấp.
- 0059 (D-Log M): nhận ra Osmo Action 6 D-Log M, độ tin cao; xem trước pass.
- Bộ đo lỗi giả lập trên một khung sạch của 0059: phát hiện 7/7, sửa có ích 7/7.

### Đợt 2 (commit 0a0d3d8, 2ae2945)

- Bộ xử lý khung của Apple (VTFrameProcessor, helper Swift), đo trên M4:
  - lọc nhiễu theo thời gian: 4K, 61 khung trong 1,7 giây;
  - nội suy 30 → 60: 4K, 61 khung trong 3,8 giây;
  - siêu phân giải ×4: 960×540 → 3840×2160, 30 khung trong 10,9 giây.
- Ổn định hình:
  - `vidstab` hai lượt;
  - Gyroflow khi file có dữ liệu con quay. Gyroflow chạy đầu tiên, trên file gốc, rồi cắt đúng số khung, vì nó render dư khoảng 3 khung sau điểm cắt.
  - Cả 13 clip DJI trong thư viện **không** có dữ liệu con quay (quay với RockSteady bật), nên với footage này vidstab là tầng dùng được.
- Các bước nhìn qua nhiều khung (nội suy, ổn định, deflicker, khử nhiễu) luôn chạy theo từng shot, không trộn qua điểm cắt.
- Chạy thật trên 0002 (xem trước 3 giây, 2 phút 13 giây cả phân tích): lọc nhiễu Apple, levels, deflicker; kiểm tra theo thời gian pass.
- Sửa lỗi phát hiện khi chạy thật:
  - ảnh tĩnh của xem trước từng lọc nhiễu từ t tới hết file; nay chỉ chuẩn bị 1 giây quanh khung đó;
  - khung đo từng bị phóng to lên 960 px với nguồn nhỏ, làm mất nhiễu khi đo; nay không bao giờ đo trên khung phóng to.

### Đợt 3 (commit 87ec0c6, 2eb3825, 389035a, 66e446e)

- **Ảnh HEIC và RAW:**
  - HEIC qua `sips` của macOS, giữ EXIF và ICC;
  - RAW qua LibRaw (`rawpy`), 16 bit, cân bằng trắng của máy. Core Image của Apple không mở được DNG của Osmo Action, LibRaw thì được: 4000×3000 trong 0,4 giây;
  - hồ sơ ghi định dạng, số bit và máy của file gốc.
- **Real-ESRGAN** (bản ncnn, GPU Apple qua MoltenVK), cho ảnh tĩnh:
  - phục hồi ảnh nén nặng (×4 rồi về cỡ cũ);
  - phóng to ảnh nhỏ tới chiều cao cần.
  - Chỉ giữ khi NIQE tốt hơn bước cổ điển ít nhất 0,5. Khi giữ, nó thay luôn deblock, deband và khử nhiễu.
  - Trên ảnh JPEG chất lượng 12 từ 0042: NIQE 2,68 so với 4,64 của bước cổ điển → giữ.
  - Trên vân giả 1/f: NIQE 14,4 so với 9,3 → không giữ, dùng deblock. Đúng như thiết kế: AI không phải mặc định.
  - Bộ đo, so AI với cổ điển: AI luôn tự nhiên hơn (NIQE) nhưng kém sát gốc hơn (PSNR, SSIM thấp hơn 0,1–2 dB), vì nó vẽ lại chi tiết. Vì thế bước này luôn gắn nhãn "AI sinh chi tiết".
- **Phục hồi khuôn mặt (ảnh tĩnh):**
  - Apple Vision tìm khuôn mặt và 5 điểm;
  - CodeFormer (ONNX, môi trường riêng) vẽ lại, trộn về qua mặt nạ mềm;
  - chỉ đề xuất cho mặt nhỏ (dưới 160 px) hoặc ảnh có nhiễu, mềm hay khối nén; chỉ giữ khi NIQE vùng mặt tốt hơn 0,5;
  - trên khung VOA bị thu nhỏ 3 lần và nén chất lượng 25: NIQE vùng mặt 7,76 → 7,09, giữ.
- **Xoá vật trong video (ProPainter, MPS):**
  - người dùng kéo khung trên ảnh xem trước; không bao giờ tự đề xuất;
  - xử lý một vùng quanh vật, gấp đôi cỡ vật, giới hạn 640×360 điểm ảnh; dán lại chỉ vùng đó lên khung gốc 10 bit;
  - ngoài vùng xoá, sai khác với nguồn bằng đúng sai khác của riêng ProRes (trung bình 2,2 mã 10 bit).
  - Đo trên M4 24 GB: 30 khung 640×360 mất 36–74 giây (RAFT 10 vòng, fp16). Lớn hơn diện tích đó, GPU treo quá 10 phút, nên diện tích bị giới hạn.
  - Chất lượng: vật nhỏ trong shot ổn định thì được. Vật lớn sát ống kính trong shot cầm tay (ngón tay ở 0002) thì xoá được nhưng vùng lấp mờ thấy rõ ở 4K.
- **Đo nhiễu và khử nhiễu, sửa sau khi bộ đo chạy trên ảnh lá cây 0042:**
  - Cách đo cũ đọc vân lá thành nhiễu (σ 10,8 trên ảnh sạch). Nay đo theo khối 16×16 và lấy 10% khối yên nhất, nhân 1,1: cùng ảnh đọc 3,2. Footage phẳng (0059) vẫn đọc gần đúng nhiễu thật.
  - Cường độ khử nhiễu chọn theo "method noise": phần bộ lọc bỏ đi không được vượt mức nhiễu đo được. Thử lần lượt 1,0 / 0,85 / 0,7, không xuống dưới 0,7.
  - Kết quả: 0059 vẫn 7/7. Trên 0042 (lá dày, vốn là JPEG), nhiễu mạnh nay lợi 2,9 dB thay vì mất 1,2 dB, nhưng SSIM vẫn giảm. Khử nhiễu trên vân lá dày vẫn là giới hạn đã biết của `nlmeans`.

### Phần cuối đợt 3 (2026-10-17)

- **Khử mờ:**
  - Trên máy: NAFNet (bản ONNX của OpenCV, MIT), chia ô 512 có chồng mép. Bản export này cần mỗi cạnh ít nhất 384 px nên ô được đệm thêm. Chạy khoảng 1,3 giây mỗi ô trên CPU; CoreML không nhanh hơn.
  - Dùng cho ảnh tĩnh và cho video tới 720p (khoảng 5 giây mỗi khung).
  - Video lớn hơn đi VRT/RVRT trên RunPod (`runpod_restore_endpoint`), chỉ khi người dùng cho phép gửi recording đó (`allow_cloud`, `nexora vq --allow-cloud`). Chế độ riêng tư vẫn chặn trong registry.
  - Bước khử mờ luôn được so với làm nét cổ điển trên khung giữa của shot. Mờ chuyển động 11 px trên ảnh lá: NAFNet thắng (PSNR 21,4 → 22,0, NIQE 7,0 → 5,4).
  - Trên clip 0002 làm mờ kiểu lệch nét (Gaussian σ 2): NAFNet thua (NIQE 6,28 so với 4,62), giữ làm nét. NAFNet học trên mờ chuyển động, không phải mờ lệch nét.
- **Đo mờ:** thước đo re-blur của Crete và cộng sự thay cho phương sai Laplacian.
  - Khung sạch đọc 0,17–0,29; mờ Gaussian σ 1,4 hay mờ chuyển động 11 px đọc từ 0,39.
  - Laplacian cũ gọi tán lá bị mờ chuyển động là nét (183).
  - Giới hạn đã biết: vệt mờ nhẹ do trộn 5 khung (đi bộ, cửa trập dài) chỉ làm thước đo nhích 0,22 → 0,25. Không có thước đo không-tham-chiếu nào bắt được nó mà không báo nhầm trên 0059.
- **Nâng sáng cục bộ:**
  - Bản đồ gain từ nền log-luma qua fast guided filter (He & Sun). Nền giữ được cạnh cứng: bản làm mượt bằng box từng tạo quầng sáng (NIQE 4,5 → 5,1).
  - Đề xuất khi trung vị dưới 0,3 và phân vị 99 trên 0,85.
  - Chỉ giữ khi làm lộ ít nhất 1/4 vùng gần đen, không cháy thêm, NIQE không xấu hơn 0,5.
  - Trên khung 0059 làm ngược sáng: vùng gần đen 16,9 % → 1,3 %, vùng cháy 2,8 % → 0, NIQE 5,75 → 5,46.
- **Lỗi tìm ra khi làm phần này:**
  - Ảnh trung gian giữa các bước của ảnh tĩnh từng bị ghi 8 bit, làm vùng tối được nâng bị vỡ dải. Nay ghi 16 bit.
  - Một bước AI không chạy được từng bị ghi là "AI không hơn". Nay ghi đúng là chạy hỏng, kèm lỗi.
- **Kiểm tra theo thời gian bằng optical flow:**
  - Lucas–Kanade nhiều tầng viết bằng numpy/scipy, ở khổ 480, nội suy bậc ba.
  - Đo chuyển động trên nguồn, rồi dự đoán khung sau từ khung trước ở cả nguồn lẫn kết quả.
  - Đo trên cảnh lia: nguồn tự dự đoán sai 0,70, chỉnh màu ×1,1 sai 0,77, hình nhấp nháy từng khung 4,33, vân sôi 3,37.
  - Ngưỡng: hỏng khi gấp 2 lần nguồn cộng 2, cảnh báo khi gấp 1,3 lần cộng 0,5. Trên footage thật (0002 4K, clip 720p) đều đạt, không báo hỏng nhầm.

Cả ba phần của đợt 3 nay đã xong. Phần làm trên GPU thuê có sẵn, chờ người dùng thuê endpoint và cho phép gửi footage.
