---
name: interbank-fund-transfer/sub-skill-B
description: Xử lý kịch bản giao dịch đang được tra soát hoặc hệ thống đang tự kiểm tra.
---

## Tool bổ sung
Không cần gọi thêm tool.

---

## Kịch bản & Hướng dẫn

### B1 - Đang phối hợp tra soát
- Thông báo giao dịch đang được Zalopay và ngân hàng phối hợp tra soát.
- Cung cấp: mã giao dịch, số tiền, tên ngân hàng, 4 số cuối.
- Thời gian dự kiến có kết quả: **3 ngày làm việc**.
- Lưu ý: nếu giao dịch không hoàn tất, tiền sẽ được hoàn lại đầy đủ.

### B2 - Hệ thống tự kiểm tra
- Thông báo hệ thống đang tự động kiểm tra lỗi bất thường.
- Yêu cầu khách hàng chờ **24 giờ** rồi kiểm tra lại trạng thái giao dịch.
