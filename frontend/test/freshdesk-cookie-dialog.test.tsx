import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { FreshdeskCookieDialog } from "../src/components/FreshdeskCookieDialog";

function Harness({
  onSubmit,
}: {
  readonly onSubmit: (cookie: string) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(true);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        reopen
      </button>
      <FreshdeskCookieDialog
        open={open}
        onClose={() => setOpen(false)}
        onSubmit={onSubmit}
      />
    </>
  );
}

describe("FreshdeskCookieDialog", () => {
  it("keeps the submit button disabled until the input looks like a cookie", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);

    const submit = screen.getByRole("button", { name: "Kiểm tra và lưu" });
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText("Cookie"), "too-short");
    expect(submit).toBeDisabled();

    await user.type(screen.getByLabelText("Cookie"), "=abcdefghijklmnop");
    expect(submit).toBeEnabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("shows the failure message and preserves the input on an invalid cookie", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(false);
    render(<Harness onSubmit={onSubmit} />);

    const textarea = screen.getByLabelText("Cookie");
    await user.type(textarea, "cs_session=stale-value-1234567890");
    await user.click(screen.getByRole("button", { name: "Kiểm tra và lưu" }));

    expect(onSubmit).toHaveBeenCalledWith("cs_session=stale-value-1234567890");
    expect(
      await screen.findByText(
        "Cookie không hợp lệ hoặc đã hết hạn. Lấy lại cookie mới rồi thử lại.",
      ),
    ).toBeInTheDocument();
    expect(textarea).toHaveValue("cs_session=stale-value-1234567890");
  });

  it("shows success then auto-closes on a valid cookie", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(true);
    render(<Harness onSubmit={onSubmit} />);

    await user.type(
      screen.getByLabelText("Cookie"),
      "cs_session=fresh-value-1234567890",
    );
    await user.click(screen.getByRole("button", { name: "Kiểm tra và lưu" }));

    expect(
      await screen.findByText(
        "Cookie hợp lệ, đã lưu. Dữ liệu sẽ cập nhật trong lượt chạy kế tiếp.",
      ),
    ).toBeInTheDocument();

    await waitFor(
      () => {
        expect(document.querySelector("dialog")).not.toHaveAttribute("open");
      },
      { timeout: 3_000 },
    );
  });

  it("never puts the cookie value in the DOM outside the textarea", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn().mockResolvedValue(false);
    const { container } = render(<Harness onSubmit={onSubmit} />);

    await user.type(
      screen.getByLabelText("Cookie"),
      "cs_session=super-secret-token-value",
    );
    await user.click(screen.getByRole("button", { name: "Kiểm tra và lưu" }));
    await screen.findByRole("alert");

    const textarea = screen.getByLabelText("Cookie") as HTMLTextAreaElement;
    const restOfDom = container.innerHTML.replace(textarea.outerHTML, "");
    expect(restOfDom).not.toContain("super-secret-token-value");
  });
});
