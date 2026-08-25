"use client";

import { useEffect, useState } from "react";

import { getAnswerRegionImageUrl, getStoredAuthToken } from "../lib/api";

export type AnswerRegionImageLoadState = "loading" | "loaded" | "error";

type AuthenticatedAnswerRegionImageProps = {
  answerRegionId: number;
  alt: string;
  onLoadStateChange?: (answerRegionId: number, state: AnswerRegionImageLoadState) => void;
};

/**
 * Answer-region images are protected by the API's bearer authentication.  A
 * normal img/src or anchor cannot attach that header, so load the image as an
 * authenticated blob and only expose an in-memory object URL to the page.
 */
export function AuthenticatedAnswerRegionImage({
  answerRegionId,
  alt,
  onLoadStateChange,
}: Readonly<AuthenticatedAnswerRegionImageProps>) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    const token = getStoredAuthToken();

    setImageUrl(null);
    setError(null);
    onLoadStateChange?.(answerRegionId, "loading");

    async function loadImage() {
      if (!token) {
        throw new Error("Sign in again before reviewing protected answer evidence.");
      }
      const response = await fetch(getAnswerRegionImageUrl(answerRegionId), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error(`The prepared answer image could not be loaded (${response.status}).`);
      }
      const contentType = response.headers.get("content-type") ?? "";
      if (!contentType.startsWith("image/")) {
        throw new Error("The prepared answer evidence did not return an image.");
      }
      objectUrl = URL.createObjectURL(await response.blob());
      if (!active) return;
      setImageUrl(objectUrl);
      onLoadStateChange?.(answerRegionId, "loaded");
    }

    void loadImage().catch((reason: unknown) => {
      if (!active) return;
      const message = reason instanceof Error ? reason.message : "The prepared answer image could not be loaded.";
      setError(message);
      onLoadStateChange?.(answerRegionId, "error");
    });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [answerRegionId, onLoadStateChange]);

  if (error) {
    return <p className="rounded border border-red-800 bg-red-950/30 p-3 text-xs text-red-100">{error} Mapping confirmation is blocked until this is fixed.</p>;
  }

  if (!imageUrl) {
    return <p className="rounded border border-slate-700 bg-slate-950 p-3 text-xs text-slate-300">Loading the mapped answer image…</p>;
  }

  return (
    <figure className="grid gap-2 rounded border border-slate-700 bg-slate-950 p-2">
      <img className="max-h-[36rem] w-full rounded object-contain" src={imageUrl} alt={alt} />
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-300">
        <span>Exact prepared crop for this mapping. Check it before confirming.</span>
        <a className="text-cyan-300 underline" href={imageUrl} target="_blank" rel="noreferrer">Open image in new tab</a>
      </figcaption>
    </figure>
  );
}
