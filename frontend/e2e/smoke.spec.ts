import { expect, test } from "@playwright/test";

const nav = (page: import("@playwright/test").Page, name: string) =>
  page.getByRole("navigation", { name: "Main" }).getByRole("link", { name });

test("agent plans, asks approval with per-item moves, applies, then a rejected run, history and tools", async ({
  page,
}) => {
  await page.goto("/");

  // run 1: approve only one of two proposed moves
  await page.getByLabel("What should the agent do?").fill("Organize my invoices into a Billing folder");
  await page.getByRole("button", { name: /Run/ }).click();
  const card = page.getByRole("group", { name: "Approval required" });
  await expect(card).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("⏸ Waiting for approval")).toBeVisible();
  await expect(card.getByLabel("Move invoices/jan.txt")).toBeChecked();
  await card.getByLabel("Move invoices/feb.txt").uncheck();
  await card.getByRole("button", { name: "Approve (1)" }).click();
  await expect(page.getByText("Moved 1 invoice file(s) into Billing/.")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Approved", { exact: true })).toBeVisible();

  // run 2 (LangGraph runtime): reject with a reason
  await page.getByRole("button", { name: "LangGraph" }).click();
  await page.getByLabel("What should the agent do?").fill("Organize the rest");
  await page.getByRole("button", { name: /Run/ }).click();
  const card2 = page.getByRole("group", { name: "Approval required" });
  await expect(card2).toBeVisible({ timeout: 15_000 });
  await card2.getByRole("button", { name: "Reject…" }).click();
  await card2.getByLabel("Rejection reason").fill("not today");
  await card2.getByRole("button", { name: "Confirm reject" }).click();
  await expect(page.getByText("OK, I left everything unchanged.")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Reason: not today")).toBeVisible();

  // history replay
  await nav(page, "History").click();
  await expect(page.getByRole("row", { name: /Organize my invoices/ })).toBeVisible();
  await page
    .getByRole("row", { name: /Organize my invoices/ })
    .getByRole("button", { name: "Replay" })
    .click();
  await expect(
    page.getByRole("region", { name: "Replay" }).getByText("Moved 1 invoice file(s) into Billing/."),
  ).toBeVisible();

  // tools page lists the allow-list
  await nav(page, "Tools").click();
  await expect(page.getByRole("heading", { name: "move_file" })).toBeVisible();
  await expect(page.getByText("needs approval").first()).toBeVisible();
});
