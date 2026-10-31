/**
 * `call kolfix/don_report.js <route> [args] [--quiet] [--print] [--diff]`
 * Operator-invoked, cached/local read-only report adapter.
 * Does not import or execute philter/consume/greenbox/accountval, and
 * NEVER writes JSON or turns on relay hooks.
 */
import {
  getProperty, haveSkill, myAscensions, myFullness, myId,
  myInebriety, mySpleenUse, print, Skill, toInt, todayToString,
} from "kolmafia";
import {
  DON_REPORT_ROUTES, nodeAddress, parseDonReportCommand,
  type DonNode, type DonScope, type DonValue,
} from "./report-contract";

function emit(scope: DonScope, node: DonNode, value: DonValue, quiet: boolean): void {
  const address = nodeAddress(scope, node);
  if (!quiet) print(`${address} = ${value === null ? "known_unknown" : value}`);
}
function scope(): DonScope {
  return {
    playerId: String(myId()),
    day: todayToString(),
    life: myAscensions(),
  };
}
function usage(): void {
  print("Don Report v1 — local cached state, NO journal or writer", "blue");
  print("call kolfix/don_report.js item_new [--quiet|--print|--diff]");
  print("call kolfix/don_report.js item_value 1000000 [--quiet]");
  print("call kolfix/don_report.js skills_current [--quiet]");
  print("call kolfix/don_report.js organ_state [--quiet]");
  print("call kolfix/don_report.js relay_state");
  print("call kolfix/don_report.js spading_state");
}
export default function main(command = ""): void {
  if (!command.trim() || command.trim() === "help") {
    usage();
    return;
  }
  let args: ReturnType<typeof parseDonReportCommand>;
  try {
    args = parseDonReportCommand(command);
  } catch (_error) {
    print("Invalid Don Report command; use 'call kolfix/don_report.js help'.", "red");
    return;
  }
  const owner = DON_REPORT_ROUTES[args.route].owner;
  const s = scope();
  const quiet = args.quiet && !args.print;
  if (args.diff) {
    print("DIFF UNKNOWN: No verified prior report receipt is loaded. No comparison claimed.", "orange");
  }
  if (args.route === "skills_current") {
    if (args.arguments.length !== 0) {
      print("skills_current takes no positional arguments.", "red");
      return;
    }
    let n = 0;
    for (const skill of Skill.all()) {
      if (!haveSkill(skill)) continue;
      emit(s, {domain: "skills", subject: `skill/${toInt(skill)}`,
        metric: "current"}, true, quiet);
      if (!quiet) print(`  ${skill}`);
      n++;
    }
    print(`Source ${owner}; ${n} currently available skills. Permanent status requires separate evidence.`);
    return;
  }
  if (args.route === "organ_state") {
    if (args.arguments.length !== 0) {
      print("organ_state takes no positional arguments.", "red");
      return;
    }
    const values: readonly [string, number][] = [
      ["liver_used", myInebriety()],
      ["stomach_used", myFullness()],
      ["spleen_used", mySpleenUse()],
    ];
    for (const [metric, value] of values)
      emit(s, {domain:"organs",subject:"organ/1",metric}, value, quiet);
    print("Source consume; observed cached organ use. No diet was planned or executed.");
    return;
  }
  if (args.route === "relay_state") {
    const enabled = getProperty("donReport_relayCaptureEnabled");
    emit(s, {domain:"relay",subject:"relay/1",metric:"capture_enabled"},
      enabled === "" ? null : enabled === "true", quiet);
    print("ChIT's original relay override remains untouched; capture defaults OFF.");
    return;
  }
  if (args.route === "spading_state") {
    const active = getProperty("spadingScript");
    print(`spadingScript = ${active === "" ? "(unset)" : active}`);
    print("Event bridge not activated; Excavator and shared spadingData are untouched.");
    return;
  }
  if (args.route === "item_value") {
    if (args.arguments.length > 1 ||
        (args.arguments.length === 1 && !/^(0|[1-9][0-9]*)$/.test(args.arguments[0]))) {
      print("Usage: item_value [minimum-meat] [--quiet|--diff|--print]", "red");
      return;
    }
    print("KNOWN_UNKNOWN: Market value needs an explicitly approved Accountval price collector.");
    print(`Threshold = ${args.arguments[0] || "0"} Meat. No market request made.`);
    return;
  }
  if (args.route === "item_new") {
    if (args.arguments.length !== 0) {
      print("item_new takes no positional arguments.", "red");
      return;
    }
    print("KNOWN_UNKNOWN: Newly acquired items require verified prior/current inventory receipts.");
    print("Philter cleanup was NOT invoked. No items were moved or sold.");
    return;
  }
  print(`Route ${args.route} -> ${owner} not implemented. No action taken.`, "orange");
}
