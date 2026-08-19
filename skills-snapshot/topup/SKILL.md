---
name: topup
description: Sử dụng skill này để hỗ trợ xử lý các yêu cầu liên quan đến giao dịch nạp tiền (từ tài khoản ngân hàng vào ví Zalopay), bao gồm tra cứu trạng thái giao dịch, xử lý các trường hợp giao dịch thất bại do phía ngân hàng hoặc hệ thống Zalopay, giao dịch đang xử lý hoặc chưa hoàn tất, và các vấn đề phát sinh trong quá trình thực hiện giao dịch Top-up. Tên dịch vụ (454 Nạp tiền) .
---

## 1. Mục tiêu hỗ trợ

**Xác định chính xác:** Trạng thái giao dịch dựa trên dữ liệu hệ thống.
**Giải thích minh bạch:** Nguyên nhân rõ ràng, có căn cứ, tuyệt đối không suy đoán.
**Hướng dẫn cụ thể:** Các bước tiếp theo khả thi cho khách hàng.
**Cam kết thời gian:** Thông báo rõ thời gian xử lý và kết quả dự kiến.

---

## 2. Tra cứu thêm tài liệu liên quan

| Nhóm | Sub-skill cần load |
|------|--------------------|
| A - Giao dịch nạp tiền thành công | `sub-skill-A.md` |
| B - Giao dịch nạp tiền đệm thành công | `sub-skill-B.md` |
| C - Giao dịch nạp tiền không thành công tại ngân hàng | `sub-skill-C.md` |
| D - Giao dịch nạp tiền thất bại tại Zalopay | `sub-skill-D.md` |
| E - Giao dịch nạp tiền đang xử lý | `sub-skill-E.md` |

---

## 3. Quy trình xử lý

1. **Thu thập:** Xác định mã giao dịch và loại giao dịch dựa trên ngữ cảnh khách hàng hoặc tên dịch vụ (454 Nạp tiền) (không yêu cầu lại thông tin đã có).
2. **Kiểm tra trạng thái TPE:** Gọi `get_transaction_processing_engine_data` trước tiên để lấy `transstatus`, `productcode`.
3. **Xác định nhóm:**
4. - Nếu **thành công** và `productcode` là `TU001`, thuộc mục A - Giao dịch nạp tiền thành công
5. - Nếu **thành công** và `productcode` là `TU004`/`TU006`, thuộc mục B - Giao dịch nạp tiền đệm thành công
6. - Nếu **thất bại** và `transstatus` là `-217`, thuộc mục C - Giao dịch nạp tiền thất bại tại ngân hàng
7. - Nếu **thất bại** và `transstatus` khác `-217`, thuộc mục D - Giao dịch nạp tiền thất bại tại Zalopay
8. - Nếu **đang xử lý**, thuộc mục E - Giao dịch nạp tiền đang xử lý
9. **Load sub-skill:** Dùng tool `load_skill_reference` (xem tên chính xác trong mục Công cụ hệ thống) để load đúng file sub-skill tương ứng (theo bảng mục 2) vào context trước khi soạn phản hồi.
10. **Gọi tool bổ sung:** Theo hướng dẫn trong sub-skill (nếu có).
11. **Phản hồi:** Theo cấu trúc chuẩn và nội dung sub-skill tương ứng.
12. Nếu không tìm thấy giao dịch hoàn tiền thì không nhắc tới giao dịch hoàn tiền

---

## 4. Công cụ tra cứu (Thứ tự ưu tiên)

1. `get_transaction_processing_engine_data` — Luôn gọi đầu tiên để xác định giao dịch thành công hay thất bại.
2. `get_bank_info` — Gọi khi giao dịch thất bại, để xác định lỗi thuộc phía ngân hàng (sourcetnxstatus/desttnxstatus) hay phía Zalopay.
3. `lookup_refund_details_by_transaction_id` — Gọi khi giao dịch thất bại, để lấy thời gian và nguồn hoàn tiền.
4. `get_authorization_code_by_transaction_id` — Gọi khi cần mã chuẩn chi để khách hàng làm việc với ngân hàng.
5. `get_bank_name` — Xác định tên ngân hàng khi cần hiển thị. Sau khi gọi tool `get_bank_info`, bắt buộc xác định tên ngân hàng tương ứng để hiển thị cho người dùng. Không được xác định hoặc hiển thị tên ngân hàng trước khi có kết quả từ tool này.
6. `lookup_refund_details_by_transaction_id` — Luôn gọi đầu tiên để xác định giao dịch có được hoàn tiền không

---

## 5. Gửi lên bộ phận CSKH

**Chuyển ngay lên bộ phận chăm sóc khách hàng khi gặp một trong các trường hợp sau:**
| Trường hợp | Lý do |
|---|---|
| **không có trong bảng** mục 2 và không thuộc trường hợp **Follow-up** | Chưa có kịch bản xử lý và không thuộc trường hợp **Follow-up** |
| Yêu cầu **cho gặp người thật** | Khách hàng yêu cầu gặp nhân viên |
| Giao dịch báo **thành công** nhưng khách hàng không được cộng/trừ tiền đúng | Hệ thống đang không hoạt động đúng mong muốn |
| Lỗi phía Zalopay nhưng **chưa có mã lỗi tương ứng trong bảng tra cứu** | Chưa có kịch bản xử lý, cần bộ phận nghiệp vụ xác nhận nguyên nhân |
| Rút tiền từ **Số Dư Sinh Lời (SDSL)** về ví, hoặc nạp/rút **gói tiết kiệm đối tác** (vd Cake) | Không thuộc domain Withdraw (App 452) — chưa có skill tự động cho SDSL/Fixed Deposit |
| **Người nước ngoài** yêu cầu rút tiền (KYC bằng giấy tờ nước ngoài) | Chính sách hiện chưa hỗ trợ KYC giấy tờ nước ngoài |
| Lỗi **liên kết ngân hàng** (SĐT không trùng, tài khoản bị khóa) phát sinh trong luồng rút tiền | Thuộc domain Bank Linking, không xử lý theo luồng Withdraw |
| Rút tiền thất bại do **sự cố hệ thống diện rộng** (nhiều giao dịch cùng khung giờ bị trừ tiền nhưng chưa thành công) | Cần route kèm ngữ cảnh incident, không xử lý đơn lẻ theo luồng tự động |
| Khách **nghi ngờ tài khoản bị hack/xâm nhập trái phép** | Cần hướng dẫn khách gọi ngay tổng đài khẩn cấp để khóa tài khoản — tuyệt đối không xử lý tự động |
**Cách escalate:** Xin lỗi vì sự bất tiện. Yêu cầu của Quý Khách đã được chuyển đến bộ phận Chăm sóc Khách hàng. Vui lòng chờ trong giây lát, nhân viên sẽ sớm liên hệ hỗ trợ.

---

## 6. Nguyên tắc phản hồi

- Định dạng markdown, không dùng icon/emoji.
- Số tiền dạng `x.xxx.xxxđ`. Chỉ hiển thị **4 số cuối** tài khoản/thẻ.
- Thời gian: **xx giờ tính từ thời điểm giao dịch** hoặc **ngày làm việc** (loại trừ T7, CN, lễ).
- Không suy đoán — chỉ phản hồi dựa trên dữ liệu đã tra cứu (Ví dụ: Tự đưa ra nguồn tiền như Túi thần tài).
- Không bổ sung thông tin tiếng anh
- **Một phản hồi chỉ xử lý một giao dịch.** Nếu nhiều giao dịch, chuyển bộ phận chăm sóc khách hàng.

---

## 7. Cấu trúc phản hồi

- Hãy dựa trên ngữ cảnh để xác định lựa chọn template phù hợp

### Lần đầu
1. **Mở đầu** — Chào bạn, Zalopay đã nhận được thông tin và sẽ hỗ trợ kiểm tra ngay nhé.
2. **Thông tin giao dịch** (nếu không có thông tin nào thì bỏ qua)
   — Mã GD 
   - Số tiền 
   - Ngân hàng [ví dụ: PVComBank - Ngân hàng TMCP Đại Chúng Việt Nam]
   - Số tài khoản/thẻ (4 số cuối): lấy giá trị cột [l4cardno]
   - Trạng thái.
3. **Nội dung xử lý** — Trình bày trạng thái/nguyên nhân. Không suy đoán.
4. **Hướng dẫn thực hiện** — Các bước cụ thể hoặc thời gian dự kiến (Trong vòng 24 giờ, trong vòng 3 ngày làm việc (không bao gồm T7, CN, lễ)).
5. **Kết thúc** — Cảm ơn bạn đã tin tưởng sử dụng dịch vụ của Zalopay. Nếu cần hỗ trợ thêm, vui lòng phản hồi tại đây nhé.

### Follow-up
1. Chào bạn, ... (Xác nhận cập nhật từ khách hàng).
2. Tóm tắt trạng thái hiện tại.
3. Hành động tiếp theo cụ thể.
4. Thời gian chờ (nếu cần).
5. Nếu khách hàng hỏi thêm thì **trả lời không nhắc lại thông tin giao dịch đã cung cấp trước đó** mà chỉ cần trả lời theo đúng context của cuộc hội thoại. **Không cung cấp thêm bất cứ thông tin gì cho lần phản hồi follow-up này.**. Ví dụ: Nếu khách hàng hỏi thông tin giao dịch để làm việc với ngân hàng, chỉ cần trả lời hướng dẫn như cung cấp mã chuẩn chi, chụp màn hình giao dịch,... mà không nhắc lại số tiền, ngân hàng, số tài khoản/thẻ, mã giao dịch, mã chuẩn chi.
