import { AppShell } from "../../../components/AppShell";
import { QuestionDetailClient } from "../../../components/QuestionDetailClient";

type Props = {
  params: Promise<{ questionId: string }>;
};

export default async function QuestionDetailPage({ params }: Props) {
  const { questionId } = await params;
  return (
    <AppShell>
      <QuestionDetailClient questionId={Number(questionId)} />
    </AppShell>
  );
}
