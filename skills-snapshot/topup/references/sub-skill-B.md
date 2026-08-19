---
name: topup/sub-skill-B
description: Xử lý giao dịch nạp tiền thành công có `product_code` là `TU004`\`TU006`
---

## Tool bổ sung
Không cần gọi thêm tool.

---

## Kịch bản & Hướng dẫn

### B1 - Giao dịch nạp tiền thành công, chưa cộng tiền cho khách hàng
- Điều kiện: `desttnxstatus` là thất bại
- Phản hồi: Bộ phận chăm sóc khách hàng sẽ phản hồi sớm cho bạn
- Gửi cho bộ phận chăm sóc khách hàng hỗ trợ

### B2 - Giao dịch nạp tiền thanh toán thành công, đã cộng tiền cho khách hàng
- Điều kiện: `desttnxstatus` là thành công và `product_code` là `TU006`
- Phản hồi: Giao dịch bạn đang gửi yêu cầu là giao dịch nạp tiền vào ví để thực hiện thanh toán. Giao dịch nạp tiền đã thành công.
- Hướng dẫn: Vui lòng vào mục Lịch sử giao dịch trên Zalopay để kiểm tra trạng thái giao dịch thanh toán.
- Cung cấp link Lịch sử giao dịch  bấm tại đây :  https://social.zalopay.vn/spa/v2/history?c=1&c_time=1761302892&trace_id=spa-c5305aed-3e5a-42a5-8aec-482f84088194
- Hãy gửi yêu cầu từ chính giao dịch chuyển tiền nếu bạn cần kiểm tra
- Nếu khách hàng yêu cầu hoàn tiền hoặc huỷ giao dịch, phản hồi: Vì giao dịch đã thành công nên Zalopay không thể huỷ giao dịch.

### B2 - Giao dịch nạp tiền chuyển tiền thành công, đã cộng tiền cho khách hàng
- Điều kiện: `desttnxstatus` là thành công và `product_code` là `TU004`
- Phản hồi: Giao dịch bạn đang gửi yêu cầu là giao dịch nạp tiền vào ví để thực hiện chuyển tiền. Giao dịch nạp tiền đã thành công.
- Hướng dẫn: Vui lòng vào mục Lịch sử giao dịch trên Zalopay để kiểm tra trạng thái giao dịch chuyển tiền.
- Cung cấp link Lịch sử giao dịch  bấm tại đây :  https://social.zalopay.vn/spa/v2/history?c=1&c_time=1761302892&trace_id=spa-c5305aed-3e5a-42a5-8aec-482f84088194
- Hãy gửi yêu cầu từ chính giao dịch chuyển tiền nếu bạn cần kiểm tra
- Nếu khách hàng yêu cầu hoàn tiền hoặc huỷ giao dịch, phản hồi: Vì giao dịch đã thành công nên Zalopay không thể huỷ giao dịch.
