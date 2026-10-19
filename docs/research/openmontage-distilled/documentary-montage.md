<!-- Chưng cất từ OpenMontage a2652b4 bằng claude -p (Opus), 2026-10-19; 131s; chi phí theo gói: 0.7248282 -->

# documentary-montage

`documentary-montage` dựng một đoạn phim ngắn 30–180s, không theo mạch kể chuyện, chỉ từ footage có thật (stock, kho lưu trữ, NASA…). Ý nghĩa của phim đến từ việc đặt các hình cạnh nhau (hiệu ứng Kuleshov, montage trí tuệ của Eisenstein), không đến từ lời bình (executive-producer.md:5-10). Phong cách tham chiếu là "tone poem" kiểu Adam Curtis, Chris Marker, Errol Morris (documentary-montage.yaml:9). Pipeline này đi theo hướng **tìm footage có sẵn**, không tự sinh: nó dựng một kho ứng viên, mỗi slot là một mô tả cảnh, rồi xếp clip theo nhịp tự sự và khớp với nhạc (yaml:4-8). Nên chọn khi người dùng nói những câu như "montage về…", "cho tôi thấy cảm giác…", "chỉ hình, không lời bình", "cắt từ stock" (executive-producer.md:12-21). Không dùng cho phim giải thích, talking-head hay trailer làm từ clip sinh ra (executive-producer.md:23-24). Mặc định không có clip AI và không có lời bình, trừ khi người dùng yêu cầu (executive-producer.md:67-72).

## Các bước

Cấu hình chung: checkpoint `guided`, ngân sách mặc định 1 USD, tối đa 3 lần sửa mỗi stage, tối đa 2 lần trả về stage trước, tổng thời gian tối đa 60 phút (yaml:12, 21-24). Stage có gate thì ghi checkpoint `awaiting_human` rồi **dừng lượt**. Mỗi gate cần duyệt riêng; một câu "cứ làm hết đi" trước đó không tính cho gate sau, trừ khi đã ghi `approval_policy` vào decision_log (checkpoint-protocol.md:110-149).

| Stage | Mục đích | Đầu vào | Đầu ra | Người duyệt |
|---|---|---|---|---|
| `idea` | Gọi tên câu hỏi chủ đề, chốt giọng, thời lượng, hình dạng, kế hoạch nhạc, câu kết, lời bình. Khoá runtime `remotion` | Yêu cầu của người dùng | `brief` | Có (yaml:46-52) |
| `scene_plan` | Đổi câu hỏi chủ đề thành các slot cụ thể: mô tả, query, nguồn ưu tiên, slot hero, thời lượng giữ | `brief` | `scene_plan` (+`metadata.slots[]`) | Có (yaml:66-74) |
| `assets` | Tìm và chọn đúng 1 clip cho mỗi slot, kèm nguồn gốc; xử lý nhạc theo plan. Có 2 đường: fast path (`direct_clip_search`) và standard path (corpus + CLIP) | `scene_plan`, `brief` | `asset_manifest` (+`rejected_picks`, `corpus_stats` hoặc `search_stats`) | Có. Duyệt dải phim (filmstrip), không render nháp (yaml:86-105; checkpoint-protocol.md:151-167) |
| `edit` | Định in/out, thứ tự, chuyển cảnh, khớp nhạc, khoảng lặng, L-cut, thời điểm hiện câu kết | `scene_plan`, `asset_manifest` | `edit_decisions` | Có (yaml:118-127) |
| `compose` | Đưa về một canvas, áp một LUT chung, trộn âm một lượt, render câu kết bằng Remotion, kiểm tra file xuất | `edit_decisions`, `asset_manifest`, `brief` | `render_report` + mp4 | **Không** (checkpoint rồi tự đi tiếp) (yaml:141-163) |

Reviewer: phát hiện mức critical thì phải kèm cách sửa. Sau tối đa 2 vòng sửa vẫn còn critical thì cho qua kèm cảnh báo (reviewer.md:42, 85-87).

## Quy tắc dựng của thể loại

- Bảng thời lượng: 30–45s ứng với 8–12 cú cắt; 60–90s: 15–25; 2–3 phút: 30–50 (idea-director.md:63-67).
- Shape `three-act` cần >90s và chia 30% / 40% / 30%. `before/after` gồm N/2 slot trước, 1 slot bản lề, N/2 slot sau (idea-director.md:75-76; scene-director.md:55-56).
- Giọng phải là MỘT giá trị trong 5 giá trị: elegiac, urgent, reverent, wry, dreamlike (idea-director.md:46-57).
- Thời lượng giữ (base/min/max): elegiac 4.0/2.5/7.0s; reverent 3.5/2.0/6.0; dreamlike 3.0/1.5/5.5; wry 2.0/1.0/4.0; urgent 1.2/0.5/2.5 (edit-director.md:64-70).
- Số slot mỗi 60s: elegiac ~15, reverent ~17, dreamlike ~20, wry ~30, urgent ~50 (scene-director.md:44-50).
- Tổng `target_hold_seconds` và tổng độ dài các cú cắt phải nằm trong ±10% của `brief.duration_seconds` (yaml:84, 139; edit-director.md:75).
- Slot hero có thời lượng giữ dài nhất (= max). Cutaway giữa chuỗi dùng base. Khi thừa thời lượng thì nén slot không-hero trước, không bao giờ cắt ngắn hero (edit-director.md:72-77).
- Cần ít nhất 2 slot hero (thường là cảnh mở, cảnh bản lề, cảnh cuối). Slot hero được k=30 ứng viên thay vì 10–12 và có 3 query (scene-director.md:208-216; asset-director.md:282).
- Mỗi slot có 2–3 query, mỗi query ≤5 từ (theo kỹ thuật: 2–5 từ) (scene-director.md:127-138, 288).
- Mô tả slot theo mẫu `<chủ thể>, <hành động/tư thế>, <bối cảnh>, <ánh sáng>, <gợi ý thời kỳ/chất liệu>`, không có từ cảm xúc, không có động từ ý định (scene-director.md:97-101, 286-287).
- `era_mix = vintage` thì ≥60% slot phải có `archive_org`, và ≥60% clip được chọn phải đến từ `archive_org` (scene-director.md:291-292; asset-director.md:447).
- Kho ứng viên lớn gấp 8–12 lần số slot; dưới 50 dòng là quá nhỏ; `per_source` lấy 4–8 (asset-director.md:238-241, 265).
- `mean_motion_score < 1.0` nghĩa là kho toàn clip tĩnh, có nguy cơ thành slideshow. Khi xếp hạng dùng `motion_min = 1.5` (asset-director.md:268-270, 284).
- Điểm CLIP: ≥0.30 là tốt; 0.22–0.30 cần người phán đoán; <0.22 thì không chọn mà mở rộng kho, tối đa 2 lượt (asset-director.md:322-341). Nếu mọi điểm đều <0.25 thì mở rộng kho (executive-producer.md:74-75).
- Xếp hạng bằng `description` của slot, không bằng query. `tag_weight` = 0.3 (0.5 khi tag tốt, 0.15 với Prelinger) (asset-director.md:290-298).
- Mỗi `clip_id` chỉ dùng cho 1 slot (`exclude_ids`). Sau đó chạy `diversify` với diversity 0.5 (asset-director.md:299-300, 351-362).
- Fast path: 3 clip mỗi query, lọc 3–40s, landscape, rộng ≥1280 (asset-director.md:137-148).
- Hai cú cắt liền nhau không được trùng cả chủ thể lẫn cỡ cảnh. Không quá 4 cú liền nhau cùng bảng màu. Hai pan cùng hướng liền nhau thì lật hoặc đổi thứ tự (edit-director.md:202-210).
- Chuyển cảnh tối đa 4 loại: cut, dissolve 0.5–1.0s, fade_to_black 0.5s, fade_in/out 0.5–1.0s. Cấm wipe, push/slide, zoom blur, RGB split, light leak, glitch (edit-director.md:155-172, 325).
- Chừa 4–6 frame ở mỗi đầu clip. Làm chậm 0.5–0.75 chỉ với cảnh gần như tĩnh. Cấm kết bằng freeze-frame (edit-director.md:108-120).
- Nhạc là BẮT BUỘC; chỉ bỏ khi người dùng opt-out rõ ràng (`source:"none"` + `opt_out_reason`) (idea-director.md:82-85).
- Nhạc: volume 0.7, fade in 1.0s, fade out 4.0s, không ducking nếu không có lời bình. Fade đuôi 3–5s (edit-director.md:133-149).
- Phim ≥60s phải có đúng một khoảng lặng ~2s ở tâm cảm xúc. Lúc compose: hạ về 0.0, giữ 0.2s rồi kéo lên lại (edit-director.md:132-133, 327; compose-director.md:137-138).
- Mặc định 60bpm thì cắt mỗi 4s nếu không có metadata nhịp. Cú cắt hero rơi vào downbeat (edit-director.md:128-131).
- L-cut kéo âm thanh 0.5–1.5s, dùng cho 3–4 chỗ chuyển khó nhất. SFX trộn ở 0.5–0.7 (edit-director.md:216-226; compose-director.md:139).
- Câu kết (end-tag) bắt buộc: 3–9 từ, là luận đề chứ không phải tóm tắt, hiện 5–8s, đề xuất 3 phương án. Mặc định `overlay` (idea-director.md:101-139).
- Thời điểm hiện câu kết: `offset = body_duration − tag_duration` (edit-director.md:234).
- Canvas: social_short 1080x1920; youtube/linkedin 1920x1080; letterbox 2.35:1 thì đệm 140px trên/dưới (compose-director.md:73-82).
- Một LUT cho cả timeline, không grade từng clip. Profile không tồn tại thì dùng `neutral_doc_20` kèm cảnh báo (compose-director.md:111-128).
- Không upscale 640x480 lên 1080p, dùng letterbox thay thế (compose-director.md:348-351).
- Xuất H.264 yuv420p, CRF 18, 24fps (không đổi lên 30), AAC 192k. Footage 30fps thì bỏ frame đều, không nội suy (compose-director.md:262-273).
- Mỗi cú cắt có một dòng `reason` (edit-director.md:328-329).

## Checklist duyệt

**idea**
- [ ] `thematic_question` có đúng 1 câu không?
- [ ] `tone` có thuộc 5 giá trị cho phép không?
- [ ] `duration_seconds` có phải số và `shape` có phải enum không?
- [ ] Có `music_plan`, hoặc `source:"none"` kèm `opt_out_reason` không?
- [ ] `end_tag_plan.text` có 3–9 từ, `duration_seconds` 5–8, `mode` ∈ {overlay, concat} không? Nếu là `null` thì có kèm lý do opt-out không?
- [ ] Trường `narration` có được ghi rõ (kể cả `"none"`) không?
- [ ] Có ít nhất 1 nguồn trong `sources_allowed` đang khả dụng không?

**scene_plan**
- [ ] Số slot có lệch ≤ ±10% so với `duration × slots_per_60s(tone)/60` không? (dung sai là suy ra)
- [ ] Mỗi slot có 2–3 query, mỗi query ≤5 từ không?
- [ ] Có ≥2 slot `hero` không?
- [ ] Tổng `target_hold_seconds` có trong ±10% thời lượng không?
- [ ] Mô tả slot có tránh được từ cảm xúc và động từ ý định không?
- [ ] Nếu `vintage`: ≥60% slot có `archive_org` không?
- [ ] `metadata.thematic_question` có khớp nguyên văn với brief không?

**assets**
- [ ] Mỗi slot có đúng 1 clip, không `clip_id` nào lặp không?
- [ ] Mọi asset có đủ `provider`, `original_url`, `license` không?
- [ ] Standard path: số dòng của kho ≥ 8× số slot, mọi clip được chọn có điểm ≥0.22 (hoặc ghi rõ người dùng cho phép), `diversify` không loại clip nào chưa được bù không?
- [ ] Fast path: đã xem thumbnail, ghi việc tái dùng clip giữa các act, đã lấp chỗ trống không?
- [ ] Mỗi mục trong `rejected_picks` có `reason` không?
- [ ] Mọi đường dẫn file có tồn tại không? Có asset nhạc (hoặc opt-out) không?

**edit**
- [ ] `renderer_family == "documentary-montage"` không?
- [ ] Cú cắt hero có giữ lâu nhất không?
- [ ] Có cặp cú cắt liền nhau nào trùng (chủ thể, cỡ cảnh) không?
- [ ] Số loại chuyển cảnh khác nhau có ≤4, và có loại nào nằm trong danh sách cấm không?
- [ ] Có `audio.music` (hoặc opt-out) không? Phim ≥60s có `silence_window` không?
- [ ] Có `end_tag.offset_seconds` (với overlay) không?
- [ ] `total_duration_seconds` có bằng tổng (out−in) và nằm trong ±10% brief không?
- [ ] Mọi cú cắt có `reason` không? Mọi `cut.source` có phải asset_id trong manifest không?

**compose**
- [ ] File có qua ffprobe không? Thời lượng có lệch ≤1s so với kế hoạch không (overlay: chỉ thân phim; concat: thân phim + câu kết)?
- [ ] Độ phân giải có khớp canvas của nền tảng không? Có áp LUT (hoặc có cảnh báo) không?
- [ ] Có luồng âm thanh, `music_mixed = true` (hoặc opt-out) không?
- [ ] `end_tag_rendered = true` và `end_tag_mode` ∈ {overlay, concat} không?
- [ ] Overlay: frame tại `offset+2s` có chữ hiện trên footage chứ không phải trên nền đen không? Concat: frame cuối có phải thẻ câu kết không?
- [ ] Frame đầu có fade-in không? Frame cuối có về đen không? Khoảng lặng có thấy rõ trên waveform không?
- [ ] Runtime có còn là `remotion`, và có hạ cấp nào xảy ra mà không báo không?
- [ ] Có lời bình nào ngoài brief không? `warnings` có liệt kê mọi thay thế không?

## Lỗi hay gặp

- Phim thành slideshow: các clip cùng độ dài giữ, không có thiết kế âm thanh (edit-director.md:33-35). Một clip thắng nhiều slot vì quên `exclude_ids` (asset-director.md:458-459).
- Cắt quá nhiều: 45s mà 50 cú là gây chóng mặt; 3 phút mà 12 cú là slideshow (idea-director.md:207-208; executive-producer.md:87).
- Xếp clip theo điểm thay vì theo nhịp tự sự; chọn chỉ dựa vào điểm (executive-producer.md:84; asset-director.md:455-457).
- Mô tả slot là ý định hoặc cảm xúc ("khoảnh khắc ngập ngừng"). Query dạng nhãn danh mục ("home", "family") (scene-director.md:298-303).
- Slot chỉ có 1 query. Quên `era_hint` khi brief là vintage. Câu hỏi chủ đề trôi đi trong lúc viết slot (scene-director.md:304-313).
- Dùng query để xếp hạng thay vì mô tả. Mở rộng kho vô hạn. Làm mất thông tin nguồn gốc (asset-director.md:464-472).
- Lặng lẽ thêm lời bình, đổi nhạc, kéo dài thời lượng, thêm tiếng nền "cho đỡ trống". Cách đúng là sửa bản dựng chứ không che lấp (executive-producer.md:88-89; edit-director.md:45-57; compose-director.md:151).
- Dissolve ở mọi cú cắt. Dùng 3 loại chuyển cảnh trong 15s đầu. Kết bằng freeze-frame. Hình cuối yếu (edit-director.md:338-352).
- Bỏ qua nhạc cho đến lúc cuối; nhạc phải là lưới thời gian để cắt theo (edit-director.md:340-341).
- Không grade clip từ nhiều thời kỳ. Grade từng clip. Upscale thay vì letterbox (compose-director.md:345-356).
- Âm thầm chuyển xuống FFmpeg hoặc HyperFrames. Chỉnh volume hoặc trim lúc render, tức là dựng lại ngay trong compose. Không mở file xuất ra kiểm tra (compose-director.md:357-366; yaml:169).
- Bỏ câu kết với lý do "hình tự nói". Theo skill thì không đủ: câu kết là luận đề (idea-director.md:212-213).

**Mâu thuẫn trong chính skill (cần biết trước khi mượn):**
- Elegiac ghi "~15 slot/60s" (scene-director.md:46), nhưng ví dụ lại ghi 90s ≈ 15 slot × ~6s (scene-director.md:306-307, 317).
- Hero giữ "2–4s" (scene-director.md:214), trái với "hero = max hold", tức 7s với elegiac (edit-director.md:72).
- Ví dụ "+10s mỗi hero" ra 5.5/6.0/7.0s, các con số không cộng lại đúng (edit-director.md:358-360).
- Quality gate của compose đòi "concat, frame cuối là thẻ câu kết" (compose-director.md:336), trái với mặc định overlay (yaml:170).
- Dung sai thời lượng không thống nhất: ±0.5s (compose-director.md:280), ±1s (yaml:165), ±1s so với *brief* (compose-director.md:332).
- Thân phim render bằng FFmpeg (compose-director.md:181), trong khi khoá runtime là remotion (compose-director.md:14).
- `music_mixed` ở chỗ này nằm trong `metadata`, chỗ khác ở cấp gốc (compose-director.md:341 so với yaml:178). Mẫu lại dùng `music_present` (compose-director.md:324).
- Nội dung thiếu nhi dùng clip fantasy AI từ Pixabay (scene-director.md:171-200), trái với "không dùng clip sinh ra" (executive-producer.md:67).
- Câu "L-cut mạch lạc hơn 50%" không có căn cứ (edit-director.md:225).

## Prompt đáng giữ

1. **Viết mô tả slot như người đi tìm bối cảnh** (scene-director.md:27-35, 118-119, 225-227): "Đừng viết như thủ thư stock ('mưa trong thành phố, 15 clip'). Hãy viết như người đi tìm bối cảnh: chủ thể, hành động, bối cảnh, ánh sáng, chất liệu thời kỳ. Nếu không hình dung ra được một bức ảnh cụ thể từ mô tả thì mô hình tìm kiếm cũng không làm được. Mô tả phải đủ cụ thể để nhận ra, đủ lỏng để còn bất ngờ."
2. **Chọn bằng phán đoán, không bằng điểm** (asset-director.md:302-318): "Xem 3–5 ứng viên đầu và xét từng cái theo: đúng thời kỳ không; độ dài và chuyển động có đủ cho thời lượng giữ không; đặt cạnh clip của slot kề bên có bị trùng cỡ cảnh/bố cục không; có đúng giọng cảm xúc không. Điểm cao không thắng được giọng. Ghi lý do cho mỗi ứng viên điểm cao bị loại."
3. **Câu hỏi chủ đề và câu kết** (idea-director.md:28-42, 116, 133): "Gọi tên câu hỏi mà phim trả lời, trong MỘT câu, có cảm xúc nhưng chưa phải danh sách shot. Kết phim bằng một câu 3–9 từ, là luận đề chứ không tóm tắt. Đưa 3 phương án và đề xuất 1."

## Đối chiếu NEXORA

| Điều OpenMontage làm | NEXORA đã có | Còn thiếu | Đề xuất cụ thể |
|---|---|---|---|
| Gate duyệt người riêng cho từng stage; compose tự đi tiếp | Gate trong DB, công tắc tự duyệt | Quy tắc "duyệt trước không tính cho gate sau" (suy ra là chưa có) | Chỉ cho bỏ qua gate khi có bản ghi `approval_policy` gắn với run |
| Brief: câu hỏi chủ đề + 5 giọng + shape + thời lượng | Kịch bản theo topic, template cấu trúc | Giọng (tone) dạng enum để điều khiển nhịp bằng số | Thêm `tone` và `shape` vào template; validate bằng schema |
| Bảng thời lượng giữ theo giọng, số slot, tổng ±10% | QC nhịp | Luật số gắn với giọng, hero giữ lâu nhất | Hàm `pacing_lint(storyboard, tone)` có unit test |
| Mô tả slot dạng danh từ + tính từ, 2–3 query ngắn | Tìm footage theo nội dung, shot spec | Trường mô tả tìm kiếm tách khỏi query; query stock bằng tiếng Anh (suy ra) | Thêm `search_description` và `queries[2..3]` vào shot spec, kèm lint độ dài và từ cảm xúc |
| Ngưỡng điểm 0.22/0.30, kho 8–12×, tối đa 2 lượt mở rộng | sourcing.match + giám khảo mô hình nhìn | Ngưỡng và kích thước kho ứng viên định lượng (mô tả không nhắc) | Cấu hình ngưỡng; dưới ngưỡng thì báo "không tìm được" thay vì chọn đại |
| `rejected_picks` có lý do | Copilot nhận xét | Log loại bỏ có cấu trúc để edit lấy phương án #2 | Bảng `pick_rejections(slot, clip, score, reason)` |
| Không dùng lại clip; `diversify`; kề nhau không trùng chủ thể + cỡ cảnh | Mối nối giữa shot, hồ sơ hình | Kiểm tra tự động cặp liền kề | Lint dựa trên `shot_size` và `subject` từ phân tích footage |
| Từ vựng chuyển cảnh ≤4, danh sách cấm | FilmCraft | Luật giới hạn số loại chuyển cảnh | Lint trên timeline |
| Nhạc bắt buộc, khoảng lặng ~2s, fade đuôi 3–5s, volume 0.7 | QC tiếng | Quy tắc bắt buộc nhạc + opt-out có lý do; khoảng lặng | Hợp đồng âm thanh trong edit, kiểm tra bằng đo RMS |
| End-tag 3–9 từ, 5–8s, overlay | Phụ đề | Khái niệm câu kết | Trường `end_tag` + render chữ phủ bằng ffmpeg drawtext/ASS (suy ra là đủ, không cần Remotion) |
| Một LUT chung, letterbox, không upscale | FilmCraft/ffmpeg | Grade đồng bộ, chặn upscale | Bước `lut3d` cho cả timeline; QC chặn tỉ lệ upscale >1.5 (suy ra) |
| Kiểm tra sau render: thời lượng, độ phân giải, âm thanh, frame đầu/cuối, waveform khoảng lặng | QC tự động | Kiểm tra frame đầu/cuối và khoảng lặng | Thêm vào QC hiện có |
| Provenance provider/url/license trên mỗi asset | Cổng bản quyền khi đăng | Lọc giấy phép theo loại; chặn ngay lúc chọn | Bắt buộc 3 trường ngay ở bước pick, không đợi đến lúc đăng |
| Không âm thầm đổi lớn (lời bình, nhạc, thời lượng, engine) | Kill switch, privacy mode | So sánh hợp đồng giữa brief và kết quả | Diff brief↔edit↔render; lệch thì mở gate |
| Chấm nguy cơ slideshow, delivery promise | Không có | Cả hai | Bản rút gọn: độ lệch chuẩn thời lượng giữ + tỉ lệ clip tĩnh |

## Đề xuất ưu tiên

1. **Lint nhịp theo giọng (code + test).** Bảng base/min/max theo tone, số slot, tổng ±10%, hero giữ lâu nhất, CV thời lượng giữ > ngưỡng để tránh slideshow. Làm test bằng fixture timeline. Chọn một bộ số duy nhất vì bản gốc tự mâu thuẫn.
2. **Lint mối nối và chuyển cảnh (code + test).** Không lặp clip, không có cặp liền kề trùng (chủ thể, cỡ cảnh), không quá 4 cú liền cùng bảng màu, ≤4 loại chuyển cảnh, có danh sách cấm, không freeze-frame cuối. Dữ liệu lấy từ hồ sơ hình đã có.
3. **Hợp đồng âm thanh và kết phim (code + test).** Nhạc bắt buộc trừ khi opt-out có lý do; khoảng lặng ~2s với phim ≥60s; fade đuôi 3–5s; câu kết 3–9 từ, 5–8s. QC đo bằng ffprobe/RMS và kiểm tra frame tại `offset+2s`.
4. **Ngưỡng tìm kiếm + log loại bỏ + provenance lúc chọn (code + test).** Áp ngưỡng điểm và kích thước kho ứng viên, tối đa 2 lượt mở rộng rồi báo "không tìm được"; bảng `pick_rejections` có lý do; chưa đủ provider/url/license thì không cho pick. Phù hợp privacy mode vì chỉ áp ở adapter cloud.
5. **Prompt cho storyboard và kịch bản (prompt).** Đưa 3 prompt ở mục trên vào Director (mô tả kiểu người tìm bối cảnh), vào giám khảo sourcing (chọn bằng phán đoán, ghi lý do) và vào bước topic (1 câu hỏi chủ đề + 3 phương án câu kết), bằng tiếng Việt, riêng query stock giữ tiếng Anh (suy ra).
