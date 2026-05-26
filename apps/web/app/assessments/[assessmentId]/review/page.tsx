import { AssessmentReviewClient } from "../../../../components/AssessmentReviewClient";

type PageProps = {
  params: Promise<{ assessmentId: string }>;
};

export default async function AssessmentReviewPage({ params }: Readonly<PageProps>) {
  const { assessmentId } = await params;
  return <AssessmentReviewClient assessmentId={Number(assessmentId)} />;
}
