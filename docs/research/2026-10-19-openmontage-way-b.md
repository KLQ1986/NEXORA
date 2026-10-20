# Cách B: chưng cất OpenMontage thành kiến thức và code của NEXORA

Ngày: 2026-10-19 · Nguồn: OpenMontage `a2652b4`.
Bản chưng cất: `docs/research/openmontage-distilled/` (4 pipeline), tạo bằng `scripts/distill_openmontage.py`. Script này chạy `claude -p` (Opus, theo gói thuê bao), chỉ có quyền đọc, mỗi lượt một pipeline, tốn khoảng 2 phút.

Cách B nghĩa là: không chạy OpenMontage như một agent thứ hai. Một model mạnh đọc nó **một lần**, rồi những gì đáng giữ được đưa vào NEXORA dưới dạng **code có test** (luật đo được) hoặc **prompt cố định**.

## Đã chưng cất

| Pipeline | File | Hợp với NEXORA khi |
|---|---|---|
| documentary-montage | `openmontage-distilled/documentary-montage.md` | Video theo chủ đề ghép từ footage và stock (như video miền Tây) |
| animated-explainer | `openmontage-distilled/animated-explainer.md` | Video giải thích có lời dẫn và hình minh hoạ |
| talking-head | `openmontage-distilled/talking-head.md` | Người nói trước máy, Copilot cắt theo lời |
| clip-factory | `openmontage-distilled/clip-factory.md` | Cắt nhiều clip ngắn từ một bản ghi dài |

Mỗi file gồm:
- các bước của pipeline;
- quy tắc dựng có số, kèm `file:dòng` nguồn;
- checklist duyệt, lỗi hay gặp, prompt đáng giữ;
- bảng đối chiếu với NEXORA và 5 đề xuất.

## Đã làm trong lần này

| # | Việc | Từ đâu | Commit |
|---|---|---|---|
| 1 | **Phân loại giấy phép** (tự do / cần ghi công / share-alike / cấm thương mại / chưa rõ). Scout không đưa ra ứng viên cấm thương mại, chỉ tự lấy loại an toàn. Cổng đăng chặn ba loại xấu, ghi công cho CC BY, lưu bằng chứng lúc tải. | Báo cáo bản quyền | `29be82d` |
| 2 | **Chấm "nhịp và đa dạng"** cho storyboard, 6 tiêu chí 0–5: lặp liền nhau, một clip dùng nhiều lần, ảnh tĩnh thay video (delivery promise), độ dài shot, cỡ cảnh đơn điệu, chuỗi shot đứng yên. Mỗi tiêu chí kèm danh sách shot gây lỗi. | slideshow_risk, documentary edit-director, animated-explainer đề xuất 1 | `16dd8d4` |
| 3 | **Luật CHAI** cho người phản biện kịch bản: chỉ đúng câu và trích cụm từ, rà hết lỗi cùng loại, cách sửa phải cụ thể. | reviewer.md | `d4f9ef5` |
| 4 | **QC "3 giây đầu"**: không mở bằng màn đen ≥1 s; có tiếng trong 3 giây đầu. | clip-factory đề xuất 2 | `cd18ccd` |
| 5 | **Chấm nhịp trên clip thật**: cỡ cảnh (mô tả của moment) và chuyển động máy (đo) của clip đã chọn được ưu tiên hơn khung trong spec; spec chỉ được dùng khi storyboard đã đặt khung. Đây là lỗ hổng 1 ở dưới. | phát hiện thêm | `cd18ccd` |

Hai chỗ **NEXORA làm tốt hơn bản gốc**:
- OpenMontage lấy điểm trung bình, nên một lỗi nặng có thể bị "trung bình hoá" mất. NEXORA ép kết luận xuống ít nhất "Nên sửa" khi có một tiêu chí ≥4.
- Storyboard chưa đặt khung hình thì không bị chấm phạt oan.

## Lỗ hổng phát hiện thêm, chưa có trong đề xuất của bản chưng cất

1. **Storyboard tạo từ kịch bản để mọi shot ở khung mặc định** (trung, ngang mắt, đứng yên). Video miền Tây có 78/78 shot như vậy.
   - Không nên gán khung tuỳ tiện, vì Director dùng `framing.size` làm tiêu chí nghiệm thu (`agents/director.py:171`) và sẽ đánh trượt clip thật.
   - Hướng đúng: lấy **cỡ cảnh và chuyển động đo được trên chính clip đã chọn** (nhãn `camera` và cỡ cảnh trong moment) để chấm nhịp.
2. **Độ dài shot của video chủ đề quá dài.** 34/78 shot của video miền Tây nằm ngoài khoảng 1,5–8 s, phần lớn là 8,5–10,4 s.
   - Bảng độ dài theo giọng điệu (documentary: elegiac 2,5–7 s … urgent 0,5–2,5 s) nên được đưa vào lúc chia shot.
3. **Bản gốc tự mâu thuẫn.** Ví dụ hai bảng số slot mỗi phút trong documentary. Bản chưng cất đã ghi chú; mỗi khi mượn một con số phải chọn một bộ số duy nhất.

## Còn lại, xếp theo giá trị trên công sức

| Ưu tiên | Việc | Loại | Nguồn |
|---|---|---|---|
| 1 | Độ dài shot theo giọng điệu khi chia shot từ kịch bản; tổng thời lượng ±10% | code + test | documentary 1 |
| 2 | Ngân sách lời đọc tiếng Việt theo âm tiết/giây đo trên giọng thật; trả kịch bản về khi vượt 15% | code + test | animated-explainer 3 |
| 3 | Cổng khớp phụ đề: mỗi cue lệch ≤0,3 s so với mốc chữ, quá 0,5 s thì làm lại | code + test | talking-head 1 |
| 4 | Biên cắt clip không rơi giữa từ hoặc giữa câu; không để lặng thừa ở đuôi | code + test | clip-factory 1 |
| 5 | Hợp đồng âm thanh documentary: nhạc bắt buộc trừ khi có lý do, fade đuôi 3–5 s, câu kết 3–9 từ hiện 5–8 s | code + test | documentary 3 |
| 6 | Kiểm thành phẩm theo nền tảng: ≈ −16 LUFS, thời lượng và dung lượng tối đa | code + test | talking-head 4 |
| 7 | Chấm điểm nhà cung cấp có giải thích (7 tiêu chí) | code | báo cáo kiến trúc |
| 8 | Prompt "người tìm bối cảnh" cho mô tả shot; chủ đề 1 câu hỏi kèm 3 phương án câu kết | prompt | documentary 5 |
| 9 | Kiểm batch cho clip-factory: phân bố clip, độ to âm đồng đều | code + test | clip-factory 4 |

## Cách chưng cất thêm pipeline khác

```bash
.venv/bin/python scripts/distill_openmontage.py cinematic podcast-repurpose
```

Mỗi lượt là một `claude -p` chỉ đọc trên `~/openmontage`, theo gói thuê bao, không dùng API key. Kết quả nằm trong `docs/research/openmontage-distilled/`.
