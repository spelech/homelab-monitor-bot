import { test, expect } from '@playwright/test';
import 'playwright-layout-inspector/matchers';

test.describe('Responsive Layout & Overflow Audits', () => {
  test.beforeEach(async ({ page }) => {
    // Mock all backend API routes for deterministic, isolated layout testing
    await page.route('**/api/dashboard', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          active_count: 1,
          resolved_count: 42,
          targets_count: 24,
          ignored_count: 2,
          maintenance_active: false,
          maintenance_reason: '',
          maintenance_until: null,
          autopilot: true,
          silent_mode: false,
          active_incidents: [
            {
              id: 'inc-sample-1',
              target_id: 'radarr4k',
              status: 'PENDING_USER',
              category: 'database',
              error_logs: 'Failed to deserialize JSON Apprise payload: syntax error',
              root_cause: 'Invalid boolean value in Apprise notifications table',
              proposed_fix: 'UPDATE Notifications SET Settings = REPLACE(Settings, \'"includePoster":0\', \'"includePoster":false\');',
              execution_log: null,
              created_at: new Date().toISOString(),
              completed_at: null,
            },
          ],
          ignored_targets: [],
          history_incidents: [
            {
              id: 'inc-hist-1',
              target_id: 'openscad',
              status: 'RESOLVED',
              category: 'caddy_route',
              error_logs: 'HTTP 401 Unauthorized bypass failed',
              root_cause: 'Missing @health matcher in Caddyfile',
              proposed_fix: 'Add handle /api/health* block before reverse_proxy in Caddyfile',
              execution_log: 'Applied Caddyfile update and restarted Caddy cleanly.',
              created_at: new Date(Date.now() - 3600000).toISOString(),
              completed_at: new Date().toISOString(),
            },
          ],
        }),
      });
    });

    await page.route('**/api/stacks', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            name: 'media_content',
            status: 'warning',
            containers: ['radarrhd', 'radarr4k', 'sonarrhd'],
            total_containers: 3,
            running_containers: 3,
            healthy_containers: 2,
            unhealthy_containers: 1,
            updates_available_count: 0,
            active_incidents_count: 1,
            last_audit: {
              id: 'audit-1',
              stack_name: 'media_content',
              status: 'WARNING',
              summary: '1 container has log errors',
              error_count: '3',
              containers_checked: '3',
              created_at: new Date().toISOString(),
            },
          },
          {
            name: 'smarthome',
            status: 'healthy',
            containers: ['homeassistant', 'mosquitto', 'zigbee2mqtt'],
            total_containers: 3,
            running_containers: 3,
            healthy_containers: 3,
            unhealthy_containers: 0,
            updates_available_count: 0,
            active_incidents_count: 0,
            last_audit: null,
          },
        ]),
      });
    });

    await page.route('**/api/upgrades/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          active: false,
          current_job: null,
        }),
      });
    });

    await page.route('**/api/upgrades/runs', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });

    await page.route('**/api/usage/summary', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_spend: 0.28,
          active_model: 'opencode/claude-3-5-sonnet',
          total_tokens: 124000,
        }),
      });
    });

    await page.route('**/api/targets', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            id: 'radarr4k',
            type: 'docker',
            is_ignored: false,
            ignored_until: null,
            docker_status: 'running',
            docker_health: 'healthy',
          },
        ]),
      });
    });

    await page.route('**/api/audits/daily*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          {
            date: new Date().toISOString().slice(0, 10),
            total_stacks: 25,
            healthy_count: 24,
            warning_count: 1,
            outages_count: 0,
            stack_audits: [
              {
                id: 'audit-today-1',
                stack_name: 'media_content',
                status: 'WARNING',
                summary: 'Radarr4k JSON error in logs',
                error_count: '2',
                containers_checked: '4',
                created_at: new Date().toISOString(),
              },
            ],
            actionable_items: [
              {
                incident_id: 'inc-sample-1',
                target_id: 'radarr4k',
                stack_name: 'media_content',
                status: 'PENDING_USER',
                category: 'database',
                root_cause: 'Invalid boolean value in Apprise notifications table',
                proposed_fix: 'UPDATE Notifications SET Settings = REPLACE(Settings, \'"includePoster\":0\', \'"includePoster\":false\');',
                can_action: true,
                created_at: new Date().toISOString(),
                deferred_until: null,
              },
            ],
          },
        ]),
      });
    });

    await page.route('**/api/incidents/*/transcript', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          events: [
            {
              timestamp: new Date().toISOString(),
              type: 'PROMPT_GENERATED',
              data: { prompt: 'Investigate radarr4k log syntax errors' },
            },
          ],
        }),
      });
    });
  });

  test('main dashboard has zero layout overflow and fits viewport', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app-container')).toBeVisible();

    // Assert zero DOM horizontal overflow
    await expect(page).toHaveNoLayoutOverflow();

    // Assert mobile viewport metadata compliance
    await expect(page).toHaveMobileFit();
  });

  test('stack SRE tab renders cleanly without overflow', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app-container')).toBeVisible();

    // Click Stack SRE tab
    await page.click('button:has-text("Stack SRE")');
    await page.waitForTimeout(300);

    await expect(page).toHaveNoLayoutOverflow();
  });

  test('incident modal dialog fits within mobile viewport with zero bleed', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app-container')).toBeVisible();

    // Click View Error Logs button to open modal
    await page.click('button:has-text("View Error Logs")');
    await expect(page.locator('.modal-backdrop')).toBeVisible();

    await expect(page).toHaveNoLayoutOverflow();

    // Close modal
    await page.click('button:has-text("Close")');
    await expect(page.locator('.modal-backdrop')).not.toBeVisible();
  });

  test('upgrade and canary hub tab renders cleanly without overflow', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app-container')).toBeVisible();

    await page.click('button:has-text("Upgrade & Canary Hub")');
    await page.waitForTimeout(300);

    await expect(page).toHaveNoLayoutOverflow();
  });

  test('daily audits tab and bulk remediation controls render cleanly without overflow', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app-container')).toBeVisible();

    // Click Daily Audits tab
    await page.click('button:has-text("Daily Audits")');
    await page.waitForTimeout(300);

    // Verify view has loaded
    await expect(page.locator('text=30-Day Daily SRE Audits')).toBeVisible();
    await expect(page).toHaveNoLayoutOverflow();

    // Select the actionable item to trigger the bulk remediation toolbar
    await page.click('button[title*="Select item for bulk remediation"]');
    await expect(page.locator('text=item(s) selected')).toBeVisible();

    // Assert zero layout overflow with bulk toolbar visible
    await expect(page).toHaveNoLayoutOverflow();
  });
});
