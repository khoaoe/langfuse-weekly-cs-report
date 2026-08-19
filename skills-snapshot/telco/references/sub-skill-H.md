---
name: telco/sub-skill-H
description: Xử lý kịch bản giao dịch telco thất bại ngay tại Zalopay, phân nhánh theo mã lỗi TPE và mã lỗi BC trên ticket.
---

## Tool bổ sung
Không cần gọi tool để xác định nguyên nhân. `Mã lỗi TPE` và `Mã lỗi BC` lấy trực tiếp từ payload ticket.

Chỉ khi khách hàng **khẳng định đã bị trừ tiền**: gọi `get_transaction_processing_engine_data` với `transaction_id` lấy từ `TransID` để lấy `sourcetnxstatus`, rồi gọi `lookup_refund_details_by_transaction_id` để kiểm tra hoàn tiền. Diễn giải kết quả:

- `sourcetnxstatus` cho thấy **đã trừ tiền**: đọc tiếp kết quả `lookup_refund_details_by_transaction_id` theo hai gạch đầu dòng cuối mục này.
- `sourcetnxstatus` cho thấy **chưa trừ tiền**, và nguồn tiền là ngân hàng liên kết — nhận biết khi ticket có `Mã lỗi BC`, hoặc khách hàng nói chính ngân hàng đã trừ tiền: **bắt buộc gọi thêm** `get_bank_connector_transaction` với `transaction_id` lấy từ `TransID` trước khi trả lời. `sourcetnxstatus` chỉ là ghi nhận phía Zalopay, không phản ánh việc ngân hàng đã tạm giữ hay đã trừ tiền; kết luận "chưa bị trừ tiền" chỉ dựa trên field này sẽ mâu thuẫn với sao kê của khách hàng.
  - Phía ngân hàng **chưa ghi nhận trừ tiền**: xác nhận giao dịch không thành công và chưa bị trừ tiền. Không hứa hoàn tiền.
  - Phía ngân hàng **đã ghi nhận trừ tiền**, hoặc tool lỗi, hoặc `bc` trống: **tuyệt đối không khẳng định khách hàng chưa bị trừ tiền**. Chuyển bộ phận chăm sóc khách hàng.
- `sourcetnxstatus` cho thấy **chưa trừ tiền**, và không có dấu hiệu nguồn tiền là ngân hàng liên kết: xác nhận giao dịch không thành công và chưa bị trừ tiền. Không hứa hoàn tiền.
- `lookup_refund_details_by_transaction_id` **đã ghi nhận** hoàn tiền: nêu số tiền hoàn và thời gian hoàn từ tool này, hướng dẫn kiểm tra tại **Lịch sử > Hoàn tiền** trong ứng dụng Zalopay.
- Đã trừ tiền và **chưa ghi nhận** hoàn tiền: chuyển bộ phận chăm sóc khách hàng.

`Mã lỗi TPE` và `Mã lỗi BC` trên ticket **không khớp điều kiện của kịch bản nào dưới đây**: chỉ xác nhận giao dịch không thành công, không tự đặt tên nguyên nhân, rồi chuyển bộ phận chăm sóc khách hàng.

---

## Kịch bản & Hướng dẫn

### H1 - Thông tin ngân hàng không tương thích
- Điều kiện: `Mã lỗi BC` là `BANK_CARD_OR_ACCOUNT_NOT_LINKED(-5206)`
- Xác định ngân hàng để hiển thị: gọi `get_bank_connector_transaction` với `transaction_id` lấy từ `TransID` để lấy `bankcode`, rồi gọi `get_bank_name` với chính `bankcode` đó. Tuyệt đối không truyền `bankconnectorcode` sang `get_bank_name` — đó là ngân hàng hoặc kênh trung gian, sẽ cho ra tên ngân hàng sai.
- Phản hồi: giao dịch không thành công do thông tin ngân hàng khách hàng nhập trên Zalopay không tương thích với thông tin tại ngân hàng. Nêu tên ngân hàng lấy từ `get_bank_name`.
- Hướng dẫn: huỷ liên kết ngân hàng và liên kết lại để tiếp tục giao dịch.
- Không lấy được tên ngân hàng (tool lỗi, `bc` trống, hoặc `bankcode` không tra được tên): bỏ hẳn phần tên ngân hàng, giữ nguyên phần còn lại của phản hồi. Không suy đoán ngân hàng nào đang bị lỗi, không lấy tên ngân hàng từ field khác trên ticket.

### H2 - Tài khoản chưa được định danh
- Điều kiện: `Mã lỗi TPE` là `-332`
- Phản hồi: giao dịch không thành công do tài khoản chưa được định danh.
- Hướng dẫn: truy cập ứng dụng Zalopay, vào mục **Tài khoản** và thực hiện định danh để xác nhận sở hữu tài khoản.

### H3 - Vượt hạn mức tài khoản trả sau
- Điều kiện: `Mã lỗi TPE` là `-358`
- Phản hồi: giao dịch không thành công và **không bị trừ tiền**, do vượt hạn mức thanh toán dịch vụ Thẻ điện thoại bằng tài khoản trả sau. Hạn mức là **150.000đ trong 30 ngày**.
- Hướng dẫn: khi ứng dụng không cho phép dùng nguồn tiền này, thực hiện lại giao dịch bằng nguồn tiền khác.
- Không hẹn thời điểm hạn mức được khôi phục.
