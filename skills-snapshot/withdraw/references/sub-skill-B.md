---
name: withdraw/sub-skill-B
description: Xử lý giao dịch rút tiền thành công nhưng khách hàng báo ngân hàng chưa nhận được tiền
---

## Tool bổ sung
Gọi `get_bank_name` để hiển thị tên ngân hàng.

---

## Kịch bản & Hướng dẫn

### B1 - Chưa quá thời gian nhận tiền
- Điều kiện: Giao dịch **thành công** và tính từ thời điểm giao dịch đến hiện tại **chưa quá 3 ngày làm việc**
- Phản hồi: Xác nhận giao dịch rút tiền thành công, tiền đã được chuyển đến ngân hàng
- Nêu thời gian nhận tiền phía ngân hàng:
- Rút về tài khoản ngân hàng: chậm nhất **24 giờ làm việc**.
- Rút về thẻ Visa/MasterCard Debit: **3 ngày làm việc** (không tính thứ Bảy, Chủ Nhật, ngày Lễ).
- Hướng dẫn: kiểm tra sao kê hoặc biến động số dư ngân hàng sau đúng thời gian trên. Nêu sẵn: nếu quá thời gian trên vẫn chưa nhận được tiền, vui lòng cung cấp ảnh sao kê ngân hàng (biến động số dư hoặc lịch sử giao dịch) từ ngày thực hiện giao dịch đến hiện tại để Zalopay tra soát

### B2 - Đã quá thời gian nhận tiền
- Điều kiện: Giao dịch **thành công** và tính từ thời điểm giao dịch đến hiện tại **đã quá 3 ngày làm việc**
- Phản hồi: Xác nhận giao dịch rút tiền thành công và đã quá thời gian ngân hàng cập nhật tiền, Zalopay sẽ tra soát chi tiết với ngân hàng
- Yêu cầu khách hàng cung cấp ảnh sao kê ngân hàng (biến động số dư hoặc lịch sử giao dịch) từ ngày thực hiện giao dịch đến hiện tại

### B3 - Khách hàng quay lại vẫn báo chưa nhận
- Điều kiện: Đã từng trả lời case này theo B1 hoặc B2 (đã từng yêu cầu ảnh sao kê), khách hàng quay lại vẫn báo chưa nhận được tiền
- Chuyển bộ phận chăm sóc khách hàng để đối soát trực tiếp với ngân hàng. Không yêu cầu ảnh lần thứ hai — nếu khách hàng đã gửi ảnh ở lượt trước, đối soát dựa trên ảnh đó

### B4 - Follow-up trong hạn chờ: phàn nàn, đòi hủy, hoặc hỏi mã để tự liên hệ ngân hàng
- Điều kiện: Giao dịch **thành công**, **chưa quá** hạn nhận tiền (24 giờ làm việc với tài khoản ngân hàng, 3 ngày làm việc với thẻ Visa/MasterCard Debit), khách hàng quay lại phàn nàn về thời gian chờ, yêu cầu huỷ/hoàn ngay, hoặc hỏi mã giao dịch để tự liên hệ ngân hàng
- Yêu cầu huỷ/hoàn: giải thích tiền đã chuyển sang ngân hàng nên không thể huỷ hoặc thu hồi
- Xác nhận lại mốc thời gian chờ theo đúng loại tài khoản/thẻ của giao dịch. Xác định được tên ngân hàng: nêu rõ đây là thời hạn xử lý chuẩn
- Không yêu cầu khách hàng tự tra cứu trên web/ứng dụng ngân hàng, không yêu cầu sao kê ở bước này, không escalate
- Đã quá hạn nhận tiền: không dùng kịch bản này, xử lý theo B2

### B5 - Khách hàng hỏi mã để đối chiếu với ngân hàng
- Điều kiện: Giao dịch thành công, khách hàng hỏi mã giao dịch, mã tra soát hoặc mã chuẩn chi để tự kiểm tra hoặc làm việc với ngân hàng
- Phản hồi: xác nhận giao dịch đã thành công, nhờ khách hàng vui lòng chờ hết thời gian trên (không nêu chính xác cho khách hàng là 24 giờ hay 3 ngày) rồi kiểm tra lại
- Nêu rõ với giao dịch rút tiền này, Zalopay hiện chưa hỗ trợ mã kiểm tra với ngân hàng
- Nêu: trường hợp khách hàng cần giấy báo có từ ngân hàng, phản hồi lại Zalopay để được hỗ trợ thêm
- Follow-up: khách hàng phản hồi yêu cầu giấy báo có: chuyển bộ phận chăm sóc khách hàng
