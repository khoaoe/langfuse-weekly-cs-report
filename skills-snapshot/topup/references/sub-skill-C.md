---
name: topup/sub-skill-C
description: Xử lý giao dịch nạp tiền thất bại có `transstatus` là `-217`
---

## Tool bổ sung
Bắt buộc gọi `lookup_refund_details_by_transaction_id` để lấy thời gian và nguồn hoàn tiền hoàn về.

---

## Kịch bản & Hướng dẫn

### C1 - `step_result` là `-3155` và khách hàng bị trừ tiền ở ngân hàng
- Phản hồi: Giao dịch thất bại do bạn chưa hoàn thành xác thực tại ứng dụng/website của ngân hàng
- Trường hợp giao dịch không thành công nhưng tài khoản ngân hàng đã bị trừ tiền, trong vòng 1-3 ngày làm việc (không bao gồm T7, CN và ngày Lễ), Zalopay và ngân hàng sẽ tra soát giao dịch:
- Nếu hệ thống Zalopay đã nhận được tiền, số tiền sẽ được cộng vào số dư tài khoản Zalopay của bạn.
- Nếu Zalopay chưa nhận được tiền, số tiền sẽ được hoàn về tài khoản ngân hàng của bạn (thời gian hoàn tiền tuỳ thuộc vào quy định của ngân hàng).

### C2 - Giao dịch thất bại, không có hoàn tiền
- Điều kiện: Không có giao dịch hoàn tiền
- Dựa vào `return_code` để xác định nguyên nhân và hướng khắc phục tương ứng
- Phản hồi: Giao dịch thất bại, nguyên nhân thất bại, hướng khắc phục
- Trong trường hợp không tìm được `return_code` trong bảng, chỉ phản hồi giao dịch thất bại, không tự suy đoán nguyên nhân thất bại
- Nếu khách hàng hỏi vì sao không được hoàn tiền, phản hồi: Trường hợp giao dịch không thành công nhưng tài khoản ngân hàng đã bị trừ tiền, trong vòng 1-3 ngày làm việc (không bao gồm T7, CN và ngày Lễ), Zalopay và ngân hàng sẽ tra soát giao dịch:
- Nếu hệ thống Zalopay đã nhận được tiền, số tiền sẽ được cộng vào số dư tài khoản Zalopay của bạn.
- Nếu Zalopay chưa nhận được tiền, số tiền sẽ được hoàn về tài khoản ngân hàng của bạn (thời gian hoàn tiền tuỳ thuộc vào quy định của ngân hàng).
| Mã lỗi | Nguyên nhân | Hướng phản hồi & khắc phục |
|---|---|---|
| -5025 | Tài khoản ngân hàng không đủ số dư | Kiểm tra số dư TKNH (lưu ý số dư tối thiểu duy trì 50.000 - 100.000đ sau khi thanh toan). Nạp tiền và thử lại. Giao dịch này không bị trừ tiền, vui lòng gửi yêu cầu từ giao dịch bị trừ tiền. |
| -5223 | Chưa xác thực sinh trắc học (NFC) tại ngân hàng | Hướng dẫn xác thực sinh trắc học tại app ngân hàng hoặc quầy giao dịch. Cung cấp hotline ngân hàng. |
| -5031 | Thẻ hết hạn sử dụng | Liên hệ ngân hàng kiểm tra. Nếu thẻ vừa gia hạn/thay đổi thì liên kết lại. Cung cấp hotline ngân hàng. |
| -3055 | Không nhập mã OTP kịp thời | Thực hiện lại giao dịch và nhập OTP kịp thời. Nếu không nhận được OTP, liên hệ ngân hàng. Cung cấp hotline ngân hàng. |
| -5218 | Lệch thông tin định danh (giấy tờ/SĐT) giữa Zalopay và ngân hàng | Hướng dẫn đồng bộ lại thông tin mới nhất ở cả 2 phía (cập nhật định danh trên Zalopay hoặc tại quầy ngân hàng). |
| -5029 | Chưa đăng ký thanh toán trực tuyến | Hướng dẫn đăng ký thanh toán trực tuyến tại app ngân hàng/ATM. Cung cấp hotline ngân hàng. |
| -5042 | Thẻ/TKNH bị khóa, ngừng hoạt động, hoặc đổi từ thẻ từ sang thẻ chip | Liên hệ ngân hàng mở khóa thẻ/tài khoản và thử lại. |
| -5116 | Chưa kích hoạt Smart OTP (thường gặp ở VCB) | Hướng dẫn kích hoạt Smart OTP và thực hiện đủ 2 giao dịch tài chính trên app ngân hàng để kích hoạt hoàn toàn. |
| -5114 | Vượt hạn mức gói dịch vụ SmartBanking (thường gặp ở BIDV) | Chờ qua ngày hôm sau hoặc liên hệ ngân hàng nâng cấp gói dịch vụ. Cung cấp hotline ngân hàng. |
| -5091 | do số điện thoại đăng ký Zalopay không trùng với số điện thoại bạn đã đăng ký ở ngân hàng | Thay đổi số điện thoại ở ngân hàng hoặc thay đổi số điện thoại ở Zalopay |

### C3 - Giao dịch thất bại, đã hoàn tiền
- Xác nhận rõ: giao dịch không thành công và **đã được hoàn tiền**.
- Cung cấp: mã giao dịch, số tiền, tên ngân hàng, 4 số cuối, **thời gian hoàn tiền**, **nguồn hoàn về** (ví Zalopay / tài khoản ngân hàng / số dư sinh lời).
- Hướng dẫn kiểm tra tại: **Lịch sử → Hoàn tiền** trong ứng dụng Zalopay.
