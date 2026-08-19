---
name: interbank-fund-transfer/sub-skill-E
description: Xử lý kịch bản lỗi xác thực - NFC, khuôn mặt, định danh (eKYC), OTP.
---

## Tool bổ sung
Không cần gọi thêm tool.

---

## E.1 - NFC

### E.1a - Chưa thực hiện xác thực NFC
- Cung cấp link NFC: `https://onelink.zalopay.vn/nfc_chatbot`
- Sau khi xác thực thành công, thực hiện lại giao dịch.
- Nếu không có CCCD gắn chip: nhấn nút

### E.1b - NFC thất bại (cần thu thập thông tin)
- Yêu cầu khách hàng cung cấp:
- Ảnh chụp màn hình thông báo lỗi khi quét NFC (bắt buộc).
- Mô tả: có quét được không, nội dung lỗi, đã thử bao nhiêu lần.
- **Không xử lý tiếp nếu chưa nhận được ảnh chụp màn hình lỗi.**

### E.1c - Lỗi kỹ thuật NFC
- Hướng dẫn: **Tài khoản → Xác thực sinh trắc học → NFC**.
- Yêu cầu: App Zalopay ≥ 10.20 (Android) / 10.17 (iOS). CCCD gắn chip 12 số. NFC bật trong cài đặt.
- Sau 5 lần thất bại, hệ thống tự hiển thị tùy chọn xác thực qua VNeID.

### E.1d - Đang chờ xét duyệt ảnh NFC
- Thời gian xét duyệt: **trong vòng 24 giờ**. Thử lại giao dịch sau khi được duyệt.

---

## E.2 - Khuôn mặt

### E.2a - Cần xác thực khuôn mặt
- Hướng dẫn: **Trung tâm bảo mật → Bảo mật giao dịch → Chọn giao dịch → Xác thực → Chụp khuôn mặt**.
- Link: `https://social.zalopay.vn/spa/v2/security-center/home`
- Sau xác thực thành công, thực hiện lại giao dịch.

### E.2b - Chưa hoàn tất xác thực khuôn mặt
- Thực hiện lại giao dịch và hoàn tất xác thực khuôn mặt theo yêu cầu hệ thống.

### E.2c - Xác thực khuôn mặt thất bại
- Hướng dẫn: nơi đủ sáng, không ngược sáng. Tháo khẩu trang, kính râm, mũ. Lau sạch camera. Giữ điện thoại ngang tầm mắt, nhìn thẳng, giữ yên 2–3 giây.
- **Ràng buộc: Phương thức xác thực do hệ thống tự đánh giá, không thể thay đổi theo yêu cầu.** Không hứa hẹn hỗ trợ đổi phương thức.

---

## E.3 - Định danh (eKYC)

### E.3a - Chưa hoàn tất định danh
- Cách 1: Thực hiện lại giao dịch → làm theo hướng dẫn định danh trong luồng.
- Cách 2: Vào link `https://onelink.zalopay.vn/nfc_chatbot`
- Không thoát ra khi đang định danh.

### E.3b - Cần cập nhật định danh (đổi giấy tờ)
- Link cập nhật: `https://onelink.zalopay.vn/eKYC_CS`
- Chỉ hỗ trợ đổi giấy tờ cũ sang mới (CMND → CCCD gắn chip). Không cập nhật sang thông tin người khác. Ảnh rõ nét, đủ sáng. Thông tin phải khớp thông tin đã đăng ký.

### E.3c - Hệ thống tạm dừng, cần định danh
- Vào **Cá nhân** (góc dưới bên phải).
- Tìm banner
- Nhấn → chọn
- Sau định danh thành công, **chờ 24 giờ** rồi thử lại giao dịch.

### E.3d - Đang chờ xét duyệt định danh
- Thời gian xét duyệt: **trong vòng 24 giờ**. Thử lại giao dịch sau khi được duyệt.

---

## E.4 - OTP

### E.4a - Chưa nhập / Hết hạn SMS OTP
- Thực hiện lại giao dịch sau **15 phút**.
- Nhập đúng 6 số trong tin nhắn **mới nhất** trong vòng 3–5 phút. Không nhấn

### E.4b - Smart OTP không khớp
- Thực hiện lại giao dịch → nhập mật khẩu thanh toán (6 số).
- Màn hình hiển thị mã Smart OTP (6 số màu xanh).
- Nhập chính xác 6 số đó vào ô bên dưới → nhấn **Hoàn tất giao dịch**.
- Nếu quên mật khẩu thanh toán: chọn
