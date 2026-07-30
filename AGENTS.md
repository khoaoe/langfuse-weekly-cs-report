# AGENTS.md — langfuse-weekly-cs-report

Hợp đồng cho agent implement (Codex). `CLAUDE.md` cùng thư mục mô tả bối cảnh và trạng thái — đọc nó trước. File này nói **cách làm việc và giới hạn**.

## Phân vai

Claude viết spec. Bạn implement. Spec ở `docs/superpowers/specs/`, plan ở `docs/superpowers/plans/`.

Trước khi viết code cho một spec: **review spec, tự kiểm chứng lại các số đo trong đó**. Spec nào cũng ghi số đo kèm cách đo — chạy lại, đừng tin sẵn. Thấy sai, mâu thuẫn, hoặc không khả thi thì **nói trước kèm bằng chứng**, đừng tự ý làm khác.

## Quy trình bắt buộc

TDD, tuần tự theo lô mà spec định nghĩa. Mỗi lô: viết test → xác nhận RED → implement → GREEN → chạy **full suite**, không chỉ test liên quan. Không nhảy lô.

```bash
.venv/bin/pytest -q          # 687 test, exit 0 là baseline hiện tại
```

## Giới hạn cứng — vi phạm là hỏng sản phẩm

- **Git repo riêng, nhánh mặc định `main`.** Không commit `.env`, `runtime/`, `artifacts/`, cache hoặc credential.
- **Không tuyên bố đã verify Docker.** Docker không chạy được ở môi trường này. Test chỉ validate Dockerfile và deployment contract, không validate hành vi image.
- **Giữ 100% `<style>`/`<script>` inline** trong `static/index.html`. CSP sha256 sinh ở `web.py:197` từ chính nội dung đó. Không asset ngoài, không thư viện chart — SVG vẽ tay.
- **Không đổi công thức metric, 4 định nghĩa outcome, hay payload API** khi spec chỉ nói về tầng trình bày.
- **Không serialize** text khách hàng, ID nội bộ Langfuse (`traceId`, `sessionId`), hay metadata bị chặn ra browser. Field duy nhất được phép: Ticket ID.
- **Không thêm dep nặng.** Runtime chỉ 4 package (`fastapi`, `httpx`, `python-dotenv`, `uvicorn`). Không numpy, không torch, không sklearn — k-means và silhouette đã viết tay thuần Python trong `reopen_sampling.py`.
- **Không đổi tên `id` đang được test.** Thêm mới thay vì đổi tên.
- Quyền file: `.env` mode `0600`, `runtime/` mode `0700`, snapshot `0600`. Sửa xong kiểm lại bằng `stat -f "%Sp %N"`.

## Điểm dừng người quyết — không được vượt

Spec `2026-07-30-reopen-reason-labeling-design.md` §10 có 3 điểm dừng. Chúng không phải formality:

| Bước | Chờ ai làm gì |
|---|---|
| 6 | PO đọc `artifacts/reopen_discovery/pii_review.csv` bằng mắt và ký duyệt. **Chưa ký thì không gọi API lần nào** |
| 8 | PO chốt `config/reopen_labels.v1.json`. Không tự sinh danh sách nhãn thay PO |
| 13 | Độ tự nhất quán của người ≥ 85% **và** cả 3 ngưỡng §5 GĐ 4 đạt, mới được bật lên dashboard |

`sample-reopen` / `eval-labels` cố ý không expose `pii_approved` trên CLI. Đừng "sửa" điều đó như một bug.

## Kiểm chứng — chạy, đừng suy luận

Không báo "đã xong" khi chưa có output. Bắt buộc chạy và dán kết quả:

```bash
.venv/bin/pytest -q
curl -s http://127.0.0.1:8765/api/dashboard | grep -cE 'UserID|TransID|traceId|sessionId'   # phải 0
stat -f "%Sp %N" .env runtime/dashboard_snapshot.json
```

Với thay đổi UI, đo bằng Chrome DevTools MCP ở **cả** `1440x900` và emulate `390x844x3,mobile,touch`, báo đúng 5 số:

```
{ stickyHeight, tapTargetsUnder44, pageOverflowX, thOffsetFromWrapTop, trendFirstBarX }
```

Ngưỡng đạt: `thOffsetFromWrapTop === 0` · `tapTargetsUnder44 === 0` · `stickyHeight <= 96` (desktop) / `<= 120` (mobile) · `pageOverflowX === false`.

Với palette, chạy validator của skill `dataviz`, đừng phán bằng mắt. Cặp đã PASS 5/5: sáng `#0068FF,#A45F00`; tối `#3B86E8,#B07A2E`.

## Bảo mật

`.env` chứa credential thật. Không in giá trị ra output, không dán vào chat, không commit. Kiểm tên biến bằng `grep -o '^[A-Z_]*=' .env`. Lỗi trả về client không được chứa giá trị credential — `llm_client.py` đã giữ nguyên tắc đó, giữ tiếp.

## Báo cáo cuối

Đối chiếu từng tiêu chí "sẵn sàng giao user" của spec (spec UI §9 có 9 mục), mỗi mục ghi **ĐẠT/CHƯA kèm số đo hoặc output lệnh**. Mục chưa đạt thì nói rõ vì sao. Không làm tròn thành đạt.
