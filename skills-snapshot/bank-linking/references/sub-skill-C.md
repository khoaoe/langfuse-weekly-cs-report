---
name: bank-linking/sub-skill-C
description: Xử lý kịch bản ngân hàng chưa được hỗ trợ liên kết, ngân hàng chỉ hỗ trợ một phương thức liên kết, loại thẻ quốc tế chưa được hỗ trợ, và tên chủ tài khoản chỉ có một từ.
---

## Tool bổ sung
Không gọi tool. Cả bốn kịch bản được xác định bằng phần **Khớp khi** của từng kịch bản dưới đây, chỉ dựa trên nội dung ticket.

Không kịch bản nào khớp: ticket không thuộc nhóm C, quay lại bước 3 của quy trình chính để load `sub-skill-AB.md`.

**Ràng buộc riêng của nhóm này:**
- Không đưa block thông tin liên kết vào phản hồi. Cả bốn kịch bản đều trả lời về chính sách, không về trạng thái một lần liên kết cụ thể.
- Chỉ nói "chưa hỗ trợ" đúng với đối tượng đã khớp bảng của kịch bản. Không suy rộng sang ngân hàng hay loại thẻ khác.
- Không cam kết thời điểm Zalopay sẽ mở hỗ trợ.

---

## Kịch bản & Hướng dẫn

### C1 - Ngân hàng chưa được hỗ trợ liên kết
- **Khớp khi:** tên ngân hàng khách hàng nêu **có** trong cột "Ngân hàng" của bảng dưới đây. Không có trong bảng: không thuộc C1. Tuyệt đối không tự kết luận một ngân hàng chưa được hỗ trợ khi tên đó không có trong bảng.
- Thông báo Zalopay chưa hỗ trợ liên kết với thẻ/tài khoản của ngân hàng đó, gọi đúng tên ngân hàng khách hàng nêu. Nêu rõ Zalopay hỗ trợ liên kết với các ngân hàng được cập nhật trong ứng dụng, để khách hàng tự đối chiếu danh sách hiện hành.
| Ngân hàng | Nội dung bổ sung | Hướng thay thế |
|---|---|---|
| Cake | Cake là ngân hàng số do VPBank phát triển; Nhưng thẻ/tài khoản ngân hàng VPBank vẫn liên kết được với Zalopay bình thường | Dùng thẻ/tài khoản của ngân hàng có trong danh sách hiển thị trên ứng dụng, hoặc thanh toán trực tiếp bằng thẻ quốc tế Visa/Mastercard/JCB phát hành tại Việt Nam mà không cần liên kết |
| Vikki Bank | Tên gọi cũ là Đông Á | Nạp tiền vào Zalopay qua ứng dụng Internet Banking hoặc website của Vikki Bank thay vì liên kết |
- **Thương hiệu số.** Dùng khi đối chiếu nguồn tên ngân hàng ở bước 5 của quy trình chính: một nguồn ghi tên thương hiệu số, nguồn còn lại ghi đúng ngân hàng gốc của nó thì không tính là không khớp.
| Tên thương hiệu số | Ngân hàng gốc |
|---|---|
| Cake | VPBank |

### C2 - Ngân hàng chỉ hỗ trợ một phương thức liên kết
- **Khớp khi:** ngân hàng khách hàng nêu **có** trong bảng dưới đây **và** hình thức liên kết trong ticket đúng là phương thức ở cột "Chưa hỗ trợ".
- **Hình thức liên kết lấy từ cả hai nguồn, không chỉ phần Mô tả.** Trường **Thông tin thẻ/tài khoản** ghi "Số tài khoản: ..." tính là khách hàng liên kết bằng **số tài khoản**; ghi "Số thẻ: ..." hoặc "6 số đầu - 4 số cuối thẻ" tính là bằng **số thẻ**. Không cần khách hàng viết thành câu trong phần Mô tả. Chỉ khi **cả** trường Thông tin thẻ/tài khoản **lẫn** phần Mô tả đều không cho biết hình thức liên kết thì mới không thuộc C2.
- **Luật quyết định, không cần đọc bảng:** cả hai ngân hàng trong bảng dưới đây đều **chưa hỗ trợ liên kết bằng số tài khoản**. Ticket nêu ngân hàng là **LPBank** hoặc **ABBank**, và hình thức liên kết xác định được ở bước 2 là **số tài khoản**: khớp C2. Trả lời theo dòng tương ứng trong bảng, **không** chuyển sang `sub-skill-AB.md`, **không** gọi tool, kể cả khi ticket có mã lỗi.
- Nêu rõ ngân hàng đó hiện chỉ hỗ trợ liên kết bằng phương thức ở cột "Hỗ trợ", chưa hỗ trợ phương thức khách hàng đang dùng.
| Ngân hàng | Hỗ trợ | Chưa hỗ trợ | Hướng dẫn |
|---|---|---|---|
| LPBank | Số thẻ | Số tài khoản | Hướng dẫn khách hàng thao tác lại và nhập số thẻ, giải thích số thẻ là dãy 16 số in trên mặt trước thẻ ATM |
| ABBank | Số thẻ vật lý | Số tài khoản | Hướng dẫn khách hàng nhập số thẻ vật lý. Khách hàng cho biết chưa được phát hành thẻ vật lý: hướng dẫn dùng ngân hàng khác để liên kết, hoặc liên hệ ABBank xin cấp thẻ vật lý |

### C3 - Loại thẻ quốc tế chưa được hỗ trợ
- **Khớp khi:** khách hàng nêu rõ loại thẻ quốc tế trong ticket, và loại đó có giá trị `Chưa` ở bảng dưới đây.
| Loại thẻ | Hỗ trợ liên kết |
|---|---|
| Visa | Có |
| Mastercard | Có |
| JCB | Có |
| Amex | Chưa |
| Loại khác không có trong bảng này | Chưa |
- - Nêu rõ Zalopay hiện chỉ hỗ trợ liên kết thẻ quốc tế Visa, Mastercard và JCB, tạm thời chưa hỗ trợ loại thẻ khách hàng nêu. Gọi đúng tên loại thẻ khách hàng nêu.
- - Ghi nhận nhu cầu của khách hàng.
- - Hướng dẫn liên kết bằng thẻ thuộc một trong ba loại được hỗ trợ, hoặc bằng thẻ/tài khoản ngân hàng nội địa.

### C4 - Tên chủ tài khoản chỉ có một từ
- **Khớp khi:** khách hàng nêu tên chủ tài khoản ngân hàng và tên đó chỉ gồm **một từ**.
- Nêu rõ Zalopay hiện chỉ hỗ trợ liên kết ngân hàng với tên chủ tài khoản gồm từ hai từ trở lên, chưa hỗ trợ tên chỉ có một từ.
- Hướng thay thế: nạp tiền vào Zalopay qua chuyển khoản ngân hàng, không cần liên kết. Thao tác: **Nạp/rút**, nhập số tiền, chọn Tiếp tục, rồi chuyển khoản theo thông tin hoặc mã QR hiển thị.
- Trong quá trình nạp tiền nếu hệ thống báo lỗi, đề nghị khách hàng gửi ảnh chụp từng bước thao tác để Zalopay kiểm tra và hỗ trợ kịp thời.
