# CLAUDE.md — langfuse-weekly-cs-report

Dashboard hiệu quả CS-agent theo tuần, read-only trên Langfuse. Đọc `../CLAUDE.md` trước để lấy bối cảnh workspace và gateway.

**Đây là Git repo riêng, nhánh mặc định `main`.** Không commit `.env`, `runtime/`, `artifacts/`, cache hoặc credential. Không tuyên bố đã verify Docker — Docker không chạy được ở đây.

## Lệnh

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q                                  # 687 test, exit 0 (2026-07-30)
.venv/bin/weekly-cs-dashboard --local --port 8765     # dashboard local, loopback only
.venv/bin/weekly-cs-report dry-run --weeks 12
.venv/bin/weekly-cs-report verify-dimensions --weeks 12
.venv/bin/weekly-cs-report inspect-session SESSION_ID
```

## Nguồn sự thật

`docs/SPEC-v2.md` thắng `README.md` khi mâu thuẫn về metric. §5 là đặc tả UI (§5.2 ba câu hỏi 10 giây, §5.3 palette + nguyên tắc, §5.4 luật mã hoá thị giác).

Spec bổ sung ở `docs/superpowers/specs/`:

| Spec | Nội dung |
|---|---|
| `2026-07-29-langfuse-weekly-cs-dashboard-design.md` | V1, khai báo điều kiện mở khoá V2 |
| `2026-07-29-live-on-open-dashboard-design.md` | Cache live-on-open, refresh nền |
| `2026-07-30-reopen-reason-labeling-design.md` | Lớp gán nhãn lý do reopen (V2). §10 có 14 bước, **3 điểm dừng người quyết** |
| `2026-07-30-dashboard-ui-uplift-design.md` | Nâng cấp UI. §9 có 9 tiêu chí sẵn sàng giao user |

## Phân loại KHÔNG dùng LLM

99% dashboard là deterministic. Đừng đi tìm model ở đâu:

- **Chuyển CS** = so khớp đúng một câu semantic cố định trong `taxonomy.v2.json` (`transfer.semantic_text`)
- **Reopen** = số học trên timestamp, cửa sổ 168h
- **4 outcome** (`ai_end_to_end`, `ai_then_cs`, `direct_cs`, `unclassified`) = thứ tự turn + có/không câu transfer
- **Nhóm vấn đề / TPE / App / entry point** = map field `input.other_info.meta` theo `taxonomy.v2.json`

Chỗ **duy nhất** cần LLM: `content_labeler.py` (lý do reopen). Thiếu config thì `llm_client.py` raise `LLMConfigurationError`, pipeline chuyển `reopen_reason.status = "pending"` — fail closed, không giả số.

## Ràng buộc kiến trúc

- **Raw trace/observation không bao giờ serialize ra đĩa.** Hệ quả: labeler phải chạy **trong cùng lượt pipeline** khi payload còn trong bộ nhớ; không chạy lại được từ artifact.
- **CSP sha256 sinh ở `web.py:197`** từ nội dung inline. Giữ 100% `<style>`/`<script>` inline trong `static/index.html`. Không asset ngoài, không thư viện chart — SVG vẽ tay.
- **Runtime deps chỉ 4**: `fastapi`, `httpx`, `python-dotenv`, `uvicorn`. Không numpy, không torch. K-means + silhouette viết tay thuần Python trong `reopen_sampling.py`. Đừng thêm dep nặng.
- `llm_client.embed()` là **Protocol** (`llm_client.py:110`) — thêm provider mới bằng implementation mới, không sửa caller.
- Một worker duy nhất khi chạy production: refresh lock và cooldown là process-local.
- Phạm vi ticket: chỉ trace có root input `source == "ticket"`. Direct chat bị loại trước khi khử trùng lặp.

## Ranh giới PII trên browser

Được phép: **Ticket ID**. Không được: UserID, TransID, số điện thoại, tên/email, nội dung hội thoại, prompt/response, raw payload, ID nội bộ Langfuse (`traceId`, `sessionId`).

Kiểm sau mỗi thay đổi payload:

```bash
curl -s http://127.0.0.1:8765/api/dashboard | grep -cE 'UserID|TransID|traceId|sessionId'   # phải là 0
```

## Trạng thái hiện tại (2026-07-30)

- Coverage: `issue_category 90,0%` · `tpe 82,3%` · `app 79,3%` · `intent 76,8%` · `skill 50,2%`. `unmapped_tpe_codes`: 15 mã.
- `reopen_reason.status = "pending"`, `labeled 0/93` — chưa gán nhãn lần nào.
- Đang ở **bước 6→7 của spec reopen §10**: `artifacts/reopen_discovery/pii_review.csv` (1.680 dòng đã mask) đã có, PO đã ký duyệt. Chờ label route + embed route chạy được, rồi `config/reopen_labels.v1.json` (hiện `"labels": []`).
- `sample-reopen` và `eval-labels` **cố ý không có đường bật `pii_approved` trên CLI** (`cli.py` docstring nói rõ). Không phải bug — hàng rào chống bấm nhầm.
- `.env` hiện trỏ label route sang `vllm.zalopay.vn/v1` + `gemma-3-27b` (keyless, đã test `200`); embed route sang HF router + `hiieu/halong_embedding`. Biến `EMBED_*` **chưa có code đọc** — là contract chờ implement.

## Lỗi UI đã xác định, chưa sửa

- `th{position:sticky;top:var(--sticky-offset)}` áp cả trong `.weekly-table-scroll` / `.explorer-table` — hai container này có `overflow-x:auto` nên là **scroll container**, khiến header bảng nằm cách mép trên bảng 134px thay vì 0. Trong container cuộn phải `top:0`.
- `renderTrend` (`static/index.html:70`) chạy `index` trên cả 13 tuần kể cả 8 tuần rỗng → 5 cột dồn về 1/3 phải. `preserveAspectRatio="none"` + `viewBox="0 0 320 160"` render ở 1374px = giãn ngang 4,3×.
- Chart hiện vẽ cột (volume) + 2 đường (tỉ lệ) cùng khung = **hai thang y**, vi phạm luật chart. Phải tách hai chart.

Chi tiết và cách sửa: `docs/superpowers/specs/2026-07-30-dashboard-ui-uplift-design.md`.
