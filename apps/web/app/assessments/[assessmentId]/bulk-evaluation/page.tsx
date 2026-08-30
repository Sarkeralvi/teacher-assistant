import { AppShell } from "../../../../components/AppShell";
import { BulkEvaluationClient } from "../../../../components/BulkEvaluationClient";

type Props = { params: Promise<{ assessmentId: string }> };

export default async function BulkEvaluationPage({ params }: Readonly<Props>) {
  const { assessmentId } = await params;
  return <AppShell><BulkEvaluationClient assessmentId={Number(assessmentId)} /></AppShell>;
}
