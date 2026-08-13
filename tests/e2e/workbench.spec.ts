import { expect, test } from "@playwright/test";

test("loads the repository research workbench", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("SourcedGrid", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "GitHub Repository Radar" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Run research|Pause|Resume/ })).toBeVisible();
  await expect(page.getByText(/repositories · 12 fields/)).toBeVisible();
});

test("opens import and encrypted credential flows", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Add repositories" })).toBeVisible();
  await page.getByPlaceholder(/openai\/openai-python/).fill("https://github.com/encode/httpx");
  await page.getByRole("button", { name: "Cancel" }).click();

  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("heading", { name: "Credentials & LLM providers" })).toBeVisible();
  await expect(page.getByLabel(/GitHub token/)).toHaveAttribute("type", "password");
});

test("opens the visual column DAG and run history", async ({ page }) => {
  await page.goto("/");
  const dag = page.getByRole("button", { name: "Edit DAG" });
  if (await dag.isEnabled()) {
    await dag.click();
    await expect(page.getByRole("dialog", { name: "Grid schema editor" })).toBeVisible();
    await expect(page.getByText("Column DAG")).toBeVisible();
    await page.getByRole("button", { name: /close/i }).last().click();
  }
  await page.getByRole("button", { name: /Run log/ }).click();
  await expect(page.getByRole("heading", { name: "Run history" })).toBeVisible();
});
