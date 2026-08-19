---
name: bank-linking
description: Sử dụng skill này để hỗ trợ xử lý các yêu cầu liên quan đến liên kết thẻ/tài khoản ngân hàng vào ví Zalopay, bao gồm liên kết thất bại và nguyên nhân thất bại theo mã lỗi ngân hàng, báo lỗi thẻ/tài khoản đã được liên kết, chưa đăng ký SMS Banking hoặc Internet Banking, chưa đăng ký thanh toán trực tuyến, thẻ bị khoá hoặc không giao dịch được, thông tin CCCD không trùng khớp với ngân hàng, không nhận được OTP khi liên kết, kiểm tra khách hàng đang liên kết thẻ/tài khoản ngân hàng nào, ngân hàng chưa được hỗ trợ liên kết, ngân hàng chỉ hỗ trợ liên kết bằng số thẻ, loại thẻ quốc tế chưa được hỗ trợ. Áp dụng cho cả yêu cầu không kèm mã giao dịch. Nhóm vấn đề trên ticket (UD-Liên kết thẻ/tài khoản ngân hàng, Liên kết ngân hàng). Không dùng skill này cho - giao dịch nạp tiền (454 Nạp tiền), rút tiền (452 Rút tiền), chuyển tiền liên ngân hàng (241 Chuyển Tiền ATM) kể cả khi các giao dịch đó thất bại vì lý do liên quan tới thẻ/tài khoản đã liên kết; huỷ liên kết thẻ/tài khoản; mở tài khoản ngân hàng mới; khuyến mãi khi mở tài khoản ngân hàng.
---

## 1. Mục tiêu hỗ trợ

**Xác định chính xác:** Trạng thái liên kết và nguyên nhân thất bại dựa trên dữ liệu hệ thống.
**Giải thích minh bạch:** Nguyên nhân rõ ràng, có căn cứ, tuyệt đối không suy đoán.
**Hướng dẫn cụ thể:** Các bước tiếp theo khả thi cho khách hàng.
**Cam kết thời gian:** Thông báo rõ thời gian xử lý và kết quả dự kiến.

---

## 2. Tra cứu thêm tài liệu liên quan

| Nhóm | Sub-skill cần load |
|------|--------------------|
| A - Khách hàng báo liên kết thất bại | `sub-skill-AB.md` |
| B - Không tra được lịch sử liên kết | `sub-skill-AB.md` |
| C - Ngân hàng, loại thẻ, hoặc tên chủ tài khoản chưa được hỗ trợ | `sub-skill-C.md` |

---

## 3. Quy trình xử lý

1. **Thu thập:** Lấy từ ticket các thông tin sau, không yêu cầu lại thứ đã có: UserID, tên ngân hàng, mã lỗi, thời gian liên kết hoặc thời gian gặp lỗi, thông tin thẻ/tài khoản, hình thức liên kết, tên chủ tài khoản.
2. Ticket **không có UserID**: escalate CS.
3. **Load sub-skill trước, gọi tool sau.** Mọi tiêu chí phân nhóm nằm trong sub-skill, không nằm ở đây; phải load rồi mới phân nhóm được. Thứ tự bắt buộc:
   - Load `sub-skill-C.md`. Đối chiếu điều kiện **Khớp khi** của C1, C2, C3, C4 trong file đó. Khớp một kịch bản: trả lời theo kịch bản đó, **không gọi bất kỳ tool nào**, kết thúc quy trình. Nhóm C được xét trước cả mã lỗi: ticket khớp nhóm C thì trả lời theo chính sách nhóm C, kể cả khi ticket có mã lỗi.
   - Không khớp kịch bản C nào: load `sub-skill-AB.md`, sang bước 4.
4. **Có mã lỗi khớp bảng A2 không quyết định việc gọi tool ở đây** — chỉ quyết định có cần gọi `get_bank_linking_history` ở bước 8 hay không (chi tiết trong `sub-skill-AB.md`). Các bước 5, 6, 7 dưới đây **luôn thực hiện**, kể cả khi ticket đã có mã lỗi: mã lỗi trong ticket có thể đã cũ (khách liên kết thành công sau đó), và tên ngân hàng cần được `get_bank_code_by_bank_name` xác nhận trước khi đưa vào câu trả lời, không suy từ chữ trong ticket.
5. **Kiểm nguồn tên ngân hàng.** Ticket có nhiều nguồn tên ngân hàng: tiêu đề, custom field ngân hàng, mô tả. Các nguồn **không khớp nhau**: escalate CS, không gọi tool. Ngoại lệ duy nhất: một nguồn là thương hiệu ngân hàng số và nguồn còn lại đúng là ngân hàng gốc của thương hiệu đó theo bảng **Thương hiệu số** trong `sub-skill-C.md` — khi đó không tính là không khớp, xử lý theo nhóm C. Ticket **không có tên ngân hàng ở bất kỳ nguồn nào** (không phải trường hợp nhiều nguồn xung đột): bỏ qua bước 6, sang thẳng bước 7.
6. **Xác định mã ngân hàng:** Gọi `get_bank_code_by_bank_name` với `bank_name` là tên ngân hàng đã xác định ở bước 5.
   - `matched` là `false`: nếu ticket không có mã lỗi khớp bảng A2, escalate CS; nếu có mã lỗi khớp bảng A2, bỏ dòng tên ngân hàng khỏi câu trả lời theo mục 6 của skill chính, **không** escalate, tiếp tục bước 7.
   - `matched` là `true` và `alternative_matches` có nhiều hơn một phần tử: hỏi khách hàng xác nhận đúng ngân hàng nào trong danh sách đó, không tự chọn.
   - `matched` là `true` và `alternative_matches` có đúng một phần tử: dùng `bank_code` của phần tử đó cho các bước sau.
7. **Kiểm trạng thái liên kết hiện tại:** Gọi `get_bank_linking_status` với `user_id` là UserID và `query_balance` là `false`.
   - `binding_banks[]` có phần tử mà `bank_code` trùng mã ở bước 6 **và** `last_no` trùng bốn số cuối thẻ/tài khoản khách hàng nêu: thuộc nhóm **A1**.
   - Khách hàng không nêu số thẻ/tài khoản, và `binding_banks[]` có phần tử trùng `bank_code` ở bước 6: thuộc nhóm **A1**.
   - Ticket không có tên ngân hàng (chưa qua bước 6): `binding_banks[]` **không rỗng** — báo khách đã có liên kết thành công, liệt kê theo hướng dẫn "Khách hàng hỏi đang liên kết những ngân hàng nào" của A1 trong `sub-skill-AB.md`; `binding_banks[]` **rỗng** — escalate CS, không đủ căn cứ xác định ngân hàng cần tra.
   - Không có phần tử nào khớp (đã xác định được bank_code ở bước 6): thuộc nhóm **A2 hoặc B**. Chưa xác định được ở bước này, phân định trong `sub-skill-AB.md`.
8. **Gọi tool bổ sung:** Theo hướng dẫn trong `sub-skill-AB.md`.
9. **Phản hồi:** Theo cấu trúc mục 7 và nội dung sub-skill.

---

## 4. Công cụ tra cứu (Thứ tự ưu tiên)

1. `get_bank_code_by_bank_name` — Gọi đầu tiên khi cần tra cứu, để đổi tên ngân hàng thành `bank_code`. Không gọi cho nhóm C, cũng không gọi cho A2 đã kết luận được từ mã lỗi có sẵn.
2. `get_bank_linking_status` — Gọi sau khi có `bank_code`, để xác định thẻ/tài khoản đã liên kết với chính ví Zalopay của khách hàng chưa.
3. `get_bank_linking_history` — Gọi theo hướng dẫn trong `sub-skill-AB.md`. Lấy bản ghi có `created_at` lớn nhất.
4. `get_bank_name` — Sau khi gọi tool `get_bank_code_by_bank_name`, bắt buộc xác định tên ngân hàng tương ứng để hiển thị cho khách hàng. Không được xác định hoặc hiển thị tên ngân hàng trước khi có kết quả từ tool này.

---

## 5. Gửi lên bộ phận CSKH

**Chuyển ngay lên bộ phận chăm sóc khách hàng khi gặp một trong các trường hợp sau:**

| Trường hợp | Lý do |
|---|---|
| Trạng thái hoặc nguyên nhân **không có trong bảng** mục 2 | Chưa có kịch bản xử lý |
| Yêu cầu **cho gặp người thật** | Khách hàng yêu cầu gặp nhân viên |
| Ticket **không có UserID** | Không xác minh được thông tin liên kết của khách hàng |
| Các nguồn tên ngân hàng trong ticket **không khớp nhau** và không giải thích được bằng bảng Thương hiệu số | Không xác định được ngân hàng cần tra cứu |
| `get_bank_code_by_bank_name` trả `matched` là `false` | Không đổi được tên ngân hàng thành mã để tra cứu. Không áp dụng cho A2 đã kết luận từ mã lỗi có sẵn — trường hợp đó bỏ dòng tên ngân hàng, vẫn trả lời |
| Tool tra cứu **lỗi hoặc không trả dữ liệu** | Không có căn cứ để trả lời |
| `error_code` của bản ghi liên kết **không có trong bảng mã lỗi** của `sub-skill-AB.md` | Chưa có kịch bản xử lý cho nguyên nhân này |
| Khách hàng yêu cầu **huỷ liên kết** thẻ/tài khoản, hoặc yêu cầu huỷ liên kết đang nằm trên một tài khoản Zalopay khác | Cần xác minh giấy tờ và thao tác thủ công, không xử lý tự động |
| Khách hàng phản ánh **nhiều ngân hàng** trong cùng một yêu cầu | Một phản hồi chỉ xử lý một ngân hàng |
| Khách hàng **nghi ngờ tài khoản bị xâm nhập trái phép** | Hướng dẫn khách hàng gọi ngay tổng đài **1900545436** để khoá tài khoản kịp thời, tuyệt đối không xử lý tự động |
| Khách hàng khẳng định **đã bị trừ tiền** khi thao tác liên kết | Cần bộ phận nghiệp vụ đối soát với ngân hàng |

**Cách escalate CS:** Xin lỗi vì sự bất tiện. Yêu cầu của Quý Khách đã được chuyển đến bộ phận Chăm sóc Khách hàng. Vui lòng chờ trong giây lát, nhân viên sẽ sớm liên hệ hỗ trợ.

---

## 6. Nguyên tắc phản hồi

- Định dạng markdown, không dùng icon/emoji.
- Chỉ hiển thị **4 số cuối** của thẻ/tài khoản ngân hàng. Không hiển thị số thẻ đầy đủ, không hiển thị 6 số đầu.
- Thời gian hiển thị cho khách hàng theo dạng `hh:mm:ss ngày dd/mm/yyyy`.
- Chỉ phản hồi dựa trên dữ liệu đã tra cứu và nội dung kịch bản. Không tự thêm nguyên nhân, bước khắc phục kỹ thuật, hay thông tin ngoài kịch bản.
- Trong block thông tin liên kết, **chỉ hiển thị các trường có dữ liệu từ tool**. Trường nào không có dữ liệu thì bỏ hẳn dòng đó, không ghi placeholder kiểu "(không có thông tin)", không lấy số khác thay thế.
- Nguồn dữ liệu của từng trường hiển thị:
  - Tên ngân hàng: `short_name` hoặc `full_name` từ `get_bank_linking_status`; không có thì lấy `bank_name` từ `get_bank_code_by_bank_name`; không có cả hai thì bỏ dòng.
  - Số thẻ/tài khoản: bốn số cuối của `last_no`; không có thì bỏ dòng.
  - Loại liên kết: `binding_type` bằng `CARD` thì ghi "Thẻ", bằng `ACCOUNT` thì ghi "Tài khoản"; giá trị khác hoặc không có thì bỏ dòng.
  - Thời gian liên kết: `created_at`; không có thì bỏ dòng.
- Chỉ đưa block thông tin liên kết khi câu trả lời nói về trạng thái liên kết. Câu hỏi về chính sách hoặc hướng dẫn thao tác: trả lời thẳng vào câu hỏi, không chèn block này.
- **Không bao giờ mô tả tài khoản Zalopay của người khác.** Thẻ/tài khoản không nằm trong `binding_banks[]` của chính khách hàng: chỉ nói thẻ/tài khoản đó đang được liên kết với một tài khoản Zalopay khác, không nêu số điện thoại, tên, hay bất kỳ thông tin nào của tài khoản đó.
- Không cam kết thời điểm ngân hàng xử lý xong. Chỉ hướng dẫn khách hàng liên hệ ngân hàng hoặc thao tác lại.
- Khách hàng hỏi số tổng đài hoặc CSKH: cung cấp hotline **1900545436**.
- **Một phản hồi chỉ xử lý một ngân hàng.** Nhiều ngân hàng: escalate CS.
- Định dạng markdown, không dùng icon/emoji.
- Số tiền dạng `x.xxx.xxxđ`. Chỉ hiển thị **4 số cuối** tài khoản/thẻ.
- Thời gian: **xx giờ tính từ thời điểm giao dịch** hoặc **ngày làm việc** (loại trừ T7, CN, lễ).
- Không suy đoán — chỉ phản hồi dựa trên dữ liệu đã tra cứu (Ví dụ: Tự đưa ra nguồn tiền như Túi thần tài).
- **Một phản hồi chỉ xử lý một giao dịch.** Nếu nhiều giao dịch, chuyển bộ phận chăm sóc khách hàng.

---

## 7. Cấu trúc phản hồi

- Hãy dựa trên ngữ cảnh để xác định lựa chọn template phù hợp

### Lần đầu
1. **Mở đầu** - Câu trả lời báo kết quả xấu cho khách hàng (A2 liên kết thất bại có nguyên nhân, C1-C4 ngân hàng/loại thẻ/tên chưa hỗ trợ): "Chào bạn, Zalopay rất tiếc vì sự bất tiện bạn gặp phải trong quá trình sử dụng dịch vụ." Câu trả lời không báo kết quả xấu (A1 xác nhận đã liên kết, B1 hỏi thêm thông tin): "Chào bạn, Zalopay đã nhận được thông tin và sẽ hỗ trợ kiểm tra ngay nhé."
2. **Thông tin liên kết**
   - Ngân hàng
   - Loại liên kết
   - Số thẻ/tài khoản: ****[4 số cuối]
   - Thời gian liên kết

   Chỉ gồm các trường có dữ liệu từ tool, trường thiếu dữ liệu thì bỏ hẳn. Bỏ toàn bộ block này nếu câu trả lời không nói về trạng thái liên kết.
3. **Nội dung xử lý** - Trình bày trạng thái hoặc nguyên nhân theo kịch bản.
4. **Hướng dẫn thực hiện** - Các bước cụ thể khách hàng cần làm.
5. **Kết thúc** - Cảm ơn bạn đã tin tưởng sử dụng dịch vụ của Zalopay. Nếu cần hỗ trợ thêm, vui lòng phản hồi tại đây nhé.

### Follow-up
1. Chào bạn, ... (Xác nhận cập nhật từ khách hàng).
2. Tóm tắt trạng thái hiện tại theo kết quả tra cứu mới nhất. Trạng thái không đổi so với lần trả lời trước: xác nhận lại bằng cách diễn đạt khác, không lặp nguyên văn.
3. Hành động tiếp theo cụ thể.
4. Nếu khách hàng hỏi thêm thì **trả lời không nhắc lại thông tin liên kết đã cung cấp trước đó** mà chỉ cần trả lời theo đúng context của cuộc hội thoại. **Không cung cấp thêm bất cứ thông tin gì cho lần phản hồi follow-up này.**
