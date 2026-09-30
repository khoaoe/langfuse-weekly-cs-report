import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { MultiSelectField } from "../src/components/MultiSelectField";

const OPTIONS = [
  { value: "get_bank_name:UNKNOWN_BANK_CODE", label: "get_bank_name:UNKNOWN_BANK_CODE" },
  { value: "get_bank_info:NO_DATA", label: "get_bank_info:NO_DATA" },
];

function ControlledField() {
  const [value, setValue] = useState("");
  return (
    <MultiSelectField
      id="toolErrorCodesInput"
      label="Lỗi gọi tool"
      options={OPTIONS}
      value={value}
      onChange={setValue}
      hasValueLabel="Chỉ ticket có lỗi"
    />
  );
}

describe("MultiSelectField has-value radio (C6)", () => {
  it("distinguishes default, has-value, and manual-selection states via the summary text", async () => {
    const user = userEvent.setup();
    render(<ControlledField />);

    expect(
      screen.getByRole("button", { name: "Lỗi gọi tool: Tất cả" }),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: /^Lỗi gọi tool:/ }));
    const panel = document.getElementById("toolErrorCodesInput") as HTMLElement;

    const allRadio = within(panel).getByRole("radio", { name: "Tất cả" });
    const hasValueRadio = within(panel).getByRole("radio", {
      name: "Chỉ ticket có lỗi",
    });
    expect(allRadio).toBeChecked();
    expect(hasValueRadio).not.toBeChecked();

    await user.click(hasValueRadio);
    expect(
      screen.getByRole("button", { name: "Lỗi gọi tool: Chỉ ticket có lỗi" }),
    ).toBeVisible();

    // Ticking any checkbox snaps the radio back to "Tất cả" -- manual
    // selection and "has value" mode are mutually exclusive.
    await user.click(
      within(panel).getByRole("checkbox", {
        name: "get_bank_name:UNKNOWN_BANK_CODE",
      }),
    );
    expect(
      screen.getByRole("button", {
        name: "Lỗi gọi tool: get_bank_name:UNKNOWN_BANK_CODE",
      }),
    ).toBeVisible();
    expect(within(panel).getByRole("radio", { name: "Tất cả" })).toBeChecked();

    expect(
      within(panel).getByRole("button", { name: "Xoá lựa chọn" }),
    ).toBeVisible();
  });

  it("keeps the clear-selection button visible while has-value mode is active", async () => {
    const user = userEvent.setup();
    render(<ControlledField />);

    await user.click(screen.getByRole("button", { name: /^Lỗi gọi tool:/ }));
    const panel = document.getElementById("toolErrorCodesInput") as HTMLElement;

    expect(
      within(panel).queryByRole("button", { name: "Xoá lựa chọn" }),
    ).toBeNull();

    await user.click(
      within(panel).getByRole("radio", { name: "Chỉ ticket có lỗi" }),
    );
    const clearButton = within(panel).getByRole("button", {
      name: "Xoá lựa chọn",
    });
    expect(clearButton).toBeVisible();

    await user.click(clearButton);
    expect(
      screen.getByRole("button", { name: "Lỗi gọi tool: Tất cả" }),
    ).toBeVisible();
  });
});

describe("MultiSelectField search", () => {
  const many = [
    "Chuyển CS",
    "Đổi mật khẩu",
    ...Array.from({ length: 8 }, (_, index) => `Nhóm ${index}`),
  ].map((label) => ({ value: label, label }));

  it("appears only once the list outgrows the panel", async () => {
    const user = userEvent.setup();
    render(
      <MultiSelectField id="few" label="Ít" options={OPTIONS} value="" onChange={() => {}} />,
    );
    await user.click(screen.getByRole("button", { name: /^Ít:/ }));
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("filters options ignoring case and Vietnamese accents", async () => {
    const user = userEvent.setup();
    render(
      <MultiSelectField id="many" label="Nhiều" options={many} value="" onChange={() => {}} />,
    );
    await user.click(screen.getByRole("button", { name: /^Nhiều:/ }));
    const panel = document.getElementById("many") as HTMLElement;

    await user.type(screen.getByRole("searchbox", { name: "Tìm trong Nhiều" }), "chuyen");
    expect(
      within(panel)
        .getAllByRole("checkbox")
        .map((box) => box.closest("label")?.textContent),
    ).toEqual(["Chuyển CS"]);

    await user.clear(screen.getByRole("searchbox"));
    await user.type(screen.getByRole("searchbox"), "doi");
    expect(within(panel).getByRole("checkbox", { name: "Đổi mật khẩu" })).toBeVisible();

    await user.type(screen.getByRole("searchbox"), "zzz");
    expect(within(panel).queryAllByRole("checkbox")).toHaveLength(0);
    expect(within(panel).getByText("Không có lựa chọn khớp")).toBeVisible();
  });
});
