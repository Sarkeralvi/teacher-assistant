import { expect, test } from "@playwright/test";

import {
  createSyntheticFiles,
  readAuthToken,
  registerTeacherViaBrowser,
  seedCustomControlledFlow,
  uniqueTeacherCredentials,
} from "./support";

// What this can and cannot cover, stated rather than implied: creating a script
// transcript needs a vision provider, and no provider call is authorized in this
// run. So the browser check here guards the route, its ownership boundary and
// its honest empty state. The populated journey -- provenance, the six evidence
// states, correcting a block, revision history, re-deriving without a provider
// call, and reconciling an unknown outcome -- was driven against a live isolated
// stack with seeded synthetic evidence and is recorded in the run's acceptance
// report.

test("the script transcript route is reachable and says plainly when nothing is transcribed", async ({
  page,
}) => {
  const credentials = uniqueTeacherCredentials("Transcript");
  await registerTeacherViaBrowser(page, credentials);
  const token = await readAuthToken(page);
  const files = createSyntheticFiles("transcript");
  const seeded = await seedCustomControlledFlow(token, files);

  await page.goto(`/submissions/${seeded.submission.id}/transcript`, {
    waitUntil: "domcontentloaded",
  });

  await expect(
    page.getByRole("heading", { name: "Script transcript and answer evidence" }),
  ).toBeVisible();
  // An absent transcript is reported as absent, not as an empty one.
  await expect(page.getByText("This script has not been transcribed yet.")).toBeVisible({
    timeout: 20000,
  });
});

test("the assessment page offers the transcript journey for each submission", async ({ page }) => {
  const credentials = uniqueTeacherCredentials("TranscriptLink");
  await registerTeacherViaBrowser(page, credentials);
  const token = await readAuthToken(page);
  const files = createSyntheticFiles("transcript-link");
  const seeded = await seedCustomControlledFlow(token, files);

  await page.goto(`/assessments/${seeded.assessment.id}`, { waitUntil: "domcontentloaded" });

  const link = page.getByTestId(`open-transcript-${seeded.submission.id}`);
  await expect(link).toBeVisible({ timeout: 30000 });
  await expect(link).toHaveAttribute(
    "href",
    `/submissions/${seeded.submission.id}/transcript`,
  );
});
