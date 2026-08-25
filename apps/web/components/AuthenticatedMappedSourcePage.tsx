"use client";

import { useEffect, useState } from "react";

import {
  getStoredAuthToken,
  getSubmissionPageImageUrl,
  type AnswerRegionSegment,
} from "../lib/api";
import { type AnswerRegionImageLoadState } from "./AuthenticatedAnswerRegionImage";

type AuthenticatedMappedSourcePageProps = {
  answerRegionId: number;
  segment: AnswerRegionSegment;
  label: string;
  onLoadStateChange?: (
    answerRegionId: number,
    segmentId: number,
    state: AnswerRegionImageLoadState,
  ) => void;
};

/** Show the complete source page with the stored crop rectangle highlighted. */
export function AuthenticatedMappedSourcePage({
  answerRegionId,
  segment,
  label,
  onLoadStateChange,
}: Readonly<AuthenticatedMappedSourcePageProps>) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [dimensions, setDimensions] = useState<{ width: number; height: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    const token = getStoredAuthToken();

    setImageUrl(null);
    setDimensions(null);
    setError(null);
    onLoadStateChange?.(answerRegionId, segment.id, "loading");

    async function loadImage() {
      if (!token) {
        throw new Error("Sign in again before reviewing the protected source page.");
      }
      const response = await fetch(getSubmissionPageImageUrl(segment.page_id), {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error(`The complete source page could not be loaded (${response.status}).`);
      }
      const contentType = response.headers.get("content-type") ?? "";
      if (!contentType.startsWith("image/")) {
        throw new Error("The source-page endpoint did not return an image.");
      }
      objectUrl = URL.createObjectURL(await response.blob());
      if (active) setImageUrl(objectUrl);
    }

    void loadImage().catch((reason: unknown) => {
      if (!active) return;
      const message = reason instanceof Error ? reason.message : "The source page could not be loaded.";
      setError(message);
      onLoadStateChange?.(answerRegionId, segment.id, "error");
    });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [answerRegionId, onLoadStateChange, segment.id, segment.page_id]);

  if (error) {
    return <p className="rounded border border-red-800 p-3 text-xs text-red-100">{error} Region confirmation is blocked.</p>;
  }
  if (!imageUrl) {
    return <p className="rounded border border-slate-700 p-3 text-xs text-slate-300">Loading complete source page…</p>;
  }

  const x = Number(segment.x);
  const y = Number(segment.y);
  const width = Number(segment.width);
  const height = Number(segment.height);
  const validBox = dimensions && [x, y, width, height].every(Number.isFinite) && width > 0 && height > 0;

  return (
    <figure className="grid gap-2 rounded border border-amber-700 bg-slate-950 p-2">
      <div className="max-h-[48rem] overflow-auto">
        <div className="relative w-full">
          <img
            className="h-auto w-full"
            src={imageUrl}
            alt={label}
            onLoad={(event) => {
              const next = {
                width: event.currentTarget.naturalWidth,
                height: event.currentTarget.naturalHeight,
              };
              setDimensions(next);
              onLoadStateChange?.(answerRegionId, segment.id, "loaded");
            }}
          />
          {validBox ? (
            <span
              aria-label="Stored answer crop boundary"
              className="pointer-events-none absolute border-4 border-red-600 bg-red-500/10 shadow-[0_0_0_2px_rgba(255,255,255,0.9)]"
              style={{
                left: `${(x / dimensions.width) * 100}%`,
                top: `${(y / dimensions.height) * 100}%`,
                width: `${(width / dimensions.width) * 100}%`,
                height: `${(height / dimensions.height) * 100}%`,
              }}
            />
          ) : null}
        </div>
      </div>
      <figcaption className="flex flex-wrap items-center justify-between gap-2 text-xs text-amber-100">
        <span>Red rectangle = exact stored crop. Confirm only if it contains the complete answer.</span>
        <a className="text-cyan-300 underline" href={imageUrl} target="_blank" rel="noreferrer">Open full page</a>
      </figcaption>
    </figure>
  );
}
