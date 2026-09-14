# Hair Studio 360 methodology

These are editable planning scenarios using the owner's requested values. Baseline hair measurements are entered by the user; they are not measured from an uploaded photo. Images illustrate a scenario and cannot establish exact follicle counts or clinical efficacy.

## Six-month presets

| Protocol | Density gain | Diameter gain in μm | Alternative diameter gain in % |
|---|---:|---:|---:|
| 1565 nm Er:glass | +13–15 hairs/cm²; default 14 | +5–8; default 6.5 | +15–22%; default 18.5% |
| 40 kHz ultrasound + serum | +31% | +10–15; default 12.5 | +30–44%; default 37% |
| Laser + ultrasound + serum | +35–40%; default 37.5% | +18–25; default 21.5 | +45–60%; default 52.5% |

The owner's combined thickness ranges include trailing plus signs. These do not define known biological maxima. The displayed 25 μm / 60% endpoints are editable scenario choices, not an upper confidence bound. Defaults are arithmetic midpoints, not study means. Combined-protocol gains replace standalone gains; they are never added or multiplied together.

An absolute micron change and a percentage change are alternative methods. For a 40 μm baseline, +12.5 μm produces 52.5 μm; +37% produces 54.8 μm. The app displays the selected method rather than treating these as identical.

## Research assessment

1. Qu et al. (2024), *1565 nm non-ablative fractional laser versus minoxidil for androgenetic alopecia*, DOI [10.1111/jocd.16173](https://doi.org/10.1111/jocd.16173). The 1565 nm arm changed from 61.55 to 63.93 μm at week 10, a +2.38 μm difference. A button applies this measured reference as an alternative thickness assumption. Applying it at six months is an extrapolation, not the study endpoint.
2. Lee et al. (2011), *The effect of a 1550 nm fractional erbium-glass laser in female pattern hair loss*, DOI [10.1111/j.1468-3083.2011.04183.x](https://doi.org/10.1111/j.1468-3083.2011.04183.x). This related 1550 nm study reported 58 to 75 μm over five months. It does not validate an identical 1565 nm protocol or the supplied +5–8 μm range.
3. [Alma TED manufacturer data](https://almainc.com/product/alma-ted/) reports density +23% at month one and +31% at month six for its protocol, based on data on file (N=31). A separate reported shedding figure concerns reduced shedding, not established complete cessation in 3–4 weeks. Generalization to a different 40 kHz device or serum is an assumption.

The exact ultrasound and combined numerical thickness ranges were not verified in a primary clinical study. They remain the owner's requested scenarios in the code. The app does not describe them as the highest achievable biological response or guaranteed re-terminalization. Shedding is qualitative context and never drives graft savings.

## Calculations

For each region, A is measured area, D baseline terminal hairs/cm², R the responsive fraction, and G the transplant-alone graft count.

- Baseline terminal hairs = A × D.
- Laser added hairs = A × absolute density gain × R.
- Other protocols added hairs = A × D × density gain percentage × R.
- R is set to zero if baseline terminal density is zero. This conservative model does not invent responsive follicles in bald regions.
- Native shaft diameter after treatment = baseline diameter + selected diameter increment × R. New and existing terminal hairs share that zone-level diameter assumption. Transplanted shaft diameter is not predicted.
- Effective hairs per graft Y = average hairs per graft × survival fraction × visible-growth fraction.
- Month-six defaults: 2 hairs/graft, 90% survival, 60% visible growth. These are editable planning assumptions. Mature mode uses 100% visibility, and clearly identifies the staged comparison against a six-month non-surgical response.
- Transplant-alone added visible hairs = G × Y.
- Combined graft count = max(0, min(G, ceil((G × Y − non-surgical added hairs) / Y))).
- Saved grafts = G − combined graft count.

Each zone is calculated separately before totals are added. Gains in the crown cannot substitute for hairline grafts. Remaining grafts are rounded upward. Non-surgical-only treatment always has zero transplanted grafts; a theoretical graft equivalent is not an actual graft procedure. If non-surgical gain exceeds a zone's target, combined grafts reach zero and excess hairs remain visible in the result totals.

Count and density represent the same endpoint over a fixed area; they never count as two independent improvements. Thickness never reduces calculated graft requirements. The combined estimate meets or exceeds the modeled terminal-hair count target at the same comparison horizon. Equal cosmetic results, surgical feasibility and long-term stability are not established by this arithmetic.
