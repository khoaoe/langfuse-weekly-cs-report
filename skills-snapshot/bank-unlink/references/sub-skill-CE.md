---
name: bank-unlink/sub-skill-CE
description: Xử lý kịch bản khách hàng hỏi cách tự huỷ liên kết thẻ/tài khoản ngân hàng trong ứng dụng khi chưa nêu ngân hàng cụ thể và chưa nêu lỗi, và kịch bản khách hàng muốn huỷ liên kết tài khoản CIMB hoặc CAKE mở kèm sản phẩm tiết kiệm.
---

## Tool bổ sung
Không gọi tool. Cả hai kịch bản được xác định bằng phần **Điều kiện** của từng kịch bản dưới đây, chỉ dựa trên nội dung ticket.

**Ràng buộc riêng của nhóm này:** không đưa block thông tin liên kết vào phản hồi. Cả hai kịch bản đều trả lời về hướng dẫn thao tác hoặc chính sách, không về trạng thái liên kết của một thẻ/tài khoản cụ thể.

---

## Kịch bản & Hướng dẫn

### C1 - Hỏi cách tự huỷ liên kết
- Điều kiện: ticket không có tên ngân hàng ở field **Tên ngân hàng** lẫn trong **Mô tả**, và không có field **Số điện thoại Zalopay**.
- Hướng dẫn các bước tự huỷ liên kết trong ứng dụng: tại trang chủ Zalopay chọn **Tài khoản > Quản lý tài chính > Tài khoản/thẻ liên kết**, chọn ngân hàng cần huỷ, chọn **Huỷ liên kết** rồi **Xác nhận** và chờ trong giây lát.
- Báo trước: huỷ liên kết có thể làm thay đổi hạn mức thanh toán của ví, và ví không còn liên kết ngân hàng nào sẽ bị khoá trong vòng 30 ngày kể từ ngày huỷ liên kết cuối cùng theo quy định của Ngân hàng Nhà nước.
- Nếu khách hàng không tự huỷ được: đề nghị cung cấp lý do huỷ liên kết và ảnh chụp màn hình báo lỗi để Zalopay hỗ trợ kiểm tra tiếp.

### E2 - Huỷ liên kết tài khoản mở kèm sản phẩm tiết kiệm
- Điều kiện: tên ngân hàng khách hàng nêu **có** trong cột "Ngân hàng" của bảng dưới đây. Tên ngân hàng không có trong bảng: không thuộc kịch bản này, quay lại bước 4 của quy trình chính.

| Ngân hàng |
|---|
| CIMB |
| CAKE |

- Giải thích tài khoản thanh toán khách hàng đang thấy là tài khoản được mở nhằm phục vụ quá trình sử dụng tài khoản tiết kiệm tại Zalopay. Gọi đúng tên ngân hàng khách hàng nêu.
- Nêu rõ tài khoản tiết kiệm khi đóng sẽ không thể mở lại được.
- Nêu rõ việc duy trì tài khoản không mất phí và không phát sinh bất kỳ khoản chi phí nào.
- Hướng dẫn: nếu không có nhu cầu sử dụng, khách hàng chỉ cần tất toán các gói tiết kiệm; khi cần dùng lại, có thể nạp tiền để tiếp tục sử dụng.
- Mời khách hàng phản hồi để Zalopay cải thiện dịch vụ.
- Khách hàng vẫn yêu cầu huỷ liên kết sau khi đã được giải thích: escalate CS.
