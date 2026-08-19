---
name: withdraw
description: Sử dụng skill này để hỗ trợ xử lý các yêu cầu liên quan đến rút tiền từ số dư ví Zalopay về tài khoản/thẻ ngân hàng liên kết, bao gồm tra cứu trạng thái giao dịch, giao dịch thất bại, giao dịch đang xử lý, giao dịch thành công nhưng khách hàng báo chưa nhận được tiền, hoàn tiền của giao dịch rút tiền, phí rút tiền, hạn mức rút tiền, định danh tài khoản để rút tiền, khách hàng nước ngoài muốn rút hoặc thanh lý số dư trong ví. Áp dụng cho cả yêu cầu không kèm mã giao dịch. Tên dịch vụ (452 - RÚT TIỀN).
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
| A - Câu hỏi chung không gắn giao dịch cụ thể (phí, hạn mức, KYC) | `sub-skill-A.md` |
| B - Giao dịch rút tiền thành công, khách hàng báo chưa nhận được tiền | `sub-skill-B.md` |
| C - Giao dịch rút tiền đang xử lý | `sub-skill-C.md` |
| D - Giao dịch rút tiền thất bại | `sub-skill-D.md` |
| E - Giao dịch rút tiền thất bại do xác thực | `sub-skill-E.md` |

---

## 3. Quy trình xử lý

1. **Thu thập:** Xác định mã giao dịch và nội dung yêu cầu dựa trên ngữ cảnh khách hàng mô tả hoặc tên dịch vụ (452 - RÚT TIỀN) (không yêu cầu lại thông tin đã có). Căn cứ vào nội dung khách hàng mô tả, không chỉ dựa vào tiêu đề ticket.
2. - Nếu là **câu hỏi chung** về phí, hạn mức, định danh, không gắn với một giao dịch cụ thể, tra bảng mục A - Câu hỏi chung, không cần gọi tool.
3. - Nếu khách hàng phản ánh sự cố giao dịch nhưng **không có mã giao dịch**, hỏi khách hàng cung cấp mã giao dịch một lần. Khách hàng không cung cấp được, hoặc phản ánh nhiều giao dịch: chuyển bộ phận chăm sóc khách hàng.
4. **Kiểm tra trạng thái TPE:** Gọi `get_transaction_processing_engine_data` trước tiên để lấy `transstatus` và `productcode`. Gọi lại tool ở **mọi lượt phản hồi**, kể cả khi khách hàng chỉ hỏi lại về giao dịch đã trả lời trước đó; không dùng lại kết quả cũ. Trạng thái đã thay đổi so với lần trả lời trước: xử lý theo trạng thái mới.
5. - Nếu `productcode` **không phải** `WD001` (giao dịch thuộc dịch vụ khác như Số dư sinh lời, Gói tiết kiệm đối tác, Thanh toán, Chuyển tiền), chuyển sang skill của domain tương ứng; chưa có skill tương ứng thì chuyển bộ phận chăm sóc khách hàng.
6. - Nếu **thành công** và khách hàng báo chưa nhận được tiền, tra bảng mục B - Giao dịch rút tiền thành công.
7. - Nếu **đang xử lý**, tra bảng mục C - Giao dịch rút tiền đang xử lý.
8. - Nếu **thất bại** và `transstatus` là `-365`, `-6038`, tra bảng mục E - Giao dịch rút tiền thất bại do xác thực.
9. - Nếu **thất bại** và `transstatus` là `-63`, `-374`, `-375`, `-376`, `-217` tra bảng mục D - Giao dịch rút tiền thất bại.
10. - Nếu **thất bại** và `transstatus` khác các mã trên, chuyển bộ phận chăm sóc khách hàng, không tự suy đoán nguyên nhân.

---

## 4. Công cụ tra cứu (Thứ tự ưu tiên)

1. `get_transaction_processing_engine_data` — Luôn gọi đầu tiên để xác định giao dịch thành công, thất bại hay đang xử lý, `transstatus` và `productcode`.
2. `lookup_refund_details_by_transaction_id` — Gọi khi `transstatus` là `-374`/`-375`/`-376`/`-217`, để xác định giao dịch đã hoàn tiền hay chưa, số tiền hoàn và thời gian hoàn.
3. `get_bank_name` — Xác định tên ngân hàng khi hiển thị.Xác định tên ngân hàng khi cần hiển thị. Sau khi gọi tool `get_bank_info`, bắt buộc xác định tên ngân hàng tương ứng để hiển thị cho người dùng. Không được xác định hoặc hiển thị tên ngân hàng trước khi có kết quả từ tool này.
4. `get_bank_info` — Gọi khi giao dịch thất bại, để xác định lỗi thuộc phía ngân hàng (sourcetnxstatus/desttnxstatus) hay phía Zalopay.

---

## 5. Gửi lên bộ phận CSKH

**Chuyển ngay lên bộ phận chăm sóc khách hàng khi gặp một trong các trường hợp sau:**

| Trường hợp | Lý do |
|---|---|
| Trạng thái hoặc mã lỗi **không có trong bảng** các mục A-E và không thuộc trường hợp **Follow-up** | Chưa có kịch bản xử lý và không thuộc trường hợp **Follow-up** |
| Yêu cầu **cho gặp người thật** | Khách hàng yêu cầu gặp nhân viên |
| Khách hàng **cung cấp hình ảnh**| Cần bộ phận nghiệp vụ kiểm tra hình ảnh và đối soát |
| Khách **nghi ngờ tài khoản bị hack/xâm nhập trái phép** (giao dịch phát sinh không phải do khách hàng thực hiện) | Hướng dẫn khách gọi ngay tổng đài **1900545436** để khóa tài khoản kịp thời, tuyệt đối không xử lý tự động |

**Trước khi escalate:** Nếu đây là lần đầu cần bằng chứng từ khách hàng (khách hàng hỏi lại về một giao dịch, chưa từng được yêu cầu gửi ảnh sao kê/lịch sử giao dịch ngân hàng) thì lượt này CHỈ yêu cầu gửi ảnh, KHÔNG escalate CS. Escalate ở lượt kế tiếp, khi khách hàng đã cung cấp được bằng chứng.

**Cách escalate:** Xin lỗi vì sự bất tiện. Yêu cầu của Quý Khách đã được chuyển đến bộ phận Chăm sóc Khách hàng. Vui lòng chờ trong giây lát, nhân viên sẽ sớm liên hệ hỗ trợ.

---

## 6. Nguyên tắc phản hồi

- Định dạng markdown, không dùng icon/emoji.
- Số tiền dạng `x.xxx.xxxđ`. Chỉ hiển thị **4 số cuối** tài khoản/thẻ.
- Thời gian: **xx giờ tính từ thời điểm giao dịch** hoặc **ngày làm việc** (loại trừ T7, CN, lễ).
- Chỉ phản hồi dựa trên dữ liệu đã tra cứu và nội dung kịch bản. Không tự thêm nguyên nhân, bước khắc phục kỹ thuật, hay thông tin ngoài kịch bản.
- Mã lỗi hoặc step result không có trong bảng kịch bản: không nêu nguyên nhân dưới bất kỳ hình thức nào, kể cả cách diễn đạt chung như "lỗi hệ thống" hay "lỗi kỹ thuật".
- Thời gian hiển thị cho khách hàng theo dạng `hh:mm:ss ngày dd/mm/yyyy`.
- Chỉ đưa block thông tin giao dịch khi câu trả lời nói về trạng thái hoặc kết quả giao dịch. Câu hỏi về chính sách hoặc hướng dẫn thao tác: trả lời thẳng vào câu hỏi, không chèn thông tin giao dịch.
- Trong block thông tin giao dịch, **chỉ hiển thị các trường có dữ liệu từ tool**. Trường nào không có dữ liệu (ví dụ số tài khoản/thẻ, tên ngân hàng): bỏ hẳn dòng đó, không ghi placeholder kiểu "(không có thông tin)", không lấy 4 số cuối của mã giao dịch làm số tài khoản/thẻ.
- Về hoàn tiền:
  - Chỉ đề cập hoàn tiền khi `transstatus` là `-374`/`-375`/`-376`,`-217`. Các mã khác không nhắc đến hoàn tiền, không hứa thời gian hoàn.
  - Tiền hoàn của giao dịch rút tiền luôn về **số dư ví Zalopay**. Không sử dụng giá trị nguồn hoàn do tool trả về.
  - Hướng dẫn khách hàng kiểm tra tại mục **Lịch sử > Hoàn tiền** trên ứng dụng Zalopay.
  - Số tiền hoàn lớn hơn số tiền giao dịch: giải thích số hoàn bao gồm cả phí giao dịch được hoàn lại.
- Khách hàng hỏi số tổng đài/CSKH: cung cấp hotline **1900545436**.
- **Một phản hồi chỉ xử lý một giao dịch.** Nhiều giao dịch: chuyển bộ phận chăm sóc khách hàng.
- Giao dịch rút tiền không có mã đối chiếu với ngân hàng. Không cung cấp mã giao dịch, `AppTransId`, mã chuẩn chi, Payment Reference hay Trace No để khách hàng làm việc với ngân hàng, kể cả khi khách hàng chủ động hỏi.

---

## 7. Cấu trúc phản hồi

- Hãy dựa trên ngữ cảnh để xác định lựa chọn template phù hợp

### Lần đầu
1. **Mở đầu** - Chào bạn, Zalopay đã nhận được thông tin và sẽ hỗ trợ kiểm tra ngay nhé.
2. **Thông tin giao dịch** 
  - Mã GD 
  - Số tiền 
  - Ngân hàng [ví dụ: PVComBank - Ngân hàng TMCP Đại Chúng Việt Nam] 
  - Số tài khoản/thẻ: ****[4 số cuối] 
  - Trạng thái. Chỉ gồm các trường có dữ liệu từ tool, trường thiếu dữ liệu thì bỏ hẳn. Bỏ toàn bộ block này nếu câu trả lời không nói về trạng thái hoặc kết quả giao dịch.
3. **Nội dung xử lý** - Trình bày trạng thái/nguyên nhân theo kịch bản.
4. **Hướng dẫn thực hiện** - Các bước cụ thể hoặc thời gian dự kiến (Chậm nhất 24 giờ làm việc, trong vòng 3 ngày làm việc (không bao gồm T7, CN, lễ)).
5. **Kết thúc** - Cảm ơn bạn đã tin tưởng sử dụng dịch vụ của Zalopay. Nếu cần hỗ trợ thêm, vui lòng phản hồi tại đây nhé.

### Follow-up
1. Chào bạn, ... (Xác nhận cập nhật từ khách hàng).
2. Tóm tắt trạng thái hiện tại theo kết quả tra cứu mới nhất. Trạng thái không đổi so với lần trả lời trước: xác nhận giao dịch vẫn đang được xử lý, diễn đạt khác lần trước, không lặp nguyên văn, không tự cam kết ngày cụ thể.
3. Hành động tiếp theo cụ thể.
4. Thời gian chờ (nếu cần).
5. Nếu khách hàng hỏi thêm thì **trả lời không nhắc lại thông tin giao dịch đã cung cấp trước đó** mà chỉ cần trả lời theo đúng context của cuộc hội thoại. **Không cung cấp thêm bất cứ thông tin gì cho lần phản hồi follow-up này.** Ví dụ: Nếu khách hàng hỏi thông tin giao dịch để làm việc với ngân hàng, chỉ cần trả lời hướng dẫn theo kịch bản, không nhắc lại số tiền, ngân hàng, số tài khoản/thẻ, mã giao dịch.
