---
name: withdraw/sub-skill-D
description: Xử lý giao dịch rút tiền thất bại có `transstatus` là `-63`, `-374`, `-375`, `-376`, `-217`
---

## Tool bổ sung
Bắt buộc gọi `lookup_refund_details_by_transaction_id` khi `transstatus` là `-374`/`-375`/`-376`/`-217` để xác định giao dịch đã hoàn tiền hay chưa, số tiền hoàn và thời gian hoàn. Gọi `get_bank_name` để hiển thị tên ngân hàng.

---

## Kịch bản & Hướng dẫn

### D1 - Số dư ví không đủ
- Điều kiện: `transstatus` là `-63`
- Cung cấp: mã giao dịch, số tiền, tên ngân hàng, 4 số cuối.
- Phản hồi: Giao dịch không thành công do số dư tài khoản Zalopay không đủ, giao dịch của bạn chưa bị trừ tiền.
- Hướng dẫn: nạp thêm tiền vào Zalopay, sau đó thực hiện lại giao dịch
- Nếu khách hàng bảo hoàn tiền, phản hồi: Giao dịch của bạn chưa bị trừ tiền, vui lòng kiểm tra lại số dư ví nhé.

### D2 - Thất bại, chưa hoàn tiền xong
- Điều kiện: Có giao dịch hoàn tiền đang xử lý
- Phản hồi: Xác nhận giao dịch thất bại, tiền sẽ được hoàn về **số dư ví Zalopay** trong vòng **3 ngày làm việc**
- Hướng dẫn kiểm tra kết quả tại: **Lịch sử > Hoàn tiền** trong ứng dụng Zalopay
- Nếu khách hàng hỏi lại: gọi lại `lookup_refund_details_by_transaction_id` trước khi trả lời:
- Tool đã ghi nhận hoàn tiền: xử lý theo D3, không lặp lại thông báo cũ.
- Tool chưa ghi nhận hoàn tiền:
- - Thông báo thời hạn hoàn tiền là **3 ngày làm việc** (không bao gồm Thứ 7, Chủ Nhật và ngày Lễ), tính từ thời điểm giao dịch thất bại.
- - Hướng dẫn khách hàng chờ trong thời hạn này để tiền được hoàn trả về **số dư ví Zalopay**.

### D3 - Thất bại, đã hoàn tiền
- Điều kiện: Giao dịch hoàn tiền thành công
- Xác nhận rõ: giao dịch không thành công và **đã được hoàn tiền**.
- Cung cấp: mã giao dịch, số tiền, tên ngân hàng, 4 số cuối, **thời gian hoàn tiền**, **nguồn hoàn về** (ví Zalopay / tài khoản ngân hàng / số dư sinh lời).
- Hướng dẫn: Vào Lịch sử giao dịch → chọn Hoàn tiền để kiểm tra lịch sử và trạng thái hoàn tiền.
- Cung cấp link Lịch sử giao dịch bấm tại đây :  https://social.zalopay.vn/spa/v2/history?c=1&c_time=1761302892&trace_id=spa-c5305aed-3e5a-42a5-8aec-482f84088194
- Nguyên nhân thất bại và hướng khắc phục:
- - Nếu `stepresult` là `-5033`: Nguyên nhân: Thẻ không hoạt động — Cách xử lý: Hướng dẫn liên hệ trực tiếp ngân hàng phát hành thẻ để kiểm tra tình trạng thẻ
- - Nếu `stepresult` là `-5206` — Nguyên nhân: Liên kết đang bị lỗi - Cách xử lý: Hướng dẫn hủy liên kết ngân hàng và liên kết lại: Tài khoản > Tài khoản/thẻ liên kết > chọn Thẻ/Tài khoản đang gặp lỗi > Hủy liên kết, sau đó liên kết lại. Nếu khách hàng báo không tự hủy liên kết được: yêu cầu ảnh báo lỗi và số tài khoản ngân hàng.
- - `stepresult` khác chưa có trong bảng, hoặc không có `stepresult`: Chỉ xác nhận giao dịch thất bại, không tự suy diễn.
- Với trường hợp `stepresult` là `-5206`: khách hàng đã cung cấp ảnh báo lỗi, hoặc vẫn không tự hủy liên kết được sau hướng dẫn: Chuyển bộ phận chăm sóc khách hàng.

### D4 - Giao dịch thất bại, không bị trừ tiền
- Điều kiện: `sourcetnxstatus` khác `SUCCESS`
- Xác nhận rõ: giao dịch không thành công và **chưa bị trừ tiền**. Cung cấp: mã giao dịch, số tiền, tên ngân hàng, 4 số cuối.
- Nguyên nhân thất bại:
- - Nếu `stepresult` là `-5033`: Nguyên nhân: Thẻ không hoạt động — Cách xử lý: Hướng dẫn liên hệ trực tiếp ngân hàng phát hành thẻ để kiểm tra tình trạng thẻ
- - Nếu `stepresult` là `-5206` — Nguyên nhân: Liên kết đang bị lỗi - Cách xử lý: Hướng dẫn hủy liên kết ngân hàng và liên kết lại: Tài khoản > Tài khoản/thẻ liên kết > chọn Thẻ/Tài khoản đang gặp lỗi > Hủy liên kết, sau đó liên kết lại. Nếu khách hàng báo không tự hủy liên kết được: yêu cầu ảnh báo lỗi và số tài khoản ngân hàng.
- - `stepresult` khác chưa có trong bảng, hoặc không có `stepresult`: Chỉ xác nhận giao dịch thất bại, không tự suy diễn.
- Với trường hợp `stepresult` là `-5206`: khách hàng đã cung cấp ảnh báo lỗi, hoặc vẫn không tự hủy liên kết được sau hướng dẫn: Chuyển bộ phận chăm sóc khách hàng.

### D5 - Giao dịch thất bại, bị trừ tiền nhưng không có giao dịch hoàn tiền
- Điều kiện: `sourcetnxstatus` là `SUCCESS` và không có giao dịch hoàn tiền
- Chuyển bộ phận chăm sóc khách hàng
