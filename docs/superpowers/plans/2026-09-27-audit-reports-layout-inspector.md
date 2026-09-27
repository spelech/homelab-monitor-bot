# Daily Audit Reports & Playwright Layout Inspector Implementation Plan

> **Goal:** Integrate `@spelech/playwright-layout-inspector` to audit and fix desktop, tablet, and mobile layouts in MonitorBot. Add a dedicated 30-day Daily SRE Audits view with actionable item breakdowns and bulk-action execution controls.

---

## 1. Requirements & User Stories

1. **Playwright Layout Inspector Integration:**
   - Install and configure `@spelech/playwright-layout-inspector` and `@playwright/test` in `frontend/`.
   - Configure multi-device testing: Desktop (`1280x800`), Tablet (`768x1024`), and Mobile (`375x667`).
   - Audit for DOM overflow (horizontal scrolling bugs), touch target sizes (minimum 44px for primary interactions), and responsive card/modal fit.
   - Refactor CSS in `frontend/src/styles/` (`global.css`, `components.css`) to resolve all layout overflow and responsiveness issues.

2. **Dedicated 30-Day Daily Audit Reports Page:**
   - Backend API:
     - `GET /api/audits/daily?days=30`: Aggregates the last 30 days of daily SRE audit runs from `stack_audits` and links any actionable `Incident` records (`origin == "sre_daily_audit"` or matching audit day).
     - `POST /api/audits/actions/bulk`: Executes actions (`fix`, `dismiss`, `defer`, `ignore`) across multiple incident IDs in a single atomic request.
   - Frontend UI:
     - Add `'audits'` tab to `TabNavigation.tsx` with calendar/report icon and badge indicator for active actionable items.
     - Build `DailyAuditsView.tsx`:
       - 30-day timeline date picker / accordion.
       - Visual summary card for the selected day: Total Stacks, Clean Stacks, Attention Items, Outages.
       - Prominent **Actionable Items Section** with checkboxes, individual "Apply Fix" / "Dismiss" buttons, and a sticky Bulk Action toolbar (`Fix Selected`, `Dismiss Selected`, `Defer Selected`).
       - Detailed Stack Audit breakdown grid with status badges and searchable/expandable logs.

---

## 2. File Architecture & Changes

### Backend (`/containers/dev/homelab-monitor-bot`)
* **[app/routers/audits.py](file:///containers/dev/homelab-monitor-bot/app/routers/audits.py)**: New router exposing `GET /api/audits/daily` and `POST /api/audits/actions/bulk`.
* **[app/main.py](file:///containers/dev/homelab-monitor-bot/app/main.py)**: Register `audits.router`.
* **[tests/test_routers_audits.py](file:///containers/dev/homelab-monitor-bot/tests/test_routers_audits.py)**: Unit and integration tests for daily audits aggregation and bulk actions.

### Frontend (`/containers/dev/homelab-monitor-bot/frontend`)
* **`package.json`**: Add `@playwright/test` and `playwright-layout-inspector`.
* **`playwright.config.ts`**: Configure multi-viewport projects (Desktop, Tablet, Mobile) and local test server.
* **`tests/e2e/layout.spec.ts`**: Playwright test suite using `LayoutInspector` to assert zero overflow and mobile fit.
* **`src/types/audit.ts`**: TypeScript models for `DailyAuditReport`, `StackAuditSummary`, `ActionableAuditItem`.
* **`src/hooks/useDailyAudits.ts`**: Custom React hook for fetching 30-day reports and dispatching individual & bulk actions.
* **`src/views/DailyAuditsView.tsx`**: The dedicated 30-day audit reports view with bulk-action controls.
* **`src/components/TabNavigation.tsx`**: Add `audits` tab.
* **`src/App.tsx`**: Mount `DailyAuditsView` on active tab `'audits'`.
* **`src/styles/global.css` & `src/styles/components.css`**: Responsive media queries for desktop, tablet, and mobile.

---

## 3. Step-by-Step Task Breakdown

### Task 1: Backend 30-Day Audits Aggregation & Bulk Action API
1. Write failing tests in `tests/test_routers_audits.py`:
   - Test `GET /api/audits/daily?days=30` returns array of 30 days grouped by date.
   - Test `POST /api/audits/actions/bulk` triggers fixes and returns processed count.
2. Implement `app/routers/audits.py`.
3. Register router in `app/main.py`.
4. Run `pytest -m "not live"` to verify pass.
5. Commit: `feat(api): add 30-day daily audits aggregation and bulk remediation endpoints`.

### Task 2: Playwright Layout Inspector & E2E Test Suite Setup
1. Configure `frontend/playwright.config.ts` with desktop (`1280x800`), tablet (`768x1024`), and mobile (`375x667`).
2. Write `frontend/tests/e2e/layout.spec.ts` using `LayoutInspector` from `playwright-layout-inspector`.
3. Run `npx playwright test` to expose current responsive layout overflow issues.
4. Commit: `test(e2e): add Playwright Layout Inspector multi-viewport audit suite`.

### Task 3: Responsive CSS Overhaul (Desktop, Tablet, Mobile)
1. In `frontend/src/styles/global.css`:
   - Ensure `overflow-x: hidden` on root containers.
   - Update grid utilities (`.grid-cols-2`, `.grid-cols-3`, `.grid-cols-4`) to transition smoothly from 1 col (mobile) to 2 cols (tablet) to 3-4 cols (desktop).
2. In `frontend/src/styles/components.css`:
   - Add responsive styles for `.app-container`, `Navbar`, `StatusHeader`, and `TabNavigation` (scrollable tabs on mobile without line breaking).
   - Add responsive adjustments for `.card`, `.stat-card`, and `.modal-content` (full-screen or 95vw on mobile).
   - Ensure button touch targets on mobile have minimum 44px height.
3. Run `npx playwright test` to verify zero DOM overflow and passing layout audits across all 3 viewports.
4. Commit: `fix(ui): responsive layout adjustments for desktop, tablet, and mobile`.

### Task 4: Frontend Daily Audits View & Bulk Remediation Components
1. Create `src/types/audit.ts` and `src/hooks/useDailyAudits.ts`.
2. Build `src/views/DailyAuditsView.tsx` with:
   - 30-day timeline selector.
   - Day summary metrics (Stacks, Outages, Warnings, Clean).
   - Actionable items list with checkboxes, "Apply Fix Now" button, and bulk action toolbar.
   - Stack breakdown grid with status tags.
3. Wire into `TabNavigation.tsx` and `App.tsx`.
4. Run `npm run build` to verify clean compilation.
5. Commit: `feat(ui): add 30-day daily audits view with bulk remediation controls`.

### Task 5: End-to-End Verification & Production Deployment
1. Run Playwright layout inspector tests across desktop, tablet, and mobile.
2. Run full pytest suite (`pytest -m "not live"`).
3. Build production bundle (`npm run build`) and sync to `/containers/monitorbot/frontend/dist/`.
4. Sync backend to `/containers/monitorbot/app/`.
5. Restart `monitorbot.service` and verify live endpoints and layout rendering.
6. Push commits to `spelech/homelab-monitor-bot.git`.
