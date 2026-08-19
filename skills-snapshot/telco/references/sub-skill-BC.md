---
name: telco/sub-skill-BC
description: Xử lý kịch bản chưa nhận được mã thẻ giải trí hoặc thẻ data (nhóm B), và kịch bản đã có mã nhưng nạp không được (nhóm C).
---

## Tool bổ sung
**Nhóm B:** Bắt buộc gọi `get_telco_order_status` TRƯỚC (`app_id` từ mã số của field `App`, `order_id` từ `AppTransId`), để xác nhận trạng thái đơn hàng thật trước khi kết luận nguyên nhân chưa nhận mã. Tuyệt đối không kết luận B1/B2 khi chưa có kết quả `status` này — "chưa nhận được mã thẻ" theo lời khách hàng không đồng nghĩa với đơn hàng đã thành công và mã đã gửi.

- `status` là `SUCCESS`: gọi tiếp `get_user_kyc_profile` với `user_id` lấy từ `UserID` và `identity_profile` là `true`. Phân nhánh theo `IdentityProfile.approved` (B1/B2 dưới).
- `status` khác `SUCCESS` (`FAIL`, `PROCESSING`, `EXPIRED`), hoặc `get_telco_order_status` lỗi/không trả dữ liệu: KHÔNG xử lý theo B1/B2. Chuyển sang xử lý theo đúng nhánh tương ứng của nhóm A (`sub-skill-A.md`, dựa theo `status` vừa nhận được) — vì đơn hàng chưa chắc đã phát mã, nguyên nhân thật có thể khác hẳn "nhập sai email".

**Nhóm C:** Không gọi tool. Mọi thông tin cần dùng nằm trên payload ticket.

Tool lỗi hoặc không trả dữ liệu: chuyển bộ phận chăm sóc khách hàng.

---

## B - Chưa nhận được mã thẻ giải trí/thẻ data, cần gửi lại

### B1 - Khách hàng đã định danh
- Điều kiện: `status` từ `get_telco_order_status` là `SUCCESS`, và `IdentityProfile.approved` từ `get_user_kyc_profile` là `true`
- Phản hồi: nguyên nhân chưa nhận được mã có thể là địa chỉ email nhận mã bị nhập sai lúc thanh toán. Nêu lại **nguyên văn** giá trị field `Email KH cung cấp` trên ticket để khách hàng đối chiếu. Tuyệt đối không tự sửa chính tả email đó, không tự đoán email đúng.
- Hướng dẫn: khách hàng phản hồi lại chính vé yêu cầu này kèm địa chỉ email đúng cần nhận mã, Zalopay sẽ hỗ trợ gửi lại mã về email mới.
- Nhắc khách hàng kiểm tra thêm hộp thư Spam/Quảng cáo của địa chỉ email đã điền trước khi cung cấp email mới.
- Ticket không có `Email KH cung cấp`: bỏ hẳn phần nêu lại email, vẫn yêu cầu khách hàng cung cấp địa chỉ email cần nhận mã.
- Follow-up: khách hàng đã cung cấp địa chỉ email: chuyển bộ phận chăm sóc khách hàng để gửi lại mã. Không hứa thời gian gửi lại.

### B2 - Khách hàng chưa định danh
- Điều kiện: `status` từ `get_telco_order_status` là `SUCCESS`, và `IdentityProfile.approved` từ `get_user_kyc_profile` là `false`
- Phản hồi: để đổi địa chỉ email nhận mã, khách hàng cần định danh tài khoản trước, sau đó phản hồi lại chính vé yêu cầu này để Zalopay hỗ trợ gửi lại mã thẻ về email mới.
- Thao tác định danh: truy cập ứng dụng Zalopay, vào mục **Tài khoản**, chọn dòng định danh, chụp ảnh Căn cước công dân và ảnh chân dung theo hướng dẫn, sau đó thực hiện sinh trắc học NFC.
- Không nêu lại email khách hàng đã điền ở kịch bản này, vì việc cần làm trước là định danh.
- Follow-up: khách hàng báo đã định danh xong và cung cấp địa chỉ email mới: chuyển bộ phận chăm sóc khách hàng để gửi lại mã.

---

## C - Đã có mã/thẻ nhưng không dùng được

### C2 - Đã có mã nhưng nạp không được
- Điều kiện: khách hàng báo đã nhận được mã hoặc thẻ nhưng nạp không thành công, gửi sai đầu số, thẻ báo đã bị dùng, hoặc SIM lỗi
- Xác định nhà mạng và loại thẻ từ field `Ghi chú` trên ticket, ví dụ `Ghi chú: Mua 1 thẻ 4G/5G Viettel 1,2GB` là thẻ data Viettel. Ticket không có `Ghi chú` hoặc `Ghi chú` không nêu nhà mạng: lấy nhà mạng và loại thẻ từ tên dịch vụ trong field `App`.
- Hướng dẫn nạp lại theo bảng cú pháp dưới. Luôn nhấn mạnh dùng **mã data code**, không dùng **mã serial 12 số**:
| Nhà mạng | Loại thẻ | Cú pháp nạp |
|---|---|---|
| Viettel | Thẻ data | Soạn `NAPDATA_<MÃ DATA CODE>` gửi `5698` |
- Nhà mạng hoặc loại thẻ **không có trong bảng trên**: tuyệt đối không tự suy đoán cú pháp và không tự suy đoán đầu số. Trả lời rằng Zalopay đang kiểm tra lại với nhà cung cấp và nhờ khách hàng gửi ảnh chụp màn hình báo lỗi.
- Kèm trong cùng phản hồi: nhờ khách hàng gửi ảnh chụp màn hình báo lỗi nếu khách hàng đã thực hiện đúng cú pháp trên mà vẫn không nạp được.
- Không khẳng định mã còn hạn hay đã bị sử dụng. Không có tool tra được trạng thái sử dụng của mã.
- Follow-up: khách hàng báo vẫn không nạp được, hoặc đã gửi ảnh chụp màn hình báo lỗi thì chuyển bộ phận chăm sóc khách hàng. Không hướng dẫn lại cú pháp lần thứ hai.
