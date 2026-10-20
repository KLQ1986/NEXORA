<!-- Chưng cất từ OpenMontage a2652b4 bằng claude -p (Opus), 2026-10-19; 168s; chi phí theo gói: 0.6446788 -->

# clip-factory

Thể loại này lấy một nội dung dài có sẵn (webinar, livestream, phỏng vấn, panel, keynote, câu chuyện khách hàng) và cắt ra **N clip ngắn, độc lập** để đăng mạng xã hội (`pipeline_defs/clip-factory.yaml:3-7`, `idea-director.md:5,27-32`). Thể loại không có bước tiền kỳ vì nguồn đã có sẵn (`executive-producer.md:7`). Kết quả là một danh mục clip có xếp hạng, không phải một video (`idea-director.md:7`). Thể loại hợp với người có nhiều footage nói chuyện dài và muốn rải nội dung theo một mục tiêu: nhận diện, thought leadership, lead gen, giáo dục sản phẩm hoặc tóm tắt sự kiện (`idea-director.md:36-40`). Trạng thái hiện tại là beta. Ngân sách mặc định 1 USD, tổng thời gian chạy tối đa 12 phút (`yaml:9,15,18`). Chỉ render bằng Remotion hoặc ffmpeg, vì thể loại cần burn phụ đề theo từng từ (`idea-director.md:11`, `compose-director.md:9`).

> Quy ước nguồn: `yaml` = `pipeline_defs/clip-factory.yaml`. Tên `*-director.md` / `executive-producer.md` nằm trong `skills/pipelines/clip-factory/`. `reviewer.md` và `checkpoint-protocol.md` nằm trong `skills/meta/`.

## Các bước

Cả 7 stage đều `checkpoint_required: true`. Mỗi stage phải qua reviewer tự kiểm rồi mới checkpoint (`reviewer.md:5`). Duyệt theo từng cổng: lời "cứ làm hết đi" ở cổng trước không có giá trị cho cổng sau (`checkpoint-protocol.md:145-149`).

| # | Stage | Mục đích | Đầu vào | Đầu ra | Người duyệt |
|---|---|---|---|---|---|
| 1 | idea | Xác định loại nguồn, mục tiêu kinh doanh, cơ cấu loại clip, số clip, nền tảng | `source_media_review` (tùy chọn) (`yaml:48-49`) | `brief` (metadata: `source_type`, `source_duration_seconds`, `clip_target_range`, `clip_families`, `primary/secondary_platforms`, `selection_criteria`, `known_visual_constraints`, `distribution_goal`; `idea-director.md:80-90`) và `decision_log`, trong đó có quyết định `render_runtime_selection` (`idea-director.md:13`) | **Có** (`yaml:55`) |
| 2 | script | Phiên âm toàn bộ nguồn, chấm điểm từng khoảnh khắc, lọc clip không đứng một mình được, chọn batch | `brief`; tool `transcriber` bắt buộc, `scene_detect` tùy chọn (`yaml:66-76`) | `script`. Metadata: `candidate_clips`, `selected_clip_ids`, `ranking_model`, `rejected_candidates`, `source_coverage_map`, `platform_assignments`. Mỗi ứng viên ghi in/out, câu hook, lý do chọn/loại, điểm từng chiều, khả năng crop (`script-director.md:63-76`) | **Có** (`yaml:78`) |
| 3 | scene_plan | Chọn khung hình theo nền tảng, dựng bố cục khung đầu tiên, khóa vùng chữ chung cho cả batch | `script` (+`brief`); tool `frame_sampler` (`yaml:89-99`) | `scene_plan`, mỗi scene là một biến thể clip (`scene-director.md:62`). Metadata: `clip_layouts`, `safe_zones`, `crop_variants`, `speaker_positions`, `platform_variants` (`scene-director.md:54-58`) | **Có** (`yaml:101`) |
| 4 | assets | Làm bộ tài sản dùng chung, phụ đề riêng cho từng clip, chuẩn hóa âm cho cả batch | `scene_plan` (+`script`); `subtitle_gen` bắt buộc, `audio_enhance` tùy chọn (`yaml:112-124`) | `asset_manifest` (`shared_assets`, `subtitle_map`, `audio_profile`, `clip_asset_index`, `style_tokens`; `asset-director.md:60-64`) | **Có** (`yaml:126`). Có thêm một cổng phụ bắt buộc: làm 1 mẫu cho cảnh chủ lực và chờ duyệt rồi mới làm hàng loạt (`asset-director.md:28-34`). Người duyệt xem trên filmstrip, không render bản nháp (`checkpoint-protocol.md:151-167`) |
| 5 | edit | Dựng template chung cho batch, chỉ ghi đè ở clip nào thật sự cần; tối ưu 2-3 giây đầu; giữ biên cắt sạch | `scene_plan`, `asset_manifest` (+`script`) (`yaml:137-141`) | `edit_decisions` (`batch_template`, `clip_variants`, `hook_windows`, `cta_windows`; `edit-director.md:49-52`) | **Không**: qua review là chạy tiếp (`yaml:146`, `checkpoint-protocol.md:24`) |
| 6 | compose | Render mỗi cặp (clip × nền tảng) thành một job riêng; job nào lỗi thì ghi lại và chạy tiếp; kiểm từng file ra | `edit_decisions`, `asset_manifest` (+`scene_plan`); bắt buộc `video_compose`, `video_trimmer`, `audio_mixer` (`yaml:157-177`) | `render_report` (`job_index`, `failed_jobs`, `shared_intermediates`, `platform_groupings`; `compose-director.md:60-63`) và `final_review` (`yaml:163-164`) | **Không** (`yaml:179`) |
| 7 | publish | Lập kế hoạch phát hành: thứ tự theo xếp hạng, caption riêng cho từng nền tảng, đóng gói theo nền tảng | `render_report`, `final_review` (+`brief`) (`yaml:190-195`) | `publish_log` (`clip_catalog`, `posting_order`, `platform_copy_map`, `schedule_notes`; `publish-director.md:44-47`) | **Có** (`yaml:199`). Nếu `final_review.status` khác `pass` thì không được đăng (`reviewer.md:316-317`) |

## Quy tắc dựng của thể loại

- Số clip theo thời lượng nguồn: 15-30 phút → 3-6 clip; 30-60 phút → 5-10; trên 60 phút → 8-15 nếu nguồn đủ chất lượng — `idea-director.md:60-62`
- EP đưa quy tắc thô "1 clip cho mỗi 5-10 phút nguồn". Với nguồn 60 phút, EP cho 6-12 clip còn idea cho 8-15, hai chỗ lệch nhau (suy ra) — `executive-producer.md:52`
- Không thổi phồng số clip; chọn tập nhỏ nhất đạt mục tiêu — `idea-director.md:64`, `script-director.md:48`
- Số ứng viên phải ≥ N mục tiêu trong brief — `yaml:85`
- Chấm mỗi ứng viên theo 5 chiều: hook, coherence, value, energy, platform_fit — `script-director.md:27-31`
- 5 loại clip nên trộn trong một batch: hook, insight, story, proof, opinion — `idea-director.md:48-52`
- Batch phải đa dạng về phần nguồn, người nói, loại clip, mức năng lượng; không dồn vào một đoạn — `script-director.md:52-55`, `executive-producer.md:74-75`
- Xếp hạng theo chất lượng, không theo thứ tự thời gian — `script-director.md:100`, `publish-director.md:19`
- Hook phải nằm trong **2-3 giây đầu** của mỗi clip — `yaml:149`, `executive-producer.md:90`, `edit-director.md:29`
- Khung đầu tiên mở bằng chuyển động, khuôn mặt hoặc kết quả; phụ đề bắt đầu cùng từ nói đầu tiên — `edit-director.md:33-35`
- Không mở đầu kiểu "như tôi vừa nói"; không để đại từ không rõ chỉ ai/cái gì; không nhắc tới ngữ cảnh phía trước; không dẫn dắt dài; không kết thúc trước khi tới ý chốt — `executive-producer.md:132`, `script-director.md:41-44`
- Không cắt giữa câu hoặc giữa từ; không để khoảng lặng thừa sau khi ý đã chốt — `yaml:104`, `edit-director.md:40-41`
- Câu kết là ý chốt của người nói. Chỉ thêm outro card khi nó đáng thời lượng; CTA/end-tag chỉ thêm "nếu cần" — `edit-director.md:43`, `asset-director.md:26`
- Tỉ lệ khung: 9:16 (Shorts/Reels/TikTok) khi crop vào mặt được; 1:1 (LinkedIn) khi cần cả người lẫn bối cảnh; 16:9 khi có slide, demo hoặc nhiều người — `idea-director.md:70-72`, `scene-director.md:24-26`
- Không mặc định 9:16. Nếu crop dọc kém thì hạ trung thực sang tỉ lệ an toàn hơn; hệ thống chưa có auto-reframe — `scene-director.md:20,28,68`
- Mỗi clip ghi rõ nền tảng, tỉ lệ khung và thời lượng, không vượt thời lượng tối đa của nền tảng — `yaml:108`, `executive-producer.md:71`. **Các file đã đọc không có con số giây cụ thể**; skill chỉ trỏ tới `lib/media_profiles.py` (chưa đọc) — `compose-director.md:22`
- 1 clip × 3 nền tảng = 3 job render — `compose-director.md:28`
- Cả batch dùng chung vị trí cho vùng hook phía trên, vùng phụ đề, vùng watermark và cách đặt lower-third; hook và phụ đề không được đè nhau — `scene-director.md:43-46,67`
- Không để hook text, phụ đề, watermark và lower-third cùng lúc trên màn hình; mọi lớp chữ phải đọc được trên điện thoại — `edit-director.md:58,65`
- Mỗi batch chỉ có một kiểu phụ đề, một kiểu hook, một lower-third, một watermark, một CTA — `asset-director.md:22-26`
- Hook overlay làm bằng chữ theo template; không tạo hình riêng trừ khi thật sự có lợi — `asset-director.md:54`
- Thời gian phụ đề tính lại từ đầu clip, không giữ mốc của nguồn — `asset-director.md:40`
- Âm thanh chuẩn hóa cho cả batch (độ to, nền nhiễu, độ rõ giọng). **Không có ngưỡng LUFS** — `asset-director.md:46-50`
- Template dựng khóa các mặc định: kiểu phụ đề, thời điểm hook, thời điểm lower-third, watermark, độ dài fade âm; branding không được làm chậm hook — `edit-director.md:21-25,64`
- Nhạc: các file clip-factory đã đọc **không có luật nào về nhạc**
- Kiểm từng file ra: đúng thời lượng, đúng độ phân giải/tỉ lệ, không có khung đen đầu, hook đúng thời điểm, phụ đề hiển thị đúng, có tiếng — `compose-director.md:49-54`. File phải qua ffprobe (`yaml:186`); `final_review` lấy mẫu ≥ 4 khung (`reviewer.md:308`)
- Job nào lỗi thì ghi lại và chạy tiếp, không chặn các file đã xuất thành công — `compose-director.md:39-43`
- Không đăng cả batch trong cùng một ngày; clip đăng đầu tiên là clip có hook mạnh nhất và đứng một mình tốt nhất — `publish-director.md:21-25,58`
- Giới hạn chạy: tối đa 3 lần sửa mỗi stage (`yaml:16`), mâu thuẫn với "tối đa 2 vòng" của reviewer (`reviewer.md:86,124`). Tối đa 3 lần trả về tổng cộng, 1 lần cho mỗi cặp stage (`executive-producer.md:125-126`). Cảnh báo khi tiêu tới 90% ngân sách (`executive-producer.md:84`)

## Checklist duyệt

**idea**
- [ ] Brief hợp lệ theo schema; ghi rõ loại nguồn (`yaml:57,61`)
- [ ] Số clip mục tiêu nằm trong khoảng tương ứng với thời lượng nguồn (`idea-director.md:60-62`)
- [ ] Brief có cơ cấu nền tảng và tiêu chí chọn clip (5 chiều) trước khi bắt đầu cắt (`yaml:59,62`)
- [ ] Đã ghi trước giới hạn crop dọc nếu có (`idea-director.md:74,97`)
- [ ] `decision_log` có `render_runtime_selection`, trong đó ghi hyperframes bị loại kèm lý do (`idea-director.md:13`)

**script**
- [ ] Có transcript đầy đủ kèm timestamp (`yaml:80`)
- [ ] Số ứng viên ≥ N (`yaml:85`)
- [ ] Mỗi clip được chọn qua kiểm tra đứng một mình: không đại từ treo, không nhắc ngữ cảnh trước, không dẫn dài, không cụt trước ý chốt (`script-director.md:41-44`)
- [ ] `source_coverage_map` cho thấy clip không dồn vào một đoạn nguồn (`script-director.md:82`)
- [ ] Có danh sách ứng viên bị loại kèm lý do (`script-director.md:66,83`)

**scene_plan**
- [ ] In/out của mọi clip không rơi giữa câu (`yaml:103-104`)
- [ ] Mỗi clip có nền tảng, tỉ lệ khung, thời lượng, và không vượt thời lượng tối đa của nền tảng (`yaml:108`, `executive-producer.md:71`)
- [ ] Vùng hook và vùng phụ đề không chồng nhau; vùng chữ thống nhất trong cả batch (`scene-director.md:43-46,67`)
- [ ] Clip nào crop dọc kém đã được hạ tỉ lệ (`scene-director.md:68`)

**assets**
- [ ] Mỗi clip có phụ đề, thời gian tính từ đầu clip (`yaml:128`, `asset-director.md:40`)
- [ ] Mỗi clip có âm đã làm sạch hoặc đường dẫn âm nguồn đã kiểm (`asset-director.md:69`)
- [ ] Âm của mọi clip được chuẩn hóa như nhau (`yaml:130`)
- [ ] Mẫu cảnh chủ lực đã được duyệt trước khi làm hàng loạt (`asset-director.md:34`)
- [ ] Clip nào cũng có đủ tài sản (`yaml:133`)

**edit**
- [ ] Mọi clip có `hook_windows` bắt đầu trong ≤ 3 giây (`yaml:149`)
- [ ] Mỗi clip đứng độc lập, không phụ thuộc clip khác (`executive-producer.md:92`)
- [ ] Kiểu phụ đề và độ dài fade giống nhau trong cả batch (`yaml:150`, `edit-director.md:59`)
- [ ] Không lúc nào có đủ 4 lớp chữ cùng lúc trên màn hình (`edit-director.md:65`)
- [ ] Clip nào cũng có edit_decisions (`yaml:153`)

**compose**
- [ ] Mọi file ra tồn tại và qua ffprobe (`yaml:186`)
- [ ] Độ phân giải và tỉ lệ đúng với nền tảng của từng job (`yaml:182`)
- [ ] Khung đầu không đen; hook đúng thời điểm; phụ đề hiển thị; có tiếng (`compose-director.md:49-54`)
- [ ] Độ to âm đồng đều giữa các clip (`yaml:183`)
- [ ] `failed_jobs` được ghi rõ ràng (`compose-director.md:41,61`)
- [ ] Có `final_review` với status `pass` và ≥ 4 khung được lấy mẫu (`reviewer.md:300-308`)

**publish**
- [ ] Mỗi clip có tiêu đề/mô tả riêng cho từng nền tảng (`yaml:201`, `publish-director.md:29-34`)
- [ ] Có `posting_order` theo xếp hạng; clip đầu tiên là clip mạnh nhất (`publish-director.md:19-25`)
- [ ] Lịch đăng không dồn cả batch vào một ngày (`publish-director.md:58`)
- [ ] Thư mục xuất chia theo nền tảng, có sẵn text để dán, dùng ngay không cần dọn (`yaml:203,206`, `publish-director.md:38,53`)

## Lỗi hay gặp

- Clip phụ thuộc ngữ cảnh, ví dụ mở đầu bằng "như tôi vừa nói" (`executive-producer.md:132`)
- Hook chậm, hoặc logo/branding đứng trước hook (`executive-producer.md:133`, `edit-director.md:64`)
- Âm lệch giữa các clip lấy từ những đoạn khác nhau của nguồn; chỉ chuẩn hóa một số clip (`executive-producer.md:134`, `asset-director.md:88`)
- Mọi clip dồn vào cùng một đoạn 10 phút (`executive-producer.md:136`)
- Lên kế hoạch theo số lượng thay vì chất lượng; xem các clip là thay thế được cho nhau (`idea-director.md:101,103`)
- Tin luôn timestamp ở lượt đầu; chọn quá nhiều clip cùng mức năng lượng; giữ thứ tự thời gian (`script-director.md:98-100`)
- Crop giữa một cảnh rộng rồi gọi đó là tối ưu dọc; bỏ qua slide/màn hình chia sẻ; mỗi clip tự chế layout riêng (`scene-director.md:73-75`)
- Quên tính lại thời gian phụ đề; thiết kế hook quá cầu kỳ khiến batch thiếu nhất quán; làm 10 clip như 10 dự án rời (`asset-director.md:86-89`)
- Ghép thành một highlight reel thay vì các clip độc lập; nhồi chữ kín màn hình (`edit-director.md:63,65`)
- Dừng cả batch vì một clip lỗi; để một biến thể nền tảng lặng lẽ dùng sai khung hoặc sai vùng phụ đề (`compose-director.md:68-69`)
- Dùng một caption cho mọi nền tảng; đăng cả batch cùng ngày; mất logic xếp hạng sau khi render (`publish-director.md:58-60`)
- Tài liệu có điểm không nhất quán: script-director yêu cầu mọi dữ kiện truy được về `research_brief` (`script-director.md:92`), nhưng pipeline không có stage research (`yaml:45-206`). Nhiều khả năng đoạn này được chép từ pipeline khác (suy ra)

## Prompt đáng giữ

1. **Chấm và kiểm tra đứng một mình** (`script-director.md:25-44`): "Bạn đang khai thác khoảnh khắc nổi bật, không tóm tắt nguồn. Chấm mỗi ứng viên theo 5 chiều: hook, mạch lạc, giá trị, năng lượng, hợp nền tảng. Người xem chưa từng thấy nguồn vẫn phải hiểu clip. Hãy loại hoặc nới rộng clip nếu có đại từ không rõ chỉ ai, nhắc tới ngữ cảnh trước, dẫn dắt dài trước khi vào ý, hoặc kết thúc trước ý chốt. Với mỗi ứng viên, ghi in/out, câu hook, lý do chọn/loại và khả năng crop."
2. **Hai, ba giây đầu và biên cắt** (`edit-director.md:31-43`): "Mở bằng chuyển động, khuôn mặt hoặc kết quả. Cho chữ hook hiện ngay nếu cần. Phụ đề bắt đầu cùng từ nói đầu tiên. Không cắt giữa từ, không để khoảng lặng sau khi ý đã chốt, không dựng mồi chỉ để dựng mồi, không thêm outro nếu nó không đáng thời lượng."
3. **Phê bình kiểu CHAI** (`reviewer.md:11-17`): "Mỗi nhận xét phải chỉ ra đúng trường, mốc thời gian hoặc khung hình có vấn đề (chính xác). Tìm thấy một lỗi thì quét tiếp những lỗi cùng loại (đầy đủ). Mỗi lỗi nghiêm trọng phải kèm cách sửa cụ thể; không đưa ra được cách sửa thì hạ xuống mức 'cần điều tra' (xây dựng)."

## Đối chiếu NEXORA

| Điều OpenMontage làm | NEXORA đã có | Còn thiếu | Đề xuất cụ thể |
|---|---|---|---|
| Một nguồn dài cho ra N clip, xếp hạng như một danh mục (`idea-director.md:7`) | Run/stage, lane trong orchestrator | Chưa có kiểu run "1 nguồn → N sản phẩm" (suy ra) | Thêm loại run `clip_batch`: mỗi clip là một sub-job có lease/timeout riêng |
| Transcript làm bề mặt tìm hook (`script-director.md:19`) | Phân tích lời nói trong thư viện footage, tìm kiếm theo nội dung | Chưa rõ có timestamp theo từng từ hay không | Bảo đảm lưu timestamp từng từ, vì biên cắt và hook đều đo bằng nó |
| Chấm 5 chiều, kiểm tra đứng một mình, có danh sách bị loại (`script-director.md:27-44,66`) | `sourcing.match` có giám khảo mô hình nhìn | Giám khảo hiện chọn clip cho shot, chưa khai thác khoảnh khắc từ nguồn dài (suy ra) | Thêm giám khảo văn bản trên transcript, đầu ra JSON có điểm và lý do |
| Bản đồ phủ nguồn, đa dạng loại clip (`script-director.md:52-55,67`) | Không | Toàn bộ | Luật code: phân bố clip giữa các phần của nguồn, số người nói |
| Số clip theo thời lượng nguồn (`idea-director.md:60-62`) | Không | Toàn bộ | Hàm đề xuất khoảng số clip, cảnh báo khi vượt |
| Chọn khung theo nền tảng, hạ tỉ lệ khi crop yếu (`scene-director.md:20-28`) | Hồ sơ hình, cú máy, shot spec có khung | Chưa có bước đo crop dọc được không (suy ra) | Dùng vị trí mặt/chủ thể trong hồ sơ hình để chấm khả năng crop 9:16 |
| Vùng chữ thống nhất cho cả batch (`scene-director.md:43-46`) | Shot spec theo từng shot | Chưa có template ở mức batch | Thêm `batch_template` (vùng an toàn, kiểu phụ đề, fade), mọi clip kế thừa |
| Làm 1 mẫu cảnh chủ lực rồi mới làm hàng loạt (`asset-director.md:28-34`) | Storyboard, Copilot, gate duyệt | Chưa có cổng "mẫu trước, hàng loạt sau" (suy ra) | Dùng lại gate có sẵn: render 1 clip mẫu, duyệt xong mới chạy phần còn lại |
| Tính lại thời gian phụ đề theo đầu clip (`asset-director.md:40`) | QC phụ đề | Chưa rõ có kiểm offset hay không | Test: từ đầu tiên trong phụ đề có mốc ≈ 0 + độ trễ của lời nói đầu |
| Chuẩn hóa âm cho cả batch (`asset-director.md:46-50`) | QC tiếng (từng video) | Chưa có kiểm chênh lệch giữa các clip | Đo integrated loudness từng clip, cảnh báo nếu chênh vượt ngưỡng (ngưỡng do NEXORA tự đặt) |
| Hook trong 2-3 giây, không khung đen đầu (`yaml:149`, `compose-director.md:51-52`) | QC hình/nhịp | Chưa có luật hook (suy ra) | Luật code đo được (xem ưu tiên #2) |
| Job lỗi thì ghi lại và chạy tiếp, có `failed_jobs` (`compose-director.md:39-43`) | Timeout, kill switch | Chưa rõ batch có cho phép thành công một phần không | Mỗi job (clip × nền tảng) có trạng thái riêng; run kết thúc ở trạng thái `partial` |
| Bắt buộc `final_review` (ffprobe, ≥ 4 khung) (`reviewer.md:300-308`) | QC tự động | Đã đủ | Giữ nguyên, áp cho từng job |
| Đăng theo xếp hạng, caption riêng từng nền tảng, không đăng dồn một ngày (`publish-director.md:19-58`) | Cổng bản quyền khi đăng | Thứ tự đăng, caption theo nền tảng, lịch đăng | Prompt viết caption theo nền tảng; luật code: tối thiểu 1 ngày giữa hai lần đăng (ngưỡng tự đặt) |
| Duyệt theo từng cổng, chỉ được bỏ khi đã ghi `approval_policy` (`checkpoint-protocol.md:145-149`) | Gate trong DB, công tắc tự duyệt | Chưa rõ công tắc tự duyệt có để lại dấu vết kiểm toán không | Khi bật tự duyệt thì ghi một bản ghi quyết định có thời điểm và phạm vi |
| Runtime phụ thuộc cloud? Không đề cập | Privacy mode chặn cloud | — | Pipeline này chỉ cần transcriber và ffmpeg local nên chạy được trong privacy mode (suy ra) |
| Chấm nguy cơ slideshow, delivery promise (`reviewer.md:179-189,261-272`) | Không | Không cần cho thể loại này | Footage thật cắt ra nên ít rủi ro slideshow (suy ra); không ưu tiên |

## Đề xuất ưu tiên

1. **Luật biên cắt — code có test.** Từ timestamp từng từ, bảo đảm in/out không rơi giữa từ hoặc giữa câu, và đuôi clip không còn khoảng lặng thừa sau từ cuối. Test bằng transcript giả có ranh giới câu, kiểm cả in và out. Nguồn: `yaml:104`, `edit-director.md:40-41`.
2. **Luật 3 giây đầu — code có test.** Ba điều kiện: lời nói hoặc chữ hook bắt đầu trong ≤ 3 giây; khung đầu không đen (blackdetect); clip có tiếng. Chạy trong QC cho từng job. Nguồn: `yaml:149`, `compose-director.md:49-54`.
3. **Chấm ứng viên và kiểm tra đứng một mình — prompt, kèm một bộ lọc code.** Prompt dùng prompt #1, đầu ra JSON có 5 điểm, lý do và danh sách bị loại. Bộ lọc code (có test) bắt câu đầu clip mở bằng cụm phụ thuộc ngữ cảnh tiếng Việt như "như tôi vừa nói", "cái đó", "còn chuyện", "vậy nên". Danh sách cụm này là đề xuất của NEXORA, không có trong OpenMontage (suy ra). Nguồn: `script-director.md:27-44`, `executive-producer.md:132`.
4. **Kiểm batch — code có test.** Ba luật:
   - Số clip nằm trong khoảng tương ứng với thời lượng nguồn.
   - Phân bố clip giữa các phần của nguồn không dồn vào một đoạn.
   - Độ to âm giữa các clip không chênh quá ngưỡng.

   Mọi clip phải kế thừa `batch_template` (vùng chữ, kiểu phụ đề, fade). Nguồn: `idea-director.md:60-62`, `executive-producer.md:74-75`, `asset-director.md:46-50`, `scene-director.md:43-46`.
5. **Render theo job, cho phép thành công một phần, kèm gói đăng — code cho phần render, prompt cho phần caption.**
   - Code: mỗi cặp clip × nền tảng là một job riêng, có `failed_jobs`; `posting_order` lấy theo xếp hạng.
   - Prompt: viết caption riêng cho từng nền tảng (TikTok/Reels thẳng và nhanh; Shorts có từ khóa; LinkedIn thiên về insight).

   Nguồn: `compose-director.md:28,39-43`, `publish-director.md:19-34`.
