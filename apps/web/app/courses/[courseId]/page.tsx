import { AppShell } from "../../../components/AppShell";
import { CourseDetailClient } from "../../../components/CourseDetailClient";

type Props = {
  params: Promise<{ courseId: string }>;
};

export default async function CourseDetailPage({ params }: Props) {
  const { courseId } = await params;
  return (
    <AppShell>
      <CourseDetailClient courseId={Number(courseId)} />
    </AppShell>
  );
}
