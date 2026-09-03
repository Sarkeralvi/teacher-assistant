"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getAnswerRegionImageUrl,
  getAnswerRegionSegmentImageUrl,
  getStoredAuthToken,
} from "../lib/api";

export type AnswerRegionImageLoadState = "loading" | "loaded" | "error";

export type EditingDecisionOverlay = {
  bbox: [number, number, number, number] | number[];
  status: "cancelled" | "replacement" | "retained" | "uncertain_correction";
  decisionIndex: number;
};

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
  editingDecisions?: EditingDecisionOverlay[];
};

type ProtectedAnswerImageProps = {
  imageUrl: string;
  alt: string;
  caption: string;
  loadingLabel: string;
  onLoadStateChange?: (state: AnswerRegionImageLoadState) => void;
  editingDecisions?: EditingDecisionOverlay[];
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
  editingDecisions = [],
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
      <div className="relative mx-auto w-fit max-w-full">
        {/* This is a bearer-authenticated in-memory Blob URL. next/image cannot fetch it server-side. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img className="block max-h-[36rem] max-w-full rounded object-contain" src={imageUrl} alt={alt} />
        {editingDecisions.map((decision) => {
          const [x1, y1, x2, y2] = decision.bbox;
          const color = decision.status === "cancelled"
            ? "border-red-500 bg-red-500/20 text-red-50"
            : decision.status === "replacement" || decision.status === "retained"
              ? "border-emerald-400 bg-emerald-400/20 text-emerald-50"
              : "border-amber-400 bg-amber-400/20 text-amber-50";
          return (
            <div
              key={`${decision.decisionIndex}-${decision.status}`}
              className={`pointer-events-none absolute border-2 ${color}`}
              style={{
                left: `${x1 / 10}%`,
                top: `${y1 / 10}%`,
                width: `${(x2 - x1) / 10}%`,
                height: `${(y2 - y1) / 10}%`,
              }}
              aria-label={`Editing decision ${decision.decisionIndex + 1}: ${decision.status}`}
            >
              <span className="absolute -top-5 left-0 rounded bg-slate-950 px-1 text-[10px]">
                {decision.decisionIndex + 1}
              </span>
            </div>
          );
        })}
      </div>
      {editingDecisions.length > 0 ? (
        <p className="text-[11px] text-slate-300">
          <span className="text-red-300">Red = excluded cancellation</span> · <span className="text-emerald-300">green = visible replacement or retained work</span> · <span className="text-amber-300">amber = uncertain correction</span>
        </p>
      ) : null}
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
  editingDecisions = [],
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
      editingDecisions={editingDecisions}
    />
  );
}
