# Monitoring workspace — design QA

## Visual truth and evidence

- Selected direction: the second displayed Product Design concept, monitoring with side facets and an inline rule editor.
- Source: [monitoring-reference.png](docs/design/monitoring-reference.png), 1487 × 1058 pixels. AI-generated concept with fictional data; original preserved outside the repository.
- Implementation: [monitoring-desktop.png](docs/design/monitoring-desktop.png), a browser-rendered fixture using the actual frontend and administrative rule routes. All names, identifiers and counts in committed captures are synthetic.
- Full-view paired input: [paired-desktop.png](docs/design/paired-desktop.png), source on the left and implementation on the right.
- Focused comparison: [paired-detail.png](docs/design/paired-detail.png), same selected, expanded group rule; controls and typography readable at native size.
- Other captures: [settings](docs/design/monitoring-settings.png), [mobile](docs/design/monitoring-mobile.png), [mobile editor and pagination](docs/design/monitoring-mobile-editor.png).

## Viewport and normalization

Desktop CSS viewport was verified as 1440 × 1024. Browser zoom was 90% (`devicePixelRatio=0.9`). The screenshot provider returned a padded 1600 × 1138 JPEG, containing the CSS viewport at the upper left. The actual 1440 × 1024 viewport was cropped without changing its contents and resized to the source's 1487 × 1058 dimensions for comparison. Earlier centered crops were rejected. The paired inputs above use the corrected viewport crop. Mobile CSS viewport was verified as 390 × 844; provider padding was removed. An additional 1012px working width had no document-level horizontal overflow.

## Findings and comparison history

1. **Initial / blocked — P1:** the incumbent table's `white-space:nowrap` leaked into the inline editor, overlapping explanatory text with switches. Fixed with explicit table/editor wrapping; post-fix paired detail has no overlap.
2. **Initial / blocked — P2:** the incumbent global cell rule kept the new table at 10px. Fixed with explicit 12px cells and 13px chat names; filters and editor labels use the corresponding readable scale.
3. **Initial / blocked — P2:** duplicated state copy and the expanded table pushed pagination out of the working viewport. RAG status now lives in the topbar, the table scroll region is bounded and the paginator remains outside it. At the verified desktop viewport its bottom was within the visible frame; mobile actions and pagination were reached and captured.
4. **Interaction pass / fixed:** clean default-rule inputs were rebuilt on every poll, potentially losing keyboard focus. Rendering now updates their contents only when the rule changes; drafts and the expanded row stay connected during polling. Cancel is disabled during an in-flight save.
5. **Final comparison / passed:** the source and corrected implementation were opened together in one full-view input and again as a focused editor pair. No actionable P0/P1/P2 differences remain for this scope.

## Required fidelity surfaces

- **Typography:** reused the project's Inter Cyrillic font. Source hierarchy is retained: 23px page title, 16–17px working headings, 12–13px table/controls, smaller secondary metadata. Long chat titles clamp to two lines; the full title is available in the editor and title tooltip. Fixed-row labels remain readable.
- **Spacing and layout:** retained the sidebar/topbar, compact queue strip, approximately 178px facet rail, dominant table and attached selected-row editor. Dividers and navy surfaces match the incumbent system. Forms wrap and pagination stays outside table scrolling. Mobile uses stacked monitor content, three facet columns and a table-local horizontal scroll region; the editor itself fits the phone width.
- **Colors and tokens:** reused the existing navy, blue, green, amber and red tokens, with explicit focus styles and semantic state text. Selection is blue; warnings describe retry state rather than exposing exception codes.
- **Assets:** reused the supplied TG paper-plane mark, Phosphor icon assets and font. No stock imagery, placeholder avatars, custom SVG illustrations or new raster product assets were needed. The queue chart is a canvas plot of supplied numerical samples.
- **Copy and content:** Russian UI preserves the real data contract. Private rules are fixed; group/channel rules are editable. RAG text and S3 binaries are separate. Existing data is retained when a rule changes. Model/server information is read-only.

## Intentional product constraints

- Total Telegram history is unknown: known coverage states replace the concept's invented history percentages.
- The backend has one queue history series, so no unsupported second chart series is fabricated.
- No invented chat descriptions, participant totals or per-chat byte totals are shown.
- Single-row expansion replaces inert selection checkboxes: there is no unrequested bulk action.
- Real page sizes are 10/25/50/100; the footer counts actual visible and filtered rows. The concept's eight-row/ten-per-page inconsistency is not reproduced.
- Activity pagination is explicitly bounded to the last 100 retained operations over 30 days.

## Interactions verified in the in-app browser

- Sidebar navigation and settings sub-tabs; default rules moved to Settings and individual rules expanded from a chat title.
- Next page (11–20 of 362), changing filters resets/clamps pagination, combined search, empty results and reset.
- Draft survives polling; other table navigation locks while a rule is dirty.
- Injected POST 503 retains input and enables retry; retry succeeds using the actual administrative route on synthetic state.
- Cancel resets a draft; private-chat switches and save are disabled.
- Injected status outage keeps last data, selection and filter state with a clear stale notice; recovery restores current status.
- Activity next page (11–20 of the bounded 100-event window).
- Keyboard focus, private rule guard, mobile editor, reachable save/cancel and pagination, and no document overflow at 390px and 1012px.
- No JavaScript runtime errors observed. HTTP 503 console entries were expected during injected failure tests.

## Follow-up polish

P3 only: source data and wording produce minor row-density differences from the concept. Native controls and exact per-chat statistics intentionally follow the product rather than decorative mock values.

## Implementation checklist

- [x] Selected reference resolved and inspected.
- [x] Working table filters, sorting, pagination and inline rule edits.
- [x] Stable polling, save/failure/retry and fixed private controls.
- [x] Settings organization and read-only service information.
- [x] Desktop, mobile and working-width browser evidence.
- [x] Corrected full-view and focused paired comparisons.

final result: passed
