---
name: withdraw/sub-skill-C
description: Xử lý giao dịch rút tiền đang xử lý (mã `-383`)
---

## Tool bổ sung
Gọi `get_bank_name` để hiển thị tên ngân hàng.

---

## Kịch bản & Hướng dẫn

### C1 - Giao dịch đang xử lý
- Thông báo giao dịch đang được Zalopay và ngân hàng phối hợp tra soát.
- Cung cấp: mã giao dịch, số tiền, tên ngân hàng, 4 số cuối.
- Gọi tool `calculate_time_difference__interbank-fund-transfer` để kiểm tra có quá 3 ngày chưa:
- - Nếu chưa quá 3 ngày: Phản hồi Zalopay đang trong quá trình tra soát, sẽ cập nhật kết quả ngay khi có kết quả tra soát. Thời gian dự kiến có kết quả: **3 ngày làm việc** (không tính T7, CN, lễ)
- - Nếu đã quá 3 ngày: Chuyển bộ phận CSKH
- Lưu ý: nếu giao dịch không hoàn tất, tiền sẽ được hoàn lại đầy đủ.

### C2 - Follow-up thúc giục
- Điều kiện: Khách hàng quay lại thúc giục về cùng giao dịch, không có thông tin mới
- Gọi lại `get_transaction_processing_engine_data` kiểm tra trạng thái trước khi trả lời.
- - Trạng thái đã đổi: xử lý theo bảng của trạng thái mới
- - Trạng thái không đổi: Gọi tool `calculate_time_difference__interbank-fund-transfer` để kiểm tra có quá 3 ngày chưa:
- - Nếu chưa quá 3 ngày: Phản hồi Zalopay vẫn đang trong quá trình tra soát và sẽ hoàn tất trong **3 ngày làm việc**
- - Nếu đã quá 3 ngày: Chuyển bộ phận CSKH
