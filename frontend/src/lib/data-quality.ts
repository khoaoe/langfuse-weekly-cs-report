import type { QualityLabel } from "./dashboard-schema";

/**
 * User-facing labels for the backend quality taxonomy.
 *
 * Keep this exhaustive so a newly-added backend enum cannot silently leak
 * implementation language into the dashboard or its CSV exports.
 */
export const DATA_QUALITY_LABELS: Readonly<Record<QualityLabel, string>> = {
  valid: "Hợp lệ",
  empty_or_technical: "Không có nội dung để phân tích",
  malformed_output: "Dữ liệu trả về sai định dạng",
  invalid_timestamp: "Thời gian không hợp lệ",
  missing_trace_id: "Không liên kết được bản ghi AI",
  missing_session_id: "Không liên kết được ticket",
  missing_turn: "Thiếu số lượt trả lời",
  invalid_turn: "Số lượt trả lời không hợp lệ",
  session_freshdesk_mismatch: "Mã ticket không khớp Freshdesk",
  empty_session: "Không có dữ liệu ticket",
  session_id_mismatch: "Mã ticket không khớp",
  duplicate_turn: "Trùng lượt trả lời",
  missing_turn0: "Thiếu lượt trả lời đầu tiên",
  no_turn_zero: "Không có lượt trả lời đầu tiên",
  unknown_quality_issue: "Lỗi chưa phân loại",
};

export function dataQualityLabel(value: QualityLabel): string {
  return DATA_QUALITY_LABELS[value];
}
