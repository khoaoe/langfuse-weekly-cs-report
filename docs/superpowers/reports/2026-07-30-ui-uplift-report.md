# Report — UI uplift

## Baseline trước khi sửa (đo 2026-07-30, Chrome DevTools MCP)

| Chỉ số | 1440x900 | 390x844x3 mobile+touch |
|---|---|---|
| stickyHeight | 132px | 276px |
| tapTargetsUnder44 | — | 31 |
| pageOverflowX | false | false |
| thOffsetFromWrapTop | 134px | 134px |
| trendFirstBarX | dồn 1/3 phải | — |
| chiều cao trang | 4.972px | 6.638px |

Test: 687 pass, exit 0.

## Palette validator — cặp đã chốt

```
Palette (light, surface #fcfcfb, categorical): 2 slots
  [PASS] Lightness band         all 2 inside L 0.43–0.77
  [PASS] Chroma floor           all 2 >= 0.1
  [PASS] CVD separation         worst adjacent #A45F00↔#0068FF ΔE 33.0 (protan) · tritan 24.1
  [PASS] Normal-vision floor    worst adjacent #A45F00↔#0068FF ΔE 36.1 (normal)
  [PASS] Contrast vs surface    all 2 >= 3:1

  → ALL CHECKS PASS  (CVD in the 6–8 floor band is legal ONLY with secondary encoding: direct labels, gaps, or texture)
  scope: categorical palettes only. For a lone status/text color check WCAG text contrast; for a sequential ramp, lightness monotonicity.


Palette (dark, surface #1a1a19, categorical): 2 slots
  [PASS] Lightness band         all 2 inside L 0.48–0.67
  [PASS] Chroma floor           all 2 >= 0.1
  [PASS] CVD separation         worst adjacent #B07A2E↔#3B86E8 ΔE 26.4 (protan) · tritan 21.5
  [PASS] Normal-vision floor    worst adjacent #B07A2E↔#3B86E8 ΔE 27.8 (normal)
  [PASS] Contrast vs surface    all 2 >= 3:1

  → ALL CHECKS PASS  (CVD in the 6–8 floor band is legal ONLY with secondary encoding: direct labels, gaps, or texture)
  scope: categorical palettes only. For a lone status/text color check WCAG text contrast; for a sequential ramp, lightness monotonicity.
```

## Lô 1
<append sau khi xong>
