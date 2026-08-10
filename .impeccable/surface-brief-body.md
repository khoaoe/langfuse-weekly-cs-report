# Weekly CS dashboard surface

- Mode: Operate.
- Audience: CS lead, PO, dev and CS agent.
- Job: read weekly state, copy the report, diagnose the largest gap and reach
  exact privacy-safe tickets.
- Primary target: `frontend/index.html`.
- Approved comp: `.impeccable/mocks/weekly-ledger-c-approved.png`.
- Direction: table-led command sheet inside the “Sổ điều hành tuần” world.
- Memorable moment: dynamic title and narrative share one horizontal band with
  a four-cell decision ledger; the action rail then hands directly into the
  Weekly Report.
- Constraints: preserve API/metric/privacy contracts, 1440×900 above-fold
  state/report, 390×844 reflow, strict same-origin CSP and no invented data.

## Fidelity inventory

| Visible ingredient | Implementation medium | Commitment |
|---|---|---|
| Official horizontal logo | Existing brand asset | Preserve geometry and clearspace |
| Compact two-row app shell | Semantic HTML/CSS | Sticky footprint within measured budget |
| Cropped Z at shell edge | Existing brand asset/CSS crop | One use only |
| Dynamic title and narrative | Semantic HTML | Deterministic real data only |
| Four-cell decision ledger | CSS grid + semantic text | Shared baseline, no floating cards |
| Action rail | Semantic list | Only actionable warnings |
| Weekly Report | Semantic table/TanStack Table | 14 columns, 13 compact rows |
| Aligned trends | Accessible SVG/Visx | Shared week positions, separate units |
| Segment and diagnostic areas | Tables/lists | Dense rules, no card mosaic |
| Mobile adaptation | CSS media/container rules | 2×2 ledger and local table scroll |

Do not literalize invented metric names, agent rows, dates or values shown by
the generative comp.
