import { AppShell } from "../../../../components/AppShell";
import { CustomControlledGradingRunClient } from "../../../../components/CustomControlledGradingRunClient";

type Props = {
  params: Promise<{ assessmentId: string }>;
};

export default async function CustomControlledGradingRunPage({ params }: Props) {
  const { assessmentId } = await params;
  return (
    <AppShell>
      <CustomControlledGradingRunClient assessmentId={Number(assessmentId)} />
    </AppShell>
  );
}
