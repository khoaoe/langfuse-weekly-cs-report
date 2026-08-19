import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MarkdownLite } from "../src/components/MarkdownLite";

describe("MarkdownLite", () => {
  it("renders **bold** as a <strong> element", () => {
    render(<MarkdownLite text="Giao dịch **thành công** rồi bạn nhé." />);
    const strong = screen.getByText("thành công");
    expect(strong.tagName).toBe("STRONG");
  });

  it("renders a block of '- ' lines as a bullet list", () => {
    render(<MarkdownLite text={"Thông tin:\n\n- Tên: Thẻ Data\n- Số tiền: 36.000đ"} />);
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Tên: Thẻ Data");
    expect(items[1]).toHaveTextContent("Số tiền: 36.000đ");
  });

  it("keeps non-bullet paragraphs as plain text, blank-line separated", () => {
    render(<MarkdownLite text={"Đoạn một.\n\nĐoạn hai."} />);
    expect(screen.getByText("Đoạn một.")).toBeInTheDocument();
    expect(screen.getByText("Đoạn hai.")).toBeInTheDocument();
  });

  it("does not treat a single dash mid-sentence as a bullet", () => {
    render(<MarkdownLite text="Mã GD: 260813-002120041 that bai." />);
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });
});
