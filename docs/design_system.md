# Design System — Credit Desk

## Brief

**Product:** A credit decisioning console used inside a retail lending operation.
**Primary users:** credit officers (score applications), risk analysts (find where risk
concentrates), lending policy managers (set and test cut-offs).
**Primary job:** *"Where is my risk, and should I approve this application?"*

The v1 app answered a coursework rubric. This version answers a job.

## What changed and why

| v1 (coursework) | v2 (product) | Reason |
|---|---|---|
| 10 flat pages named after rubric items ("Analytical Questions", "Findings & Recommendations") | 7 pages grouped into *Portfolio / Decisioning / Governance* | Users navigate by task, not by report section |
| Emoji navigation labels | Material Symbols, grouped `st.navigation` | Emoji reads as hobby project |
| KPIs truncate (`$119,8…`) | Compact notation (`$119.8K`) in a custom KPI component | Never hide a number in a financial tool |
| Filtered KPIs show no comparison | Every KPI shows delta vs. whole book | A filter that changes nothing must *look* like it changed nothing |
| Simulator = form → probability | Underwriting workspace: decision, reason codes, sensitivity, decision record | Adverse-action explainability is a legal requirement, not a nicety |
| No cut-off control | Live approval-threshold tuner with business trade-off | This is the number a bank actually tunes |
| No exceptions view | Policy-breach watchlist queue | Finance dashboards are work queues wearing charts |
| Single hardcoded dataset | Upload your own book + batch scoring | Required for real use |

## Tokens

### Colour

Deliberately *not* navy-and-gold (the default "bank" costume the v1 app wore), and not the
cream/terracotta or near-black/acid-green palettes.

| Token | Hex | Role |
|---|---|---|
| `INK` | `#1B2430` | Primary text, headings |
| `INK_SOFT` | `#5B6879` | Labels, secondary text |
| `BORDER` | `#DDE2EA` | Hairlines, card edges |
| `CANVAS` | `#F3F5F8` | App background (cool neutral) |
| `SURFACE` | `#FFFFFF` | Cards, tables |
| `BRAND` | `#0B6B62` | Deep teal — primary action, brand |
| `BRAND_DEEP` | `#07453F` | Navigation rail, depth |
| `BRAND_TINT` | `#E4F1EF` | Selected states, callouts |
| `LOW` | `#1F7A5C` | Low risk |
| `MED` | `#C2721A` | Medium risk |
| `HIGH` | `#A32C2C` | High risk |

Risk colours are desaturated on purpose. Traffic-light saturation is for dashboards that
want to look urgent; a credit book wants to look *measured*.

### Type

One family — **IBM Plex Sans** (400/500/600/700). It was drawn for enterprise data
interfaces and its tabular figures line up in columns, which is the whole job here.
No serif display face: a second family would be decoration, and the weight/size scale
already carries the hierarchy.

All figures use `font-variant-numeric: tabular-nums`. This is functional, not stylistic —
digits must not shift width between rows of a loan table.

Scale: 30 / 22 / 16 / 14 / 12.5 / 11.5 px. Headings sentence case, tight tracking
(`-0.015em`). No tracked-out all-caps eyebrows.

### Layout

Left-aligned throughout, 1360px max. Persistent nav rail, page header with a live context
line, filter bar, then content. Density is high on purpose — the user is a professional
comparing segments, not a consumer glancing at a balance.

```
┌──────────┬──────────────────────────────────────────────┐
│ rail     │ page title                                    │
│ (teal,   │ context line: 2,000 applications · no filters │
│  grouped)├───────────────────────────────────────────────┤
│          │ [ KPI ][ KPI ][ KPI ][ KPI ]  ← each w/ rail  │
│ ───────  ├──────────────────────┬────────────────────────┤
│ filters  │ primary chart        │ exceptions queue       │
│ ───────  ├──────────────────────┴────────────────────────┤
│ book     │ supporting analysis                           │
└──────────┴───────────────────────────────────────────────┘
```

### The signature element: the band rail

Credit risk is the study of *where a number crosses a line*. Rather than spend the design
budget on gradient washes or a card kit, it goes into one recurring component: a thin
horizontal rail showing policy bands and a marker for where this value actually sits.

```
 policy bands →  ▓▓▓▓▓▓▓▓░░░░░░░░▒▒▒▒▒▒▒▒████████
 value marker →          ▼
                 <20%    20-30%   30-45%   45%+
```

It appears under KPIs, beside every DTI figure, in the segment table, and as the centrepiece
of the underwriting decision. One idea, used consistently, so a user learns to read it once.

Everything else stays quiet: hairline borders, no drop shadows except a 1px lift on the
active card, one border-radius (6px) for containers and 3px for chips.

## Principles

1. **One number answers the first question.** Everything else is one level down.
2. **Comparison is mandatory.** A metric without a baseline is trivia.
3. **Thresholds are drawn, not described.**
4. **Every model output carries its reasons.** No score without reason codes.
5. **Product language, not coursework language.** "Score an application", not "Applicant
   What-If Simulator". "Risk drivers", not "Analytical Questions".
6. **The disclaimer is in the workflow, not a banner people scroll past.**
