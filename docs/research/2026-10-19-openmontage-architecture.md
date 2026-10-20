# OpenMontage: kiến trúc, pipeline, thuật toán, dữ liệu và giấy phép

Ngày: 2026-10-19 · Đối tượng: `~/openmontage`, commit `a2652b4` (2026-07-06), giấy phép **AGPL-3.0**.
Cách làm: skill REA, hướng repo mã nguồn (đọc code, trích file:dòng, giới hạn rõ phạm vi khi khẳng định "không có", đối chiếu dữ liệu thật).
Báo cáo đi kèm, riêng về stock và bản quyền: `2026-10-19-openmontage-stock-rights.md`.

Quy ước: **[QS]** là quan sát trực tiếp; **[SR]** là suy ra; **[?]** là chưa biết.

## Danh sách câu hỏi

| # | Câu hỏi | Trạng thái |
|---|---|---|
| 1 | Kiến trúc tổng thể: ai điều phối? | Đã trả lời |
| 2 | Pipeline và stage được định nghĩa thế nào? | Đã trả lời |
| 3 | Hợp đồng của tool, registry, cách chọn nhà cung cấp | Đã trả lời |
| 4 | Agent và skills: duyệt chất lượng, checkpoint | Đã trả lời |
| 5 | Các thuật toán chất lượng và các con số | Đã trả lời |
| 6 | Dữ liệu ra khỏi máy | Đã trả lời (đếm theo khai báo) |
| 7 | Ngân sách và xử lý lỗi | Trả lời một phần |
| 8 | Giấy phép: code, render, nội dung lấy về, nhạc | Trả lời một phần |
| 9 | Khác gì NEXORA, nên học gì | Đã trả lời |

## 1. Kiến trúc: agent là bộ não, Python chỉ là công cụ [QS]

`PROJECT_CONTEXT.md`: *"The AI agent IS the intelligence. Python exists only for tools and persistence."* Repo nói thẳng là không có bộ điều phối, không có reviewer, không có handler viết bằng Python.

```
agent đọc manifest pipeline (YAML) → đọc skill của stage director (MD)
→ gọi tool (Python BaseTool) → tự duyệt (meta skill reviewer)
→ checkpoint (tiện ích Python) → đưa người duyệt
```

Kiến thức được chia ba tầng:
1. `tools/tool_registry.py`: có những tool gì.
2. `skills/` (156 file MD): OpenMontage dùng chúng thế nào.
3. `.agents/skills/`: công nghệ bên dưới hoạt động ra sao.

Trường `agent_skills[]` của mỗi tool nối tầng 1 với tầng 3.

Repo có file hướng dẫn riêng cho từng agent: CLAUDE.md, CODEX.md, CURSOR.md, COPILOT.md. Tất cả trỏ về `AGENT_GUIDE.md` (712 dòng).

[SR] Hệ quả: chất lượng và tính lặp lại phụ thuộc vào việc agent làm theo hướng dẫn đến đâu. Không có máy trạng thái nào *ép* stage, cổng duyệt hay giới hạn số vòng làm lại. Chúng là luật viết bằng chữ.

## 2. Pipeline [QS]

Có 13 manifest trong `pipeline_defs/`: talking-head, animated-explainer, screen-demo, clip-factory, podcast-repurpose, cinematic, animation, character-animation, hybrid, avatar-spokesperson, localization-dub, documentary-montage, framework-smoke.

Các trạng thái chuẩn: `idea → script → scene_plan → assets → edit → compose → publish`. Mỗi stage khai báo:
- `skill` (director);
- `produces` và `required_artifacts_in`;
- `tools_available`;
- `checkpoint_required` và `human_approval_default`;
- `review_focus` và `success_criteria`.

Ví dụ `documentary-montage.yaml`:
- `orchestration.mode: executive-producer`;
- `budget_default_usd: 1.00`;
- `max_revisions_per_stage: 3`, `max_send_backs: 2`;
- `max_wall_time_minutes: 60`.

Artifact chuẩn (`brief`, `script`, `scene_plan`, `asset_manifest`, `edit_decisions`, `render_report`, `publish_log`) được kiểm theo JSON schema trong `schemas/artifacts/`.

Mỗi pipeline cũng có một *luật* riêng. Ví dụ documentary bắt buộc có kế hoạch nhạc và một câu kết, trừ khi người dùng từ chối.

## 3. Tool, registry và chọn nhà cung cấp [QS]

**`tools/base_tool.py`.** Mỗi tool khai báo:
- `tier`, `stability`, `execution_mode`, `determinism`;
- `runtime`: LOCAL, LOCAL_GPU, API hoặc HYBRID;
- `ResourceProfile` (CPU, RAM, VRAM, đĩa, mạng) và `RetryPolicy`;
- `capability`, `provider`, `supports`, `best_for`, `not_good_for`, `fallback_tools`, `agent_skills`;
- schema vào và ra.

`ToolResult` trả về `cost_usd`, `seed`, `model` và `duration_seconds`.

**Mẫu "selector + provider".** Mỗi nhóm có một tool định tuyến, ví dụ `tts_selector`, `video_selector`, `image_selector`, và nhiều tool cho từng nhà cung cấp.

**Chọn nhà cung cấp** (`lib/scoring.py:36-45`) bằng điểm có trọng số:

| Tiêu chí | Trọng số |
|---|---|
| task_fit | 0,30 |
| output_quality | 0,20 |
| control | 0,15 |
| reliability | 0,15 |
| cost_efficiency | 0,10 |
| latency | 0,05 |
| continuity | 0,05 |

Mỗi lựa chọn phải giải thích được bằng ba tiêu chí đứng đầu.

## 4. Duyệt chất lượng và checkpoint [QS]

**`skills/meta/reviewer.md`** áp dụng luật **CHAI**, viện dẫn một nghiên cứu của CMU/Harvard:
- **Accurate:** mỗi phát hiện phải chỉ vào đúng trường, dòng hoặc khung hình.
- **Complete:** thấy một lỗi nghiêm trọng thì quét hết các lỗi cùng loại.
- **Constructive:** lỗi "critical" phải kèm cách sửa.

Mức độ gồm critical, suggestion (phải kèm `proposed_change`) và investigation.

**Tối đa 2 vòng**, sau đó *"pass with warnings… never block indefinitely"* (dòng 86-87, 124). Bước đầu tiên luôn là kiểm schema.

**`skills/meta/checkpoint-protocol.md`:** `checkpoint_required` × `human_approval_default` quyết định ba khả năng: lưu và hỏi người, lưu và tự đi tiếp, hoặc bỏ qua.

## 5. Các thuật toán và các con số [QS]

- **Xếp hạng stock** bằng CLIP ViT-B/32. Điểm = 0,7 × hình + 0,3 × tag. Có lọc chuyển động và chống trùng bằng MMR. Chi tiết ở báo cáo về stock.
- **Nguy cơ "giống slideshow"** (`lib/slideshow_risk.py`) chấm 6 tiêu chí, mỗi tiêu chí 0–5, càng thấp càng tốt:
  - repetition (lặp lại);
  - decorative_visuals (hình chỉ để trang trí);
  - weak_motion (chuyển động không có mục đích);
  - weak_shot_intent (khung hình không có lý do);
  - typography_overreliance (quá nhiều chữ);
  - unsupported_cinematic_claims (gắn mác điện ảnh mà không có cấu trúc).

  Kết luận theo điểm: dưới 2 là strong, dưới 3 là acceptable, dưới 4 là revise, **từ 4 trở lên là fail** và không được sang bước dựng.
- **`variation_checker`:** tìm mẫu lặp trong scene plan *trước khi* sinh asset.
- **`delivery_promise`:** khoá "lời hứa" của sản phẩm ngay từ bước đề xuất. Một video đã hứa `motion_led` thì **không được âm thầm đổi sang ảnh tĩnh** (`still_fallback_allowed: False`).
- **`source_media_review`:** chuẩn hoá việc kiểm tra footage do người dùng đưa vào: âm thanh, lấy mẫu khung hình, phát hiện cảnh, bản chép lời.
- **`verify_scene_pacing`:** kiểm nhịp các bước trong cảnh khớp với lời dẫn.

## 6. Dữ liệu ra khỏi máy [QS]

Đếm theo khai báo `runtime` của tool: **31 API, 8 HYBRID, 14 LOCAL, 12 LOCAL_GPU**.

Các tool gọi ra ngoài gồm:
- **Video AI:** Kling, Veo, Sora, Runway, Seedance, Minimax, Grok, Higgsfield, HeyGen, LTX trên Modal.
- **Ảnh:** Flux, Imagen, OpenAI, Recraft, Grok, DashScope.
- **Giọng đọc:** ElevenLabs, OpenAI, Google, DashScope, Doubao.
- **Nhạc:** Suno, music_gen, Freesound, Pixabay.
- **Stock:** Pexels, Pixabay, corpus và direct search.
- Ngoài ra: nhận dạng giọng nói DashScope, xoá phông.

[SR] Không có "chế độ riêng tư" nào chặn chung các lời gọi ra ngoài. Việc dùng hay không phụ thuộc vào key có sẵn và lựa chọn của agent. Phạm vi tìm: `tools/`, `lib/`, mẫu `privacy|local_only|offline`, không ra kết quả nào có tác dụng chặn. [?] Chưa đọc hết `config.yaml`.

## 7. Ngân sách và xử lý lỗi

**[QS]** `tools/cost_tracker.py` đi theo chu trình *estimate → reserve → reconcile*, ghi vào `cost_log.json`. Mặc định giữ lại 10% (`reserve_pct=0.10`). Có hai chế độ `BudgetMode`:
- `warn`;
- `cap`: ném `BudgetExceeded` khi vượt.

`RetryPolicy` khai báo theo từng tool.

**[SR]** Ngân sách chỉ có hiệu lực nếu agent gọi tracker. Giống mọi thứ khác ở đây, không có tầng Python nào bắt buộc việc gọi. [?] Chưa kiểm tra tool nào thực sự gọi tracker.

## 8. Giấy phép

- **Code:** **AGPL-3.0** [QS]. NEXORA gọi OpenMontage trong một tiến trình riêng và không import nó (`adapters/openmontage.py`). Theo memory "personal use: ignore licences", NEXORA dùng cho cá nhân nên không bị ràng buộc khi phân phối.
- **Render:** Remotion 4.0.484 trong `remotion-composer/` [QS]. [SR] Remotion có giấy phép công ty riêng: miễn phí cho cá nhân và nhóm nhỏ, công ty lớn hơn phải mua.
- **Stock:** chỉ *ghi lại*, không lọc. Xem báo cáo về stock: trong 33 clip NEXORA đã tải qua OpenMontage, chỉ khoảng 4 clip an toàn.
- **Nhạc:**
  - Freesound (`tools/audio/freesound_music.py:166, 183`) chỉ lọc theo thời lượng và gán giấy phép chung chung *"Creative Commons (check individual sound license)"* [QS]. [SR] Freesound có cả CC BY-NC, nên một bài lấy về có thể **cấm dùng thương mại**.
  - Pixabay Music gán đúng giấy phép tự do [QS].
  - [?] Chưa đọc điều khoản thương mại của Suno.

## 9. So với NEXORA

| | OpenMontage | NEXORA |
|---|---|---|
| Điều phối | Agent đọc YAML/MD, không có tầng Python ép buộc | Orchestrator có lane, lease, timeout, kill switch, gate duyệt trong DB |
| Pipeline | 13 thể loại, mỗi stage có director, review_focus, success_criteria | Ít thể loại hơn; Producer, Director, Storyboard |
| Duyệt chất lượng | Reviewer theo luật CHAI, tối đa 2 vòng, chỉ góp ý | QC và review_cut có số đo; storyboard có "nghiệm thu" |
| Chọn nhà cung cấp | Điểm trọng số 7 tiêu chí, có giải thích | Định tuyến theo adapter và privacy; chưa chấm điểm nhà cung cấp |
| Chống slideshow | slideshow_risk, variation_checker, delivery_promise | Chưa có tương đương |
| Ngân sách | estimate/reserve/reconcile, giữ lại 10% | budget_cap theo dự án, cost_records |
| Riêng tư | Không có công tắc chung | Privacy mode chặn mọi adapter cloud |
| Giấy phép | Ghi lại, không lọc (cả stock lẫn nhạc) | Cổng rights khi đăng, nhưng mới kiểm *có* chuỗi giấy phép |

## Đề xuất cho NEXORA

1. **Lọc giấy phép thật**, gồm cả **nhạc**. Đây là 5 đề xuất ở báo cáo về stock, mở rộng thêm nhạc: Freesound phải loại NC.
2. **Mượn bộ chấm "nguy cơ slideshow"**: 6 tiêu chí, ngưỡng 4 là fail. Đặt ở bước Storyboard trước khi dựng: chấm lặp bố cục, hình chỉ để trang trí, chuyển động không mục đích. Hợp với loại video theo chủ đề, nhiều câu lời dẫn.
3. **Mượn "delivery promise"**: khoá loại sản phẩm (video động hay ảnh động) từ đầu và báo rõ khi phải lùi xuống ảnh tĩnh, thay vì lặng lẽ thay.
4. **Mượn luật CHAI cho Copilot/Director**: mỗi nhận xét phải chỉ đúng shot hoặc khung, lỗi nặng phải kèm cách sửa, tối đa 2 vòng rồi đi tiếp kèm cảnh báo.
5. **Chấm điểm nhà cung cấp có giải thích** khi có nhiều nguồn cùng làm một việc (tạo hình, giọng đọc): phù hợp, chất lượng, kiểm soát, ổn định, giá, tốc độ. NEXORA đang chọn theo thứ tự đăng ký.
6. **Không bắt chước** kiểu "chỉ là luật viết bằng chữ". Cái NEXORA làm tốt hơn là có tầng ép buộc: gate, kill switch, privacy. Mọi thứ mượn về nên thành code có test, không phải chỉ thành lời nhắc.
