import { getProperty, print, setProperty } from "kolmafia";
import { DON_SOURCES } from "./report-contract";

/**
 * KoLFix-owned policy namespace; all collection toggles default OFF.
 * Preferences are operator requests, not evidence or journal authority.
 * No hooks, network, files, gameplay or automatic initialization.
 */
export const REPORT_DEFAULTS: ReadonlyArray<readonly [string, string]> = [
  ["donReport_schemaVersion", "1.0"],
  ["donReport_collectionEnabled", "false"],
  ["donReport_relayCaptureEnabled", "false"],
  ["donReport_recordEnabled", "false"],
  ["donReport_diffEnabled", "false"],
  ["donReport_printChanges", "false"],
  ["donReport_notifyDiff", "false"],
  ...DON_SOURCES.map((source): readonly [string, string] =>
    [`donReport_source_${source}`, "false"]
  ),
];

export function initializeReportPreferences(): number {
  let created = 0;
  for (const [key, initial] of REPORT_DEFAULTS) {
    if (getProperty(key) === "") {
      setProperty(key, initial);
      created++;
    }
  }
  print(`Don Report defaults initialized: ${created}.`, "green");
  print("All capture and recording disabled by default. No hooks installed.", "gray");
  return created;
}
export function verifyReportPreferences(): boolean {
  const invalid: string[] = [];
  for (const [key, initial] of REPORT_DEFAULTS) {
    const actual = getProperty(key);
    if (key === "donReport_schemaVersion") {
      if (actual !== initial) invalid.push(key);
    } else if (actual !== "false" && actual !== "true") {
      invalid.push(key);
    }
  }
  if (invalid.length > 0) {
    print(`Don Report preferences NEED REVIEW: ${invalid.join(", ")}`, "red");
    return false;
  }
  print("Don Report toggles valid (not proof that any collector is active).", "green");
  return true;
}
export function showReportPreferences(): void {
  print("Don Report v1 canonical index configuration — NO live writer", "blue");
  for (const [key] of REPORT_DEFAULTS) {
    const current = getProperty(key);
    print(`${key} = ${current === "" ? "(unset)" : current}`);
  }
  print("Sources remain independent; multiple claims cannot overwrite canonical nodes.", "orange");
}
