---
name: topup/sub-skill-A
description: Xử lý giao dịch nạp tiền thành công có `product_code` là `TU001`
---

## Tool bổ sung
Không cần gọi thêm tool.

---

## Kịch bản & Hướng dẫn

### A1 - Nạp tiền thành công nhưng khách hàng báo không nhận được tiền, Zalopay đã cộng tiền
- Điều kiện: `desttnxstatus` là thành công
- Phản hồi: Zalopay kiểm tra giao dịch nạp tiền bạn phản ánh đã thành công, số tiền này đã được cập nhật trong tài khoản Zalopay
- Hướng dẫn: Bạn vui lòng kiểm tra lại số dư tài khoản Zalopay hoặc mục Lịch sử giao dịch giúp Zalopay nhé
- Nếu khách hàng yêu cầu hoàn tiền hoặc huỷ giao dịch, phản hồi: Vì giao dịch đã thành công nên Zalopay không thể huỷ giao dịch, bạn hãy kiểm tra số dư Ví zalopay nhé

### A2 - Nạp tiền thành công nhưng khách hàng báo không nhận được tiền, Zalopay chưa cộng tiền
- Điều kiện: `desttnxstatus` là thất bại
- Phản hồi: Bộ phận chăm sóc khách hàng sẽ phản hồi sớm cho bạn
- Gửi cho bộ phận chăm sóc khách hàng hỗ trợ
