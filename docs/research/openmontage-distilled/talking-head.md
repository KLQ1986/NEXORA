<!-- Chưng cất từ OpenMontage a2652b4 bằng claude -p (Opus), 2026-10-19; 129s; chi phí theo gói: 0.6249278 -->

# talking-head

`talking-head` biến video quay sẵn cảnh một người nói trước máy thành video hoàn chỉnh: có phụ đề chạy theo từng chữ, đồ họa minh họa chèn lên hình, âm thanh đã xử lý và gói sẵn để đăng (`pipeline_defs/talking-head.yaml:3-6`). Pipeline lấy footage làm gốc chứ không xuất phát từ ý tưởng. Kịch bản được rút ra từ bản ghi lời nói chứ không viết mới. Độ dài video do footage gốc quyết định, và việc khó nhất là chép lời đúng và khớp thời gian (`skills/pipelines/talking-head/executive-producer.md:33-43`). Thể loại này hợp với người làm nội dung cá nhân, phỏng vấn, bài giảng hay chia sẻ chuyên môn (suy ra). Nên chọn khi đã có sẵn đoạn quay người nói kèm âm thanh. Không có tiếng thì không chạy được pipeline này (`executive-producer.md:201`). Chi phí thấp, mặc định 0,50 USD, vì gần như chỉ là xử lý (`talking-head.yaml:32`, `executive-producer.md:40`).

## Các bước

Có 7 stage chạy nối tiếp, do Executive Producer (EP) điều phối. EP được sửa lại một stage tối đa 3 lần và trả về stage trước tối đa 3 lần (`talking-head.yaml:29-34`, `executive-producer.md:105`).

| Stage | Mục đích | Đầu vào | Đầu ra | Người duyệt |
|---|---|---|---|---|
| idea | Đọc thông số footage bằng ffprobe, xem nhanh nội dung, lập brief (tiêu đề, hook, ý chính, giọng, nền tảng, thời lượng đích); chốt runtime remotion hoặc ffmpeg (`idea-director.md:11,25-53`) | footage thô | `brief`, `decision_log` (`talking-head.yaml:45-47`) | Có (`talking-head.yaml:49-50`) |
| script | Chép lời bằng WhisperX, có mốc thời gian từng chữ; chia đoạn theo chủ đề và khoảng lặng; gắn gợi ý chèn đồ họa (`script-director.md:21-44`) | `brief` | `script` (`talking-head.yaml:61-66`) | Có (`talking-head.yaml:72-73`) |
| scene_plan | Lấy mẫu khung hình, nhận diện phông xanh, vị trí người nói và vùng an toàn; đề xuất overlay theo nội dung lời nói; lên kế hoạch cắt lặng và đổi khung hình (`scene-director.md:21-226`) | `script` (+`brief`) | `scene_plan` kèm file props JSON cho Remotion (`scene-director.md:141`) | Có. Riêng kế hoạch tăng cường bắt buộc trình người dùng trước khi làm tiếp (`scene-director.md:111,143`) |
| assets | Làm phụ đề, tách và chuẩn hóa âm, tìm nhạc, tạo tài sản overlay. Trước khi làm hàng loạt phải duyệt một mẫu "hero" (`asset-director.md:19-61`) | `scene_plan` (+`script`) | `asset_manifest` | Có (`talking-head.yaml:126-127`) và thêm một lần duyệt mẫu hero (`asset-director.md:24-25`) |
| edit | Cắt lặng, dựng đoạn chính, cấu hình phụ đề, âm thanh, ducking, đặt overlay (`edit-director.md:17-63`) | `scene_plan`, `asset_manifest` | `edit_decisions` | Không (`talking-head.yaml:152`) |
| compose | Kiểm tra trước khi render; chạy chuỗi làm đẹp, tăng tốc, đổi khung hình; đốt phụ đề và overlay trong một lần chạy Remotion; trộn nhạc; encode; QA hình và tiếng (`compose-director.md:26-461`) | `edit_decisions`, `asset_manifest` | `render_report`, `final_review` | Không (`talking-head.yaml:204`), nhưng bảng sửa lỗi ASR phải trình người dùng (`compose-director.md:61`) |
| publish | Viết metadata (tiêu đề, mô tả, tag, chapter theo mốc đoạn), ý tưởng thumbnail, gói xuất bản ở trạng thái draft (`publish-director.md:16-41`) | `render_report`, `final_review` | `publish_log` | Có (`talking-head.yaml:222`) |

Mỗi stage cần duyệt sẽ ghi checkpoint `awaiting_human` rồi dừng lượt. Lời "cứ làm đi" ở cổng trước không có hiệu lực cho cổng sau (`idea-director.md:71-74`). Giá trị trong manifest là bắt buộc, code từ chối nếu thiếu cờ duyệt (`skills/meta/checkpoint-protocol.md:104-108`).

## Quy tắc dựng của thể loại

**Ngân sách và giới hạn chạy**
- Ngân sách mặc định 0,50 USD. Khi đã tiêu quá 80% mà vẫn còn stage thì cảnh báo và bỏ các bước làm đẹp tùy chọn (`talking-head.yaml:32`, `executive-producer.md:259-261`).
- Một stage được sửa tối đa 3 lần, quá thì cho qua kèm cảnh báo (`executive-producer.md:135-136,355`). Lưu ý `reviewer.md` lại ghi tối đa 2 vòng (`skills/meta/reviewer.md:86-87`), hai nơi mâu thuẫn nhau.
- Mỗi cặp stage chỉ được trả về 1 lần, toàn pipeline tối đa 3 lần. Tổng thời gian chạy tối đa 10 phút (`executive-producer.md:149,356-359`).
- Runtime chỉ được là remotion (ưu tiên) hoặc ffmpeg, không dùng HyperFrames, và phải nói rõ cho người dùng biết (`idea-director.md:11-13`, `compose-director.md:9-12`).

**Bản ghi lời (transcript) và cách chia đoạn**
- Độ tin cậy trung bình dưới 0,8 thì sửa lại bằng cách chạy model large-v3 (`executive-producer.md:212-214`).
- Chữ nào có xác suất dưới 0,7 thì đánh dấu kèm mốc thời gian để người dùng kiểm tra (`compose-director.md:43-44`).
- Mốc thời gian phải tăng dần. Khoảng trống quá 2 giây không có chữ nào thì có thể đã bỏ sót lời (`executive-producer.md:215-216`).
- Lặng quá 1,5 giây là chỗ có thể ngắt đoạn (`script-director.md:30`). Đoạn dài quá 60 giây thì cân nhắc tách ra (`executive-producer.md:222`).
- Footage dài hơn 3 lần thời lượng đích thì báo là cần cắt nhiều (`executive-producer.md:204`).

**Cảnh và cắt lặng**
- Mỗi đoạn kịch bản là một cảnh `talking_head` (`scene-director.md:180`). Các cảnh phải phủ kín footage: hở quá 1 giây hoặc chồng lên nhau thì phải sửa (`executive-producer.md:228-231`).
- Lấy 5 khung hình chia đều để phân tích bối cảnh quay; lấy 5-8 khung khi xem nội dung (`scene-director.md:25,63`).
- Cắt lặng với ngưỡng -35 dB, khoảng lặng tối thiểu 0,5 giây, chừa đệm 0,08 giây để khỏi mất chữ (`edit-director.md:25-27`, `scene-director.md:169-170,217`).
- Chế độ `remove` (cắt nhảy) dùng cho Reels/TikTok/Shorts. Chế độ `speed_up` (tua nhanh 6x qua đoạn lặng) dùng cho YouTube/LinkedIn (`edit-director.md:33-34`).
- Tổng thời gian lặng quá 5 giây thì khuyên cắt trước khi render (`compose-director.md:40`).

**Overlay (đồ họa và chữ trên hình)**
- Mỗi phút video thành phẩm có 3-6 overlay, mỗi cái hiện 3-5 giây (`scene-director.md:102,104`).
- Overlay xuất hiện đúng lúc người nói nhắc tới nội dung, ưu tiên chỗ người nói ngừng nghỉ (`scene-director.md:103,106`).
- Không dùng 5 `text_card` liền nhau, phải đổi loại (`scene-director.md:105`).
- `full_overlay` (phủ toàn khung) chỉ được 1-2 giây (`scene-director.md:206`, `compose-director.md:253`).
- Vị trí: `lower_third` là 30% dưới, `upper_third` 30% trên, `side_panel` 40% (`scene-director.md:203-205`). Compose lại ghi panel 45% (`compose-director.md:251-252`), hai nơi lệch nhau.
- `comparison` cần rộng từ 900px nên không dùng ở khung dọc 720px; thay bằng 2 `stat_card` hiện lần lượt (`scene-director.md:87,97`).
- `kpi_grid` chỉ nhận số thuần (`scene-director.md:99`, `asset-director.md:127`). Bảng ở `asset-director.md:97` lại gợi ý "2.4M", mâu thuẫn.
- Khi đổi tốc độ, tính lại mốc overlay theo công thức `t / speed_factor` (`compose-director.md:271`).

**Phụ đề**
- Lệch so với lời nói tối đa ±0,3 giây; lệch quá 0,5 giây thì làm lại phụ đề (`executive-producer.md:166-168,248-250`).
- Tối đa 5 chữ mỗi dòng SRT (`asset-director.md:40`).
- Phụ đề Remotion: 4 chữ mỗi trang, cỡ chữ 52, tô màu chữ đang đọc, đặt ở đáy khung (`compose-director.md:156,161-162,170-172`).
- Kích thước khung và số frame phải lấy từ kết quả probe, không ghi cứng (`compose-director.md:159-160`).
- Khi dùng FFmpeg dự phòng ở khung dọc: phụ đề nằm trong 20% dưới cùng, `MarginV` từ 160 trở lên trên chiều cao 1920. Không bao giờ để ở giữa hay nửa trên (`compose-director.md:179,186`).
- Luôn truyền bảng sửa lỗi ASR, kể cả khi rỗng `{}` (`compose-director.md:152`).

**Hình**
- Làm đẹp theo đúng thứ tự: mặt → mắt → màu → âm (`compose-director.md:67-72`).
- Cường độ chỉnh mắt giữ trong 0,2-0,5 (`compose-director.md:84`).
- Thứ tự xử lý: tăng tốc sau làm đẹp, trước reframe (`compose-director.md:107`). Reframe làm sau làm đẹp và chỉnh màu nhưng trước khi đốt phụ đề, dùng `face_padding` 0,4 và `smoothing_window` 15 (`compose-director.md:118-119,133`).
- Tỉ lệ khung theo nền tảng: 9:16 cho Reels/TikTok/Shorts, 1:1 cho feed, 16:9 cho YouTube/LinkedIn, 4:5 cho bài dọc Instagram (`compose-director.md:126-129`).
- Hệ số tăng tốc 1,25 cho nhịp gọn mà vẫn tự nhiên; 1,5 cho đoạn tóm tắt (`compose-director.md:103-104`).

**Âm thanh và nhạc**
- Lời nói chuẩn hóa về -16 LUFS (`executive-producer.md:172`).
- Nhạc nền duck còn 15% dưới lời nói (`compose-director.md:322-328`).
- Với reel nhiều clip, dùng `segmented_music` ở mức 0,20, fade 0,5 giây, chỉ phát trong các đoạn có người nói (`compose-director.md:376-381`).
- Chạy `audio_energy` để bỏ phần mở đầu nhạc quá nhỏ (`asset-director.md:57`).

**Chuyển cảnh và xuất file**
- Ghép clip bằng crossfade 0,5 giây khi chuyển từ người nói sang clip trình diễn; giữa các clip trình diễn thì dip đen (`compose-director.md:357-364`).
- Thời lượng thành phẩm lệch tối đa ±5% so với đích (`executive-producer.md:159,281`).
- Encode cuối là bắt buộc (`compose-director.md:393`).
- Dung lượng: Reels tối đa 90 giây và dưới 50 MB; TikTok dưới 100 MB; Shorts tối đa 60 giây và dưới 40 MB; YouTube dưới 25 MB/phút (`compose-director.md:402-405`). Mẫu cấu hình dùng 4M video / 192k audio (`compose-director.md:415-416`).
- Chapter lấy theo mốc các đoạn kịch bản (`publish-director.md:22`).
- Skill không có luật nào về câu kết hay CTA cuối video.

## Checklist duyệt

- [ ] Mọi artifact đều qua kiểm tra schema (`talking-head.yaml:56,79,106,133,158,210,227`). Sai schema là lỗi critical (`reviewer.md:35`).
- [ ] Brief nhắc đúng file footage, có nền tảng đích, và thời lượng đích không vượt độ dài footage (`talking-head.yaml:52-57`).
- [ ] Footage có track âm thanh và đã được probe trước khi bắt đầu (`executive-producer.md:201,444`).
- [ ] Độ tin cậy transcript trung bình từ 0,8 trở lên; danh sách chữ dưới 0,7 đã được người dùng xem (`executive-producer.md:212`, `compose-director.md:43`).
- [ ] Mốc thời gian các đoạn tăng dần và nằm trong độ dài footage (`talking-head.yaml:80`, `executive-producer.md:215,221`).
- [ ] Các cảnh phủ kín footage: không có khoảng hở quá 1 giây, không chồng nhau (`talking-head.yaml:107`, `executive-producer.md:230-231`).
- [ ] Overlay có mật độ 3-6 mỗi phút và mỗi cái dài 3-5 giây (`scene-director.md:234`).
- [ ] Mỗi overlay khớp một câu nói tại đúng mốc đó và có số liệu đúng lời người nói (`scene-director.md:233`, `asset-director.md:174`).
- [ ] Không có component nào vi phạm ràng buộc chiều rộng hoặc kiểu giá trị (`scene-director.md:238`).
- [ ] File phụ đề tồn tại và mọi cue lệch dưới 0,3 giây (`talking-head.yaml:129`, `executive-producer.md:248`).
- [ ] Mọi đường dẫn tài sản trỏ tới file có thật (`talking-head.yaml:131,134`).
- [ ] Các cắt trỏ tới file nguồn hợp lệ và mốc nằm trong độ dài nguồn (`talking-head.yaml:159-160`).
- [ ] Phụ đề đã bật, có style, và cấu hình âm thanh đầy đủ (`talking-head.yaml:155-156`).
- [ ] File thành phẩm tồn tại và phát được; thời lượng lệch ≤5%; độ phân giải đúng đích (`talking-head.yaml:206,211`, `executive-producer.md:159-160`).
- [ ] Âm lượng ≈ -16 LUFS, không clipping; nếu có nhạc thì đã duck (`executive-producer.md:171-173`).
- [ ] Trên các khung lấy từ visual_qa, phụ đề nằm ở đáy và không đè lên mặt (`compose-director.md:431`).
- [ ] Dung lượng file nằm trong ngưỡng của nền tảng (`compose-director.md:399-407`).
- [ ] Metadata có đủ tiêu đề, mô tả, tag, chapter, và có gói xuất bản hoặc URL (`talking-head.yaml:224-228`).

## Lỗi hay gặp

- Để transcript tệ chảy xuống các stage sau, làm sai phụ đề và cắt dựng. Không giữ `transcript_segments` xuyên suốt tới stage assets (`executive-producer.md:441,446`).
- Làm đẹp quá tay: footage đã ổn mà vẫn chạy face/color, hoặc chỉnh mắt quá mạnh khiến trông giả (`executive-producer.md:442`, `compose-director.md:84`).
- Phụ đề dùng style SRT mặc định thay vì style của playbook (`executive-producer.md:443`). Phụ đề nằm giữa khung đè lên mặt (`compose-director.md:179,186`).
- Cắt quá tay những đoạn trông như lạc đề nhưng thật ra chứa bối cảnh (`executive-producer.md:445`).
- Nhồi quá nhiều overlay hoặc lặp một loại; overlay xuất hiện không trùng lúc người nói nhắc tới (`scene-director.md:102-105`).
- Ghi cứng width/height hoặc số frame khi render phụ đề (`compose-director.md:159-160`).
- Đưa chuỗi như "15+" vào `kpi_grid`, hoặc dùng `comparison` ở khung dọc 720px (`asset-director.md:126-127`).
- Dùng nền màu phẳng thay cho AnimatedBackground (`asset-director.md:108`, `compose-director.md:291`).
- Bỏ bước encode cuối, ra file quá nặng (Reel 66 giây nặng 76 MB) (`compose-director.md:393,407`).
- Sinh tài sản hàng loạt trước khi người dùng duyệt mẫu hero (`asset-director.md:27`).
- Tự chọn runtime mà không báo người dùng; tự làm stage tiếp theo ngay trong cùng lượt sau cổng duyệt (`idea-director.md:13,73`).
- Đổi tốc độ nhưng quên tính lại mốc overlay (`compose-director.md:271`).

## Prompt đáng giữ

1. **Nghe hiểu rồi mới đề xuất** (`scene-director.md:53-61,101-106`): "Đọc hết transcript. Đánh dấu chỗ người nói đưa ra con số, so sánh A với B, liệt kê, thuật ngữ mới, chuyển chủ đề, và cung bậc cảm xúc. Mỗi chỗ đề xuất đúng một overlay hợp loại, đặt ngay lúc họ nói câu đó, dài 3-5 giây, 3-6 cái mỗi phút, không lặp loại. Trình bảng | Thời điểm | Loại | Nội dung | Lý do | rồi chờ duyệt."
2. **Kiểm từ dễ nghe nhầm** (`compose-director.md:42-45,137-152`): "Quét transcript tìm tên riêng, tên thương hiệu, thuật ngữ chuyên ngành và chữ có độ tin cậy dưới 0,7. Lập bảng sửa sai → đúng, trình người dùng xem, rồi áp cho cả phụ đề lẫn caption. Không cần sửa gì thì vẫn trả về bảng rỗng để chứng minh đã kiểm."
3. **Phản biện phải kèm cách sửa** (`reviewer.md:15,17,42`): "Mỗi lỗi nghiêm trọng phải kèm cách sửa cụ thể (câu thay thế, giá trị trường). Không đưa ra được cách sửa thì xếp vào loại 'cần điều tra'. Tìm thấy một lỗi thì quét tiếp các lỗi cùng loại ở chỗ khác trước khi trả kết quả."

## Đối chiếu NEXORA

| Điều OpenMontage làm | NEXORA đã có | Còn thiếu | Đề xuất cụ thể |
|---|---|---|---|
| Chế độ footage làm gốc: kịch bản rút từ transcript (`script-director.md:7`) | Phân tích lời nói trong thư viện; kịch bản viết theo chủ đề | Luồng kịch bản = transcript đã chia đoạn (suy ra) | Thêm template "talking-head": đoạn = khoảng lời nói có `start`/`end`; Claude chỉ chia đoạn và gắn gợi ý chèn đồ họa, không viết lại lời |
| Cổng chất lượng transcript: tin cậy ≥0,8, chữ <0,7, khoảng trống >2 giây (`executive-producer.md:210-222`) | Phân tích lời nói | Không thấy ngưỡng tin cậy và cổng chặn (suy ra) | Thêm stage gate trong orchestrator; trượt thì sửa lại stage script |
| Phụ đề khớp từng chữ ±0,3 giây (`executive-producer.md:248`) | QC phụ đề | Không rõ có đo độ lệch so với mốc từng chữ (suy ra) | Thêm metric `max_cue_drift_s` vào QC phụ đề: ≤0,3 là pass, >0,5 là sửa lại |
| Sửa lỗi ASR cho tên riêng (`compose-director.md:135-152`) | — | Bảng sửa lỗi theo dự án và theo tiếng Việt (thanh dấu, tên riêng) (suy ra) | Lưu bảng sửa lỗi trong DB theo kênh; Copilot đề xuất, người duyệt |
| Overlay 3-6/phút, 3-5 giây, đúng lúc nói (`scene-director.md:102-106`) | Storyboard, shot spec, Copilot | Không có luật mật độ/thời lượng chữ trên hình (suy ra) | Đưa luật overlay vào shot spec và đo trong QC nhịp |
| Vùng an toàn quanh mặt; phụ đề trong 20% dưới (`scene-director.md:40-45`, `compose-director.md:179`) | Hồ sơ hình, cú máy | Kiểm phụ đề/overlay có đè lên khung mặt (suy ra) | QC hình: giao giữa bbox chữ và bbox mặt phải bằng 0 trên các khung lấy mẫu |
| Cắt lặng -35 dB / 0,5 giây / đệm 0,08 giây; remove hoặc speed_up theo nền tảng (`edit-director.md:22-34`) | FilmCraft/ffmpeg, QC nhịp | Bộ thông số chuẩn và chế độ theo nền tảng (suy ra) | Đưa thông số vào preset dựng theo nền tảng |
| Âm -16 LUFS, duck nhạc 15% (`executive-producer.md:172`, `compose-director.md:327`) | QC tiếng | Không rõ có mục tiêu số cụ thể (suy ra) | Đặt ngưỡng LUFS và mức duck trong QC tiếng |
| Ngưỡng dung lượng/thời lượng theo nền tảng (`compose-director.md:399-407`) | Cổng bản quyền khi đăng | Kiểm thông số xuất theo nền tảng | Thêm bước kiểm đóng gói trước khi đăng |
| EP trả về stage nguồn kèm phản hồi có cấu trúc, tối đa 1 lần mỗi cặp stage (`executive-producer.md:143-149,287-336`) | run/stage, kill switch, gate | Trả về stage trước với lý do, có giới hạn (suy ra) | Bảng `send_back` (từ stage, tới stage, lý do, số lần), giới hạn 1 lần mỗi cặp và 3 lần mỗi run |
| Duyệt mẫu hero trước khi làm hàng loạt (`asset-director.md:19-27`) | Gate người, tự duyệt có công tắc | Gate trung gian trong một stage (suy ra) | Thêm gate con "mẫu hero" trước khi sinh overlay hàng loạt |
| Nhạc Pixabay, web_search (`asset-director.md:56`, `script-director.md:61`) | Privacy mode chặn cloud | — | Privacy mode tắt 2 bước này, dùng thư viện nhạc cục bộ; WhisperX chạy cục bộ trên Mac (suy ra) |

## Đề xuất ưu tiên

1. **Cổng khớp phụ đề (code có test).** So từng cue với mốc chữ trong transcript: ≤0,3 giây là pass, trên 0,5 giây thì làm lại phụ đề. Test với cue lệch giả lập 0,2 / 0,4 / 0,6 giây.
2. **Cổng chất lượng transcript cùng bảng sửa lỗi tiếng Việt.** Phần cổng là code có test: tin cậy trung bình ≥0,8, đánh dấu chữ <0,7, mốc tăng dần, khoảng trống >2 giây, đoạn >60 giây. Phần đề xuất từ cần sửa (tên riêng, thanh dấu) là prompt cho Copilot, và người dùng duyệt bảng sửa lỗi qua gate.
3. **Luật bố cục chữ trên hình (code có test).** Mật độ 3-6 overlay mỗi phút, mỗi cái 3-5 giây, `full_overlay` ≤2 giây, không quá 4 overlay cùng loại liền nhau, ràng buộc chiều rộng/kiểu giá trị của component. Phụ đề trong 20% dưới và không giao với bbox mặt.
4. **Kiểm thành phẩm theo nền tảng (code có test).** Thời lượng lệch ≤5%, âm ≈ -16 LUFS (dung sai tự đặt, suy ra), dung lượng và thời lượng tối đa theo nền tảng, tổng lặng còn lại dưới 5 giây.
5. **Prompt "nghe hiểu rồi đề xuất" cho Storyboard/Director ở chế độ talking-head.** Dùng Prompt 1 để đề xuất overlay neo vào câu nói. Kết quả ra bảng duyệt qua gate người, và luật ở mục 3 sẽ chấm lại bảng này.
