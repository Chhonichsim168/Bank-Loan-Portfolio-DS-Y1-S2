# Credit Desk v21 — portfolio filter bar

Built on v20. No change to the model, data, policy rules, calculations or database.

## What changed
* The portfolio filters moved **out of the sidebar** into a **filter bar at the top of the four
  pages that use them**: Portfolio overview, Segments, Approval drivers, Policy and cut-offs.
* Pages that do not use the filters (Score an application, Score a file, Loan book, Decision queue,
  Model performance, Data and governance, User management, My account) no longer show them, so a
  filter change never looks like it "did nothing".
* The bar is one white card:
  * the five filters side by side: Period, Property area, Employment, Risk tier, Outcome
    (plus From - to when Period = Custom range);
  * the result in large type: **514** of 2,000 applications · 26%;
  * one chip per active filter (e.g. `Period: 01 Oct 2025 – 30 Sep 2026 ✕`, `Area: Urban ✕`,
    `Risk: High ✕`): click a chip to remove just that filter; **Clear all** removes every filter;
  * "Showing the whole book" when no filter is on.
* Filters are kept while moving between pages, including through pages without the bar
  (`src/state.py: init` writes the values back each run).
* The sidebar now holds only the menu, the signed-in user / Sign out and the source footer.

## Files
* new `views/_filters.py` (the bar); `views/overview.py`, `segments.py`, `drivers.py`, `policy.py`
  call `filter_bar(c)` in place of the old one-line context bar;
* `app.py` (sidebar filters removed), `src/state.py`, `src/ui.py` (styles);
* tests: new `tests/test_v21.py` (11 tests). Full suite: **227 passed**.
