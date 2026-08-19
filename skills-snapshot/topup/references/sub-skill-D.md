---
name: topup/sub-skill-D
description: Xử lý giao dịch nạp tiền thất bại có `transstatus` khác `-217`
---

## Tool bổ sung
Không cần gọi thêm tool.

---

## Kịch bản & Hướng dẫn

### Giao dịch thất bại do hạn mức trong ngày, dùng Vietcombank
- Điều kiện: Giao dịch thất bại có `step_result` là `-344` và giao dịch nạp tiền từ Vietcombank
- Phản hồi: Zalopay kiểm tra giao dịch của bạn không thành công do đã vượt hạn mức thanh toán theo ngày với tài khoản Vietcombank.     Theo quy định của ngân hàng, tài khoản Vietcombank liên kết tài khoản Zalopay có hạn mức như sau:  - Trong vòng 24 giờ tính từ khi liên kết thành công: tối đa 2 triệu đồng/ngày.  - Trên 24 giờ từ khi liên kết: tối đa 50 triệu đồng/ngày, 10 triệu/giao dịch.
- Hướng dẫn: Bạn vui lòng thực hiện lại giao dịch với tài khoản Vietcombank vào ngày tiếp theo, hoặc thanh toán bằng nguồn tiền khác giúp Zalopay nhé
- Nếu khách hàng hỏi vì sao chưa hoàn tiền, phản hồi: Bạn không bị trừ tiền, hãy kiểm tra lại số dư tài khoản ngân hàng nhé

### Giao dịch thất bại
- Dựa vào `message` để đưa ra nguyên nhân thất bại và hướng xử lý
- Phản hồi: Nguyên nhân thất bại, hướng xử lý
- Trong trường hợp cần hỗ trợ thêm, bạn hãy phản hồi lại nhé
- Nếu khách hàng hỏi vì sao chưa hoàn tiền, phản hồi: Bạn không bị trừ tiền, hãy kiểm tra lại số dư tài khoản ngân hàng nhé
