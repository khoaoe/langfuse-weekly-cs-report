---
name: interbank-fund-transfer/sub-skill-FGH
description: Xử lý kịch bản bảo mật (F), hạn mức (G), hoặc `step_result` chứa `-1|20|700210`
---

## Tool bổ sung
Không cần gọi thêm tool.

---

## F - Bảo mật

### F1 - Tạm khóa / Nghi vấn thiết bị lạ
- Thông báo tài khoản đang tạm thời bị hạn chế giao dịch vì lý do bảo mật.
- Chờ **24 giờ** rồi thử lại.
- Lưu ý: không chia sẻ mật khẩu, mã OTP cho bất kỳ ai. Chỉ đăng nhập trên thiết bị cá nhân.

### F2 - Hệ thống tạm dừng vì rủi ro bảo mật
- Không thao tác liên tục.
- Thực hiện lại giao dịch sau **24 giờ** kể từ lần thất bại **cuối cùng**.

### F3 - Nội dung chuyển tiền bất thường (-1|20|700210)
- Thông báo: Zalopay không hỗ trợ các mục đích bất hợp pháp (cá độ, đánh bạc, rửa tiền...).
- Yêu cầu khách hàng cung cấp đủ 3 thông tin:
- Nguồn gốc số dư tại Zalopay (nạp từ đâu).
- Mục đích các giao dịch chuyển tiền.
- Ý nghĩa nội dung chuyển tiền.
- **Ràng buộc: Tuyệt đối không gợi ý câu trả lời cho khách hàng.**

---

## G - Hạn mức

### G1 - Vượt hạn mức 100 triệu/30 ngày
- Gợi ý phương án thay thế:
- Chuyển số tiền nhỏ hơn (nếu còn hạn mức).
- Chờ vài ngày (hạn mức tăng khi giao dịch cũ qua 30 ngày).
- Rút tiền về ngân hàng: **Ví → Rút tiền**.
- Chuyển cho người dùng Zalopay khác (không bị giới hạn hạn mức này).

### G2 - Vượt hạn mức ngân hàng trong ngày
- Gợi ý phương án thay thế:
- Thanh toán bằng nguồn tiền khác: số dư ví, số dư sinh lời, thẻ/tài khoản ngân hàng khác.
- Sử dụng lại nguồn tiền này sau **24 giờ** (hạn mức ngân hàng làm mới theo ngày).

---

## H - Lỗi hệ thống / App

### H1 - Lỗi app, cần cập nhật
- Cập nhật app Zalopay lên phiên bản mới nhất (CH Play / App Store).
- Thoát hoàn toàn app và mở lại.
- Thực hiện lại giao dịch.

### H2 - Lỗi tạm thời, thử lại sau
- Chờ **10–15 phút** rồi thử lại giao dịch.

### H3 - Hết thời gian thanh toán
- Chờ **10 phút** rồi tạo lại giao dịch **mới**.
- Lưu ý: xác nhận thanh toán (nhập mật khẩu/OTP) kịp thời sau khi tạo, tránh để hết thời gian chờ.

### H4 - Số dư sinh lời không đủ
- Gợi ý chuyển sang nguồn tiền khác: số dư ví Zalopay, thẻ/tài khoản ngân hàng.

### H5 - Lỗi tạm thời số dư sinh lời
- Gợi ý đổi sang nguồn tiền khác (số dư ví, thẻ ngân hàng, tài khoản ngân hàng) hoặc thử lại vào thời điểm khác.
