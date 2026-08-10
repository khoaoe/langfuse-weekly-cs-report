import { formatCount, formatRate } from "./format";
import type { TransferTriggerReason } from "./dashboard-schema";

const TRANSFER_REASON_LABELS: Readonly<Record<TransferTriggerReason, string>> = {
  skill_suggested_transfer: "Skill đề xuất chuyển CS",
  ai_response_requires_transfer:
    "Phản hồi AI được nhận diện là cần chuyển CS",
  missing_transaction_id: "Skill cần mã giao dịch nhưng ticket chưa có",
  max_replies_exceeded: "Khách tiếp tục hỏi sau 3 phản hồi AI",
  out_of_scope: "Bộ kiểm tra xác định nội dung ngoài phạm vi hỗ trợ",
  empty_message: "Tin nhắn không có nội dung",
  prompt_injection: "Phát hiện nội dung có dấu hiệu can thiệp hệ thống",
  output_check_error: "Lỗi bộ kiểm tra đầu ra",
  other_guardrail: "Điều kiện khác trên trace chuyển CS",
  unknown: "Chưa xác định được từ trace",
};

export function transferReasonLabel(reason: TransferTriggerReason): string {
  return TRANSFER_REASON_LABELS[reason];
}

export function formatMissingStepResult(
  count: number,
  denominator: number,
): string {
  const measured = `${formatCount(count)}/${formatCount(
    denominator,
  )} ticket chuyển CS`;
  if (count === 0) {
    return `${measured} không thiếu Step result.`;
  }

  const rate = count / denominator;
  const consequence =
    rate > 0.5
      ? "Phần lớn ca chuyển CS hiện chưa truy được tới bước lỗi cụ thể."
      : "Các ca này hiện chưa truy được tới bước lỗi cụ thể.";
  return `${measured} (${formatRate(
    rate,
  )}) không có Step result. ${consequence}`;
}
