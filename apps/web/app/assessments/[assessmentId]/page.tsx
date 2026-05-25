import { AppShell } from "../../../components/AppShell";
import { AssessmentDetailClient } from "../../../components/AssessmentDetailClient";

type Props = {
  params: Promise<{ assessmentId: string }>;
};

export default async function AssessmentDetailPage({ params }: Props) {
  const { assessmentId } = await params;
  return (
    <AppShell>
      <AssessmentDetailClient assessmentId={Number(assessmentId)} />
    </AppShell>
  );
}
