---
name: bank-unlink/sub-skill-AD
description: Xử lý kịch bản thẻ/tài khoản ngân hàng đang được giữ liên kết trên một ví Zalopay khác, và kịch bản ví đó đã hết liên kết ngân hàng này nhưng khách hàng vẫn không liên kết lại được trên ví hiện tại.
---

## Tool bổ sung

**Ràng buộc riêng của nhóm này:** dữ liệu ở bước 7 của quy trình chính được tra trên một ví Zalopay khác ví đang gửi yêu cầu. **Không đưa block thông tin liên kết vào phản hồi**, không nêu số điện thoại kể cả đã che, không nêu họ tên, không nêu `user_id`, không nêu thời gian liên kết của ví đó. Chỉ được gọi là **một tài khoản Zalopay khác**.

Xác định kịch bản theo thứ tự sau.

1. **Nhóm A** (`binding_banks[]` của ví kia có phần tử trùng `bank_code`):
   - Khách hàng **không** nêu việc mất quyền truy cập ví đang giữ liên kết: thuộc **A1**, không gọi thêm tool.
   - Khách hàng nêu **mất SIM, mất số điện thoại, mất máy, quên mật khẩu, hoặc không đăng nhập được** ví đang giữ liên kết: gọi `get_user_kyc_profile` **hai lần trong cùng một lượt**, `identity_profile` là `true`:
     - lần một với `user_id` là **UserID của ticket**,
     - lần hai với `user_id` là giá trị `get_zalopay_id_by_phone` trả về ở bước 6 của quy trình chính.

     So sánh `Profile.identity_profile.full_name` của hai kết quả sau khi bỏ dấu, chuyển chữ thường và gom khoảng trắng thừa.
     - Hai giá trị **trùng nhau**: thuộc **A2**.
     - Hai giá trị **khác nhau**: thuộc **A3**.
     - Một trong hai lần gọi **không trả về** `full_name`: escalate CS.
2. **Nhóm D** (`binding_banks[]` của ví kia **không** có phần tử trùng `bank_code`): gọi `get_bank_linking_history` với `zalo_pay_id` là **UserID của ticket** (ví đang gửi yêu cầu), `bank_code` là mã đã xác định ở bước 6 của quy trình chính, `from` là ngày submit ticket trừ 6 ngày, `to` là ngày submit ticket, cả hai theo định dạng `yyyy-MM-dd`, `binding_trans_type` là `BINDING`, `page` là `0`, `size` là `20`.
   - `content[]` **có ít nhất một** bản ghi `error_code` bằng `-5040`: thuộc **D2**.
   - `content[]` **không có** bản ghi nào `error_code` bằng `-5040`, kể cả khi `content[]` rỗng: thuộc **D1**.
   - Tool lỗi hoặc không trả dữ liệu: escalate CS.

---

## Kịch bản & Hướng dẫn

### A1 - Vẫn còn liên kết trên ví khác, khách hàng còn truy cập được ví đó
- Điều kiện: `binding_banks[]` của ví kia có phần tử trùng `bank_code`, khách hàng không nêu việc mất quyền truy cập ví đó.
- Thông báo thẻ/tài khoản ngân hàng khách hàng muốn liên kết **đang được liên kết với một tài khoản Zalopay khác**. Nêu rõ mỗi thẻ/tài khoản ngân hàng chỉ liên kết được với một ví Zalopay tại một thời điểm.
- Hướng dẫn: đăng nhập tài khoản Zalopay đang giữ liên kết, vào **Tài khoản > Quản lý tài chính > Tài khoản/thẻ liên kết**, chọn ngân hàng cần huỷ, chọn **Huỷ liên kết** rồi **Xác nhận**. Sau khi huỷ thành công, thực hiện liên kết lại trên ví hiện tại.
- Báo trước: huỷ liên kết có thể làm thay đổi hạn mức thanh toán của ví đó, và ví không còn liên kết ngân hàng nào sẽ bị khoá trong vòng 30 ngày kể từ ngày huỷ liên kết cuối cùng theo quy định của Ngân hàng Nhà nước.
- Khách hàng cho biết không tự huỷ được: hướng dẫn hoàn tất định danh trên chính tài khoản Zalopay đó rồi gửi yêu cầu hỗ trợ từ tài khoản đó.

### A2 - Vẫn còn liên kết trên ví khác, khách hàng không truy cập được ví đó, họ tên định danh trùng khớp
- Điều kiện: khách hàng nêu mất SIM, mất số điện thoại, mất máy, quên mật khẩu, hoặc không đăng nhập được ví đang giữ liên kết; `full_name` của hai ví trùng nhau.
- Thông báo Zalopay có thể hỗ trợ huỷ liên kết trên tài khoản Zalopay đang giữ liên kết sau khi xác minh chứng từ.
- Yêu cầu khách hàng gửi **ảnh chụp Căn cước công dân bản gốc, đủ hai mặt, thấy rõ bốn góc, chụp trực tiếp từ bản gốc, không dùng bản scan hoặc ảnh chụp lại** của chủ thẻ/tài khoản.
- Lượt phản hồi tiếp theo trong cùng ticket: escalate CS, không tự đánh giá ảnh, không xin lại chứng từ.

### A3 - Vẫn còn liên kết trên ví khác, họ tên định danh không trùng khớp
- Điều kiện: `full_name` của ví đang gửi yêu cầu và `full_name` của ví đang giữ liên kết khác nhau.
- Thông báo Zalopay chưa thể hỗ trợ huỷ liên kết vì thông tin định danh của người gửi yêu cầu không trùng với chủ tài khoản Zalopay đang giữ liên kết.
- **Không nêu họ tên của bất kỳ ví nào, không nêu điểm khác nhau giữa hai họ tên, không nêu bất kỳ thông tin nào của ví đang giữ liên kết.**
- Hướng dẫn khách hàng liên hệ tổng đài **1900545436**, chọn nhánh **1** rồi nhánh **4**, để được xác minh trực tiếp.

### D1 - Ví kia đã hết liên kết ngân hàng này, lịch sử liên kết không có mã lỗi -5040
- Điều kiện: `binding_banks[]` của ví kia không có phần tử trùng `bank_code`, và `content[]` của `get_bank_linking_history` không có bản ghi `error_code` bằng `-5040`.
- Thông báo Zalopay đã kiểm tra và tài khoản Zalopay trước đó **hiện không còn liên kết** ngân hàng khách hàng nêu. Gọi đúng tên ngân hàng đã xác nhận từ tool.
- Hướng dẫn khách hàng kiểm tra lại và thực hiện liên kết ngân hàng đó trên tài khoản Zalopay hiện tại.
- Khách hàng cho biết vẫn liên kết không thành công sau khi thử lại: đề nghị gửi ảnh chụp màn hình báo lỗi để Zalopay kiểm tra tiếp.

### D2 - Ví kia đã hết liên kết ngân hàng này, lịch sử liên kết có mã lỗi -5040
- Điều kiện: `content[]` của `get_bank_linking_history` có ít nhất một bản ghi `error_code` bằng `-5040`.
- Escalate CS. Cần bộ phận nghiệp vụ làm việc với ngân hàng.
- Không nêu nguyên nhân dưới bất kỳ hình thức nào, kể cả cách diễn đạt chung như "lỗi hệ thống", "lỗi kỹ thuật", hay "lỗi từ phía ngân hàng".
