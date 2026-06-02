import { expect, test } from "@playwright/test";

import { browserAuthSmoke, uniqueTeacherCredentials } from "./support";

test("auth smoke registers, logs out, and logs back in through the browser", async ({ page }) => {
  const credentials = uniqueTeacherCredentials("AuthSmoke");

  await browserAuthSmoke(page, credentials);

  await expect(page.getByTestId("current-teacher")).toContainText(credentials.name);
  await expect(page.getByTestId("current-teacher")).toContainText(credentials.email);
});
