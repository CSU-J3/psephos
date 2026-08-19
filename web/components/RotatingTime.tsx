"use client";

import { useEffect, useState } from "react";

// The collection timestamp, rotating through seven zones on a 4 s cycle.
//
// ALL SEVEN, INCLUDING ALASKA AND HAWAII, because the record covers all 51
// jurisdictions and a clock that stops at Pacific quietly says otherwise.
//
// IANA names with `timeZoneName: "short"`, never a stored offset table. An offset
// table reads EST in August and breaks twice a year; Intl knows the rules and this
// page is read year-round. UTC is special-cased to the compact military form
// (18:16Z) because "18:16 UTC" is the one reading where the suffix is redundant.
const ZONES = [
  { tz: "UTC", utc: true },
  { tz: "America/New_York", utc: false },
  { tz: "America/Chicago", utc: false },
  { tz: "America/Denver", utc: false },
  { tz: "America/Los_Angeles", utc: false },
  { tz: "America/Anchorage", utc: false },
  { tz: "Pacific/Honolulu", utc: false },
] as const;

const CYCLE_MS = 4000;

function reading(at: Date, zone: (typeof ZONES)[number]): string {
  if (zone.utc) {
    const hh = String(at.getUTCHours()).padStart(2, "0");
    const mm = String(at.getUTCMinutes()).padStart(2, "0");
    return `${hh}:${mm}Z`;
  }
  return new Intl.DateTimeFormat("en-US", {
    timeZone: zone.tz,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZoneName: "short",
  }).format(at);
}

/**
 * `iso` is the collection timestamp, rendered server-side into the `datetime`
 * attribute so the machine-readable value is exact and zone-independent.
 *
 * Every reading is computed with an explicit `timeZone`, so server and client agree
 * and there is no hydration mismatch. The rotation index starts at 0 on both sides.
 *
 * No `aria-live`. The value does not change -- only which zone expresses it -- and
 * announcing seven restatements of one timestamp every four seconds is noise. The
 * `title` carries all seven at once for anyone who wants them without waiting.
 */
export function RotatingTime({ iso }: { iso: string }) {
  const at = new Date(iso);
  const readings = ZONES.map((z) => reading(at, z));
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);

  useEffect(() => {
    if (paused) return;
    const id = setInterval(() => setIndex((i) => (i + 1) % ZONES.length), CYCLE_MS);
    return () => clearInterval(id);
  }, [paused]);

  return (
    <time
      dateTime={iso}
      title={readings.join(" · ")}
      // The stack sizes to its widest child, so the width is reserved at mount by
      // the layout engine and nothing downstream of it moves on a swap.
      className="rt-stack tabular-nums"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
    >
      {readings.map((r, i) => (
        <span
          key={ZONES[i].tz}
          className={`rt-reading ${i === index ? "rt-in" : "rt-out"}`}
          // The six inactive readings are transparent, not hidden: they must keep
          // occupying the grid cell or the reservation collapses to the active
          // string's width, which is the twitch this exists to prevent.
          aria-hidden={i === index ? undefined : true}
        >
          {r}
        </span>
      ))}
    </time>
  );
}
