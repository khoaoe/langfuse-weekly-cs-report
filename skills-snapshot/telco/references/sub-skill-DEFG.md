---
name: telco/sub-skill-DEFG
description: Xử lý kịch bản nghi trừ tiền nhiều lần (nhóm D), thanh toán tự động (nhóm E), yêu cầu huỷ giao dịch đã thành công (nhóm F), và yêu cầu xuất hoá đơn VAT (nhóm G).
---

## Tool bổ sung
**Nhóm D:** Bắt buộc gọi `get_transaction_processing_engine_data` với `transaction_id` lấy từ `TransID`, để lấy `amount` và `apptime` của đúng giao dịch đang có trên ticket.

**Nhóm F:** Bắt buộc gọi `get_telco_order_status` với `app_id` lấy từ mã số của field `App` và `order_id` lấy từ `AppTransId`, để xác nhận trạng thái đơn hàng trước khi trả lời.

**Nhóm E và nhóm G:** Không gọi tool. Mọi thông tin cần dùng nằm trên payload ticket.

Tool lỗi hoặc không trả dữ liệu: chuyển bộ phận chăm sóc khách hàng.

---

## D - Nghi bị trừ tiền hoặc thanh toán nhiều lần

### D1 - Nghi bị trừ tiền hoặc thanh toán nhiều lần
- Điều kiện: khách hàng phản ánh bị trừ tiền hoặc thanh toán nhiều lần cho cùng một nhu cầu, và ticket chỉ có một `AppTransId`
- Phản hồi: nêu đúng một giao dịch đang có trên ticket, gồm `amount` và `apptime` từ `get_transaction_processing_engine_data`.
- **Tuyệt đối không kết luận khách hàng chỉ có một giao dịch, và không kết luận không có giao dịch trùng lặp.** Zalopay không tra cứu được toàn bộ giao dịch của một khách hàng theo khoảng thời gian, nên chỉ nói được về đúng giao dịch có mã trên ticket.
- Hướng dẫn: khách hàng cung cấp thêm mã giao dịch của các lần bị trừ tiền còn lại, lấy tại mục **Lịch sử giao dịch** trên ứng dụng Zalopay.
- Không đề nghị khách hàng gửi ảnh chụp màn hình trừ tiền, vì Zalopay chỉ đối chiếu được theo mã giao dịch.
- Follow-up: khách hàng cung cấp thêm mã giao dịch: xử lý từng mã theo đúng quy trình mục 3, mỗi phản hồi chỉ xử lý một giao dịch. Khách hàng không cung cấp được mã giao dịch nào khác: chuyển bộ phận chăm sóc khách hàng.

---

## E - Thắc mắc bị trừ tiền do thanh toán tự động

### E1 - Bị trừ tiền do thanh toán tự động
- Điều kiện: `Product Code` trên ticket là `AC003`
- Phản hồi: xác nhận giao dịch nạp tiền điện thoại hoặc nạp data cho số điện thoại (4 số cuối) đã thành công. Nêu rõ đây là giao dịch **thanh toán tự động**, khi đến ngày thanh toán theo cài đặt của khách hàng thì Zalopay tự động thực hiện thanh toán từ nguồn tiền khách hàng đã bật.
- Hướng dẫn: nếu khách hàng không muốn tiếp tục thanh toán tự động cho dịch vụ này, thực hiện huỷ đăng ký theo các bước sau
- — Bạn vui lòng nhấn vào đây https://social.zalopay.vn/spa/v2/autodebit/agreements?category=bill,
- chọn mục **Điện thoại**
- nhấn vào dịch vụ muốn huỷ và chọn **Huỷ thanh toán tự động**
- nhấn **Huỷ gói** rồi **Đóng** để hoàn tất.
- Nêu rõ khách hàng có thể đăng ký lại bất kỳ lúc nào nếu cần.
- Khách hàng cần hỗ trợ thêm về giao dịch của nhà mạng: nêu kênh liên hệ theo bảng dưới, xác định nhà mạng từ tên dịch vụ trong field `App`:
| Nhà mạng | Kênh liên hệ |
|---|---|
| Viettel | tổng đài 18008098 hoặc website https://viettel.vn |
- Nhà mạng không có trong bảng trên: bỏ hẳn phần kênh liên hệ. Tuyệt đối không tự suy đoán số tổng đài hay website nhà mạng.

---

## F - Yêu cầu huỷ giao dịch đã thành công do thao tác nhầm

### F1 - Yêu cầu huỷ giao dịch đã thành công
- Điều kiện: `status` từ `get_telco_order_status` là `SUCCESS`, và khách hàng yêu cầu huỷ hoặc hoàn giao dịch do tự nạp nhầm số điện thoại hoặc nhầm dịch vụ
- Phản hồi: xác nhận giao dịch cho số điện thoại (4 số cuối) đã thành công và thuê bao đã nhận được dịch vụ. Nêu tên gói nếu có.
- Nêu rõ Zalopay chỉ là đơn vị trung gian thanh toán nên chưa thể chủ động hỗ trợ hoàn hoặc huỷ giao dịch đã thành công.
- Không hứa kiểm tra thêm, không hẹn thời gian, không gợi ý khách hàng liên hệ nhà mạng để đòi hoàn tiền.
- `status` không phải `SUCCESS`: không trả lời theo kịch bản này, xử lý theo nhóm A.

---

## G - Yêu cầu xuất hoá đơn VAT

### G1 - Yêu cầu xuất hoá đơn VAT
- Điều kiện: khách hàng yêu cầu xuất hoá đơn VAT cho một giao dịch telco
- Chính sách áp dụng cho mọi nhánh: Zalopay chỉ hỗ trợ xuất hoá đơn cho giao dịch phát sinh **trong cùng ngày** gửi yêu cầu.
- Yêu cầu gửi **trong cùng ngày** thực hiện giao dịch: hướng dẫn khách hàng xuất hoá đơn tại **Hoá đơn > Xuất hoá đơn VAT** trong ứng dụng Zalopay.
- Yêu cầu gửi **sau ngày** thực hiện giao dịch: nêu rõ chính sách trên, xác nhận chưa thể hỗ trợ cho giao dịch này, và nhắc khách hàng các lần sau gửi yêu cầu trong cùng ngày thực hiện giao dịch.
- Không xác định được ngày thực hiện giao dịch hoặc ngày khách hàng gửi yêu cầu: chuyển bộ phận chăm sóc khách hàng, không đoán ngày.
- Ticket đã có `Tên công ty` và `Mã số thuế`: không hỏi lại hai thông tin này.
- Không cam kết thời gian phát hành hoá đơn.
