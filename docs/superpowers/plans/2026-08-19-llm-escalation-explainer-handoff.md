# Giao việc — implement "Vì sao?" (LLM escalation explainer)

Dán toàn bộ file này cho Sonnet 5 (high) làm prompt mở đầu.

---

## Nhiệm vụ

Implement feature theo spec:

`docs/superpowers/specs/2026-08-19-llm-escalation-explainer-design.md`

Spec là **nguồn sự thật duy nhất**. Đọc trọn spec + `CLAUDE.md` của repo trước khi viết dòng code đầu tiên. Không đọc spec cũ nào khác.

Repo: `langfuse-weekly-cs-report` (git repo riêng, nhánh mặc định `main`).

---

## Đã điều tra và xác minh — KHÔNG điều tra lại

Toàn bộ mục này đã được kiểm bằng cách đọc code thật. Tin và dùng luôn. Đọc lại là đốt token vô ích.

### Backend đang có

| Sự thật | Vị trí |
|---|---|
| `_evidence()` chỉ đọc key `input`/`output`, **bỏ hẳn `metadata`** — đây là bug gốc | `src/weekly_cs_report/trace_explainer.py:373` |
| Cắt chuỗi 2000 ký tự | `trace_explainer.py:26` `_EVIDENCE_MAX_STRING_LENGTH` |
| `load_skill_reference` bị dán nhãn "Chọn skill: X", nuốt `filename` | `trace_explainer.py:301` |
| Thứ tự ưu tiên verdict (dùng lại để xác định giai đoạn quyết định) | `trace_explainer.py:134` `compute_verdict()` |
| Route `trace_explain` — pattern để copy: sync def, regex ticket id, `JSONResponse({"detail":{"code":...}}, status_code=...)` | `src/weekly_cs_report/web.py:397-430` |
| `_TraceExplainCache` khởi tạo trong `create_app` | `web.py:321` |
| Mã lỗi đang dùng: `invalid_ticket_id` 400, `trace_not_found` 404, `langfuse_unavailable` 503 | `web.py:402-429` |
| `LLMClient` Protocol: `generate_structured(*, messages, response_schema) -> StructuredGeneration` | `src/weekly_cs_report/llm_client.py:198` |
| `StructuredGeneration(value: Mapping, usage: LLMUsage)` | `llm_client.py:176` |
| `FakeLLMClient` — dùng cho toàn bộ test tầng 2 | `llm_client.py:291` |
| `GemmaHFLLMClient` raise `PIIApprovalRequiredError` khi `pii_approved=False` | `llm_client.py:523` |
| Validator base URL | `llm_client.py:107` `_is_safe_base_url()` |
| Regex chuỗi số dài đã có, tái dùng tinh thần này để che PII | `src/weekly_cs_report/enrichment.py:33` `_LONG_NUMERIC_RUN` |
| `transfer_reason` mapping rule → nhánh | `enrichment.py:215` |
| TPE resolver v2-safe **đang dùng production** | `src/weekly_cs_report/tpe_status.py` `resolve_tpe_status()` |
| Đường dẫn field ticket trong meta | `config/taxonomy.v2.json` → `dimensions.app.meta_path` = `["App"]` |

### cs-agent (repo `../cs-agent-master`) — chỉ để hiểu, không sửa

| Sự thật | Vị trí |
|---|---|
| Tool span ghi `input = {"tool_name":…, "input": <tham số>}` và `output = {"result": <kết quả>}` ⇒ tên file sub-skill nằm ở **`input.input.filename`** | `core/agents/executor.py:445-451` |
| `llm_call:iter_N` **chỉ** ghi `{"messages_count": N}` ⇒ **system prompt và nội dung `SKILL.md` KHÔNG BAO GIỜ có trong trace** | `core/agents/executor.py:296` |
| `guardrail` span ghi `metadata=check.metadata` **song song** với `output`, không lồng trong `output` | `core/orchestrator.py:493`, `core/agents/executor.py:386` |
| `cs_escalation` đặt `metadata={"reason": reasoning}` — đây là field cần lấy | `core/guardrails/rules/output/cs_escalation.py:88-92` |
| `load_skill_reference(filename)` trả `{"filename":…, "content": <full markdown>}` | `core/plugins/loader.py:184-189` |
| `calculate_time_difference` trả `{hours, minutes, seconds, total_seconds, is_negative}` | `core/plugins/loader.py:204-211` |
| `list_skill_references` trả `{"files": [...]}` | `core/plugins/loader.py:179-182` |
| Envelope lỗi dùng chung mọi tool: `{"error": "NO_DATA"\|"EXCEPTION"\|"UNKNOWN_BANK_CODE", "message": …}` và `{"info": "NO_DATA", "message": …}` | `core/tools/telco/handlers.py`, `core/tools/bank/handlers.py` |
| **Tool có thể tự ra lệnh chuyển CS** — nguồn của nhánh E7 | `core/tools/telco/handlers.py:113` |
| `get_bank_name` trả `{bank_code, short_name, long_name, candidates}` | `core/tools/bank/handlers.py` |
| Model production: `google/gemma-4-31B-it` qua `https://litellm.zalopay.vn/v1` | `config/prod.yaml:3` |

Tool chưa liệt kê ở trên: đọc `core/tools/*/handlers.py` **một lần**, điền vào `tool_labels`, xong. Không đoán key.

**Danh sách span và rule đã quét đầy đủ — có sẵn ở §17.9 của spec. Đừng đi tìm lại.** Ba điểm rút ra, đọc kỹ:

1. **Xác định "bị chặn" bằng `is_blocking_guardrail()` (`enrichment.py:270`), không bao giờ suy từ tên rule.** Họ `cs_escalation` có 4 biến thể, **2 trong đó là PASS**: `cs_escalation_llm` và `cs_escalation_check_error` đều `passed=True`. So khớp tiền tố tên rule sẽ phân loại sai ngay ở nhánh phổ biến nhất.
2. **Có span `general_response`** (`executor.py:197-202`) chưa ai để ý — nhánh trả lời chung khi không skill nào khớp. Nó là tín hiệu mạnh của E6.
3. **`taxonomy.v2.json` → `guardrail.violation_rules` là danh sách thiếu** (không có `cs_escalation_regex`, `foreign_language`, `multilingual_jailbreak`, `profanity`, `inappropriate_tone_llm`). Đừng dùng nó để quyết định chặn/không, và đừng "sửa" nó — nó phục vụ pipeline metric khác.

### Skill files — đã parse toàn bộ 33 file

Cấu trúc: `{skill}/SKILL.md` + `{skill}/references/sub-skill-*.md`, **đồng nhất cả 6 skill** (`ibft`, `topup`, `withdraw`, `telco`, `bank-linking`, `bank-unlink`). Nguồn: `../docs/cs-agent-skills/`.

**Năm ngoại lệ đã đo, phải xử đúng — đây là chỗ dễ hỏng nhất:**

| Ngoại lệ | File | Hệ quả |
|---|---|---|
| ID có dấu chấm `### E.1a - …` | `ibft/references/sub-skill-E.md` | Regex `[A-Z]+[0-9]+` bỏ sót **toàn bộ file 83 dòng, 12 case** |
| Hai ID một heading `### D1, D2 - …` | `ibft/references/sub-skill-CD.md:25` | Không được tách thành 2 case |
| **Không có ID** `### Giao dịch thất bại do hạn mức…` | `topup/references/sub-skill-D.md`, `sub-skill-E.md` | `case_id = None`, **vẫn phải là case** |
| ID trùng trong cùng file (`B1`,`B2`,`B2`) | `topup/references/sub-skill-B.md` | **Cấm dùng case ID làm khoá** |
| `SKILL.md` không có case, dùng mục đánh số `## 5. Gửi lên bộ phận CSKH` | mọi `SKILL.md` | Parser riêng |

⇒ Anchor **luôn** là `<đường dẫn>#L<số dòng heading>`. Không bao giờ là case ID.

### Frontend đang có

Token dùng lại, đã có trong `frontend/src/components/trace-explainer.module.css`:
`--space-1..5`, `--rule`, `--rule-strong`, `--surface`, `--surface-sunken`, `--ink`, `--muted`, `--interactive`, `--interactive-ink`, `--success-text`, `--warning-text`, `--warning`, `--radius-tight`.

Class dùng chung từ `dashboard.module.css`: `styles.section`, `styles.sectionHead`, `styles.sectionTitle`, `styles.action`.

Công thức màu đã có, tái dùng nguyên:
- nền bước bị chặn: `color-mix(in srgb, var(--warning) 12%, var(--surface))` — như `.stepBlocked`
- nền khối trích dẫn: `color-mix(in srgb, var(--interactive) 6%, var(--surface))` — như `.agentBubble`

Pattern `useQuery` để copy: `TraceExplainer.tsx:243` (`queryKey`, `enabled`, `retry: false`, parse rồi throw khi `!ok`).

Pattern Zod + parse để copy: `frontend/src/lib/trace-explain-schema.ts`.

---

## Thứ tự làm

Theo bảng §16 của spec, 11 bước. Ba điều bắt buộc:

1. **Bước 2 (parser) làm trước mọi thứ khác** và phải xanh 5 ca ngoại lệ ở §13.1 trước khi đi tiếp. Parser sai thì mọi tầng trên đều sai và rất khó truy.
2. **Bước 7 là mốc giao được** — dừng ở đây nếu chưa có LiteLLM key, báo lại, đừng chặn.
3. **Bước 8, 9, 10 làm tuần tự, không gộp.** Mỗi stage xanh test rồi mới sang stage sau.

---

## Bẫy đã biết

- `_evidence()` bỏ `metadata` — sửa ở đó, **không** patch riêng `cs_escalation`.
- Case ID **không** duy nhất và **có thể vắng**. Dùng file+dòng.
- Nội dung `SKILL.md` **không có trong trace**, chỉ có trong snapshot. Sub-skill thì ngược lại: ưu tiên bản trong trace.
- `pii_approved` là cổng cứng. **Không lật cờ.** Làm dossier sạch từ trong kiểu dữ liệu (§7.4).
- `categories._tpe_mapping()` là code chết mang lỗi v1/v2 — **đừng sửa, đừng gọi**. Dùng `tpe_status.resolve_tpe_status()`. Xem mục "Bẫy đã biết" trong `CLAUDE.md`.
- Nhánh E7 (tool tự ra lệnh chuyển CS) dễ bị bỏ sót vì không có case skill nào để trích.
- Stage B trả **chỉ số dòng**; backend cắt nguyên văn. Nếu bạn thấy mình đang viết validator so khớp substring cho câu trích do model sinh ra thì đã hiểu sai spec — đọc lại §8.2.

---

## Test — làm gì, không làm gì

**Làm:** đúng những test liệt kê ở §13.1 và §13.2 của spec. Chúng nhắm thẳng vào các bẫy thật, không phải test cho đủ số.

**Không làm:**
- Không dựng công cụ chạy golden set tự động. PO tự nghiệm thu thủ công.
- Không viết test cho code không đụng tới.
- Không chạy `npm run test:e2e` trừ khi đã đổi frontend đáng kể.
- Không tuyên bố đã verify Docker — Docker không chạy được ở môi trường này.
- Không gọi model thật trong bất kỳ test nào. `FakeLLMClient` hết.

Lệnh chạy test Python (đúng như `CLAUDE.md`):

```bash
uv run --isolated --extra dev --locked pytest -q --basetemp="$(mktemp -d)"
```

---

## Quy tắc tiết kiệm

- Không đọc lại file đã liệt kê ở mục "Đã điều tra và xác minh". Cần dòng nào thì mở đúng dòng đó.
- Không refactor code ngoài phạm vi. Có thấy chỗ xấu thì ghi lại, đừng sửa.
- **Không thêm dependency.** Runtime deps của repo đúng 4 gói: `fastapi`, `httpx`, `python-dotenv`, `uvicorn`. Frontend không thêm package.
- Không đổi `_STORAGE_VERSION`. Feature này không đụng projection.
- Không đổi payload của `GET /api/trace-explain/{ticket_id}` đang có.
- Không dùng Explore agent quét cả repo — spec đã có toàn bộ đường dẫn.

---

## Dừng lại và hỏi PO khi

- Chưa có **LiteLLM virtual key** (`sk-…`) cho `litellm.zalopay.vn` → làm tới bước 7 rồi báo.
- Thiếu **danh sách 20 App ID của `telco`** → điền phần đã biết, đánh dấu `TODO_PO` trong `config/explain_context.v1.json`, báo lại. Không tự bịa App ID.
- Phát hiện ngoại lệ parse skill **ngoài 5 ca đã liệt kê** → dừng, báo, đừng tự nới regex cho qua.
- `_is_safe_base_url()` từ chối `https://litellm.zalopay.vn/v1` → báo ngay, đừng sửa validator để lách.
- Bất kỳ chỗ nào buộc phải nới ranh giới PII rộng hơn §7 → dừng, hỏi.

---

## Bàn giao

Xong thì báo gọn: đã làm tới bước nào, test nào xanh, còn gì chờ PO, và **cách chạy local để PO tự nghiệm thu**:

```bash
.venv/bin/weekly-cs-dashboard --local --port 8765
```

Không tự tuyên bố đạt chất lượng — PO nghiệm thu thủ công.
