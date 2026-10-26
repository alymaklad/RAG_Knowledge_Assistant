import { expect, test, type Page } from "@playwright/test";

// Demo account created by backend/scripts/seed_demo.py (local development only).
const EMAIL = process.env.E2E_EMAIL ?? "demo@example.edu";
const PASSWORD = process.env.E2E_PASSWORD ?? "demo-password-123";

async function signIn(page: Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Courses", level: 1 })).toBeVisible();
}

test("sign in, open materials, ask a question and see a cited answer", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: /CS 221/ }).first().click();

  await page.getByRole("link", { name: "Materials" }).click();
  await expect(page.getByText("week06_bayesian_networks.pdf")).toBeVisible();

  await page.getByRole("link", { name: "Ask" }).click();
  const box = page.getByPlaceholder("Ask about your materials");
  await box.fill("What is a Markov blanket?");
  await box.press("Enter");

  await expect(page).toHaveURL(/\/chat\/[0-9a-f-]{36}$/);
  // A citation marker in the answer and a matching sidenote in the margin.
  await expect(page.getByRole("button", { name: /^Source \d+$/ }).first()).toBeVisible({
    timeout: 90_000,
  });
  await expect(page.getByRole("button", { name: /Open source \d+: week06/ }).first()).toBeVisible();
  await expect(page.locator("mark.marker").first()).toBeVisible();
});

test("unknown course id shows a not-found message", async ({ page }) => {
  await signIn(page);
  await page.goto("/courses/00000000-0000-0000-0000-000000000000/chat");
  await expect(page.getByText("Course not found.")).toBeVisible();
});
