import { AppShell } from "../../../../components/AppShell";
import { CustomControlledGradingRunClient } from "../../../../components/CustomControlledGradingRunClient";

type Props = {
  params: Promise<{ assessmentId: string }>;
  searchParams?: Promise<{ mode?: string }>;
};

export default async function CustomControlledGradingRunPage({ params, searchParams }: Props) {
  const { assessmentId } = await params;
  const resolvedSearchParams = searchParams ? await searchParams : undefined;
  const mode = resolvedSearchParams?.mode === "semi_automated" ? "semi_automated" : "custom_controlled";
  return (
    <AppShell>
      <CustomControlledGradingRunClient assessmentId={Number(assessmentId)} mode={mode} />
    </AppShell>
  );
}
