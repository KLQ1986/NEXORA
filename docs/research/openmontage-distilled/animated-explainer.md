<!-- Chưng cất từ OpenMontage a2652b4 bằng claude -p (Opus), 2026-10-19; 151s; chi phí theo gói: 1.060702 -->

# animated-explainer

Đây là thể loại video giải thích sinh hoàn toàn bằng AI từ một chủ đề hay ý tưởng: lời đọc, hình và nhạc đều do máy làm ra, không dùng footage có sẵn (`pipeline_defs/animated-explainer.yaml:3-4`). Quy trình nghiên cứu trước. Agent tìm hiểu chủ đề, đưa ra các concept kèm chi phí và phải được người dùng duyệt rõ ràng rồi mới sinh asset (`animated-explainer.yaml:5-6`). Thể loại này hợp với người cần video ngắn có số liệu và nguồn để đăng TikTok, Reels, YouTube hay LinkedIn, dài 30–180s (`skills/pipelines/explainer/proposal-director.md:222-228`). Nên chọn khi chủ đề trừu tượng và cần sơ đồ, biểu đồ, thẻ số liệu thay vì cảnh quay thật. Không nên chọn khi đã có footage tự quay (suy ra). Ghi chú: thư mục `skills/pipelines/animated-explainer/` không tồn tại. YAML trỏ tới `skills/pipelines/explainer/` (`animated-explainer.yaml:30-38`). `idea-director.md` có trong thư mục đó nhưng không nằm trong `required_skills`.

## Các bước

Người điều phối là Executive Producer. Nó chạy các stage tuần tự, có thể trả việc về stage trước (send-back) và giữ trạng thái xuyên stage (`executive-producer.md:5,80,129-135`).

| Stage | Mục đích | Đầu vào | Đầu ra | Người duyệt |
|---|---|---|---|---|
| research | Khảo sát nội dung đã có, xu hướng, số liệu có nguồn, câu hỏi thật của khán giả, các góc tiếp cận; chỉ dùng web search, không tốn tiền (`research-director.md:5,318`) | Chủ đề, gợi ý khán giả/nền tảng | `research_brief` | Không, và không ghi checkpoint (`yaml:69-70`; `executive-producer.md:184`) |
| proposal | ≥3 concept, mood board, kế hoạch sản xuất, ước tính chi phí từng hạng mục, kế hoạch nhạc và giọng, chọn render runtime | `research_brief` | `proposal_packet`, `decision_log` | **Có**. Đây là cổng chặn trước khi tiêu tiền (`yaml:90-91`; `proposal-director.md:445`) |
| ↳ sample | Clip mẫu 10–15s (hook cộng một cảnh giữa), chỉ chạy khi có video tham chiếu | Concept đã duyệt | `sample_v{N}.mp4` | **Có** (`yaml:106-109`; `checkpoint-protocol.md:209`) |
| script | Viết lời đọc theo ngân sách từ, kèm cue hình và chỉ dẫn giọng | `proposal_packet` (+`research_brief`) | `script` | **Có** (`yaml:127-128`) |
| scene_plan | Tách mỗi section thành 1–3 cảnh, mỗi cảnh có loại, khung, chuyển động, transition, asset cần có | `script` (+proposal) | `scene_plan` | **Có** (`yaml:149-150`) |
| assets | Tạo mẫu trước, sau đó sinh hàng loạt TTS, ảnh, sơ đồ, nhạc; kiểm tra file và thời lượng | `scene_plan`, `script` | `asset_manifest` | **Có**. Duyệt dạng filmstrip, không render nháp (`yaml:186-187`; `checkpoint-protocol.md:151-167`) |
| edit | Lập EDL gồm cut, layer, phụ đề, nhạc có ducking, luật nhịp | `scene_plan`, `asset_manifest` | `edit_decisions` | Không, nhưng có checkpoint (`yaml:208-210`) |
| compose | Kiểm tra trước render, render, rồi tự review bản render (probe, khung hình, phiên âm) | `edit_decisions`, `asset_manifest` | `render_report`, `final_review` | Không. Vẫn trình review cho người trước khi coi là bản cuối (`yaml:239-240`; `compose-director.md:371`) |
| publish | Viết metadata SEO, chapter, ý tưởng thumbnail, đóng gói export (không upload) | `render_report`, `final_review` | `publish_log` | **Có** (`yaml:261-262`; `publish-director.md:112`) |

Giới hạn chạy: tối đa 3 lần sửa mỗi stage, 3 lần send-back, ngân sách mặc định $2, thời gian 20 phút (`yaml:48-51`). Các file khác nhau ở vài chỗ. EP ghi 15 phút và 1 send-back cho mỗi cặp stage (`executive-producer.md:335,338`), còn reviewer chỉ cho 2 vòng (`reviewer.md:86-87`). Khi chạm giới hạn thì đi tiếp kèm cảnh báo, không chặn (`executive-producer.md:340`).

## Quy tắc dựng của thể loại

- Thời lượng theo nền tảng: TikTok/Shorts 30–60s, Reels 30–90s, YouTube 60–180s, LinkedIn 60–120s — `proposal-director.md:222-228`
- Ngân sách từ ở ~150 từ/phút: 30s ≈ 65–75 từ, 60s ≈ 130–150, 90s ≈ 195–225, 120s ≈ 260–300 — `script-director.md:117-128`
- Tổng thời lượng kịch bản lệch tối đa ±10% so với mục tiêu — `animated-explainer.yaml:130,138`. EP yêu cầu sửa khi ước tính vượt 115% hoặc dưới 70% — `executive-producer.md:205-210`
- Lời đọc chiếm 85–90% thời lượng video. Tốc độ 2.0–2.5 từ/giây cho giọng tài liệu, 2.5–3.0 cho giọng năng động — `scene-director.md:140-141`
- Chừa 0.5–1s lặng giữa các cảnh. Cảnh mở và cảnh kết chỉ có lời đọc ngắn — `scene-director.md:147,152`
- Cung truyện: HOOK 0–5s, SETUP 5–15s, BUILD, CLIMAX, LANDING 5s cuối — `script-director.md:57-75`
- Hook dưới 20 từ, phải tạo khoảng trống thông tin, phải dựa trên một phát hiện nghiên cứu. Cấm mở bằng "In this video…", "Hey guys…" — `proposal-director.md:151-154`
- Nối các section bằng "therefore/but", không dùng "and then" — `script-director.md:66-68`
- Ít nhất 1 enhancement cue mỗi 8–10s; video 60s cần tối thiểu 6–8 cue — `script-director.md:166`; `yaml:131`
- Mỗi section lời đọc có ≥2 delivery cue cụ thể (pace, energy, emphasis, pause…) — `script-director.md:147-151`
- Mỗi section tách thành 1–3 cảnh — `scene-director.md:41`
- Thời lượng cảnh theo loại: hero_title/text_card 3–5s, stat_card/comparison/callout 4–6s, chart/kpi 5–7s, diagram 4–8s, generated/broll 3–6s — `scene-director.md:70-84`
- Không quá 3 cảnh liền nhau cùng loại, dùng ≥3 loại cảnh — `scene-director.md:202-203`; `yaml:158`. YAML lại ghi "no 3+ consecutive" (`yaml:153`), chặt hơn và mâu thuẫn với hai chỗ trên
- Khoảng hở giữa các cảnh quá 1s thì phải sửa — `scene-director.md:198`; `executive-producer.md:218`
- Tối đa 20% số cảnh được cố ý lệch playbook, và phải ghi `playbook_override` — `proposal-director.md:267`
- Chữ phải đúng nguyên văn (CTA, tên, số điện thoại, pháp lý) thì render bằng `text_card`, không dùng ảnh AI — `scene-director.md:240`; `asset-director.md:261`
- Mỗi đoạn TTS lệch ±15% so với dự kiến. Vượt 15% thì gửi về script kèm số từ tối đa; vượt đến 25% thì có thể nới cảnh — `asset-director.md:98`; `executive-producer.md:237-241`
- Nhạc: volume 0.08, fade in 2s, fade out 3s, ducking −8 dB, attack 200ms, release 500ms — `edit-director.md:96-106`. Nhánh Remotion dùng 0.12, 1.5s, 2.5s — `compose-director.md:196`
- Bài nhạc phải dài ít nhất bằng video, nếu ngắn hơn thì loop. Không có nhạc thì ghi `music_status: unavailable`, không được im lặng bỏ qua — `asset-director.md:140-141`
- Nguồn nhạc chốt ngay ở proposal, ưu tiên `music_library/` trước — `proposal-director.md:368,398`
- Phụ đề bắt buộc: ≤8 từ/dòng, cỡ 48, nhánh SRT ≤42 ký tự/dòng, burn cứng vào hình — `edit-director.md:63-76`; `compose-director.md:267-273,443`
- Câu kết: LANDING tóm lại thông điệp chính cộng CTA, không đưa thông tin mới. CTA phải cụ thể, làm theo được — `script-director.md:73-74,203`
- Thành phẩm lệch ±5% thời lượng mục tiêu; đồng bộ hình–tiếng ±0.5s — `yaml:243`; `executive-producer.md:153,262`
- Publish: tiêu đề ≤60 ký tự, 5–10 tag, 3–5 hashtag, chữ trên thumbnail 3–5 từ, chapter bám `start_seconds` của từng section — `publish-director.md:28,42,47,55,84`
- Ngân sách: cảnh báo khi đã tiêu 90%, giữ ≥30% cho assets và compose — `executive-producer.md:245-247,420`
- Nghiên cứu: ≥3 data point, ≥5 nguồn, ≥2 nguồn gốc, gắn cờ nguồn cũ hơn 2 năm, chạy 10–25 lượt tìm — `research-director.md:236-242,297-317`

## Checklist duyệt

**research**
- [ ] Có ≥3 nội dung đã khảo sát, ≥3 data point có URL, ≥5 nguồn, ≥2 nguồn gốc (`yaml:72-80`; `research-director.md:240`)
- [ ] Có ≥3 góc tiếp cận, góc nào cũng có `grounded_in`; câu hỏi khán giả lấy từ forum thật (`yaml:74-76`)

**proposal**
- [ ] Có ≥3 concept khác nhau về cấu trúc truyện và mẫu hook; `selected_concept` trỏ đúng một `concept_id` (`yaml:93,101-102`; `proposal-director.md:253-255`)
- [ ] Chi phí chia theo từng công cụ, so với trần ngân sách, đưa ≥2 phương án sản xuất ở các mức giá khác nhau (`yaml:96-98,103`; `proposal-director.md:470`)
- [ ] `approval.status` là approved hoặc approved_with_changes (`yaml:104`)
- [ ] Quyết định chọn runtime liệt kê đủ các runtime trong `options_considered` (`reviewer.md:253-256`)

**script**
- [ ] Số từ lệch ≤±10% ngân sách; có ≥1 cue mỗi 8–10s; đủ 5 phần hook→setup→build→climax→landing (`yaml:130-132`)
- [ ] Mỗi section có chỉ dẫn giọng và ≥2 delivery cue; có `voice_performance` kèm section dùng làm mẫu (`yaml:133-134`; `script-director.md:81-84`)
- [ ] Mọi dữ kiện truy được về `research_brief` (`script-director.md:218-220`)

**scene_plan**
- [ ] Cảnh phủ kín 0→tổng thời lượng, không hở >1s; không quá 3 cảnh liền cùng loại; dùng ≥3 loại (`yaml:152-158`)
- [ ] Mỗi `required_asset` làm được bằng công cụ có trong plan; mỗi cảnh ghi đủ 5 khía cạnh, chỗ nào không áp dụng thì ghi N/A rõ ràng (`yaml:154`; `scene-director.md:161`)

**assets**
- [ ] Mọi path đều tồn tại; có narration cho mọi section; tổng chi phí ≤ ngân sách đã duyệt (`yaml:189-196`)
- [ ] Mỗi đoạn TTS lệch ≤±15%; batch dùng đúng giọng và tham số của mẫu đã duyệt (`asset-director.md:217-219`)

**edit**
- [ ] Mọi cut tham chiếu asset có thật; không hở, không chồng; phụ đề bật; ducking đã cấu hình (`yaml:211-217`)
- [ ] Không có cut nào ngắn hơn hay dài hơn mức hold của playbook (`edit-director.md:118-121`)

**compose**
- [ ] ffprobe chạy được, có luồng audio, thời lượng lệch ≤±5%, độ phân giải khớp profile (`yaml:242-243,249`; `compose-director.md:304-315`)
- [ ] Phiên âm bản render ra >0 từ, đạt ≥80% số từ kịch bản, từ cuối khớp kịch bản (`compose-director.md:339-352`)
- [ ] `final_review` có ≥4 frame mẫu; runtime thực chạy khớp proposal (`reviewer.md:307`; `yaml:245`)
- [ ] Không có khoảng lặng hay clipping >1s (`compose-director.md:384`)

**publish**
- [ ] `final_review.status == pass`; có chapter; thư mục export có video, metadata, thumbnail (`reviewer.md:317`; `yaml:265-269`)

## Lỗi hay gặp

- Viết quá nhiều từ. Đây là lỗi số 1: TTS có nhịp cố định nên lời sẽ bị đọc dồn hoặc video bị kéo dài (`script-director.md:224`).
- Hook dồn thông tin thay vì khơi tò mò. Chỉ dẫn giọng chung chung kiểu "đọc tự nhiên" (`script-director.md:225,227`).
- 3 concept thực chất là 1, chỉ đổi tên. Concept không bám nghiên cứu (`proposal-director.md:465,468`).
- Hứa trước những công cụ chưa có, giấu chi phí (`proposal-director.md:466-467`).
- Mỗi section chỉ một cảnh nên hình đứng im. Concept động mà dùng ảnh tĩnh. Mô tả asset mơ hồ. Chỉ ghi tên preset (`scene-director.md:233-239`).
- Dùng ảnh AI cho cảnh có chữ phải đúng nguyên văn, mô hình bịa sai chữ (`scene-director.md:240`; `asset-director.md:261`).
- Dán cùng một style prefix vào mọi prompt ảnh nên trông "máy làm". Retry y nguyên prompt cũ (`asset-director.md:256,260`).
- Sinh asset trước khi kiểm ngân sách. Bỏ qua delivery cue (`asset-director.md:255,258`).
- Hở timeline gây khung đen. Không ducking. Một kiểu transition cho mọi cut. Phụ đề sai font (`edit-director.md:166-170`).
- Chỉ xem frame mà bỏ bước phiên âm, nên lọt cả video mất tiếng (`compose-director.md:300-302`).
- Lặng lẽ đổi runtime hoặc hạ chất lượng từ chuyển động xuống ảnh tĩnh (`reviewer.md:250,313`).
- Sửa quá tay, send-back quá sớm cho lỗi nhỏ (±10%), không mang style anchor theo (`executive-producer.md:419-423`).
- Đã "go ahead" một lần rồi bỏ qua các gate sau. Mỗi gate cần duyệt riêng (`checkpoint-protocol.md:145-149`).

## Prompt đáng giữ

1. **Biên kịch theo ngân sách** (`script-director.md:57-75,130,166`): "Đếm từ trước khi viết. Mở bằng câu hỏi, khẳng định táo bạo hoặc một dữ kiện bất ngờ; không bao giờ mở bằng 'Trong video này…'. Các đoạn nối nhau bằng 'vì vậy / nhưng', không dùng 'rồi thì'. Mỗi 8–10 giây phải có một chỉ dẫn hình. Đoạn kết chỉ nhắc lại thông điệp chính cộng một lời kêu gọi cụ thể, không thêm ý mới. Vượt ngân sách 20% thì cắt thẳng tay."
2. **Tự soát prompt sinh hình 3 bước** (`asset-director.md:194-206`): "Viết bản nháp prompt. Chấm bản nháp theo 5 khía cạnh: chủ thể, chuyển động của chủ thể, bối cảnh/overlay, khung hình, máy quay. Khía cạnh nào thiếu thì phải là cố ý (ghi N/A). Tách nghĩa các thuật ngữ dễ lẫn (dolly hay zoom). Thay tính từ cảm tính như 'hiện đại', 'chuyên nghiệp' bằng nguyên nhân thị giác cụ thể. Viết lại rồi mới gửi; lưu bộ ba (nháp, phê bình, bản cuối) để kiểm toán."
3. **Phê bình CHAI cho giám khảo/Copilot** (`reviewer.md:11-19,42`): "Mỗi nhận xét phải chỉ ra trường, mốc thời gian hoặc khung hình cụ thể. Gặp một lỗi thì quét hết các lỗi cùng loại. Lỗi nghiêm trọng phải kèm cách sửa cụ thể (đoạn văn thay thế, giá trị trường). Nếu không đưa được cách sửa thì hạ xuống mức 'cần điều tra'."

## Đối chiếu NEXORA

| Điều OpenMontage làm | NEXORA đã có | Còn thiếu | Đề xuất cụ thể |
|---|---|---|---|
| Research brief có ngưỡng: ≥3 data point, ≥5 nguồn, ≥2 nguồn gốc, gắn cờ nguồn >2 năm | Kiểm chứng dữ kiện có nguồn | Không rõ có ngưỡng định lượng hay không | Validator đếm nguồn, nguồn gốc và tuổi nguồn trước gate kịch bản |
| ≥3 concept khác biệt kèm chi phí, duyệt trước khi tiêu tài nguyên | Viết theo topic, có template, gate trong DB | Không rõ có bước đưa nhiều concept/hook kèm `grounded_in` | Prompt tạo 3 concept khác cấu trúc truyện, có gate trước bước dựng |
| Ngân sách từ theo thời lượng (±10%) và vòng TTS→script (±15%) | Kịch bản và phản biện | Tốc độ đọc tiếng Việt chưa hiệu chỉnh (suy ra) | Đo âm tiết/giây trên giọng thật, đặt luật ±10% |
| ≥1 cue hình mỗi 8–10s; mỗi section 1–3 cảnh | Storyboard có shot spec | Luật mật độ đo được | Kiểm tra số lần đổi hình theo cửa sổ 10s |
| Đa dạng cảnh (≤3 liên tiếp cùng loại, ≥3 loại) và slideshow risk | Director, Copilot, mối nối giữa shot | Chấm nguy cơ "slideshow" | Hàm điểm theo các chiều lặp layout, tỉ lệ thẻ chữ, cảnh thiếu mục đích (`reviewer.md:191-199`) |
| Checklist 5 khía cạnh, overlay tách riêng, N/A ghi rõ | Khung, ống kính, chuyển động, nghiệm thu | Không rõ có tách overlay và có bắt ghi N/A | Thêm trường `overlays[]` và bắt buộc có lý do N/A |
| Chữ nguyên văn render bằng code | (không rõ) | Quy tắc này | Cấm sinh chữ trong ảnh/video AI cho cảnh CTA, tên riêng |
| Duyệt mẫu trước batch (TTS, ảnh, nhạc ≤3 vòng) | Chấm stock qua ảnh xem trước rồi mới tải | Chấm điểm nhà cung cấp | Lưu điểm duyệt và từ chối theo từng nhà cung cấp |
| Phụ đề bắt buộc (≤8 từ, ≤42 ký tự), ducking −8 dB | FilmCraft/ffmpeg, QC phụ đề | Không rõ ngưỡng cụ thể | Đưa các ngưỡng vào QC |
| Review sau render: có audio, ±5%, phiên âm ≥80%, ≥4 frame | QC hình, tiếng, phụ đề, nhịp | Không rõ có so phiên âm bản render với kịch bản | Thêm bước phiên âm tiếng Việt (OpenMontage để cứng `'en'`: `compose-director.md:336`) |
| Delivery promise, cấm lặng lẽ đổi runtime | Không | Delivery promise | Ghi lời hứa vào gate, QC đối chiếu tỉ lệ cảnh động |
| Gate theo từng stage, `awaiting_human`, ghi `approval_policy` khi được ủy quyền | Gate trong DB, tự duyệt có công tắc | Không rõ có log lý do khi bật tự duyệt | Ghi quyết định mỗi lần tự duyệt thay người |
| Resume giữa stage (`partial_progress`) | Lease, timeout, kill switch | Không rõ resume ở mức từng cảnh | Lưu danh sách scene đã xong trong stage |
| Kiểm tra giấy phép khi publish | Cổng bản quyền khi đăng | Lọc giấy phép theo loại | Phân loại giấy phép từ lúc sourcing (suy ra) |
| Ngân sách $, cảnh báo 90%, giữ 30% | Privacy mode chặn cloud | Ước tính chi phí từng hạng mục | Ước tính thời gian/chi phí cloud cho từng job (suy ra) |

## Đề xuất ưu tiên

1. **Validator storyboard. Code có test.** Gồm: không quá 3 shot liền cùng loại, ≥3 loại, không hở >1s, ≥1 lần đổi hình mỗi 10s, thời lượng shot nằm trong khoảng theo loại. Đây là phiên bản đầu của chỉ số "slideshow risk". Test bằng fixture storyboard đạt và trượt.
2. **QC sau dựng mở rộng. Code có test.** Gồm: có luồng audio, thời lượng ±5%, phiên âm tiếng Việt bản render đạt ≥80% số từ kịch bản và từ cuối khớp, ≥4 frame mẫu, không lặng >1s, phụ đề ≤8 từ và ≤42 ký tự/dòng. Test bằng file mẫu thiếu tiếng hoặc bị cắt đuôi.
3. **Ngân sách lời đọc tiếng Việt và vòng phản hồi. Code có test.** Đo âm tiết/giây trên giọng thật (suy ra: không dùng 150 WPM tiếng Anh). Kiểm ±10% ở gate kịch bản. Sau khi có audio, đoạn nào vượt 15% thì tự trả về kịch bản kèm số âm tiết tối đa. Test bằng số liệu giả lập.
4. **Prompt biên kịch và Copilot.** Dùng bộ prompt mục 1 và 3 ở phần "Prompt đáng giữ": cung 5 phần, câu nối "vì vậy/nhưng", đoạn kết không thêm ý mới và có CTA cụ thể, nhận xét bắt buộc kèm cách sửa. Đây là prompt, không phải luật đo được.
5. **Delivery promise và chữ nguyên văn. Code (schema/kiểm tra) kèm prompt.** Lưu lời hứa đã duyệt (tỉ lệ shot động, phong cách) vào gate DB. QC chặn khi bị lặng lẽ hạ cấp. Shot có chữ nguyên văn bắt buộc render bằng FilmCraft/ffmpeg, không dùng hình sinh AI.
