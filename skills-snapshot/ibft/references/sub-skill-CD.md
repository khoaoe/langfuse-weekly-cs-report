---
name: interbank-fund-transfer/sub-skill-CD
description: Xử lý kịch bản giao dịch thất bại và có giao dịch hoàn tiền - đã hoàn tiền (nhóm C) hoặc đang xử lý hoàn tiền (nhóm D).
---

## Tool bổ sung
**Nhóm C,D:** Bắt buộc gọi `lookup_refund_details_by_transaction_id` để lấy thời gian và nguồn hoàn tiền hoàn về.

---

## Kịch bản & Hướng dẫn

### C1 - Thất bại & Đã hoàn tiền thành công
- Điều kiện: Có giao dịch hoàn tiền thành công
- Xác nhận rõ: giao dịch không thành công và **đã được hoàn tiền**.
- Cung cấp: mã giao dịch, số tiền, tên ngân hàng, 4 số cuối, **thời gian hoàn tiền**, **nguồn hoàn về** (ví Zalopay / tài khoản ngân hàng / số dư sinh lời).
- Hướng dẫn: Vào Lịch sử giao dịch → chọn Hoàn tiền để kiểm tra lịch sử và trạng thái hoàn tiền.
- Cung cấp link Lịch sử giao dịch bấm tại đây :  https://social.zalopay.vn/spa/v2/history?c=1&c_time=1761302892&trace_id=spa-c5305aed-3e5a-42a5-8aec-482f84088194

### C2 - Thất bại & Chưa bị trừ tiền & Không có nguyên nhân thất bại
- Điều kiện: `sourcetnxstatus` khác `FAILED`
- Xác nhận rõ: giao dịch không thành công và **chưa bị trừ tiền**.
- Cung cấp: mã giao dịch, số tiền, tên ngân hàng, 4 số cuối

### D1, D2 - Thất bại & Đang xử lý hoàn tiền (3 ngày)
- Điều kiện: Có giao dịch hoàn tiền đang xử lý
- Xác nhận rõ: giao dịch không thành công và **đang được hoàn tiền**.
- Thời gian dự kiến: **3 ngày làm việc**.
- Hướng dẫn: Vào Lịch sử giao dịch → chọn Hoàn tiền để kiểm tra lịch sử và trạng thái hoàn tiền.
- Cung cấp link Lịch sử giao dịch bấm tại đây :  https://social.zalopay.vn/spa/v2/history?c=1&c_time=1761302892&trace_id=spa-c5305aed-3e5a-42a5-8aec-482f84088194
