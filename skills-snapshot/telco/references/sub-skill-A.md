---
name: telco/sub-skill-A
description: Xử lý kịch bản khách hàng đã thanh toán nhưng thuê bao chưa nhận được dịch vụ, data, hoặc tiền vào tài khoản.
---

## Tool bổ sung
Bắt buộc gọi `get_telco_order_status` với `app_id` lấy từ mã số của field `App` và `order_id` lấy từ `AppTransId`. Phân nhánh theo `status` trả về, không phân nhánh theo `Trạng thái Merchant` trên ticket.

`status` là `FAIL`: gọi thêm `lookup_refund_details_by_transaction_id` với `transaction_id` lấy từ `TransID`.

`status` là `EXPIRED`, hoặc tool lỗi, hoặc tool không trả dữ liệu: chuyển bộ phận chăm sóc khách hàng.

---

## Kịch bản & Hướng dẫn

### A1 - Đơn hàng thành công
- Điều kiện: `status` từ `get_telco_order_status` là `SUCCESS`
- Phản hồi: xác nhận giao dịch đã thành công và thuê bao đã nhận được dịch vụ. Nêu tên gói và 4 số cuối số điện thoại thuê bao.
- Nêu rõ lý do Zalopay không tra cứu được chi tiết bên trong tài khoản thuê bao: quy định bảo mật thông tin khách hàng từ phía nhà mạng.
- Hướng dẫn: chủ thuê bao dùng đúng số điện thoại đang sử dụng dịch vụ liên hệ trực tiếp nhà mạng để được kiểm tra chi tiết.
- Xác định nhà mạng theo `telco_code` từ `get_telco_order_status`. Không xác định được thì lấy tên nhà mạng trong `package_name` hoặc trong tên dịch vụ của field `App`. Tra kênh liên hệ theo bảng dưới:
| Nhà mạng | Kênh liên hệ |
|---|---|
| Viettel | tổng đài 18008098 hoặc website https://viettel.vn |
- Nhà mạng không có trong bảng trên: bỏ hẳn phần kênh liên hệ, chỉ hướng dẫn khách hàng liên hệ nhà mạng đang sử dụng. Tuyệt đối không tự suy đoán số tổng đài hay website nhà mạng.
- Không hứa Zalopay sẽ kiểm tra tiếp với nhà mạng, không hẹn thời gian.

### A2 - Đơn hàng đang xử lý
- Điều kiện: `status` từ `get_telco_order_status` là `PROCESSING`
- Phản hồi: giao dịch khách hàng phản ánh đã được Zalopay ghi nhận và đang được ưu tiên kiểm tra với nhà mạng.
- Thời gian: trong vòng **2 ngày làm việc** (không tính T7, CN, ngày lễ và nghỉ bù), nhà mạng sẽ cập nhật kết quả.
- Nêu đủ hai khả năng, không nghiêng về khả năng nào:
- Nhà mạng đã nhận được thông tin thanh toán: giao dịch hoàn tất và khách hàng nhận được dịch vụ.
- Nhà mạng chưa nhận được thanh toán: Zalopay hoàn tiền về nguồn tiền khách hàng đã dùng.
- Nêu rõ hiện khách hàng không cần thực hiện thêm thao tác nào khác.
- Follow-up: gọi lại `get_telco_order_status` trước khi trả lời, không dùng lại kết quả cũ. `status` đã đổi sang `SUCCESS` xử lý theo A1, đổi sang `FAIL` xử lý theo A3. Vẫn `PROCESSING` và đã quá 2 ngày làm việc kể từ lần hẹn trước: chuyển bộ phận chăm sóc khách hàng.

### A3 - Đơn hàng thất bại
- Điều kiện: `status` từ `get_telco_order_status` là `FAIL`
- Phản hồi: giao dịch không thành công hoặc nhà cung cấp đã huỷ.
- `lookup_refund_details_by_transaction_id` **đã ghi nhận** giao dịch hoàn tiền: xác nhận đã hoàn tiền, nêu số tiền hoàn, thời gian hoàn và nguồn hoàn về, tất cả lấy từ chính tool này. Hướng dẫn kiểm tra số tiền hoàn tại mục **Số dư ví Zalopay** và thời gian hoàn tại mục **Lịch sử** trong ứng dụng Zalopay.
- `lookup_refund_details_by_transaction_id` **chưa ghi nhận** giao dịch hoàn tiền: xác nhận giao dịch không thành công, tiền sẽ được hoàn về nguồn tiền khách hàng đã dùng trong vòng **3 ngày làm việc**. Không nêu số tiền hoàn, không nêu thời gian hoàn. Hướng dẫn kiểm tra kết quả tại **Lịch sử > Hoàn tiền** sau khi hoàn tất.
- Follow-up: gọi lại `lookup_refund_details_by_transaction_id` trước khi trả lời. Đã hoàn thì nêu số tiền và thời gian hoàn, không lặp lại thông báo cũ. Đã quá 3 ngày làm việc mà vẫn chưa ghi nhận hoàn tiền: chuyển bộ phận chăm sóc khách hàng.
