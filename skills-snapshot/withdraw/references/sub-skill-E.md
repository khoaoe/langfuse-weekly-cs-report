---
name: withdraw/sub-skill-E
description: Xử lý giao dịch rút tiền thất bại do xác thực (`transstatus` là `-365`, `-6038`)
---

## Tool bổ sung
Không cần gọi thêm tool.

---

## Kịch bản & Hướng dẫn

### E1 - Phân biệt nguyên nhân xác thực theo step result
- Step result `-1005` — Nguyên nhân: Xác thực sinh trắc học NFC không thành công — Cách xử lý: Hướng dẫn truy cập mục Tài khoản để hoàn thành xác thực sinh trắc học, sau đó thực hiện lại giao dịch. Nêu sẵn: nếu thực hiện NFC vẫn không thành công, vui lòng chụp ảnh lỗi hiển thị trên ứng dụng và phản hồi kèm mô tả để Zalopay kiểm tra chi tiết
- Step result `-1006` — Nguyên nhân: Tài khoản chưa xác thực NFC — Cách xử lý: Hướng dẫn quét CCCD gắn chip tại mục Tài khoản để hoàn thành xác thực, sau đó thực hiện lại giao dịch
- Step result `-1015` — Nguyên nhân: Chưa hoàn tất xác thực khuôn mặt theo yêu cầu hệ thống — Cách xử lý: Hướng dẫn thực hiện lại giao dịch và hoàn tất xác thực khuôn mặt khi hệ thống yêu cầu
- Step result `-1024` — Nguyên nhân: Thiết bị bị can thiệp hệ thống (root, jailbreak, mở khóa bootloader) — Cách xử lý: Hướng dẫn đăng nhập và sử dụng Zalopay trên thiết bị khác chưa từng bị can thiệp hệ thống
- Step result khác chưa có trong bảng, hoặc không có step result: chỉ xác nhận giao dịch không thành công, không tự suy đoán nguyên nhân. Không kịch bản nào trong nhóm E khớp yêu cầu của khách hàng: chuyển bộ phận chăm sóc khách hàng.
- Giao dịch thất bại do xác thực không trừ tiền, không đề cập hoàn tiền

### E2 - Khách hàng báo mất CCCD gắn chip, chưa làm lại
- Điều kiện: Sau khi được hướng dẫn xác thực NFC, khách hàng phản hồi mất CCCD gắn chip và chưa làm lại
- Phản hồi: Theo quy định của Ngân hàng Nhà nước, khách hàng cần xác thực sinh trắc học (NFC) trong quá trình sử dụng dịch vụ của Zalopay. Tính năng xác thực NFC yêu cầu Căn cước công dân gắn chip còn hiệu lực. Trường hợp khách hàng chưa có giấy tờ phù hợp, Zalopay hiện chưa thể hỗ trợ cập nhật sinh trắc học
- Hướng dẫn: liên hệ cơ quan chức năng để được cấp lại Căn cước công dân, sau đó thực hiện xác thực NFC lại để tránh gián đoạn khi sử dụng dịch vụ
- Không đề xuất phương án xác thực thay thế, không hướng dẫn thủ tục hoặc thời gian cấp lại Căn cước công dân
- Đây là câu trả lời về chính sách: không đưa block thông tin giao dịch vào phản hồi

### E3 - Khách hàng đòi hoàn tiền hoặc khẳng định mất tiền
- Điều kiện: Khách hàng yêu cầu hoàn tiền hoặc khẳng định đã bị trừ tiền trên giao dịch thất bại do xác thực
- Phản hồi: Giải thích giao dịch không thành công nên Zalopay không trừ tiền cho giao dịch này
- Hướng dẫn: kiểm tra mục Lịch sử giao dịch trên ứng dụng Zalopay để xác định giao dịch thực sự bị trừ tiền, sau đó gửi yêu cầu hỗ trợ cho đúng giao dịch đó để Zalopay kiểm tra
- Không tự suy đoán khoản tiền đã đi vào giao dịch nào
- Khách hàng vẫn khẳng định bị trừ tiền ở đúng giao dịch này: yêu cầu ảnh chụp màn hình trừ tiền hoặc sao kê ngân hàng. Lượt này chỉ yêu cầu ảnh, không chuyển bộ phận chăm sóc khách hàng.
- Follow-up: đã yêu cầu ảnh ở lượt trước và khách hàng đã cung cấp ảnh: chuyển bộ phận chăm sóc khách hàng
