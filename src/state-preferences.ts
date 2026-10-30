import { getProperty, print, setProperty } from "kolmafia";

/**
 * Don State Engine v0.2 preference projection, NOT the event journal.
 *
 * Safe defaults are written ONLY by explicit "kolfix stateInit".
 * Values in these KoLmafia preferences can be edited by players and scripts,
 * so they are never proof of actual game-state changes or permission to act.
 * No hooks, adventuring, ascension, browser actions, or automatic reset.
 *
 * State engine source contract:
 * https://github.com/donCannoli-burns/don_custom_functions/pull/5
 */
export const DON_STATE_SCHEMA_VERSION = "0.2";

export const DON_STATE_FLAGS = [
  "start_day",
  "setup_l1",
  "leg1_farm",
  "post_farm_l1",
  "drunk_farm",
  "pills",
  "pvp_fights",
  "sea_prep",
  "pre_ascension",
  "ascension",
  "in_ronin",
  "post_ascension_hook",
  "path_run",
  "new_life",
  "stillsuit_l1",
  "stillsuit_l2",
  "get_cool_ready",
  "get_cool_used",
  "setup_l2",
  "leg2_farm",
  "post_farm_l2",
  "organ_maxing",
  "overdrink",
  "max_adv",
  "mall_managed",
  "end_day",
] as const;

type ValueKind =
  | "boolean"
  | "flag"
  | "counter"
  | "nullableCounter"
  | "date"
  | "timestamp"
  | "phase"
  | "text"
  | "evidence"
  | "schema";

export interface StatePreferenceDefinition {
  readonly key: string;
  readonly defaultValue: string;
  readonly kind: ValueKind;
  readonly purpose: "policy" | "projection" | "scope" | "calendar";
}

const policy: readonly StatePreferenceDefinition[] = [
  {
    key: "donState_schemaVersion",
    defaultValue: DON_STATE_SCHEMA_VERSION,
    kind: "schema",
    purpose: "policy",
  },
  {
    key: "donState_loopRun",
    defaultValue: "false",
    kind: "boolean",
    purpose: "policy",
  },
  {
    key: "donState_stopForDiscrepancy",
    defaultValue: "true",
    kind: "boolean",
    purpose: "policy",
  },
  {
    key: "donState_autoFallback",
    defaultValue: "false",
    kind: "boolean",
    purpose: "policy",
  },
  {
    key: "donState_nextFallback",
    defaultValue: "false",
    kind: "boolean",
    purpose: "policy",
  },
  {
    key: "donState_maxAutomaticAdventureSpend",
    defaultValue: "0",
    kind: "counter",
    purpose: "policy",
  },
  {
    key: "donState_nextFlagExpected",
    defaultValue: "",
    kind: "phase",
    purpose: "policy",
  },
  {
    key: "donState_nextFallbackFlag",
    defaultValue: "",
    kind: "phase",
    purpose: "policy",
  },
];

const scope: readonly StatePreferenceDefinition[] = [
  {
    key: "donState_scopePlayerId",
    defaultValue: "",
    kind: "text",
    purpose: "scope",
  },
  {
    key: "donState_scopeDay",
    defaultValue: "",
    kind: "date",
    purpose: "scope",
  },
  {
    key: "donState_scopeAscensions",
    defaultValue: "",
    kind: "nullableCounter",
    purpose: "scope",
  },
  {
    key: "donState_lastProjectionReceipt",
    defaultValue: "",
    kind: "text",
    purpose: "scope",
  },
];

const journalProjection: readonly StatePreferenceDefinition[] = [
  {
    key: "donState_lastFlagName",
    defaultValue: "",
    kind: "phase",
    purpose: "projection",
  },
  {
    key: "donState_lastFlagActivation",
    defaultValue: "",
    kind: "timestamp",
    purpose: "projection",
  },
  {
    key: "donState_lastFlagEdit",
    defaultValue: "",
    kind: "timestamp",
    purpose: "projection",
  },
  ...DON_STATE_FLAGS.map(
    (flag): StatePreferenceDefinition => ({
      key: `donState_flag_${flag}`,
      defaultValue: "0",
      kind: "flag",
      purpose: "projection",
    })
  ),
  ...[1, 2, 3, 4, 5].reduce<StatePreferenceDefinition[]>(
    (acc, n) => [
      ...acc,
      {
        key: `donState_discrepancy_${n}`,
        defaultValue: "false",
        kind: "boolean",
        purpose: "projection",
      },
      {
        key: `donState_discrepancy_${n}_note`,
        defaultValue: "",
        kind: "text",
        purpose: "projection",
      },
    ],
    []
  ),
];

const calendar: readonly StatePreferenceDefinition[] = [
  {
    key: "donState_nextHalloween",
    defaultValue: "",
    kind: "date",
    purpose: "calendar",
  },
  {
    key: "donState_daysTillHalloween",
    defaultValue: "unknown",
    kind: "nullableCounter",
    purpose: "calendar",
  },
  {
    key: "donState_isHalloween",
    defaultValue: "unknown",
    kind: "evidence",
    purpose: "calendar",
  },
  {
    key: "donState_eveOfHalloween",
    defaultValue: "unknown",
    kind: "evidence",
    purpose: "calendar",
  },
  {
    key: "donState_eveOfEvent",
    defaultValue: "unknown",
    kind: "evidence",
    purpose: "calendar",
  },
  {
    key: "donState_eventEvidence",
    defaultValue: "unknown",
    kind: "evidence",
    purpose: "calendar",
  },
];

/** The complete namespaced, versioned preference contract. */
export const DON_STATE_PREFERENCES: readonly StatePreferenceDefinition[] = [
  ...policy,
  ...scope,
  ...journalProjection,
  ...calendar,
];

function isPhase(value: string): boolean {
  return value === "" || DON_STATE_FLAGS.some((flag) => flag === value);
}

function isNonnegativeInteger(value: string): boolean {
  return /^(0|[1-9][0-9]*)$/.test(value) && Number.isSafeInteger(Number(value));
}

function validValue(pref: StatePreferenceDefinition, value: string): boolean {
  switch (pref.kind) {
    case "boolean":
      return value === "true" || value === "false";
    case "flag":
      return /^[0-5]$/.test(value);
    case "counter":
      return isNonnegativeInteger(value);
    case "nullableCounter":
      return value === "" || value === "unknown" || isNonnegativeInteger(value);
    case "date":
      return value === "" || /^[0-9]{8}$/.test(value);
    case "timestamp":
      return (
        value === "" || /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value)
      );
    case "phase":
      return isPhase(value);
    case "evidence":
      return (
        value === "true" ||
        value === "false" ||
        value === "unknown" ||
        (pref.key === "donState_eventEvidence" && value === "confirmed") ||
        (pref.key === "donState_eventEvidence" && value === "conflict")
      );
    case "schema":
      return value === DON_STATE_SCHEMA_VERSION;
    case "text":
      return value.length <= 1024 && !/[\r\n]/.test(value);
  }
}

/** Only missing nonempty defaults are set; no existing nonempty value is edited. */
export function initializeDonStatePreferences(): number {
  let initialized = 0;
  for (const pref of DON_STATE_PREFERENCES) {
    if (pref.defaultValue !== "" && getProperty(pref.key) === "") {
      setProperty(pref.key, pref.defaultValue);
      initialized += 1;
    }
  }
  print(`Don State v0.2 defaults initialized: ${initialized} missing values.`, "green");
  print("No game actions, phase transitions, ascension hooks, or reset performed.", "gray");
  return initialized;
}

/** Read-only validation; do not guess or repair corrupted projections. */
export function verifyDonStatePreferences(): boolean {
  const invalid: string[] = [];
  for (const pref of DON_STATE_PREFERENCES) {
    const raw = getProperty(pref.key);
    // Empty optional values are intentionally not persisted.
    if (raw === "" && pref.defaultValue === "") continue;
    if (!validValue(pref, raw)) invalid.push(pref.key);
  }

  const player = getProperty("donState_scopePlayerId");
  const day = getProperty("donState_scopeDay");
  const ascensions = getProperty("donState_scopeAscensions");
  const hasActiveFlag = DON_STATE_FLAGS.some(
    (flag) =>
      getProperty(`donState_flag_${flag}`) !== "0" && getProperty(`donState_flag_${flag}`) !== ""
  );

  if (
    hasActiveFlag &&
    (!/^[0-9]{1,12}$/.test(player) || !/^[0-9]{8}$/.test(day) || !isNonnegativeInteger(ascensions))
  ) {
    invalid.push("donState_scope_incomplete_for_active_flags");
  }

  if (
    getProperty("donState_autoFallback") === "true" &&
    getProperty("donState_nextFallbackFlag") === ""
  )
    invalid.push("donState_nextFallbackFlag_missing");

  if (
    getProperty("donState_nextFallback") === "true" &&
    getProperty("donState_autoFallback") !== "true"
  )
    invalid.push("donState_nextFallback_without_policy");

  if (invalid.length) {
    print(`Don State preferences NEED REVIEW: ${invalid.join(", ")}`, "red");
    return false;
  }
  print("Don State preference syntax valid. Cached flags are NOT verified game evidence.", "green");
  return true;
}

/** Human-facing, read-only status. Never call initialize from here. */
export function showDonStatePreferences(): void {
  print("Don State Engine v0.2 — preference view (NOT journal authority)", "blue");
  for (const pref of DON_STATE_PREFERENCES) {
    if (pref.purpose === "policy" || pref.purpose === "scope" || pref.purpose === "calendar") {
      const actual = getProperty(pref.key);
      print(`${pref.key} = ${actual === "" ? "(unset)" : actual}`);
    }
  }
  const stages = DON_STATE_FLAGS.map(
    (flag) => `${flag}:${getProperty(`donState_flag_${flag}`) || "unset"}`
  );
  print(`Projected flags: ${stages.join(" | ")}`);
  print("0=pending, 1=started, 2=finished, 3=skipped, 4=failed, 5=reconcile");
  print("Warning: journal receipts, not writable preferences, must prove completion.", "orange");
}
