// External-CDN player photos and club badges with a graceful fallback: on load error
// the <img> swaps to a neutral monogram chip, so an offline or missing asset never
// breaks the row and never implies a different player/club.

import { useState } from "react";
import { playerPhotoUrl, teamBadgeUrl } from "@/lib/images";
import { cn } from "@/lib/utils";

const SIZES = {
  sm: "size-5 text-[8px]",
  md: "size-7 text-[9px]",
} as const;

interface AvatarProps {
  className?: string;
  size?: keyof typeof SIZES;
}

export function PlayerPhoto({
  code,
  name,
  className,
  size = "md",
}: AvatarProps & { code: number; name: string }) {
  const [failed, setFailed] = useState(false);
  const box = SIZES[size];
  if (failed) {
    return (
      <span
        aria-hidden
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-sm bg-muted font-semibold text-muted-foreground",
          box,
          className,
        )}
      >
        {name.slice(0, 2).toUpperCase()}
      </span>
    );
  }
  return (
    <img
      src={playerPhotoUrl(code)}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      className={cn("shrink-0 rounded-sm bg-muted object-cover object-top", box, className)}
    />
  );
}

export function TeamBadge({
  teamCode,
  shortName,
  className,
  size = "sm",
}: AvatarProps & { teamCode: number; shortName: string }) {
  const [failed, setFailed] = useState(false);
  const box = SIZES[size];
  if (failed) {
    return (
      <span
        aria-hidden
        className={cn(
          "inline-flex shrink-0 items-center justify-center rounded-sm bg-muted font-semibold text-muted-foreground",
          box,
          className,
        )}
      >
        {shortName.slice(0, 3).toUpperCase()}
      </span>
    );
  }
  return (
    <img
      src={teamBadgeUrl(teamCode)}
      alt=""
      loading="lazy"
      decoding="async"
      onError={() => setFailed(true)}
      className={cn("shrink-0 rounded-sm bg-muted object-contain", box, className)}
    />
  );
}
