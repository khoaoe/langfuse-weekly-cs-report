import type { ReactNode } from "react";

const FRESHDESK_TICKET_BASE_URL =
  "https://vngzalopay.freshdesk.com/a/tickets/";
const VALID_TICKET_ID_PATTERN = /^[1-9]\d{0,19}$/;

export function isValidFreshdeskTicketId(ticketId: string): boolean {
  return VALID_TICKET_ID_PATTERN.test(ticketId);
}

export function FreshdeskTicketLink({
  ticketId,
  className,
  children,
}: {
  readonly ticketId: string;
  readonly className?: string | undefined;
  readonly children?: ReactNode;
}) {
  const content = children ?? ticketId;
  if (!isValidFreshdeskTicketId(ticketId)) {
    return <>{content}</>;
  }

  return (
    <a
      className={className}
      href={`${FRESHDESK_TICKET_BASE_URL}${ticketId}`}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={`Mở ticket ${ticketId} trên Freshdesk trong thẻ mới`}
    >
      {content}
    </a>
  );
}
