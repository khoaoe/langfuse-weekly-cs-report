---
name: interbank-fund-transfer/sub-skill-A
description: Xử lý kịch bản giao dịch thành công nhưng người nhận chưa thấy tiền vào tài khoản.
---

## Tool bổ sung
Không cần gọi thêm tool.

---

## Kịch bản & Hướng dẫn

### A1 - Có mã chuẩn chi
- Cung cấp đầy đủ: mã giao dịch, mã chuẩn chi (nếu có), số tiền, tên ngân hàng, 4 số cuối.
- Hướng dẫn người nhận mang mã chuẩn chi đến ngân hàng để tra soát.
- Kiểm tra nếu giao dịch có quá 24 giờ chưa:
- - Nếu chưa: Phản hồi một số ngân hàng có thể cập nhật chậm, vui lòng nhờ người nhận kiểm tra lại sau 24 giờ
- - Nếu đã quá 24 giờ: Nhờ khách hàng gửi lại sao kê/lịch sử giao dịch của người nhận để Zalopay hỗ trợ tra soát
- SLA tra soát: 3-5 ngày làm việc, không bao gồm Thứ 7, Chủ Nhật và ngày lễ.
- Sau khi khách hàng gửi lại sao kê/lịch sử giao dịch, chuyển cho bộ phận CSKH để hỗ trợ thêm

### A4 - Không bị lừa đảo và có thông tin 'hỗ trợ thu hồi giao dịch chuyển khoản nhầm'
- Cung cấp: mã giao dịch, số tiền, trạng thái, tên ngân hàng, 4 số cuối.
- Xác nhận trạng thái: **Đã gửi công văn đến ngân hàng**.
- Thời gian xử lý: **45–60 ngày làm việc** (không tính T7, CN, ngày lễ).
- Nếu thu hồi thành công: Zalopay thông báo ngay cho khách hàng.
- Sau 60 ngày không có thông tin: ngân hàng không thu hồi được — hướng dẫn liên hệ trực tiếp ngân hàng nhận.
- Nếu người nhận có dấu hiệu lừa đảo: hướng dẫn liên hệ cơ quan chức năng. Zalopay phối hợp cung cấp thông tin khi được cơ quan chức năng yêu cầu.

### A5 - Bị lừa đảo và yêu cầu **hỗ trợ thu hồi giao dịch chuyển khoản nhầm**
- Điều kiện: khách tự nêu rõ trong tin nhắn là muốn **thu hồi/yêu cầu lấy lại tiền đã chuyển** (không chỉ mô tả bị lừa hoặc muốn "hoàn tiền" chung).
- Ví dụ khớp A5: "Tôi bị lừa chuyển khoản, nhờ Zalopay **thu hồi lại giao dịch** giúp tôi."
- Cung cấp: mã giao dịch, số tiền, trạng thái, tên ngân hàng, 4 số cuối.
- Zalopay không thể huỷ giao dịch được vì đã giao dịch đã thành công, người nhận đã nhận tiền
- Zalopay có thể hỗ trợ gửi công văn đến ngân hàng
- Thời gian xử lý: **45–60 ngày làm việc** (không tính T7, CN, ngày lễ).
- Nếu thu hồi thành công: Zalopay thông báo ngay cho khách hàng.
- Sau 60 ngày không có thông tin: ngân hàng không thu hồi được — hướng dẫn liên hệ trực tiếp ngân hàng nhận.
- Nếu người nhận có dấu hiệu lừa đảo: hướng dẫn liên hệ cơ quan chức năng. Zalopay phối hợp cung cấp thông tin khi được cơ quan chức năng yêu cầu.

### A6 - Bị lừa đảo và **không** yêu cầu **hỗ trợ thu hồi giao dịch chuyển khoản nhầm**
- Điều kiện: khách chỉ mô tả tình huống/nghi ngờ bị lừa đảo, hoặc muốn "hoàn tiền"/"lấy lại tiền" nhưng **chưa** nói rõ ý muốn thu hồi giao dịch. Tiêu đề ticket boilerplate (vd: "Nhờ Zalopay hỗ trợ thu hồi giao dịch chuyển khoản nhầm") không tính là xác nhận.
- Ví dụ khớp A6: "Tôi nghi ngờ là lừa đảo nên muốn hoàn tiền, người bán không phản hồi lại tôi." (chưa xác nhận rõ muốn thu hồi)
- Cung cấp: mã giao dịch, số tiền, trạng thái, tên ngân hàng, 4 số cuối.
- Zalopay không thể huỷ giao dịch được vì đã giao dịch đã thành công, người nhận đã nhận tiền
- Hướng xử lý: Zalopay có thể gửi công văn đến ngân hàng để hỗ trợ thu hồi. Bạn có muốn xác nhận thu hồi không?
- Nếu khách xác nhận "có" ở lượt sau: chuyển sang xử lý theo **A5** (Thời gian xử lý 45–60 ngày làm việc, không tính T7, CN, ngày lễ).
- Nếu người nhận có dấu hiệu lừa đảo: hướng dẫn liên hệ cơ quan chức năng. Zalopay phối hợp cung cấp thông tin khi được cơ quan chức năng yêu cầu.

### A7 - Bị lừa đảo và yêu cầu **Assistance with recalling mistaken transfers**
- Điều kiện: khách tự nêu rõ trong tin nhắn là **Assistance with recalling mistaken transfers**
- Cung cấp: mã giao dịch, số tiền, trạng thái, tên ngân hàng, 4 số cuối.
- Xác nhận trạng thái: **Đã gửi công văn đến ngân hàng**.
- Thời gian xử lý: **45–60 ngày làm việc** (không tính T7, CN, ngày lễ).
- - Nếu thu hồi thành công: Zalopay thông báo ngay cho khách hàng.
- - Sau 60 ngày không có thông tin: ngân hàng không thu hồi được — hướng dẫn liên hệ trực tiếp ngân hàng nhận.
- Nếu người nhận có dấu hiệu lừa đảo: hướng dẫn liên hệ cơ quan chức năng. Zalopay phối hợp cung cấp thông tin khi được cơ quan chức năng yêu cầu.

### A8 - Không bị lừa đảo và yêu cầu **Assistance with recalling mistaken transfers**
- Điều kiện: khách tự nêu rõ trong tin nhắn là **Assistance with recalling mistaken transfers**
- Cung cấp: mã giao dịch, số tiền, trạng thái, tên ngân hàng, 4 số cuối.
- Xác nhận trạng thái: **Đã gửi công văn đến ngân hàng**.
- Thời gian xử lý: **45–60 ngày làm việc** (không tính T7, CN, ngày lễ).
- Nếu thu hồi thành công: Zalopay thông báo ngay cho khách hàng.
- Sau 60 ngày không có thông tin: ngân hàng không thu hồi được — hướng dẫn liên hệ trực tiếp ngân hàng nhận.
- Nếu người nhận có dấu hiệu lừa đảo: hướng dẫn liên hệ cơ quan chức năng. Zalopay phối hợp cung cấp thông tin khi được cơ quan chức năng yêu cầu.
