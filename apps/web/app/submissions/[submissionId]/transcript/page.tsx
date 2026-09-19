import ScriptTranscriptReviewClient from "../../../../components/ScriptTranscriptReviewClient";

type PageProps = {
  params: Promise<{ submissionId: string }>;
};

export default async function ScriptTranscriptPage({ params }: Readonly<PageProps>) {
  const { submissionId } = await params;
  return (
    <main className="mx-auto max-w-5xl p-6">
      <h1 className="text-2xl font-semibold">Script transcript and answer evidence</h1>
      <p className="mt-1 text-sm text-slate-600">
        The script as it was read, once, and what each question&apos;s answer is based on.
      </p>
      <div className="mt-6">
        <ScriptTranscriptReviewClient submissionId={Number(submissionId)} />
      </div>
    </main>
  );
}
