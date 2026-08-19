---
name: bank-unlink/sub-skill-B
description: Xử lý kịch bản khách hàng yêu cầu huỷ liên kết thẻ/tài khoản ngân hàng trên chính ví Zalopay đang gửi yêu cầu, gồm huỷ liên kết đang gặp lỗi, huỷ liên kết chưa từng thao tác, và ngân hàng khách hàng nêu không nằm trong danh sách đang liên kết.
---

## Tool bổ sung

Dữ liệu ở bước 7 của quy trình chính đã tra trên chính ví đang gửi yêu cầu. Xác định kịch bản theo thứ tự sau.

1. `binding_banks[]` **không có** phần tử nào mà `bank_code` trùng `bank_code` xác định ở bước 6 của quy trình chính: thuộc **B3**, **không gọi thêm tool**.
2. `binding_banks[]` **có** phần tử trùng: gọi `get_bank_unlink_history` với `zalo_pay_id` là **UserID của ticket**, `bank_code` là mã đã xác định ở bước 6, `binding_trans_type` gồm `UNBINDING`, `UNBIND_BANK_TOKEN`, `FORCE_UNBINDING_ALL_BANKS`, `page` là `0`, `size` là `20`. Khoảng thời gian, định dạng `yyyy-MM-dd`:
   - Ticket **có** field **Thời gian gặp lỗi**: `from` là ngày đó trừ 3 ngày, `to` là ngày nhỏ hơn giữa ngày đó cộng 3 ngày và ngày hiện tại.
   - Ticket **không có** field đó: `from` là ngày submit ticket trừ 6 ngày, `to` là ngày hiện tại.

   Xử lý kết quả, chỉ xét **bản ghi có `created_at` lớn nhất**:
   - `error_code` của bản ghi đó **có** trong bảng mã lỗi ở B1: thuộc **B1**, xử lý theo đúng dòng khớp.
   - `error_code` của bản ghi đó **không có** trong bảng mã lỗi ở B1: escalate CS.
   - Không có bản ghi nào: thuộc **B2**.
   - Tool lỗi hoặc không trả dữ liệu: escalate CS.

---

## Kịch bản & Hướng dẫn

### B1 - Đang liên kết, thao tác huỷ liên kết ghi nhận mã lỗi
- Điều kiện: `binding_banks[]` có phần tử trùng `bank_code`, và `error_code` của bản ghi huỷ liên kết mới nhất có trong bảng dưới đây.
- **Kẹp nhánh bằng `error_code`, không kẹp bằng tên trạng thái hay chuỗi mô tả.** `error_code` là số, ổn định giữa các nguồn.

| `error_code` | Xử lý |
|---|---|
| `-5206` | Escalate CS. Không tự hướng dẫn tiếp, không nêu nguyên nhân. |

- `error_code` **không có trong bảng này**: escalate CS. Không nêu nguyên nhân dưới bất kỳ hình thức nào, kể cả cách diễn đạt chung như "lỗi hệ thống", "lỗi kỹ thuật", hay "lỗi từ phía ngân hàng".

### B2 - Đang liên kết, chưa ghi nhận thao tác huỷ liên kết nào
- Điều kiện: `binding_banks[]` có phần tử trùng `bank_code`, và `get_bank_unlink_history` không trả về bản ghi nào.
- Cung cấp block thông tin liên kết theo cấu trúc phản hồi, lấy từ phần tử khớp trong `binding_banks[]`.
- Hướng dẫn khách hàng tự huỷ liên kết trong ứng dụng: **Tài khoản > Quản lý tài chính > Tài khoản/thẻ liên kết**, chọn ngân hàng cần huỷ, chọn **Huỷ liên kết** rồi **Xác nhận** và chờ trong giây lát.
- Báo trước: huỷ liên kết có thể làm thay đổi hạn mức thanh toán của ví, và ví không còn liên kết ngân hàng nào sẽ bị khoá trong vòng 30 ngày kể từ ngày huỷ liên kết cuối cùng theo quy định của Ngân hàng Nhà nước.
- Nếu sau khi huỷ, khách hàng gặp thông báo không đủ hạn mức thanh toán: hướng dẫn liên kết thêm một tài khoản ATM để nâng hạn mức trở lại.
- Khách hàng cho biết không tự huỷ được: đề nghị cung cấp lý do huỷ liên kết và ảnh chụp màn hình báo lỗi để Zalopay hỗ trợ kiểm tra tiếp.

### B3 - Ví hiện tại không liên kết ngân hàng khách hàng nêu
- Điều kiện: `binding_banks[]` không có phần tử nào trùng `bank_code`.
- Thông báo tài khoản Zalopay hiện tại **đang không liên kết** ngân hàng khách hàng nêu. Gọi đúng tên ngân hàng đã xác nhận từ tool.
- Khách hàng hỏi **đang liên kết những ngân hàng nào**: liệt kê từng phần tử trong `binding_banks[]` theo dạng tên ngân hàng kèm bốn số cuối của `last_no`.
- `binding_banks[]` rỗng: báo tài khoản Zalopay hiện tại chưa ghi nhận liên kết ngân hàng nào.
- Khách hàng khẳng định đã liên kết ngân hàng đó: đề nghị gửi ảnh chụp màn hình mục **Tài khoản/thẻ liên kết** để Zalopay kiểm tra tiếp.
