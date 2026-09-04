"use client";

import { buttonClass, inputClass } from "./AppShell";
import type { BrainProfile, GradingRun } from "../lib/api";

type Props = {
  profiles: BrainProfile[];
  requiredCapability: string;
  run: GradingRun | null;
  selectedProfileId: string;
  consentConfirmed: boolean;
  busy: boolean;
  onProfileChange: (profileId: string) => void;
  onConsentChange: (confirmed: boolean) => void;
  onLock: () => void;
};

export function BrainProfileSelector({
  profiles,
  requiredCapability,
  run,
  selectedProfileId,
  consentConfirmed,
  busy,
  onProfileChange,
  onConsentChange,
  onLock,
}: Readonly<Props>) {
  const matchingProfiles = profiles.filter((profile) =>
    profile.capabilities.includes(requiredCapability),
  );
  const locked = Boolean(run?.brain_profile_id);
  const selectedProfile = profiles.find(
    (profile) => profile.id === (run?.brain_profile_id ?? selectedProfileId),
  );
  const consentRequired = Boolean(
    selectedProfile && !["local", "mock"].includes(selectedProfile.data_destination),
  );
  const canLock = Boolean(
    run &&
      selectedProfile?.ready &&
      selectedProfile.capabilities.includes(requiredCapability) &&
      (!consentRequired || consentConfirmed),
  );

  return (
    <section
      className="grid gap-3 rounded-xl border border-cyan-800/70 bg-cyan-950/20 p-4"
      data-testid="brain-profile-selector"
    >
      <div>
        <p className="font-semibold text-cyan-100">Brain provider profile</p>
        <p className="mt-1 text-xs text-slate-300">
          Choose a ready profile that supports {requiredCapability.replaceAll("_", " ")}.
          The choice is locked to this grading run.
        </p>
      </div>
      <label className="grid gap-2 text-sm text-slate-200">
        Provider profile
        <select
          className={inputClass}
          data-testid="brain-profile-select"
          disabled={busy || locked || !run}
          value={selectedProfile?.id ?? ""}
          onChange={(event) => onProfileChange(event.target.value)}
        >
          <option value="">Select a profile</option>
          {matchingProfiles.map((profile) => (
            <option disabled={!profile.ready} key={profile.id} value={profile.id}>
              {profile.display_name} · {profile.model} · {profile.data_destination}
              {profile.ready ? "" : " · not ready"}
            </option>
          ))}
        </select>
      </label>
      {selectedProfile ? (
        <p className="text-xs text-slate-300" data-testid="brain-profile-summary">
          {selectedProfile.vendor} · {selectedProfile.transport} · endpoint {selectedProfile.endpoint}
          {selectedProfile.ready ? " · ready" : ` · ${selectedProfile.readiness_detail}`}
        </p>
      ) : null}
      {consentRequired ? (
        <label
          className="flex items-start gap-3 rounded border border-amber-700/60 bg-amber-950/30 p-3 text-sm text-amber-100"
          data-testid="brain-profile-consent"
        >
          <input
            className="mt-1"
            type="checkbox"
            checked={consentConfirmed}
            disabled={busy || locked}
            onChange={(event) => onConsentChange(event.target.checked)}
          />
          <span>
            I authorize transfer of the explicitly requested grading evidence to this
            non-local provider. Outputs remain drafts requiring teacher review.
          </span>
        </label>
      ) : null}
      {run ? (
        locked ? (
          <p className="text-sm text-emerald-200" data-testid="brain-profile-locked">
            Locked to {selectedProfile?.display_name ?? run.brain_profile_id} for grading run #{run.id}.
          </p>
        ) : (
          <div>
            <button
              className={buttonClass}
              disabled={busy || !canLock}
              type="button"
              onClick={onLock}
            >
              Lock profile for this grading run
            </button>
          </div>
        )
      ) : (
        <p className="text-sm text-amber-200">Create a grading run before selecting a profile.</p>
      )}
      {matchingProfiles.length === 0 ? (
        <p className="text-sm text-amber-200">No registered profile supports this capability.</p>
      ) : null}
    </section>
  );
}
