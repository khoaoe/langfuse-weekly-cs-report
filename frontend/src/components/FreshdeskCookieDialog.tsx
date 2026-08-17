import { useEffect, useRef, useState, type FormEvent } from "react";

import dashboardStyles from "./dashboard.module.css";
import csatStyles from "./csat-section.module.css";

const MIN_COOKIE_LENGTH = 20;
const MAX_COOKIE_LENGTH = 8_000;

export interface FreshdeskCookieDialogProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onSubmit: (cookie: string) => Promise<boolean>;
}

/**
 * Cookie-entry dialog for the Freshdesk UI-API transport (spec
 * 2026-08-12-freshdesk-cookie-crawl-design.md SS6.2). Only opens when a user
 * explicitly clicks a trigger -- the CSAT section's CTA or the header chip.
 */
export function FreshdeskCookieDialog({
  open,
  onClose,
  onSubmit,
}: FreshdeskCookieDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [cookie, setCookie] = useState("");
  const [status, setStatus] = useState<
    "idle" | "checking" | "success" | "error"
  >("idle");

  useEffect(() => {
    const node = dialogRef.current;
    if (node === null) {
      return;
    }
    if (open && !node.open) {
      setStatus("idle");
      node.showModal();
    } else if (!open && node.open) {
      node.close();
    }
  }, [open]);

  useEffect(() => {
    const node = dialogRef.current;
    if (node === null) {
      return;
    }
    const handleClose = () => {
      setCookie("");
      setStatus("idle");
      onClose();
    };
    node.addEventListener("close", handleClose);
    return () => node.removeEventListener("close", handleClose);
  }, [onClose]);

  const trimmed = cookie.trim();
  const looksValid =
    trimmed.length >= MIN_COOKIE_LENGTH &&
    trimmed.length <= MAX_COOKIE_LENGTH &&
    trimmed.includes("=");
  const canSubmit = looksValid && status !== "checking";

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    setStatus("checking");
    void (async () => {
      const ok = await onSubmit(trimmed);
      if (ok) {
        setStatus("success");
        window.setTimeout(() => {
          dialogRef.current?.close();
        }, 1_500);
      } else {
        setStatus("error");
      }
    })();
  };

  return (
    <dialog
      ref={dialogRef}
      className={csatStyles.cookieDialog}
      aria-labelledby="freshdesk-cookie-title"
    >
      <form
        method="dialog"
        className={csatStyles.cookieForm}
        onSubmit={handleSubmit}
      >
        <h2 id="freshdesk-cookie-title" className={csatStyles.cookieTitle}>
          Kết nối Freshdesk
        </h2>
        <ol className={csatStyles.cookieSteps}>
          <li>
            Mở{" "}
            <a
              href="https://vngzalopay.freshdesk.com"
              target="_blank"
              rel="noreferrer"
            >
              Freshdesk
            </a>{" "}
            và đăng nhập
          </li>
          <li>
            DevTools (F12) → tab Network → bấm một ticket bất kỳ → chọn
            request bất kỳ → copy toàn bộ giá trị header{" "}
            <code>Cookie</code>
          </li>
          <li>Dán vào ô dưới</li>
        </ol>
        <label className={csatStyles.cookieField} htmlFor="freshdeskCookieInput">
          <span>Cookie</span>
          <textarea
            id="freshdeskCookieInput"
            rows={4}
            autoComplete="off"
            spellCheck={false}
            value={cookie}
            disabled={status === "checking"}
            onChange={(event) => {
              setCookie(event.target.value);
              if (status === "error") {
                setStatus("idle");
              }
            }}
          />
        </label>
        {status === "error" ? (
          <p className={csatStyles.cookieMessageError} role="alert">
            Cookie không hợp lệ hoặc đã hết hạn. Lấy lại cookie mới rồi thử
            lại.
          </p>
        ) : null}
        {status === "success" ? (
          <p className={csatStyles.cookieMessageSuccess} role="status">
            Cookie hợp lệ, đã lưu. Dữ liệu sẽ cập nhật trong lượt chạy kế
            tiếp.
          </p>
        ) : null}
        <div className={csatStyles.cookieActions}>
          <button
            type="button"
            className={dashboardStyles.action}
            onClick={() => dialogRef.current?.close()}
          >
            Đóng
          </button>
          <button
            type="submit"
            className={dashboardStyles.action}
            disabled={!canSubmit}
          >
            {status === "checking" ? "Đang kiểm tra…" : "Kiểm tra và lưu"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
