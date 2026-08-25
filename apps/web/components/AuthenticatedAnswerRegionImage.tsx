"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getAnswerRegionImageUrl,
  getAnswerRegionSegmentImageUrl,
  getStoredAuthToken,
} from "../lib/api";

export type AnswerRegionImageLoadState = "loading" | "loaded" | "error";

export async function fetchProtectedImageResponse(url: string, token: string): Promise<Response> {
  try {
    return await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  } catch (error) {
    if (!(error instanceof TypeError)) throw error;
    await new Promise<void>((resolve) => window.setTimeout(resolve, 250));
    return fetch(url, { headers: { Authorization: `Bearer ${token}` } });
  }
}

type AuthenticatedAnswerRegionImageProps = {
  answerRegionId: number;
  alt: string;
  onLoadStateChange?: (answerRegionId: number, state: AnswerRegionImageLoadState) => void;
};

type AuthenticatedAnswerRegionSegmentImageProps = {
  answerRegionId: number;
  segmentId: number;
  orderIndex: number;
  alt: string;
  onLoadStateChange?: (
    answerRegionId: number,
    segmentId: number,
    state: AnswerRegionImageLoadState,
  ) => void;
};

type ProtectedAnswerImageProps = {
  imageUrl: string;
  alt: string;
  caption: string;
  loadingLabel: string;
  onLoadStateChange?: (state: AnswerRegionImageLoadState) => void;
};

/**
 * Answer-region images are protected by the API's bearer authentication.  A
 * normal img/src or anchor cannot attach that header, so load the image as an
 * authenticated blob and only expose an in-memory object URL to the page.
 */
function ProtectedAnswerImage({
  imageUrl: protectedImageUrl,
  alt,
  caption,
  loadingLabel,
  onLoadStateChange,
}: Readonly<ProtectedAnswerImageProps>) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    const token = getStoredAuthToken();

    setImageUrl(null);
    setError(null);
    onLoadStateChange?.("loading");

    async function loadImage() {
      if (!token) {
        throw new Error("Sign in again before reviewing protected answer evidence.");
      }
      const response = await fetchProtectedImageResponse(protectedImageUrl, token);
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
      onLoadStateChange?.("loaded");
    }

    void loadImage().catch((reason: unknown) => {
      if (!active) return;
      const message = reason instanceof Error ? reason.message : "The prepared answer image could not be loaded.";
      setError(message);
      onLoadStateChange?.("error");
    });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [onLoadStateChange, protectedImageUrl]);

  if (error) {
    return <p className="rounded border border-red-800 bg-red-950/30 p-3 text-xs text-red-100">{error} Mapping confirmation is blocked until this is fixed.</p>;
  }

  if (!imageUrl) {
    return <p className="rounded border border-slate-700 bg-slate-950 p-3 text-xs text-slate-300">{loadingLabel}</p>;
  }

  return (
    <figure className="grid gap-2 rounded border border-slate-700 bg-slate-950 p-2">
      <img className="max-h-[36rem] w-full rounded object-contain" src={imageUrl} alt={alt} />
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-300">
        <span>{caption}</span>
        <a className="text-cyan-300 underline" href={imageUrl} target="_blank" rel="noreferrer">Open image in new tab</a>
      </figcaption>
    </figure>
  );
}

export function AuthenticatedAnswerRegionImage({
  answerRegionId,
  alt,
  onLoadStateChange,
}: Readonly<AuthenticatedAnswerRegionImageProps>) {
  const handleLoadStateChange = useCallback(
    (state: AnswerRegionImageLoadState) => onLoadStateChange?.(answerRegionId, state),
    [answerRegionId, onLoadStateChange],
  );
  return (
    <ProtectedAnswerImage
      imageUrl={getAnswerRegionImageUrl(answerRegionId)}
      alt={alt}
      caption="Exact prepared crop for this mapping. Check it before confirming."
      loadingLabel="Loading the mapped answer image…"
      onLoadStateChange={handleLoadStateChange}
    />
  );
}

export function AuthenticatedAnswerRegionSegmentImage({
  answerRegionId,
  segmentId,
  orderIndex,
  alt,
  onLoadStateChange,
}: Readonly<AuthenticatedAnswerRegionSegmentImageProps>) {
  const handleLoadStateChange = useCallback(
    (state: AnswerRegionImageLoadState) => onLoadStateChange?.(answerRegionId, segmentId, state),
    [answerRegionId, onLoadStateChange, segmentId],
  );
  return (
    <ProtectedAnswerImage
      imageUrl={getAnswerRegionSegmentImageUrl(answerRegionId, segmentId)}
      alt={alt}
      caption={`Answer segment ${orderIndex} in reading order. All segments below are sent together for transcription.`}
      loadingLabel={`Loading answer segment ${orderIndex}…`}
      onLoadStateChange={handleLoadStateChange}
    />
  );
}
