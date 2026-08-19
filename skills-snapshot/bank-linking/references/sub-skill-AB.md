---
name: bank-linking/sub-skill-AB
description: Xử lý kịch bản thẻ/tài khoản đã liên kết với chính ví Zalopay của khách hàng, liên kết thất bại đã tra được nguyên nhân theo mã lỗi, và liên kết thất bại không tra được lịch sử liên kết.
---

## Tool bổ sung
Xác định nhóm theo thứ tự sau.

1. Ticket **đã có sẵn mã lỗi** khác `NONE` và bảng mã lỗi ở mục A2 có dòng khớp, **và** bước 7 của quy trình chính (`get_bank_linking_status`) **không** cho kết quả khớp nhóm A1: thuộc **A2**, trả lời theo đúng dòng đó, dùng tên ngân hàng đã xác nhận ở bước 6 nếu có. **Không cần gọi thêm `get_bank_linking_history`** — bước 5, 6, 7 của quy trình chính vẫn luôn thực hiện trước, mã lỗi chỉ thay cho việc phải tra `get_bank_linking_history`. Bước 6 trả `matched` là `false`, hoặc ticket không có tên ngân hàng: bỏ dòng tên ngân hàng trong phản hồi theo mục 6 của skill chính, **không escalate CS**.
2. Bước 7 của quy trình chính **có** kết quả khớp nhóm A1 (`binding_banks[]` khớp `bank_code` và `last_no`, hoặc khách không nêu số thẻ/tài khoản và `binding_banks[]` có phần tử trùng `bank_code`): thuộc **A1**, bỏ qua mã lỗi trong ticket dù có — mã lỗi đó có thể đã cũ, khách hàng đã liên kết thành công sau lần báo lỗi ban đầu. Không gọi thêm tool.
3. Còn lại (không khớp A1, không có mã lỗi khớp bảng): **bắt buộc gọi `get_bank_linking_history`**, lấy bản ghi có `created_at` lớn nhất.
   - Ticket có `trans_id` khác `0`: gọi theo chế độ `trans_id`, không kèm bất kỳ filter nào khác. Không trả về bản ghi nào thì gọi lại theo chế độ khoảng thời gian.
   - Chế độ khoảng thời gian: `zalo_pay_id` là UserID, `bank_code` là mã đã xác định ở quy trình chính, `binding_trans_type` là `BINDING`, `page` là `0`, `size` là `20`. Ticket **có** thời gian liên kết hoặc thời gian gặp lỗi thì `from` là ngày đó trừ 3 ngày, `to` là ngày nhỏ hơn giữa ngày đó cộng 3 ngày và ngày submit ticket. Ticket **không có** thời gian đó thì `from` là ngày submit ticket trừ 6 ngày, `to` là ngày submit ticket. Cả hai theo định dạng `yyyy-MM-dd`.
   - `error_code` của bản ghi đó có trong bảng mã lỗi ở mục A2: thuộc **A2**.
   - `error_code` của bản ghi đó **không có** trong bảng mã lỗi: escalate CS.
   - Không có bản ghi nào: thuộc **B1**.

---

## A - Khách hàng báo liên kết thất bại

### A1 - Thẻ/tài khoản đã liên kết thành công với chính ví Zalopay của khách hàng
- Xác nhận rõ: thẻ/tài khoản khách hàng muốn liên kết **đang được liên kết với chính tài khoản Zalopay của bạn**.
- Cung cấp block thông tin liên kết theo cấu trúc phản hồi, lấy từ phần tử khớp trong `binding_banks[]`.
- Hướng dẫn kiểm tra: **Tài khoản > Tài khoản/thẻ liên kết** trên ứng dụng Zalopay.
- Khách hàng hỏi **đang liên kết những ngân hàng nào**: liệt kê từng phần tử trong `binding_banks[]` theo dạng tên ngân hàng kèm bốn số cuối. `binding_banks[]` rỗng: báo hiện chưa ghi nhận liên kết nào, rồi xử lý theo phần hướng dẫn liên kết ở B1.
- Khách hàng vẫn báo gặp lỗi hoặc mô tả không rõ nhu cầu: xác nhận trạng thái đã liên kết, rồi đề nghị khách hàng mô tả cụ thể hơn và gửi ảnh chụp màn hình báo lỗi.
- Khách hàng nêu nhu cầu dùng thẻ đã liên kết cho **thanh toán tự động**: hướng dẫn khách hàng điều chỉnh thứ tự nguồn tiền trong ứng dụng. Thẻ đó là thẻ quốc tế Visa/Mastercard/JCB: thông báo dịch vụ thanh toán tự động hiện chưa hỗ trợ nguồn tiền thẻ quốc tế, hướng dẫn chọn nguồn tiền khác đang hiển thị.

### A2 - Liên kết thất bại, tra được nguyên nhân theo mã lỗi
- Mở đầu nội dung xử lý bằng câu: "Zalopay rất tiếc vì bạn liên kết ngân hàng không thành công." Sau đó nêu nguyên nhân đúng theo cột **Nguyên nhân** của dòng khớp trong bảng dưới đây, không diễn đạt thành nguyên nhân khác.
- Hướng xử lý theo cột **Hướng dẫn cho khách hàng** của chính dòng đó.
- Không ghép nguyên nhân của nhiều mã lỗi vào một câu trả lời.
- **Bảng mã lỗi liên kết.** **Kẹp nhánh bằng `error_code`, không kẹp bằng `error_code_enum`.** `error_code` là số, ổn định giữa các nguồn. Cột `error_code_enum` chỉ để đối chiếu; mã nào có nhiều biến thể tên thì liệt kê đủ trong cột đó, khớp biến thể nào cũng tính là khớp.
| `error_code` | `error_code_enum` | Nguyên nhân | Hướng dẫn cho khách hàng |
|---|---|---|---|
| `-10325` | `BM_CARD_LINKED` | Thẻ/tài khoản đã liên kết thành công với chính tài khoản Zalopay này | Xử lý theo A1. |
| `-5029` | `BANK_CARD_NOT_REGISTERED_ONLINE_PAYMENT` | Thẻ hoặc tài khoản chưa đăng ký dịch vụ thanh toán trực tuyến | Liên hệ ngân hàng đăng ký dịch vụ thanh toán trực tuyến, sau đó thực hiện lại. Khách hàng vừa chuyển từ thẻ từ sang thẻ chip: hướng dẫn đăng ký lại dịch vụ thanh toán trực tuyến tại ứng dụng ngân hàng hoặc tại ATM. |
| `-5033` | `BANK_INACTIVE_CARD` | Thẻ không hoạt động | Liên hệ ngân hàng phát hành thẻ để được hỗ trợ, sau đó thực hiện lại. Ngân hàng là BIDV: bổ sung thông tin từ ngày 08/12/2024 BIDV đã tạm ngưng hỗ trợ thẻ Từ và chuyển sang thẻ Chip, hướng dẫn liên hệ ngân hàng đổi sang thẻ Chip rồi huỷ liên kết thẻ Từ và liên kết lại. |
| `-5038` | `BANK_INVALID_ACCOUNT_OR_CARD_INFO`, `BANK_CARD_INFO_INVALID` | Thẻ/tài khoản không hợp lệ: số thẻ, số tài khoản, tên chủ thẻ, hoặc ngày phát hành thẻ không đúng; hoặc thẻ/tài khoản chưa được kích hoạt; hoặc thẻ từ bị khoá | Kiểm tra lại số thẻ hoặc số tài khoản, tên chủ thẻ, ngày phát hành thẻ, rồi nhập lại. Đã nhập đúng mà vẫn lỗi: liên hệ ngân hàng phát hành thẻ. |
| `-5039` | `BANK_ACCOUNT_OR_CARD_NOT_FOUND` | Không tìm thấy thông tin thẻ hoặc tài khoản | Liên hệ ngân hàng đang sử dụng để kiểm tra lại thông tin thẻ/tài khoản, sau đó thực hiện lại vào thời điểm khác. |
| `-5040` | `BANK_ACCOUNT_OR_CARD_ALREADY_LINKED` | Thẻ/tài khoản đang được liên kết | Đối chiếu với `binding_banks[]`: có phần tử khớp thì xử lý theo A1. Không có phần tử nào khớp: escalate CS. |
| `-5041` | `BANK_CARD_OR_ACCOUNT_INVALID_STATE`, `BANK_CARD_INVALID_STATE` | Thẻ/tài khoản ở trạng thái không giao dịch được | Liên hệ ngân hàng phát hành để được hỗ trợ, sau đó thực hiện lại — có thể tìm kênh liên hệ ngân hàng ở mặt sau thẻ. Khách hàng vừa chuyển từ thẻ từ sang thẻ gắn chip: hướng dẫn huỷ liên kết thẻ cũ trên Zalopay (Tài khoản > Nguồn tiền > chọn thẻ cần huỷ > kéo xuống cuối màn hình > Hủy liên kết) rồi liên kết lại. |
| `-5042` | `BANK_CARD_OR_ACCOUNT_HAS_BEEN_LOCKED`, `BANK_ACCOUNT_LOCKED` | Thẻ/tài khoản ngân hàng đã bị khoá | Liên hệ ngân hàng phát hành để kiểm tra nguyên nhân và mở khoá. Sau khi được mở khoá, thực hiện liên kết lại. |
| `-5084` | `BANK_3DS_VALIDATION_FAILED`, `BANK_3DS_VALIDATION_FAIL` | Giao dịch chưa xác nhận OTP từ phía ngân hàng | Kiểm tra dịch vụ bảo mật thanh toán trực tuyến 3D Secure của thẻ có đang hoạt động không, và nhập đúng mã OTP. Thẻ vẫn hoạt động bình thường mà không thực hiện được: liên hệ trực tiếp ngân hàng. |
| `-5092` | `BANK_INVALID_IDENTITY_INFO` | Số chứng minh thư, căn cước, hoặc hộ chiếu không trùng khớp với thông tin đăng ký tại ngân hàng | Cập nhật thông tin giấy tờ trên Zalopay hoặc tại ngân hàng cho trùng khớp nhau, sau đó liên kết lại. |
| `-5207` | `BANK_USER_HAS_NOT_BEEN_REGISTER_SMS` | Khách hàng chưa đăng ký dịch vụ SMS tại ngân hàng | Liên hệ ngân hàng phát hành đăng ký dịch vụ SMS Banking. `bank_code` xác nhận ở bước 6 của quy trình chính là Vietcombank (`ZPVCB`): nói rõ có thể đăng ký SMS Banking hoặc VCB Digibank. `bank_code` là ngân hàng khác, hoặc chưa xác nhận được (bước 6 không chạy): chỉ nói SMS Banking, bỏ hẳn cụm "hoặc VCB Digibank". Khách hàng đã đăng ký bằng số điện thoại khác: đổi số điện thoại Zalopay cho trùng với số đã đăng ký tại ngân hàng, hoặc đến quầy giao dịch ngân hàng đổi số cho trùng với số trên Zalopay. |
| `-5217` | `BANK_WALLET_ACCOUNT_ALREADY_LINKED` | Tài khoản ví đã được liên kết | Đối chiếu với `binding_banks[]`: có phần tử khớp thì xử lý theo A1. Không có phần tử nào khớp: thông báo thẻ/tài khoản này đang được liên kết với một tài khoản Zalopay khác, hướng dẫn khách hàng huỷ liên kết tại tài khoản đó rồi liên kết lại. Khách hàng không truy cập được tài khoản đó: escalate CS. |
| `-5219` | `BANK_USER_HAS_NOT_BEEN_REGISTER_EBANK`, `User ebank not found` | Khách hàng chưa đăng ký dịch vụ Internet Banking hoặc Ebank | Liên hệ ngân hàng đăng ký dịch vụ Internet Banking và dịch vụ Thanh toán trực tuyến, sau đó thực hiện lại. |
- `error_code` **không có trong bảng này**: escalate CS. Không nêu nguyên nhân dưới bất kỳ hình thức nào, kể cả cách diễn đạt chung như "lỗi hệ thống", "lỗi kỹ thuật", hay "lỗi từ phía ngân hàng".

---

## B - Không tra được lịch sử liên kết

### B1 - Không tra được lịch sử liên kết
- Điều kiện: `get_bank_linking_history` không trả về bản ghi nào, và `binding_banks[]` không có phần tử nào khớp ngân hàng khách hàng nêu.
- Không nêu bất kỳ nguyên nhân nào. Không dùng cách diễn đạt chung như "lỗi hệ thống", "lỗi kỹ thuật", "lỗi từ phía ngân hàng".
- Thông báo Zalopay chưa ghi nhận được thao tác liên kết với ngân hàng khách hàng nêu, và đề nghị khách hàng gửi **ảnh chụp màn hình báo lỗi** để Zalopay kiểm tra và hỗ trợ tiếp.
- Khách hàng cho biết đã bỏ hoặc không còn dùng thẻ/tài khoản của ngân hàng đó: hướng dẫn sử dụng thẻ/tài khoản của ngân hàng khác để liên kết.
- Khách hàng hỏi cách liên kết, hoặc `binding_banks[]` rỗng: nêu điều kiện và các bước liên kết.
- Điều kiện: thẻ hoặc tài khoản ngân hàng đã đăng ký dịch vụ Internet Banking và thanh toán trực tuyến, và số điện thoại đăng ký tại ngân hàng trùng với số điện thoại đăng ký Zalopay.
- Thao tác: **Tài khoản > Tài khoản/thẻ liên kết**, chọn thêm thẻ/tài khoản, chọn ngân hàng, nhập thông tin thẻ hoặc số tài khoản, rồi xác thực OTP.
