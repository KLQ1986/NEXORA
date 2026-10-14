# Hiểu footage: phân đoạn, phân loại và mô tả

Bản thiết kế, 2026-10-13. Trạng thái: đợt 1 đã xong, xem `docs/PLAN.md`.

Bổ sung ngày 2026-10-14: `2026-10-14-footage-profile-design.md` mở rộng bản này ra đủ 16 nhóm thông tin người vận hành yêu cầu, thêm các nguồn đo trong máy (Apple Vision, SoundAnalysis, giải mã phần cứng), bộ mẫu và cổng phát hành theo từng trường, và **thay thứ tự xây ở mục 18**. Chỗ hai bản khác nhau thì bản bổ sung thắng.

## 1. Mục tiêu

NEXORA nhận diện, phân loại và mô tả footage **đúng nội dung, đúng phân cảnh, đủ hành động**, cho bốn loại nguyên liệu có trong kho: đời sống và tài liệu không lời, người nói trước máy, video đã dựng sẵn, cảnh quay đặc biệt (drone, timelapse, quay chậm, nhiều máy, quay màn hình).

Nguyên tắc chi phối mọi quyết định bên dưới:

- **Code dựng cấu trúc, mô hình điền nội dung.** Ranh giới, gộp, làm mịn và kiểm tra nằm trong code. Mô hình chỉ trả lời câu hỏi hẹp: mô tả các khung này, chọn một nhãn trong danh sách, có hoặc không.
- **Đổi mô hình không đổi code.** Mô hình mạnh hơn làm kết quả tốt lên; code không biết tên mô hình.
- **Không có mô hình vẫn có cấu trúc.** Cú máy, nhịp và mọi nhãn đo được phải có ngay cả khi không mô hình nào chạy.
- **Kiểm thử không cần mô hình thật.** Mọi luật là hàm thuần, thử bằng dãy số viết tay hoặc video tổng hợp và adapter giả.

### Ngoài phạm vi

- Trích đoạn theo câu hỏi tự do ("lấy đoạn chèo thuyền"): lượt sau, dựng trên nền này.
- Phần dựng và hoàn thiện (timeline có phiên bản, chỉnh màu, chuyển cảnh, FilmCraft làm engine hoàn thiện): lượt sau nữa.
- Tinh chỉnh (huấn luyện lại) mô hình.
- Đồ thị quan hệ giữa các phân cảnh.

Ba mục từng nằm ở đây nay thuộc bản bổ sung 2026-10-14: chọn mô hình bằng số đo (mục 4.6 của bản đó), vector hình ảnh (nhóm 15), và hiểu âm thanh nền (nhóm 09). Gom người theo hình dáng cũng thuộc bản đó (nhóm 06), chỉ trong kho của người vận hành.

## 2. Thuật ngữ và các bậc

Thang nguyên liệu, từ nhỏ đến lớn:

| Bậc | Tiếng Việt | Tên trong code | Là gì |
|---|---|---|---|
| Frame | Khung hình | `frame` (đã có) | Hình đại diện của một nhịp |
| Beat | Nhịp | `segment` (đã có, đổi cách chia) | Một việc đang diễn ra, 2 đến 15 giây |
| Shot | Cú máy | `footage_shot` (mới) | Một lần bấm máy liên tục, giữa hai điểm cắt |
| Scene | Phân cảnh | `footage_scene` (mới) | Một sự việc trọn vẹn: cùng nơi, cùng lúc, cùng nhân vật |
| | Buổi quay | `session` (đã có) | Các file cùng thư mục, cùng ngày |
| | Video nguồn | `asset` (đã có) | Một file |

Tên `footage_shot` và `footage_scene` được chọn để không lẫn với bảng `shots` (một câu của kịch bản) và cột `shots.scene` (cảnh của kịch bản), vốn thuộc thang tác phẩm.

**Nhịp là đơn vị gốc.** Cú máy và phân cảnh là hai cách gom độc lập trên nhịp:

- Cú máy gom theo kỹ thuật: máy quay liên tục.
- Phân cảnh gom theo nội dung. Ranh giới phân cảnh có thể rơi giữa một cú máy dài, và một phân cảnh có thể trải trên nhiều file.

Tầng nhịp giữ tên `segment` vì `sourcing/match.py`, giao diện Thư viện và `quality/evaluation.py` đang đọc cấp này. Chúng chạy tiếp không phải sửa; khác biệt là nhịp có độ dài thay đổi và không vắt qua hai cú máy.

**Take (lần quay)** không phải một bậc: nó là một phiên bản của cùng một hành động, xử lý ở mục 9.

## 3. Tín hiệu đo từ hình và tiếng

Một lượt giải mã duy nhất qua FFmpeg cho ra khung thu nhỏ (96×54, tối đa 30 khung mỗi giây; file quay 120 khung mỗi giây được lấy thưa lại). Từ đó code tính các dãy số theo thời gian. Kết quả được lưu đệm theo checksum của file và phiên bản bộ phân tích.

| Tín hiệu | Cách đo | Dùng cho |
|---|---|---|
| Chữ ký khung | Lưới 32×18 độ sáng trung bình, cộng histogram 16 ngăn cho mỗi kênh màu | Điểm cắt, chuyển mờ, ranh giới nhịp, độ giống giữa các nhịp |
| Độ khác giữa hai khung | 0,5 × khoảng cách histogram + 0,5 × min(1, 2 × chênh lệch lưới) | Như trên |
| Chuyển động máy | Độ dịch của bốn góc phần tư giữa hai khung: trung bình là lia, phân kỳ là đẩy hoặc kéo | Nhãn chuyển động máy, ranh giới nhịp |
| Độ rung | Độ lệch giữa đường đi của máy và chính nó sau khi làm trơn | Nhãn chất lượng |
| Chuyển động chủ thể | Phần khác biệt còn lại sau khi bù chuyển động máy | Đỉnh hành động, điểm cắt sạch |
| Độ nét | Năng lượng gradient | Nhãn chất lượng |
| Phơi sáng | Tỷ lệ điểm ảnh chạm đỉnh và chạm đáy | Nhãn chất lượng |
| Tâm chú ý | Trọng tâm của năng lượng gradient, hơi thiên về giữa khung | Vị trí chủ thể, hướng chuyển động trên màn hình |
| Mức âm lượng | Khung 10 ms | Siết ranh giới từ, khoảng lặng |
| Viền đen | Dò vùng hình thật của file (viền trên dưới hoặc hai bên) | Nhãn viền đen; mọi tín hiệu khác chỉ tính trong vùng hình thật |

Cần thêm một thư viện: `numpy`. Tính các dãy trên bằng Python thuần cho file dài một giờ quá chậm; `numpy` là phụ thuộc nhỏ, giấy phép BSD.

## 4. Chia cú máy

**Cắt cứng.** Khung *i* mở một cú máy mới khi độ khác của nó thoả cả bốn điều kiện:

1. vượt ngưỡng tuyệt đối theo độ nhạy;
2. vượt 2,5 lần trung vị của 5 khung trước và 5 khung sau, cộng 0,05;
3. là cực đại cục bộ;
4. cách điểm cắt trước ít nhất độ dài cú máy tối thiểu (mặc định 6 khung).

Điều kiện 2 là thay đổi quan trọng nhất so với ngưỡng cố định 0,35 hiện nay: cảnh nhiều chuyển động cần cú nhảy lớn hơn cảnh tĩnh, nên máy lia nhanh không bị nhận nhầm là điểm cắt. Điều kiện 4 gộp chớp sáng và khung hỏng đơn lẻ.

**Điểm cắt yếu.** Hai cú máy cùng tông màu (hai cảnh liền nhau của một bộ phim cũ, hai góc của một căn bếp) cho cú nhảy nhỏ hơn ngưỡng tuyệt đối. Cú nhảy đó vẫn là điểm cắt khi nó nổi bật so với xung quanh (điều kiện 2) **và** hình sau nó là một hình khác: lưới độ sáng nửa giây trước và nửa giây sau ít tương quan với nhau. Chớp sáng và khung hỏng cũng nổi bật, nhưng để lại hình như cũ, nên bị loại.

**Chuyển mờ và fade.** So màu của khung *i* với khung trước đó nửa giây. Một dải mà độ khác xa này cao là ứng viên, và phải qua hai phép thử để phân biệt với những thứ khác cũng làm màu đổi nhanh:

1. *Hình có đổi không.* Hình trước và sau dải phải là hai hình khác nhau. Phim nhấp nháy và ánh sáng thay đổi giữ nguyên hình, nên bị loại.
2. *Có phải pha trộn không.* Khung ở giữa dải phải gần với một hỗn hợp của hình trước và hình sau. Máy lia nhanh và bàn tay che ống kính không thoả điều này, nên bị loại.

Ranh giới đặt ở giữa dải, và dải được ghi lại là vùng chuyển tiếp để không nhịp nào lấy khung trong đó. Mờ ra qua tối rồi mờ vào lại là một lần chuyển, không phải hai. Fade qua đen kéo dài dùng kết quả dò đoạn đen đã có.

Các khung lặp lại khung trước (footage quay ở tốc độ thấp nhưng lưu ở tốc độ cao) không được tính vào mức xáo động xung quanh; nếu tính, mức đó thành 0 và mọi chuyển động đều trông như điểm cắt.

**Không có điểm cắt.** Cả file là một cú máy.

## 5. Chia nhịp trong một cú máy

Ranh giới ứng viên, theo thứ tự ưu tiên:

1. **Nội dung trôi đi**: độ khác giữa khung hiện tại và khung đầu của nhịp đang mở vượt ngưỡng. Bắt được thay đổi chậm mà so từng cặp khung liền nhau không thấy.
2. **Máy đổi trạng thái**: từ tĩnh sang chuyển động hoặc ngược lại.
3. **Chủ thể bắt đầu hoặc ngừng chuyển động.**

Luật áp sau đó:

- Với footage có lời nói, ranh giới dịch về khe giữa hai câu gần nhất trong vòng 0,4 giây; không ranh giới nào nằm trong một từ.
- Nhịp ngắn hơn độ dài tối thiểu (mặc định 3 giây) gộp vào nhịp kề có chữ ký giống nó hơn.
- Nhịp dài hơn 15 giây mà không có ứng viên thì chia đều. Đây là phương án cuối, tương đương cách làm hiện nay.
- Cú máy ngắn hơn hai lần độ dài tối thiểu là một nhịp.

**Ranh giới người vận hành đặt.** Một ranh giới cú máy hoặc nhịp do người vận hành thêm, dời hoặc xoá được ghim lại. Mọi lần chia lại sau đó giữ nguyên các ranh giới đã ghim và chỉ chia phần ở giữa chúng.

**Bất biến phủ kín.** Trong mỗi cú máy, các nhịp phủ kín phần dùng được, không hở và không chồng. Đây là định nghĩa kỹ thuật của "đủ hành động": không giây nào dùng được nằm ngoài mô tả.

**Khoảng dùng được.** Đoạn đen vẫn bị loại. Đoạn rung, mất nét, cháy sáng hoặc đứng hình không bị loại mà được gắn nhãn chất lượng trên nhịp: quyết định dùng hay không là của người dựng.

**Chọn khung.** Mỗi nhịp lấy 3 đến 8 khung: khung đầu, khung cuối và các khung ở đỉnh chuyển động chủ thể. Nhịp nhiều chuyển động được nhiều khung hơn.

## 6. Nhãn phân loại

Mỗi nhãn mang ba thứ: **giá trị**, **nguồn** (`measured`, `model`, `human`) và **độ tin cậy** (cao, vừa, thấp). Nhãn nguồn `human` không bao giờ bị ghi đè.

Độ tin cậy do code tính; mô hình không được hỏi nó chắc đến đâu.

| Nguồn | Cao | Vừa | Thấp |
|---|---|---|---|
| `human` | luôn luôn | | |
| `measured` | số đo cách xa ngưỡng | số đo gần ngưỡng | nhịp có chất lượng hình kém |
| `model` | một số đo hoặc cả hai nhịp kề trong cùng cú máy xác nhận | không có gì xác nhận hay phản bác | một luật kiểm tra chéo phản bác, hoặc mô hình trả lời "không rõ" |

**Đo bằng code, không cần mô hình:**

| Nhãn | Giá trị |
|---|---|
| Chuyển động máy | tĩnh, lia ngang, lia dọc, đẩy vào, kéo ra, cầm tay |
| Độ rung, độ nét, phơi sáng | tốt, chấp nhận được, kém (kèm số đo) |
| Có lời nói | có, không |
| Tốc độ quay | thường, quay chậm (file từ 100 khung mỗi giây trở lên) |
| Viền đen | không, trên dưới, hai bên |
| Tỷ lệ khung | ngang, dọc, vuông |
| Hướng chuyển động trên màn hình | trái sang phải, phải sang trái, không rõ |
| Vị trí chủ thể | toạ độ x, y trong khung |

**Mô hình chọn từ danh sách cố định:**

| Nhãn | Giá trị |
|---|---|
| Cỡ cảnh | cực toàn, toàn, trung, cận, đặc tả |
| Góc máy | ngang tầm mắt, từ trên xuống, từ dưới lên, trên cao |
| Nơi chốn | trong nhà, ngoài trời |
| Thời điểm | ngày, đêm, bình minh hoặc hoàng hôn, không rõ |
| Số người | không, một, hai, nhóm, đám đông |
| Loại nội dung | hành động đời sống, người nói trước máy, phong cảnh, chi tiết cận, màn hình, đồ hoạ hoặc chữ, timelapse |
| Chữ hoặc logo chèn sẵn | có, không |
| Watermark | có, không |

Câu trả lời ngoài danh sách được ghi là "không rõ" với độ tin cậy thấp, không làm hỏng cả nhịp.

Viền đen, chữ chèn sẵn và watermark quyết định một clip đã dựng sẵn có dùng lại được không; phần ghép cảnh sau này xếp các nhịp sạch lên trước.

**Mô tả tự do** (như hiện nay, giữ nguyên): mô tả 1 đến 2 câu, chủ thể, bối cảnh, chữ trên hình.

## 7. Hành động và sự việc

**Bản ghi hành động.** Với mỗi nhịp, mô hình trả về danh sách hành động có cấu trúc: *ai, làm gì, với cái gì*. Prompt của nhịp sau kèm danh sách hành động của nhịp trước và yêu cầu dùng lại đúng cụm từ cũ nếu hành động còn tiếp diễn. Nhờ đó việc gộp là so chuỗi, không phải đoán nghĩa.

**Sự việc (`event`).** Code gộp các nhịp liền nhau trong cùng cú máy có cùng chủ thể và hành động thành một sự việc có điểm đầu, điểm cuối.

**Ba pha, do code suy ra:**

- *Bắt đầu*: nhịp đầu của sự việc.
- *Cao trào*: nhịp có chuyển động chủ thể lớn nhất (số đo, không phải ý kiến của mô hình).
- *Kết thúc*: nhịp cuối.

**Trọn vẹn hay bị cụt.** Sự việc chạm mép đầu của cú máy (trong vòng 0,5 giây) là "cụt đầu"; chạm mép cuối là "cụt đuôi". Với nhịp ở mép, mô hình còn được hỏi một câu có hoặc không: hành động trong các khung này đã xong chưa. Hai nguồn bất đồng thì gắn cờ (mục 10).

## 8. Phân cảnh

Các nhịp được duyệt theo thứ tự quay trong một buổi quay (file xếp theo giờ tạo). Giữa hai nhịp liền nhau, code tính điểm ranh giới từ:

- **khoảng cách thời gian** giữa hai file: vượt ngưỡng (mặc định 10 phút) là ranh giới chắc chắn;
- **độ khác hình ảnh** giữa chữ ký trung bình của hai nhịp;
- **nhãn nơi chốn** đổi;
- **tập chủ thể** ít trùng nhau;
- **lời nói**: không ranh giới nào xẻ đôi một câu.

Điểm vượt ngưỡng thì mở phân cảnh mới. Mỗi phân cảnh có tên và tóm tắt do mô hình viết từ mô tả các nhịp, giống bước tóm tắt video hiện có.

**Ba quan hệ giữa hai cú máy trong một phân cảnh.** Chúng phải được phân biệt, vì người dựng dùng mỗi loại một cách khác:

| Quan hệ | Là gì | Nhận ra bằng |
|---|---|---|
| Nối tiếp | Việc này xảy ra sau việc kia | Mặc định, theo giờ quay |
| Góc máy khác | Hai máy quay cùng một khoảnh khắc | Hai file đã được đồng bộ theo tiếng (`metadata.angles`, do `library/sync.py` ghi) |
| Quay lại | Cùng hành động, làm lại lần nữa | Cùng chủ thể và hành động, khác thời điểm (mục 9) |

Trong một buổi quay, hai file có tiếng mà khoảng thời gian quay chồng lên nhau được thử đồng bộ tự động. Đạt độ chắc tối thiểu thì chúng được nối là hai góc máy. Các nhịp của hai góc máy chồng nhau về thời gian thật thuộc cùng một phân cảnh và được ghi là song song, không phải nối tiếp. Một cặp góc máy không bao giờ bị tính là hai lần quay lại.

**Lưu trữ.** Phân cảnh thuộc về thư viện, không thuộc về một file, nên cần bảng riêng: `footage_scenes` (tên, tóm tắt, buổi quay, nguồn) và `footage_scene_beats` (phân cảnh, nhịp, thứ tự, nhịp song song ở góc máy khác nếu có). Để tìm được, mỗi phân cảnh có một dòng cấp `scene` trong chỉ mục cho từng file nó đi qua, mang cùng văn bản.

**Người vận hành** gộp, tách và đổi tên phân cảnh. Phân cảnh đã chỉnh mang nguồn `human`; lần gom lại sau không đụng tới nó.

## 9. Thông tin để cắt và nối

- **Điểm cắt sạch**: trong mỗi nhịp, các thời điểm mà máy ổn định, chuyển động chủ thể thấp và không nằm trong một từ.
- **Hướng chuyển động trên màn hình**: từ quỹ đạo của tâm chú ý và chuyển động chủ thể.
- **Bản đồ độ phủ**: với mỗi phân cảnh, những cỡ cảnh đã có và còn thiếu.
- **Các lần quay lại**: những sự việc có cùng chủ thể và hành động, trong cùng phân cảnh, đến từ các cú máy khác nhau, được gom thành một nhóm và xếp hạng theo độ nét, độ rung và độ trọn vẹn.

## 10. Kiểm tra chéo và hàng chờ xem lại

Code đối chiếu lời mô hình với số đo và với chính nó. Mỗi vi phạm tạo một cờ gắn vào nhịp.

| Luật | Cờ khi |
|---|---|
| Chuyển động máy | Mô tả nói máy đứng yên trong khi số đo là đang lia, hoặc ngược lại |
| Lời nói | Mô tả nhắc tới lời nói trong khi file không có tiếng |
| Nơi chốn | Hai nhịp liền nhau cùng cú máy mang nhãn trong nhà và ngoài trời |
| Số người | Số người nhảy từ "không" sang "đám đông" giữa hai nhịp liền nhau cùng cú máy mà hình ít thay đổi |
| Trọn vẹn | Vị trí ở mép cú máy và câu trả lời của mô hình bất đồng |
| Chất lượng thấp | Nhịp mất nét hoặc rung nặng: mô tả có thể không đáng tin |
| Trả lời hỏng | Mô hình không trả về JSON đọc được, hoặc mọi nhãn đều "không rõ" |

Cờ có ba trạng thái: mở, đã xử lý, bỏ qua. Thư viện có một hàng chờ liệt kê các nhịp có cờ mở, để người vận hành chỉ xem chỗ đáng ngờ thay vì cả kho.

## 11. Sổ nhân vật, nơi chốn, đồ vật

Một sổ đăng ký ở cấp thư viện: bảng `entities` (loại: người, nơi, vật; tên; các tên gọi khác; ghi chú) và `entity_mentions` (mục trong sổ, nhịp, nguồn, độ tin cậy).

Lượt này code liên kết bằng tên: chủ thể trong mô tả hoặc ghi chú của người quay trùng với tên hay tên gọi khác của một mục. Người vận hành tạo mục, gộp hai mục và xác nhận liên kết. Nhận ra cùng một người qua hình dáng là việc của mô hình, để lượt sau; cấu trúc dữ liệu đã sẵn chỗ cho nó (cột nguồn và độ tin cậy).

## 12. Lời nói

- **Siết ranh giới từ.** Whisper đặt cuối mỗi từ trùng đầu từ sau, nên khoảng lặng bị nuốt vào từ. Code dời đầu và cuối mỗi từ vào trong, qua các khung 10 ms có mức âm dưới ngưỡng. Ngưỡng nằm giữa nền ồn (phân vị 10) và mức tiếng nói (phân vị 95) của chính file: 30% quãng từ dưới lên, và cao hơn nền ít nhất 6 dB. Một từ giữ ít nhất 60 ms. Việc này chữa điểm đã ghi trong `PLAN.md` ("whisper cho mốc liền nhau, không có khoảng lặng") và làm ranh giới câu ở mục 5 đáng tin.
- **Phân biệt người nói không cần mô hình.** Gom các đoạn lời nói theo đặc trưng giọng (thống kê MFCC, gom cụm phân cấp). Chạy được với phỏng vấn có giọng khác nhau và lượt lời rõ; lời nói chồng nhau hoặc có nhạc nền làm nó nhầm. Nhãn người nói sửa tay được.

## 13. Hợp đồng với mô hình

Chỉ dùng ba thao tác đã có của adapter `model`: `describe` (hình và prompt vào, JSON ra), `chat`, `embed`. Không thao tác mới nào là bắt buộc.

- Mọi câu hỏi phân loại là chọn trong danh sách hoặc có/không. Không hỏi mô hình con số hay mốc thời gian.
- Một câu trả lời hỏng làm hỏng một trường, không làm hỏng một nhịp; một nhịp hỏng không làm hỏng một video.
- Mô tả của một nhịp được khoá theo: file, điểm đầu và điểm cuối của nhịp (tick), các khung đã chọn, phiên bản prompt và ghi chú của người quay. Đổi một trong các thứ đó thì mô tả hết hạn; bản người sửa thì không.
- Phiên bản của luật chia nhịp **không** nằm trong khoá. Khi một ngưỡng được chỉnh và kho được chia lại, nhịp nào giữ nguyên ranh giới và khung thì giữ nguyên mô tả; chỉ nhịp đổi ranh giới mới được mô tả lại. Chỉnh ngưỡng nhờ vậy không thành một lượt mô tả lại cả kho.
- Mỗi nhịp tốn một lời gọi `describe` (mô tả, nhãn và hành động trong cùng một câu trả lời JSON). Câu hỏi có hoặc không về độ trọn vẹn chỉ được hỏi cho nhịp ở mép cú máy. Mỗi phân cảnh tốn một lời gọi `chat`.

## 14. Dây chuyền và dữ liệu

`library.understand` lên phiên bản 2:

| Bước | Cần | Làm gì |
|---|---|---|
| `signals` | ffmpeg | Giải mã một lượt, tính và lưu đệm các tín hiệu |
| `structure` | (code thuần) | Cú máy, nhịp, nhãn đo được, điểm cắt sạch |
| `frames` | ffmpeg | Xuất các khung đã chọn cho từng nhịp |
| `describe` | model | Mô tả, nhãn mô hình, hành động có cấu trúc |
| `events` | (code thuần) | Gộp sự việc, pha, trọn vẹn |
| `scenes` | model (chỉ để đặt tên) | Gom phân cảnh, tóm tắt |
| `checks` | (code thuần) | Kiểm tra chéo, tạo cờ |
| `index` | model | Vector cho văn bản mới |

Hai bước đầu không cần mô hình, nên cấu trúc có ngay sau khi nhập file.

**Thời gian.** Ranh giới mới được lưu bằng số nguyên tick, 254.016.000.000 tick mỗi giây (chia hết cho mọi tốc độ khung hình và tần số lấy mẫu thông dụng), qua một module `core/timebase.py`. Cột giây kiểu số thực của bảng `moments` được giữ và tính từ tick, để mã hiện có chạy tiếp. Phần dựng phim sau này dùng cùng đơn vị.

**Chuyển đổi kho hiện có.** Khi một file được phân tích lại:

- các `segment` 12 giây cũ do mô hình viết bị thay bằng nhịp mới;
- `segment` người vận hành đã sửa được giữ lại dưới dạng ghi chú (cấp `note`, đã có) ở đúng khoảng thời gian của nó;
- lựa chọn clip của các dự án không bị ảnh hưởng, vì chúng lưu file và khoảng thời gian;
- bảng `match_feedback` hiện khoá theo `moment_id`. Nó được thêm khoảng thời gian, để phản hồi cũ áp cho nhịp mới nào chồng lên khoảng đó.

**Ghép cảnh với nhịp ngắn.** Một nhịp có thể ngắn hơn độ dài một câu kịch bản. Khi đó clip được nới sang các nhịp kề trong cùng cú máy, ưu tiên nhịp cùng sự việc, và không bao giờ vượt ranh giới cú máy. Đây là thay đổi duy nhất ở `sourcing/match.py` trong đợt 1.

**Điều kiện xong của đợt 1** (người vận hành đổi ngày 2026-10-14). Bản đầu của thiết kế đòi bộ 17 mẫu ghép cảnh có sẵn không được giảm quá 5 điểm phần trăm. Phép đo cho thấy điều kiện đó đo sai thứ cần đo: các mẫu ấy do chính hệ thống đề xuất trên cách chia cũ, và trong video có nội dung lặp lại thì một đoạn khác cùng nội dung bị tính là sai. Điều kiện xong nay là:

- tìm kiếm ra đúng video cho mỗi mẫu cũ, không kém trước;
- không video nào hở hoặc chồng nhịp;
- trên footage tự quay của người vận hành, vốn không có điểm cắt, hệ thống không đặt ranh giới cú máy nào.

Mẫu ghép cảnh để đo về sau do người vận hành tự chọn tay.

## 15. Danh sách tình huống

Mỗi dòng là một bài kiểm thử, chạy bằng video tổng hợp (mỗi cú máy một hoạ tiết, có chuyển động và nhiễu) hoặc dãy tín hiệu viết tay, và adapter giả.

| # | Tình huống | Kết quả phải có |
|---|---|---|
| 1 | Cú máy dài không có điểm cắt | Một cú máy, nhiều nhịp, phủ kín |
| 2 | Video đã dựng, toàn cắt cứng | Mỗi điểm cắt một ranh giới cú máy |
| 3 | Video có chuyển mờ | Ranh giới ở giữa vùng mờ; không khung nào lấy trong vùng |
| 4 | Fade qua đen | Hai cú máy, đoạn đen bị loại |
| 5 | Máy lia nhanh, không cắt | Không điểm cắt giả |
| 6 | Chớp sáng hoặc một khung hỏng | Không điểm cắt giả |
| 7 | Clip ngắn hơn 3 giây | Một cú máy, một nhịp |
| 8 | File dài hơn một giờ | Xong trong giới hạn thời gian, bộ nhớ không tăng theo độ dài |
| 9 | Ảnh tĩnh | Một nhịp, một khung, không bước tín hiệu |
| 10 | Video không tiếng | Không bước lời nói, nhãn "không có lời nói" |
| 11 | Người nói, có khoảng nghỉ | Không ranh giới nhịp nào nằm trong một từ |
| 12 | Hai người nói | Hai nhãn người nói |
| 13 | Quay chậm 120 khung mỗi giây | Nhãn quay chậm; tín hiệu lấy thưa lại |
| 14 | Tốc độ khung hình thay đổi | Ranh giới theo mốc thời gian thật của khung |
| 15 | Đoạn rung, mất nét, cháy sáng | Nhịp được giữ và mang nhãn chất lượng kém, có cờ |
| 16 | Hình đứng yên dài | Một nhịp tĩnh, không bị loại |
| 17 | Hành động kéo qua ba nhịp | Một sự việc, ba pha |
| 18 | Hành động bị cụt ở cuối cú máy | Nhãn "cụt đuôi" |
| 19 | Cùng hành động quay ba lần | Một nhóm ba lần quay, có xếp hạng |
| 20 | Một phân cảnh trên ba file | Một phân cảnh, ba dòng trong chỉ mục |
| 21 | Một cú máy đi qua hai nơi | Hai phân cảnh, ranh giới giữa cú máy |
| 22 | Hai file cách nhau một giờ | Hai phân cảnh |
| 23 | Mô hình trả lời ngoài danh sách | Nhãn "không rõ", nhịp vẫn được lưu |
| 24 | Mô hình trả về JSON hỏng | Nhịp chưa mô tả, có cờ, video vẫn xong |
| 25 | Không có mô hình | Cú máy, nhịp và nhãn đo được vẫn có |
| 26 | Mô hình nói máy tĩnh, số đo nói đang lia | Có cờ |
| 27 | Phân tích lại file đã có bản sửa tay | Bản sửa tay còn nguyên dưới dạng ghi chú |
| 28 | Chạy lại không đổi gì | Không lời gọi mô hình nào |
| 29 | Hai file trùng nội dung | File trùng không được phân tích lại |
| 30 | Ổ chứa file gốc bị rút | Phân tích trên bản proxy |
| 31 | Hai máy quay cùng một khoảnh khắc | Một phân cảnh, các nhịp song song, không nhóm quay lại nào |
| 32 | Hai file chồng giờ quay nhưng tiếng không khớp | Không nối góc máy; xử lý như nối tiếp |
| 33 | Video có viền đen trên dưới | Nhãn viền đen; viền không làm sai độ sáng và điểm cắt |
| 34 | Chỉnh một ngưỡng chia nhịp rồi chạy lại | Chỉ nhịp đổi ranh giới gọi mô hình |
| 35 | Người vận hành dời một ranh giới rồi hệ thống chia lại | Ranh giới đã ghim còn nguyên |
| 36 | File riêng tư, mô hình chạy trên cloud | Bước mô tả bị chặn có lý do; cấu trúc vẫn có |
| 37 | Chạm trần chi phí giữa chừng | Dừng mô tả, các nhịp còn lại mang cờ "chưa mô tả", chạy tiếp được sau |
| 38 | Câu kịch bản dài hơn nhịp khớp nhất | Clip nới sang nhịp kề cùng cú máy, không vượt điểm cắt |

## 16. Bộ đo

Mở rộng `quality/evaluation.py`:

- **Mẫu ranh giới**: người vận hành đánh dấu trên một video các điểm đổi cú máy, đổi nhịp, đổi phân cảnh mà họ cho là đúng.
- **Số đo**: với mỗi loại ranh giới, tỷ lệ bắt đúng và tỷ lệ bắt sót, sai lệch cho phép 0,5 giây.
- **Bất biến phủ kín** được kiểm trên mọi file của kho ở mỗi lần chạy.
- Mỗi lần chạy lưu kèm cấu hình như hiện nay, để so được trước và sau khi đổi một ngưỡng, một luật hoặc một mô hình.

**Hiệu chỉnh ngưỡng.** Mọi ngưỡng của thiết kế này (độ nhạy điểm cắt, mức trôi nội dung, độ dài nhịp tối thiểu và tối đa, điểm ranh giới phân cảnh, khoảng cách 10 phút, các mức chất lượng) nằm trong một nhóm cấu hình, mỗi ngưỡng có giá trị mặc định. Giá trị mặc định ban đầu là ước đoán. Quy trình chỉnh: chạy bộ đo, đổi một ngưỡng, chạy lại, giữ thay đổi nếu số đo tốt lên. Lượt này dùng một bộ ngưỡng chung; bộ ngưỡng riêng cho từng loại footage chỉ được thêm khi số đo cho thấy một bộ chung không đủ.

## 17. Ý tưởng lấy từ FilmCraft

FilmCraft (`reference/filmcraft`, bản `cee1feb`, giấy phép MIT hoặc Apache-2.0) được đọc để học cách làm. Không dòng mã nào được chép: FilmCraft viết bằng Rust, các ý dưới đây được viết lại bằng Python và ghi nguồn trong chú thích đầu module.

| Ý tưởng | Nằm ở đâu trong FilmCraft | Dùng ở mục |
|---|---|---|
| Chữ ký khung (lưới độ sáng và histogram) và ngưỡng theo trung vị cục bộ | `crates/render/src/scene.rs` | 3, 4 |
| Kiểm thử bằng khung tổng hợp có hoạ tiết theo cú máy | cùng file, phần `tests` | 15 |
| Đường đi của máy và độ rung từ bộ ổn định hình | `crates/render/src/vfx/temporal.rs`, `track.rs` | 3 |
| Tâm chú ý từ năng lượng gradient | `temporal.rs`, hàm `saliency_centroid` | 3, 6 |
| Siết ranh giới từ bằng mức âm | `crates/speech/src/vad.rs` | 12 |
| Phân biệt người nói không cần mô hình | `crates/speech/src/diarize.rs` | 12 |
| Đơn vị thời gian nguyên | `crates/time/src/lib.rs` | 14 |
| Bản chép lời theo thời gian của file gốc, không theo timeline | `docs/transcripts.md` | (NEXORA đã làm vậy) |

FilmCraft không có: chia nhịp trong cú máy, phân cảnh, mô tả nội dung, phân loại, hành động, sổ nhân vật. Những phần đó là của riêng thiết kế này.

Hai ý đáng lấy cho lượt dựng phim, ghi lại để không quên: đồng bộ nhiều máy bằng tương quan chéo âm thanh có trọng số pha (`crates/audio-dsp/src/sync.rs`), và mã băm nội dung cho từng đoạn render để chỉ dựng lại phần đã đổi (`crates/render/src/preview.rs`).

## 18. Thứ tự xây

> Đã thay bằng mục 10 của `2026-10-14-footage-profile-design.md` (chín đợt, xếp theo mức giúp chọn đúng nguyên liệu). Bảng dưới đây giữ lại làm lịch sử.

Thiết kế này quá lớn cho một kế hoạch triển khai. Nó được xây thành sáu đợt, mỗi đợt có kế hoạch riêng và chạy được độc lập:

| Đợt | Nội dung | Mục |
|---|---|---|
| 1 | Tín hiệu, cú máy, nhịp, nhãn đo được, đơn vị thời gian, bộ đo ranh giới, chuyển đổi kho, ghép cảnh với nhịp ngắn, dải thời gian trong Thư viện | 3, 4, 5, 6 (phần đo), 14, 16, 20 |
| 2 | Mô tả phiên bản 2 với nhãn từ danh sách, độ tin cậy, kiểm tra chéo, hàng chờ xem lại, chi phí và quyền riêng tư | 6 (phần mô hình), 10, 13, 19, 20 |
| 3 | Hành động có cấu trúc, sự việc, pha, trọn vẹn, điểm cắt sạch, hướng chuyển động | 7, 9 (hai ý đầu) |
| 4 | Phân cảnh qua nhiều file, góc máy khác, bản đồ độ phủ, các lần quay lại, màn hình phân cảnh | 8, 9 (hai ý cuối), 20 |
| 5 | Sổ nhân vật, nơi chốn, đồ vật | 11 |
| 6 | Siết ranh giới từ, phân biệt người nói | 12 |

Đợt 1 đi trước vì mọi đợt sau dựa trên ranh giới nhịp. Đợt 6 không phụ thuộc đợt 2 đến 5 và có thể làm sớm hơn nếu footage có lời nói được ưu tiên.

Tình huống ở mục 15 thuộc đợt nào thì kiểm thử của nó được viết trong đợt đó: 1 đến 11, 13 đến 16, 27 đến 30, 33 đến 35 và 38 thuộc đợt 1; 23 đến 26, 36 và 37 thuộc đợt 2; 17 và 18 thuộc đợt 3; 19 đến 22, 31 và 32 thuộc đợt 4; 12 thuộc đợt 6. Tình huống 11 chạy ở đợt 1 với ranh giới từ hiện có của whisper, và chính xác hơn sau đợt 6.

## 19. Chi phí và quyền riêng tư

**Số lời gọi mô hình.** Ước lượng cho một giờ footage, với nhịp dài trung bình 6 giây: khoảng 600 lời gọi mô tả, khoảng 100 câu hỏi có hoặc không ở mép cú máy, và vài chục lời gọi tóm tắt phân cảnh. Cách chia 12 giây hiện nay tốn khoảng 300 lời gọi cho cùng một giờ. Đây là ước lượng trên giấy; số thật được ghi lại ở lần chạy đầu của đợt 2.

**Trần chi phí.** Bước `describe` được đánh dấu là tốn kém, nên trần của từng lượt chạy và trần theo ngày, theo tháng đã có trong bộ điều phối áp dụng cho nó. Khi mô hình chạy trên cloud, hệ thống cho biết số lời gọi dự kiến trước khi bắt đầu.

**Thứ tự khi ngân sách có hạn.** Nhịp có chất lượng hình tốt được mô tả trước, nhịp kém sau. Chạm trần thì bước mô tả dừng; các nhịp còn lại mang cờ "chưa mô tả" và được làm tiếp ở lượt sau mà không lặp lại phần đã xong.

**Quyền riêng tư.** Mỗi file đã có một lớp riêng tư (`privacy_class`); mặc định là không rời khỏi máy. Khung hình của một file riêng tư không bao giờ được gửi tới mô hình chạy trên cloud: bước mô tả của file đó bị chặn kèm lý do, không tự chuyển sang cloud. Người vận hành đổi lớp riêng tư cho từng file hoặc cả buổi quay. Cấu trúc và nhãn đo được không bị ảnh hưởng, vì chúng được tính trong máy.

## 20. Màn hình cho người vận hành

Mỗi đợt giao phần màn hình của nó; không màn hình nào được xây trước dữ liệu nó hiển thị.

**Dải thời gian của một video** (trang Thư viện, đợt 1). Một dải ngang theo thời gian của file, gồm ba lớp chồng nhau: cú máy (các vạch ranh giới), nhịp (các khối, màu theo chất lượng hình), phân cảnh (các băng có tên, từ đợt 4). Vùng chuyển mờ và đoạn bị loại được tô khác. Bấm vào một nhịp để xem các khung của nó, mô tả và các nhãn; mỗi nhãn có dấu cho biết nguồn và độ tin cậy, và sửa được tại chỗ.

**Đánh dấu ranh giới** (cùng dải đó, đợt 1). Người vận hành thêm, dời hoặc xoá một ranh giới ngay trên dải. Mỗi thao tác làm hai việc: ghim ranh giới đó (mục 5) và lưu nó làm mẫu cho bộ đo (mục 16).

**Hàng chờ xem lại** (đợt 2). Danh sách các nhịp có cờ mở, mỗi dòng gồm khung hình, lý do bị gắn cờ, lời mô hình và số đo đặt cạnh nhau. Ba thao tác: xác nhận mô hình đúng, sửa, bỏ qua.

**Phân cảnh của một buổi quay** (đợt 4). Danh sách phân cảnh với ảnh đại diện, tên, độ dài và các file nó đi qua. Gộp hai phân cảnh kề nhau, tách một phân cảnh tại một nhịp, đổi tên. Mỗi phân cảnh hiển thị bản đồ độ phủ, các nhóm quay lại có xếp hạng, và các góc máy song song.

**Sổ nhân vật, nơi chốn, đồ vật** (đợt 5). Danh sách các mục, số nhịp liên kết với mỗi mục, gộp hai mục, và các liên kết chờ xác nhận.
