import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AppShell } from "../src/components/AppShell";
import { server } from "./msw/server";

function renderShell() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AppShell
        weekDefinition="mon_sun"
        onWeekDefinitionChange={() => {}}
        snapshot={null}
        statusMessage=""
        onRefresh={() => {}}
        refreshDisabled={false}
        refreshHint=""
        runtimeKind="loading"
        activeFilters={[]}
        onRemoveFilter={() => {}}
        onResetFilters={() => {}}
      >
        <section id="weekly">Dashboard body</section>
      </AppShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  server.use(
    http.get("/api/trace-explain/:ticketId", ({ params }) =>
      HttpResponse.json({
        ticket_id: String(params.ticketId),
        turns: [],
        langfuse_url: "https://langfuse.zalopay.vn/project/x/traces",
      }),
    ),
  );
});

afterEach(() => {
  window.location.hash = "";
});

describe("AppShell hash routing", () => {
  it("renders the dashboard children when the hash is not a trace route", () => {
    window.location.hash = "#weekly";
    renderShell();

    expect(screen.getByText("Dashboard body")).toBeInTheDocument();
    expect(screen.queryByText("Vì sao agent làm vậy")).not.toBeInTheDocument();
  });

  it("renders TraceExplainer instead of the dashboard body for #trace/<id>", () => {
    window.location.hash = "#trace/12345";
    renderShell();

    expect(screen.getByText("Vì sao agent làm vậy")).toBeInTheDocument();
    expect(screen.queryByText("Dashboard body")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Mã ticket")).toHaveValue("12345");
  });

  it("reacts to a hashchange after mount (e.g. the browser Back button)", async () => {
    window.location.hash = "#weekly";
    renderShell();
    expect(screen.getByText("Dashboard body")).toBeInTheDocument();

    window.location.hash = "#trace/999";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(await screen.findByText("Vì sao agent làm vậy")).toBeInTheDocument();

    window.location.hash = "#weekly";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(await screen.findByText("Dashboard body")).toBeInTheDocument();
  });

  it("treats a bare #trace hash as trace mode with no ticket selected yet", () => {
    window.location.hash = "#trace";
    renderShell();

    expect(screen.getByText("Vì sao agent làm vậy")).toBeInTheDocument();
    expect(screen.getByText("Dán mã ticket ở trên để xem.")).toBeInTheDocument();
  });

  it("shows only a minimal header in trace mode -- brand and theme toggle, no dashboard controls", () => {
    window.location.hash = "#trace/12345";
    renderShell();

    expect(screen.getByText("Báo cáo hiệu quả CS Agent")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Giao diện hiện tại/ }),
    ).toBeInTheDocument();
    // Dashboard-only chrome must not leak into the focused trace view --
    // TraceExplainer's own "Quay lại dashboard" link is the way back instead.
    expect(screen.queryByRole("link", { name: "Báo cáo tuần" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Làm mới" })).not.toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Định nghĩa tuần" })).not.toBeInTheDocument();
  });
});
