# Langfuse Weekly CS Report

Dashboard read-only cho PO, CS và Dev theo dõi hiệu quả CS-agent theo tuần.
Dữ liệu báo cáo chính lấy từ Langfuse. CSAT, đối chiếu CS-human và độ phủ
ticket Freshdesk lấy qua job riêng; web server không gọi Freshdesk.

## 1. Yêu cầu

Môi trường phát triển được kiểm thử với:

- Python 3.11.15
- [uv](https://docs.astral.sh/uv/)
- Node.js 24 và npm 11
- Quyền đọc Langfuse; thêm quyền đọc Freshdesk nếu cần cập nhật CSAT

Kiểm tra nhanh:

```bash
python3 --version
uv --version
node --version
npm --version
```

`pyproject.toml` khai báo Python `>=3.9` để phục vụ lock theo marker, nhưng
baseline được hỗ trợ cho project là Python 3.11.

## 2. Clone và cấu hình credential

```bash
git clone <repository-url>
cd langfuse-weekly-cs-report
cp .env.example .env
chmod 600 .env
```

Mở `.env` bằng editor cục bộ và điền:

| Tính năng | Biến bắt buộc |
|---|---|
| Dashboard và báo cáo Langfuse | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` |
| Cập nhật CSAT/đối chiếu Freshdesk | `FRESHDESK_BASE_URL`, `FRESHDESK_API_KEY` |
| Gán nhãn lý do reopen | `LABEL_API_KEY`, `LABEL_BASE_URL`, `LABEL_MODEL` |
| Embedding cho luồng gán nhãn reopen | `EMBED_API_KEY`, `EMBED_BASE_URL`, `EMBED_MODEL` |
| CS-agent skill discovery | `CS_AGENT_ENABLED`, `CS_AGENT_BASE_URL`, `CS_AGENT_TOKEN`, `CS_AGENT_CAS_COOKIE` |

Chỉ ba biến Langfuse là cần để chạy dashboard cơ bản. Các biến Freshdesk và
CS-agent chỉ cần khi chạy các job tương ứng. Các biến `LABEL_*` và `EMBED_*`
không cần cho dashboard thông thường.

Không commit `.env`, không in giá trị credential ra terminal/chat, và không
đặt credential trên command line. Chỉ kiểm tra tên biến khi cần:

```bash
grep -o '^[A-Z_]*=' .env
stat -f '%A %N' .env       # macOS; kết quả cần là 600
```

## 3. Cài dependency và build frontend

Chạy từ thư mục project:

```bash
uv sync --locked --extra dev
npm ci

# Kiểm tra trước khi chạy
npm run typecheck
npm run test:unit
npm run build
```

`npm run build` tạo SPA tại `src/weekly_cs_report/static/spa/`. Phải chạy lại
lệnh này sau khi thay đổi `frontend/` hoặc asset frontend.

Chạy toàn bộ Python test suite trong môi trường dev bị cô lập:

```bash
task_basetemp="$(mktemp -d)"
chmod 700 "$task_basetemp"
uv run --isolated --extra dev --locked pytest -q --basetemp="$task_basetemp"
```

## 4. Chạy dashboard local

```bash
.venv/bin/weekly-cs-dashboard --local --port 8765
```

Mở <http://127.0.0.1:8765>.

Kiểm tra service:

```bash
curl -fsS http://127.0.0.1:8765/healthz
curl -fsS http://127.0.0.1:8765/readyz
curl -fsS http://127.0.0.1:8765/api/dashboard >/dev/null
```

- `/healthz` trả `200` khi process còn phản hồi.
- `/readyz` có thể trả `503` trong lúc snapshot đầu tiên đang được tạo; trả
  `200` khi đã có snapshot hợp lệ.
- Dashboard chỉ bind loopback trong `--local`, nên URL này chỉ dành cho máy
  đang chạy process, không phải URL chia sẻ cho cả team; đây là **not a coworker-shareable deployment**.
- Dừng bằng `Ctrl-C`.

Nếu cổng `8765` đang được dùng:

```bash
.venv/bin/weekly-cs-dashboard --local --port 8766
```

## 5. Cập nhật dữ liệu Freshdesk và snapshot

Dashboard cơ bản chỉ đọc Langfuse. Để cập nhật CSAT và đối chiếu kết quả trên
Freshdesk, cần dashboard đang chạy và đã điền credential Freshdesk:

```bash
./scripts/refresh_dashboard_data.sh
```

Script này tuần tự:

1. lập inventory ticket Freshdesk và đối chiếu với Ticket ID Langfuse;
2. lấy survey chỉ gắn trực tiếp với `Admin CS ZaloPay`;
3. đối chiếu conversation Freshdesk theo metadata đã được phê duyệt;
4. yêu cầu dashboard tạo và publish snapshot mới.

Phần inventory dùng các trạng thái quan sát riêng: `invoked_no_result` là
ticket đã có trong Langfuse nhưng không có AI First/chuyển CS; `not_observed_invoked`
hiển thị là **Không thấy lần gọi CS-agent**, không phải kết luận trigger chắc
chắn thất bại. Chỉ conversation Freshdesk `category=3`, `private=false`,
`incoming=false` mới được tính là public agent reply. Job dùng per-ticket
conversation fetch; không cần quyền bulk satisfaction ratings.

Job dùng cache private trong `runtime/`, không đưa raw conversation, tên/email,
UserID, TransID hoặc internal ID lên browser. `runtime/` không được commit.
Nếu dashboard chạy ở cổng khác `8765`:

```bash
DASHBOARD_LOCAL_PORT=8766 ./scripts/refresh_dashboard_data.sh
```

Không cần chạy script này để chỉ xem dashboard với dữ liệu Langfuse hiện có.

Có thể chạy riêng bước inventory để kiểm tra aggregate, nhưng bước này cần
snapshot Langfuse hiện có và roster Freshdesk đã được phê duyệt:

```bash
.venv/bin/weekly-cs-report fetch-freshdesk-entry-coverage \
  --weeks 13 --max-workers 1 --max-duration 7200 \
  --runtime-dir "$PWD/runtime"
```

Output chỉ là aggregate JSON. Job chỉ lấy ticket Freshdesk có thời gian tạo từ
tuần `06/07/2026` trở đi; các tuần trước mốc này không được suy là ticket không
được CS-agent xử lý. Inventory dùng `per_page=50` cố định. Hai checkpoint riêng
(`inventory_checkpoint.json` theo trang và `coverage_checkpoint.json` theo tiến
độ ticket) nằm trong `artifacts/freshdesk_entry_coverage/`, đều private và
được ghi atomically. Chạy lại sẽ tiếp tục từ checkpoint gần nhất sau rate-limit
hoặc hết thời gian; chỉ khi inventory và toàn bộ đối chiếu hoàn tất mới thay
`runtime/entry_coverage_cache.json`. Nếu job chưa hoàn tất, snapshot dashboard
cũ vẫn được giữ.

Trong một checkout mới, các file roster Freshdesk private có thể chưa tồn tại
vì chúng bị `.gitignore` loại khỏi repository. Khi đó cần lấy bản đã được PO
phê duyệt từ người quản trị project. Không tự tạo roster human-agent. Nếu chỉ
cần CSAT, có thể chạy discovery một lần sau khi được cấp quyền:

```bash
.venv/bin/weekly-cs-report discover-agents \
  --weeks 13 --max-workers 1 --max-duration 7200
```

Lệnh này ghi `config/freshdesk_agents.v1.json` private. Luồng đối chiếu
Freshdesk cần thêm roster và source review được phê duyệt tương ứng; thiếu các
file đó thì chỉ bỏ qua bước đối chiếu, không ảnh hưởng dashboard Langfuse.

## 6. Các lệnh hữu ích

CLI mặc định chạy dry-run:

```bash
.venv/bin/weekly-cs-report
.venv/bin/weekly-cs-report dry-run --weeks 12 --include-current-wtd
.venv/bin/weekly-cs-report inspect-session SESSION_ID
```

Kiểm tra P0 data integrity trên Langfuse:

```bash
.venv/bin/weekly-cs-report verify-dimensions \
  --weeks 12 \
  --include-current-wtd \
  --as-of 2026-07-31T10:00:00+07:00
```

Thêm `--require-p0` nếu lệnh phải trả exit `0` khi và chỉ khi cả hai gate P0
đạt ngưỡng. Lệnh này chỉ đọc Langfuse, không đọc Freshdesk và không ghi raw
trace/observation ra đĩa.

Xem đầy đủ subcommand:

```bash
.venv/bin/weekly-cs-report --help
.venv/bin/weekly-cs-dashboard --help
```

## 7. Xử lý lỗi thường gặp

### `SPA build is missing`

Chạy lại:

```bash
npm ci
npm run build
```

### `dashboard runtime directory is unsafe`

Dashboard yêu cầu thư mục `runtime/` có mode `700`; các file cache/snapshot
bên trong phải có mode `600`. Không đặt `runtime/` bên trong thư mục static.
Kiểm tra và sửa quyền trên đúng thư mục project:

```bash
mkdir -p runtime
chmod 700 runtime
find runtime -maxdepth 1 -type f -exec chmod 600 {} +
```

### `/readyz` trả `503`

Đây thường là lúc snapshot đầu tiên đang load từ Langfuse. Chờ process hoàn
tất rồi gọi lại `/readyz`. Nếu vẫn lỗi, kiểm tra credential Langfuse và log
lỗi cố định của process; không in `.env`.

### Freshdesk refresh không chạy

Kiểm tra tên biến đã có trong `.env`, file có mode `600`, và dashboard đang
chạy đúng cổng. Job Freshdesk dùng per-ticket fetch; bulk satisfaction ratings
không phải dependency của project.

### Muốn rollback về giao diện cũ

Chỉ dùng khi cần chẩn đoán:

```bash
DASHBOARD_FRONTEND_MODE=legacy \
  .venv/bin/weekly-cs-dashboard --local --port 8765
```

## 8. Ranh giới dữ liệu và tài liệu

Dashboard cho phép hiển thị Ticket ID để điều tra. Các trường sau **not browser fields**:
User ID, Trans ID, phone, names/emails, conversation text,
prompts/responses, raw payloads hoặc Langfuse internal IDs như `traceId` và
`sessionId`.

## 9. Production

Lệnh `--local` chỉ dành cho development. Production phải chạy sau proxy xác
thực với `DASHBOARD_AUTH_MODE=proxy`, one worker và exactly one active replica, runtime directory
riêng mode `700`, và secret store được phê duyệt. Không coi local URL là
deployment chia sẻ.

Production contract tối thiểu:

- `DASHBOARD_AUTH_MODE=proxy`, `DASHBOARD_IDENTITY_HEADER` và
  `DASHBOARD_RUNTIME_DIR` phải được cấp từ runtime/secret configuration.
- Chạy **exactly one active replica**, một worker, chiến lược `Recreate` và
  **no surge**. Không scale ngang vì refresh lock/cache hiện là process-local.
- Proxy phải **terminate TLS/SSO**, strip mọi **client-supplied identity header**
  rồi mới set **trusted identity header**. Service chỉ nhận
  **ingress only from the authenticated reverse proxy** và probe hợp lệ.
- `NetworkPolicy` phải giới hạn **ingress only from the authenticated reverse proxy**,
  egress tới DNS và `https://langfuse.zalopay.vn`, và volume phải là
  **dedicated persistent-volume subdirectory**.
- Container chạy non-root với `runAsUser: 10001`, `runAsGroup: 10001`; init
  step dùng `chown 10001:10001`, `chmod 0700` cho runtime và `chmod 0600`
  cho snapshot.
- `/healthz` là **liveness**, `/readyz` là **readiness**; `/readyz` trả `503`
  cho tới khi có snapshot hợp lệ.

Service giữ **last-good** snapshot khi refresh Langfuse lỗi hoặc enrichment
chưa hoàn chỉnh. Snapshot `partial` không được publish/serve; nhãn
`Chưa xác định được từ trace` chỉ dùng sau khi toàn bộ enrichment đã hoàn tất.
Chu kỳ 5 phút
được tính từ **successful cache commit**; cần tính cả **refresh start** và
**refresh duration**, nên đây **not a source-data freshness SLA**.

Deployment cần internal registry, internal domain, access policy, **approved secret storage**
và egress phù hợp. Docker/container build chưa được coi là đã
verify chỉ vì README có hướng dẫn; xem CI workflow và `CLAUDE.md` cho các gate
tương ứng.
