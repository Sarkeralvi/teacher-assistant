import { AppShell } from "../../../../components/AppShell";
import { CustomControlledGradingRunClient } from "../../../../components/CustomControlledGradingRunClient";

type Props = {
  params: Promise<{ assessmentId: string }>;
  searchParams?: Promise<{ mode?: string }>;
};

export default async function CustomControlledGradingRunPage({ params, searchParams }: Props) {
  const { assessmentId } = await params;
  const resolvedSearchParams = searchParams ? await searchParams : undefined;
  const mode = resolvedSearchParams?.mode;
  if (mode === "semi_automated" || mode === "fully_automated") {
    return (
      <AppShell>
        <ModeUnavailableNotice mode={mode} />
      </AppShell>
    );
  }
  return (
    <AppShell>
      <CustomControlledGradingRunClient assessmentId={Number(assessmentId)} mode="custom_controlled" />
    </AppShell>
  );
}

function ModeUnavailableNotice({ mode }: Readonly<{ mode: "semi_automated" | "fully_automated" }>) {
  return (
    <section className="rounded border border-amber-700 bg-amber-950/40 p-6 text-amber-100" data-testid="grading-mode-unavailable">
      <p className="text-sm uppercase tracking-wide text-amber-200">Mode unavailable</p>
      <h1 className="mt-2 text-3xl font-semibold">
        {mode === "semi_automated" ? "Semi-Automated" : "Fully Automated"} grading is not ready
      </h1>
      <p className="mt-3 max-w-2xl text-sm text-amber-50">
        {mode === "semi_automated"
          ? "Mode 'semi_automated' is not available for teacher workflow yet. Use Custom Controlled."
          : "Mode 'fully_automated' is not available for teacher workflow yet. Use Custom Controlled."}
      </p>
      <p className="mt-3 text-sm text-amber-100">Custom Controlled remains the only teacher-ready grading workflow.</p>
    </section>
  );
}
