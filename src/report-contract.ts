/**
 * Don Report v1 canonical addressing and evidence registry.
 * Pure data layer: no KoLmafia imports, writes, URLs or game effects.
 */
export const DON_REPORT_VERSION = "1.0" as const;
export const DON_SOURCES = [
  "accountval",
  "philter",
  "greenbox",
  "consume",
  "chit",
  "excavator",
  "watersheep",
  "custom_ash",
] as const;
export type DonSource = typeof DON_SOURCES[number];
export type DonState = "observed" | "known_unknown" | "ignored" | "unobserved" | "conflict";
export type DonEvidenceKind = "cached" | "parsed_page" | "derived" | "manual_claim";
export type DonValue = string | number | boolean | null;
export interface DonScope {
  readonly playerId: string;
  readonly day: string; // KoL rollover YYYYMMDD
  readonly life: number; // Lifetime ascensions
}
export interface DonNode {
  readonly domain: string;
  readonly subject: string; // Stable ID, e.g. item/123 or skill/456
  readonly metric: string; // e.g. quantity, estimated_meat, acquired
}
export interface DonReport {
  readonly schema: "don-report-v1";
  readonly id: string;
  readonly address: string;
  readonly scope: DonScope;
  readonly node: DonNode;
  readonly source: DonSource;
  readonly state: DonState;
  readonly evidence: DonEvidenceKind;
  readonly value: DonValue;
  readonly observedAt: string;
  readonly reason: string | null;
  readonly receiptId: string | null;
}
export interface DonProjection {
  readonly address: string;
  readonly state: DonState;
  readonly value: DonValue;
  readonly contributors: readonly string[];
  readonly conflicts: readonly string[];
}

const TOKEN = /^[a-z][a-z0-9_]{0,39}$/;
const SUBJECT = /^[a-z][a-z0-9_]*\/[1-9][0-9]*$/;
const ID = /^[A-Za-z0-9_-]{1,80}$/;
const DATE = /^[0-9]{8}$/;
const TIME = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/;
const SENSITIVE =
  /(?:https?:|pwd\s*[:=]|password\s*[:=]|token\s*[:=]|cookie\s*[:=]|authorization\s*[:=]|@|[<>\r\n])/i;

export function validScope(s: DonScope): boolean {
  return (
    !!s &&
    /^[0-9]{1,12}$/.test(s.playerId) &&
    DATE.test(s.day) &&
    Number.isSafeInteger(s.life) &&
    s.life >= 0
  );
}
export function nodeAddress(s: DonScope, n: DonNode): string {
  if (
    !validScope(s) ||
    !n ||
    !TOKEN.test(n.domain) ||
    !SUBJECT.test(n.subject) ||
    !TOKEN.test(n.metric)
  )
    throw new Error("DON_REPORT_INVALID_ADDRESS");
  return `donstate:v1:${s.playerId}:${s.day}:${s.life}:${n.domain}:${n.subject}:${n.metric}`;
}
export function sourceDirectory(source: DonSource): string {
  if (!DON_SOURCES.includes(source)) throw new Error("DON_REPORT_UNKNOWN_SOURCE");
  return `d_data/d_${source}`;
}
export function reportFilePath(report: DonReport): string {
  validateReport(report);
  // Individual sources own separate materialized exports; path is a proposal,
  // not write authorization. Production must allocate a unique receipt ID.
  return `${sourceDirectory(report.source)}/${report.scope.playerId}/${report.scope.day}/life-${
    report.scope.life
  }/${report.id}.json`;
}
export function validateReport(r: DonReport): void {
  if (
    !r ||
    r.schema !== "don-report-v1" ||
    !ID.test(r.id) ||
    !DON_SOURCES.includes(r.source) ||
    !validScope(r.scope) ||
    r.address !== nodeAddress(r.scope, r.node) ||
    !TIME.test(r.observedAt) ||
    !["observed", "known_unknown", "ignored", "unobserved", "conflict"].includes(r.state) ||
    !["cached", "parsed_page", "derived", "manual_claim"].includes(r.evidence) ||
    (r.reason !== null &&
      (typeof r.reason !== "string" || r.reason.length > 160 || SENSITIVE.test(r.reason))) ||
    (r.receiptId !== null && !ID.test(r.receiptId))
  )
    throw new Error("DON_REPORT_INVALID_RECORD");
  const v = r.value;
  if (r.state !== "observed" && v !== null) throw new Error("DON_REPORT_NONOBSERVED_VALUE");
  if (
    r.state === "observed" &&
    !(
      typeof v === "boolean" ||
      (typeof v === "number" && Number.isFinite(v) && Number.isSafeInteger(v)) ||
      (typeof v === "string" && v.length > 0 && v.length <= 160 && !SENSITIVE.test(v))
    )
  )
    throw new Error("DON_REPORT_UNSAFE_VALUE");
}
function equalValue(a: DonValue, b: DonValue): boolean {
  return typeof a === typeof b && a === b;
}

/**
 * Canonical index is derived, not writable. Never last-writer-wins.
 * Conflicting observations remain visible even if sourced from trusted scripts.
 */
export function projectReports(reports: readonly DonReport[], address: string): DonProjection {
  const observed: DonReport[] = [];
  const contributors: string[] = [];
  const conflicts: string[] = [];
  const ids = new Map<string, string>();
  let ignored = false,
    knownUnknown = false;
  for (const r of reports) {
    validateReport(r);
    if (r.address !== address) throw new Error("DON_REPORT_SCOPE_MIX");
    const fingerprint = JSON.stringify(r);
    const seen = ids.get(r.id);
    if (seen !== undefined) {
      if (seen !== fingerprint) throw new Error("DON_REPORT_IDEMPOTENCY_CONFLICT");
      continue;
    }
    ids.set(r.id, fingerprint);
    contributors.push(r.id);
    if (r.state === "conflict") conflicts.push(r.id);
    if (r.state === "observed") observed.push(r);
    if (r.state === "known_unknown") knownUnknown = true;
    if (r.state === "ignored") ignored = true;
  }
  if (observed.length > 1 && observed.some((r) => !equalValue(r.value, observed[0].value)))
    conflicts.push(...observed.map((r) => r.id));
  const state: DonState =
    conflicts.length > 0
      ? "conflict"
      : observed.length > 0
      ? "observed"
      : knownUnknown
      ? "known_unknown"
      : ignored
      ? "ignored"
      : "unobserved";
  return {
    address,
    state,
    value: state === "observed" ? observed[0].value : null,
    contributors,
    conflicts: [...new Set(conflicts)],
  };
}
export const DON_REPORT_ROUTES = {
  item_value: { owner: "accountval", domain: "economy", requiresPriceConsent: true },
  item_new: { owner: "philter", domain: "inventory", requiresPriceConsent: false },
  skills_current: { owner: "greenbox", domain: "skills", requiresPriceConsent: false },
  organ_state: { owner: "consume", domain: "organs", requiresPriceConsent: false },
  relay_state: { owner: "chit", domain: "relay", requiresPriceConsent: false },
  spading_state: { owner: "excavator", domain: "events", requiresPriceConsent: false },
} as const;
export type DonReportRoute = keyof typeof DON_REPORT_ROUTES;
export function parseDonReportCommand(input: string): {
  route: DonReportRoute;
  arguments: string[];
  quiet: boolean;
  diff: boolean;
  print: boolean;
} {
  if (typeof input !== "string" || input.length > 256 || /[\r\n;|&#]/.test(input))
    throw new Error("DON_REPORT_INVALID_COMMAND");
  const args = input.trim().split(/\s+/).filter(Boolean);
  const name = args.shift();
  if (!name || !(name in DON_REPORT_ROUTES)) throw new Error("DON_REPORT_UNKNOWN_COMMAND");
  const opts = args.filter((a) => a.startsWith("-"));
  if (opts.some((a) => !["--quiet", "--diff", "--print"].includes(a)))
    throw new Error("DON_REPORT_UNKNOWN_OPTION");
  return {
    route: name as DonReportRoute,
    arguments: args.filter((a) => !a.startsWith("-")),
    quiet: opts.includes("--quiet"),
    diff: opts.includes("--diff"),
    print: opts.includes("--print"),
  };
}
