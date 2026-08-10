# AGENTS.md — langfuse-weekly-cs-report

Hợp đồng cho agent implement (Codex). `CLAUDE.md` cùng thư mục mô tả bối cảnh và trạng thái — đọc nó trước. File này nói **cách làm việc và giới hạn**.

## Phân vai

Agent review và trực tiếp implement approved spec; không dừng ở phân tích hoặc viết thêm plan khi execution đã được duyệt.

Đọc `PRODUCT.md`, `DESIGN.md`, `docs/SPEC-v2.md`, production-frontend spec và plan trước khi sửa code.

Trước khi viết code cho một spec: **review spec, tự kiểm chứng lại các số đo trong đó**. Spec nào cũng ghi số đo kèm cách đo — chạy lại, đừng tin sẵn. Thấy sai, mâu thuẫn, hoặc không khả thi thì **nói trước kèm bằng chứng**, đừng tự ý làm khác.

## Quy trình bắt buộc

TDD, tuần tự theo lô mà spec định nghĩa. Mỗi lô: viết test → xác nhận RED → implement → GREEN → chạy **full suite**, không chỉ test liên quan. Không nhảy lô.

```bash
npm run test:unit
npm run typecheck
npm run build
.venv/bin/pytest -q
```

## Giới hạn cứng — vi phạm là hỏng sản phẩm

- **Git repo riêng, nhánh mặc định `main`.** Không commit `.env`, `runtime/`, `artifacts/`, cache hoặc credential.
- **Không tuyên bố đã verify Docker.** Docker không chạy được ở môi trường này. Test chỉ validate Dockerfile và deployment contract, không validate hành vi image.
- Không sửa SPA mới trong `static/index.html`; giữ file này làm legacy rollback và build React/Vite vào `static/spa/`.
- `/assets/*` phải chịu cùng auth boundary như `/` và `/api/*`; chỉ serve regular file dưới asset root, không traversal hoặc directory listing.
- SPA CSP phải self-only, cấm inline style/script attributes, `unsafe-inline`, `unsafe-eval`, CDN và external request.
- Root HTML dùng `no-store`; hashed assets dùng `private, max-age=31536000, immutable`.
- Node 24/npm 11 là build-only; production image cuối chỉ chạy Python 3.11.
- **Không đổi công thức metric, 4 định nghĩa outcome, hay payload API** khi spec chỉ nói về tầng trình bày.
- **Không serialize** text khách hàng, `traceId`, `observationId`, session identifier riêng hay metadata bị chặn ra browser. Ticket ID là định danh điều tra duy nhất được phép. Ngoại lệ hẹp: frontend bundle và href Langfuse đã duyệt được chứa project routing ID cố định, không phải secret, `cmqubjzur000hz507ptubh2l9`; segment session phải dùng lại Ticket ID, không lấy thêm field Langfuse.
- **Không thêm dep nặng.** Runtime chỉ 4 package (`fastapi`, `httpx`, `python-dotenv`, `uvicorn`). Không numpy, không torch, không sklearn — k-means và silhouette đã viết tay thuần Python trong `reopen_sampling.py`.
- Giữ compatibility DOM IDs trong một release; test mới ưu tiên role, accessible name và hành vi.
- Không reset, stash hoặc overwrite dirty worktree; thay đổi không thuộc task luôn được xem là của user.
- Quyền file: `.env` mode `0600`, `runtime/` mode `0700`, snapshot `0600`. Sửa xong kiểm lại bằng `stat -f "%Sp %N"`.

## Frontend contract

- Chỉ dùng literal `Zalopay`; nguồn upstream canonical duy nhất là `../docs/zalopay-guideline/`. Các logo, graphic và webfont thực sự dùng phải là bản copy có provenance trong `assets/` của project; frontend không đọc file trực tiếp ngoài project và không ship `.ai`/PDF.
- Không card mosaic, glassmorphism, gradient trang trí, dual-axis chart, donut, gauge hoặc entrance animation.
- Weekly Report giữ đúng 14 cột; WTD không so trực tiếp với tuần đầy đủ và tuần rỗng không được biến thành 0.
- Error UI chỉ hiển thị thông báo tiếng Việt đã sanitize; không raw payload, error code nội bộ hoặc stack trace.
- Wording transfer là “tín hiệu chuyển CS”, không khẳng định nguyên nhân khi payload chỉ chứa observation overlap.

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

UI phải kiểm bằng Playwright tại `1440×900` và `390×844`, cả light/dark: first viewport, global overflow, local table scroll, sticky header/cột Tuần, keyboard, focus, reduced motion và tap target 44×44.

Chạy axe; không chấp nhận serious/critical violation, console error, CSP error hoặc external network request.

Release budget: initial JS ≤250 KB gzip, CSS ≤80 KB gzip, ba WOFF2 ≤300 KB và không public source map.

`npm audit` không còn high/critical; wheel/package và Docker contract phải chứng minh chứa đủ hashed asset.

## Bảo mật

`.env` chứa credential thật. Không in giá trị ra output, không dán vào chat, không commit. Kiểm tên biến bằng `grep -o '^[A-Z_]*=' .env`. Lỗi trả về client không được chứa giá trị credential — `llm_client.py` đã giữ nguyên tắc đó, giữ tiếp.

## Báo cáo cuối

Đối chiếu từng acceptance gate trong production-frontend spec, ghi **ĐẠT/CHƯA** kèm output thật; phân biệt production candidate với approval để gọi là official.
