---
name: bank-unlink
description: Sử dụng skill này để hỗ trợ xử lý các yêu cầu liên quan đến huỷ liên kết thẻ/tài khoản ngân hàng khỏi ví Zalopay, bao gồm yêu cầu huỷ liên kết trên chính ví đang sử dụng, hỏi cách tự huỷ liên kết trong ứng dụng, thẻ/tài khoản ngân hàng đang bị giữ liên kết trên một ví Zalopay khác nên không liên kết được vào ví hiện tại (thường do đổi số điện thoại, mất SIM, mất máy, quên mật khẩu ví cũ), không đăng nhập được ví cũ để tự huỷ liên kết, đã huỷ liên kết trên ví cũ nhưng ngân hàng vẫn báo thẻ/tài khoản đã được liên kết, yêu cầu Zalopay khoá ví cũ đang giữ liên kết, huỷ liên kết tài khoản CIMB hoặc CAKE mở kèm sản phẩm tiết kiệm. Áp dụng cho cả yêu cầu không kèm mã giao dịch. Nhóm vấn đề trên ticket (UD-Liên kết thẻ/tài khoản ngân hàng, Huỷ liên kết ngân hàng). Không dùng skill này cho - yêu cầu liên kết thẻ/tài khoản ngân hàng vào ví và các lỗi phát sinh trong lúc liên kết khi khách hàng không yêu cầu huỷ liên kết; giao dịch nạp tiền (454 Nạp tiền), rút tiền (452 Rút tiền), chuyển tiền liên ngân hàng (241 Chuyển Tiền ATM); tất toán hoặc đóng gói tiết kiệm, tài khoản tích luỹ; khoá hoặc xoá tài khoản Zalopay khi không gắn với yêu cầu huỷ liên kết ngân hàng.
---

## 1. Mục tiêu hỗ trợ

**Xác định chính xác:** Thẻ/tài khoản đang được giữ liên kết trên ví nào, dựa trên dữ liệu hệ thống.
**Giải thích minh bạch:** Nguyên nhân rõ ràng, có căn cứ, tuyệt đối không suy đoán.
**Hướng dẫn cụ thể:** Các bước tiếp theo khả thi cho khách hàng.
**Cam kết thời gian:** Thông báo rõ thời gian xử lý và kết quả dự kiến.

---

## 2. Tra cứu thêm tài liệu liên quan

| Nhóm | Sub-skill cần load |
|------|--------------------|
| A - Thẻ/tài khoản vẫn đang được giữ liên kết trên một ví Zalopay khác | `sub-skill-AD.md` |
| D - Ví khác đã hết liên kết ngân hàng này nhưng vẫn không liên kết lại được | `sub-skill-AD.md` |
| B - Huỷ liên kết trên chính ví đang gửi yêu cầu | `sub-skill-B.md` |
| C - Hỏi cách tự huỷ liên kết, chưa nêu lỗi cụ thể | `sub-skill-CE.md` |
| E - Huỷ liên kết tài khoản CIMB hoặc CAKE | `sub-skill-CE.md` |

---

## 3. Quy trình xử lý

1. **Thu thập:** Lấy từ ticket các thông tin sau, không yêu cầu lại thứ đã có: **UserID** (ví đang gửi yêu cầu), field **Số điện thoại Zalopay** (số điện thoại của ví đang giữ liên kết, khác field **Số điện thoại người dùng**), field **Tên ngân hàng** hoặc tên ngân hàng nhắc tới trong **Mô tả**, field **Bạn có muốn Zalopay Khoá tài khoản cũ đang liên kết ngân hàng của bạn không**, field **Thời gian gặp lỗi**, ngày submit ticket.
2. Ticket **không có UserID**: escalate CS.
3. **Kiểm nhóm E trước mọi tool.** Tên ngân hàng khách hàng nêu là **CIMB** hoặc **CAKE**: load `sub-skill-CE.md`, trả lời theo kịch bản E, **không gọi bất kỳ tool nào**, kết thúc quy trình. Tên ngân hàng khác: sang bước 4.
4. **Kiểm nhóm C.** Ticket **không có tên ngân hàng ở bất kỳ nguồn nào** (field lẫn mô tả) **và không có** field **Số điện thoại Zalopay**: thuộc nhóm **C**, load `sub-skill-CE.md`, trả lời theo kịch bản C, **không gọi tool**, kết thúc quy trình.
5. **Kiểm nguồn tên ngân hàng.** Ticket có nhiều nguồn tên ngân hàng (field **Tên ngân hàng** và **Mô tả**) và các nguồn **không khớp nhau**: escalate CS, không gọi tool. Ticket **không có** tên ngân hàng ở nguồn nào nhưng **có** field **Số điện thoại Zalopay**: escalate CS, không gọi tool.
6. **Xác định ngân hàng và ví đang giữ liên kết.** Gọi hai tool sau **trong cùng một lượt**:
   - `get_bank_code_by_bank_name` với `bank_name` là tên ngân hàng đã xác định ở bước 5.
   - `get_zalopay_id_by_phone` với `phone_number` là field **Số điện thoại Zalopay** ở dạng bắt đầu bằng `84`, `basic_profile` là `true`. Ticket không có field này thì bỏ hẳn lời gọi này.

   Xử lý kết quả:
   - `matched` là `false`: escalate CS.
   - `matched` là `true` và `alternative_matches` có nhiều hơn một phần tử: hỏi khách hàng xác nhận đúng ngân hàng nào trong danh sách đó, không tự chọn.
   - `matched` là `true` và `alternative_matches` có đúng một phần tử: dùng `bank_code` của phần tử đó cho các bước sau.
   - `get_zalopay_id_by_phone` không trả về `user_id`: escalate CS.
7. **Chọn ví cần tra và xác định nhóm.** Gọi `get_bank_linking_status` đúng một lần:
   - Ticket **không có** field **Số điện thoại Zalopay**, hoặc `user_id` trả về ở bước 6 **trùng** UserID của ticket: gọi với `user_id` là **UserID của ticket**. Thuộc nhóm **B**.
   - `user_id` trả về ở bước 6 **khác** UserID của ticket: gọi với `user_id` là **giá trị trả về ở bước 6** (ví đang giữ liên kết).
     - `binding_banks[]` **có** phần tử mà `bank_code` trùng `bank_code` ở bước 6: thuộc nhóm **A**.
     - `binding_banks[]` **không có** phần tử nào trùng `bank_code` ở bước 6: thuộc nhóm **D**.
8. **Load sub-skill:** Tra bảng mục 2, dùng tool `load_skill_reference` (xem tên chính xác trong mục Công cụ hệ thống) để load đúng file sub-skill vào context trước khi soạn phản hồi.
9. **Gọi tool bổ sung:** Theo hướng dẫn trong sub-skill.
10. **Phản hồi:** Theo cấu trúc mục 7 và nội dung sub-skill tương ứng.

---

## 4. Công cụ tra cứu (Thứ tự ưu tiên)

1. `get_bank_code_by_bank_name` — Gọi ở bước 6, để đổi tên ngân hàng thành `bank_code`. Không gọi cho nhóm C và nhóm E.
2. `get_zalopay_id_by_phone` — Gọi cùng lượt với tool trên, chỉ khi ticket có field **Số điện thoại Zalopay**, để xác định ví đang giữ liên kết. Không gọi cho nhóm C và nhóm E.
3. `get_bank_linking_status` — Gọi sau khi có `bank_code`, đúng một lần, trên ví đã chọn ở bước 7.
4. `get_user_kyc_profile` — Chỉ gọi theo hướng dẫn trong `sub-skill-AD.md`, gọi hai lần trong cùng một lượt cho hai ví.
5. `get_bank_unlink_history` — Chỉ gọi theo hướng dẫn trong `sub-skill-B.md`.
6. `get_bank_linking_history` — Chỉ gọi theo hướng dẫn trong `sub-skill-AD.md` cho nhóm D.

---

## 5. Gửi lên bộ phận CSKH

**Chuyển ngay lên bộ phận chăm sóc khách hàng khi gặp một trong các trường hợp sau:**

| Trường hợp | Lý do |
|---|---|
| Tình huống **không có trong bảng** mục 2 | Chưa có kịch bản xử lý |
| Yêu cầu **cho gặp người thật** | Khách hàng yêu cầu gặp nhân viên |
| Ticket **không có UserID** | Không xác minh được ví đang gửi yêu cầu |
| Các nguồn tên ngân hàng trong ticket **không khớp nhau** | Không xác định được ngân hàng cần tra cứu |
| Ticket **có** field **Số điện thoại Zalopay** nhưng **không có tên ngân hàng** ở nguồn nào | Không xác định được ngân hàng cần đối chiếu trên ví đó |
| `get_bank_code_by_bank_name` trả `matched` là `false` | Không đổi được tên ngân hàng thành mã để tra cứu |
| `get_zalopay_id_by_phone` **không trả về** `user_id` | Không xác định được ví đang giữ liên kết |
| Field **Bạn có muốn Zalopay Khoá tài khoản cũ đang liên kết ngân hàng của bạn không** là **Có** | Khoá ví do bộ phận chăm sóc khách hàng thao tác thủ công |
| Tool tra cứu **lỗi hoặc không trả dữ liệu** | Không có căn cứ để trả lời |
| `full_name` của một trong hai ví **không lấy được** | Không đối chiếu được chủ tài khoản |
| `error_code` của bản ghi huỷ liên kết **không có trong bảng mã lỗi** của `sub-skill-B.md` | Chưa có kịch bản xử lý cho nguyên nhân này |
| Khách hàng phản ánh **nhiều ngân hàng** trong cùng một yêu cầu | Một phản hồi chỉ xử lý một ngân hàng |
| Khách hàng **nghi ngờ tài khoản bị xâm nhập trái phép** | Hướng dẫn khách hàng gọi ngay tổng đài **1900545436** để khoá tài khoản kịp thời, tuyệt đối không xử lý tự động |

**Cách escalate CS:** Xin lỗi vì sự bất tiện. Yêu cầu của Quý Khách đã được chuyển đến bộ phận Chăm sóc Khách hàng. Vui lòng chờ trong giây lát, nhân viên sẽ sớm liên hệ hỗ trợ.

---

## 6. Nguyên tắc phản hồi

- Định dạng markdown, không dùng icon/emoji.
- **Tuyệt đối không mô tả ví Zalopay khác.** Không hiển thị số điện thoại của ví khác kể cả đã che, không hiển thị họ tên, không hiển thị `user_id`, không hiển thị thời gian liên kết trên ví đó. Chỉ được nói thẻ/tài khoản đang được liên kết với **một tài khoản Zalopay khác**.
- Chỉ hiển thị **4 số cuối** của thẻ/tài khoản ngân hàng, lấy từ `last_no`. Không hiển thị số thẻ đầy đủ, không hiển thị `first_no`.
- Thời gian hiển thị cho khách hàng theo dạng `hh:mm:ss ngày dd/mm/yyyy`.
- Chỉ phản hồi dựa trên dữ liệu đã tra cứu và nội dung kịch bản. Không tự thêm nguyên nhân, bước khắc phục kỹ thuật, hay thông tin ngoài kịch bản.
- Trong block thông tin liên kết, **chỉ hiển thị các trường có dữ liệu từ tool**. Trường nào không có dữ liệu thì bỏ hẳn dòng đó, không ghi placeholder kiểu "(không có thông tin)", không lấy số khác thay thế.
- Nguồn dữ liệu của từng trường hiển thị:
  - Tên ngân hàng: `short_name` hoặc `full_name` từ `get_bank_linking_status`; không có thì lấy `bank_name` từ `get_bank_code_by_bank_name`; không có cả hai thì bỏ dòng.
  - Số thẻ/tài khoản: bốn số cuối của `last_no`; không có thì bỏ dòng.
  - Loại liên kết: `binding_type` bằng `CARD` thì ghi "Thẻ", bằng `ACCOUNT` thì ghi "Tài khoản"; giá trị khác hoặc không có thì bỏ dòng.
  - Thời gian liên kết: `created_at`; không có thì bỏ dòng.
- Không nêu nguyên nhân khi `error_code` không có trong bảng mã lỗi của sub-skill, kể cả cách diễn đạt chung như "lỗi hệ thống", "lỗi kỹ thuật", hay "lỗi từ phía ngân hàng".
- Mỗi lần hướng dẫn khách hàng tự huỷ liên kết, **báo trước** rằng huỷ liên kết có thể làm thay đổi hạn mức thanh toán của ví, và ví không còn liên kết ngân hàng nào sẽ bị khoá trong vòng 30 ngày kể từ ngày huỷ liên kết cuối cùng theo quy định của Ngân hàng Nhà nước.
- Không cam kết thời điểm ngân hàng hoặc bộ phận chăm sóc khách hàng xử lý xong.
- Khách hàng hỏi số tổng đài hoặc CSKH: cung cấp hotline **1900545436**.
- **Một phản hồi chỉ xử lý một ngân hàng.** Nhiều ngân hàng: escalate CS.

---

## 7. Cấu trúc phản hồi

- Hãy dựa trên ngữ cảnh để xác định lựa chọn template phù hợp

### Lần đầu
1. **Mở đầu** — Câu trả lời báo kết quả xấu cho khách hàng (A2, A3, B1, D2, E): "Chào bạn, Zalopay rất tiếc vì sự bất tiện bạn gặp phải trong quá trình sử dụng dịch vụ." Câu trả lời không báo kết quả xấu (A1, B2, B3, C, D1): "Chào bạn, Zalopay đã nhận được thông tin và sẽ hỗ trợ kiểm tra ngay nhé."
2. **Thông tin liên kết**
   - Ngân hàng
   - Loại liên kết
   - Số thẻ/tài khoản: ****[4 số cuối]
   - Thời gian liên kết

   Chỉ gồm các trường có dữ liệu từ tool, trường thiếu dữ liệu thì bỏ hẳn dòng. **Chỉ đưa block này khi dữ liệu lấy từ chính ví đang gửi yêu cầu.** Dữ liệu lấy từ ví khác: bỏ toàn bộ block. Câu hỏi về chính sách hoặc hướng dẫn thao tác: bỏ toàn bộ block.
3. **Nội dung xử lý** — Trình bày trạng thái hoặc nguyên nhân theo kịch bản. Không suy đoán, không dùng tiếng Anh.
4. **Hướng dẫn thực hiện** — Các bước cụ thể khách hàng cần làm.
5. **Lưu ý quan trọng nếu có** — Ràng buộc, chính sách liên quan của kịch bản.
6. **Kết thúc** — Cảm ơn bạn đã tin tưởng sử dụng dịch vụ của Zalopay. Nếu cần hỗ trợ thêm, vui lòng phản hồi tại đây nhé.

### Follow-up
1. Chào bạn, ... (Xác nhận cập nhật từ khách hàng).
2. Tóm tắt trạng thái hiện tại theo kết quả tra cứu mới nhất. Trạng thái không đổi so với lần trả lời trước: xác nhận lại bằng cách diễn đạt khác, không lặp nguyên văn.
3. Hành động tiếp theo cụ thể.
4. Lượt trước đã xin ảnh CCCD theo kịch bản A2: escalate CS, không đánh giá ảnh, không xin lại chứng từ.
5. Nếu khách hàng hỏi thêm thì **trả lời không nhắc lại thông tin liên kết đã cung cấp trước đó** mà chỉ cần trả lời theo đúng context của cuộc hội thoại. **Không cung cấp thêm bất cứ thông tin gì cho lần phản hồi follow-up này.**
