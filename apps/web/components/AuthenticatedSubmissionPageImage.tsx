"use client";

import { useEffect, useState } from "react";

import { getStoredAuthToken, getSubmissionPageImageUrl } from "../lib/api";
import { fetchProtectedImageResponse } from "./AuthenticatedAnswerRegionImage";

type Props = { pageId: number; label: string };

/** Load a private source page with bearer auth and keep it out of public URLs. */
export function AuthenticatedSubmissionPageImage({ pageId, label }: Readonly<Props>) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setImageUrl(null);
    setError(null);

    async function load() {
      const token = getStoredAuthToken();
      if (!token) throw new Error("Sign in again before reviewing this page.");
      const response = await fetchProtectedImageResponse(getSubmissionPageImageUrl(pageId), token);
      if (!response.ok) throw new Error(`The source page could not be loaded (${response.status}).`);
      if (!(response.headers.get("content-type") ?? "").startsWith("image/")) {
        throw new Error("The source-page endpoint did not return an image.");
      }
      objectUrl = URL.createObjectURL(await response.blob());
      if (active) setImageUrl(objectUrl);
    }

    void load().catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "The page could not be loaded.");
    });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [pageId]);

  if (error) return <p className="rounded border border-red-300 bg-red-50 p-3 text-xs text-red-800">{error}</p>;
  if (!imageUrl) return <p className="rounded border border-slate-200 p-3 text-xs text-slate-500">Loading complete source page…</p>;
  return (
    <figure className="rounded border border-slate-200 bg-slate-50 p-2">
      <div className="max-h-[48rem] overflow-auto">
        {/* Private bearer-authenticated Blob URL; next/image cannot fetch it server-side. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="h-auto w-full" src={imageUrl} alt={label} />
      </div>
      <figcaption className="mt-2 text-right text-xs">
        <a className="underline" href={imageUrl} target="_blank" rel="noreferrer">Open full page</a>
      </figcaption>
    </figure>
  );
}
