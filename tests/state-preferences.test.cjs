"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");

const src = fs.readFileSync("src/state-preferences.ts", "utf8");
const main = fs.readFileSync("src/main.ts", "utf8");
const flags = [
  "start_day", "setup_l1", "leg1_farm", "post_farm_l1", "drunk_farm",
  "pills", "pvp_fights", "sea_prep", "pre_ascension", "ascension",
  "in_ronin", "post_ascension_hook", "path_run", "new_life",
  "stillsuit_l1", "stillsuit_l2", "get_cool_ready", "get_cool_used",
  "setup_l2", "leg2_farm", "post_farm_l2", "organ_maxing",
  "overdrink", "max_adv", "mall_managed", "end_day",
];
let passed = 0;
function check(label, fn) { fn(); ++passed; }

const flagPart = src.match(/export const DON_STATE_FLAGS = \[([\s\S]*?)\] as const;/);
check("flag registry exists", () => assert.ok(flagPart));
const actual = Array.from(flagPart[1].matchAll(/"([a-z0-9_]+)"/g), x => x[1]);
check("all 26 upstream phase flags are represented in exact order", () => assert.deepEqual(actual, flags));
check("discrepancy projection has five boolean+note slots", () => {
  assert.ok(src.includes("[1, 2, 3, 4, 5]"));
  assert.ok(src.includes("key: `donState_discrepancy_${n}_note`"));
});
for (const [key, value] of [
  ["donState_loopRun", "false"], ["donState_stopForDiscrepancy", "true"],
  ["donState_autoFallback", "false"], ["donState_nextFallback", "false"],
  ["donState_maxAutomaticAdventureSpend", "0"],
  ["donState_eventEvidence", "unknown"], ["donState_daysTillHalloween", "unknown"]
]) {
  check(key + " safe default", () => {
    assert.ok(src.includes('key: "' + key + '", defaultValue: "' + value + '"'));
  });
}
check("namespace is always donState_", () => {
  assert.ok(src.includes("key: `donState_flag_${flag}`"));
  assert.ok(src.includes('key: "donState_'));
});
check("only missing defaults can be written", () => {
  assert.ok(src.includes('pref.defaultValue !== "" && getProperty(pref.key) === ""'));
  assert.ok(src.includes('setProperty(pref.key, pref.defaultValue)'));
});
check("status never calls initializer", () => {
  const section = src.split("export function showDonStatePreferences")[1];
  assert.ok(!section.includes("initializeDonStatePreferences()"));
  assert.ok(!section.includes("setProperty("));
});
check("all state commands bypass legacy handlers", () => {
  const position = main.indexOf("if (config.stateStatus || config.stateInit || config.stateVerify)");
  assert.ok(position > 0);
  assert.ok(position < main.indexOf("const propertyManager = new PropertiesManager()"));
});
check("broad session restore excludes Don State namespace", () => {
  assert.match(main, /if \(pref\.startsWith\("donState_"\)\)/);
});
check("no scheduled or gameplay execution in preference module", () => {
  assert.ok(!/\b(?:visitUrl|cliExecute|runChoice|adventure|adv1|buy|setAutoAttack)\s*\(/.test(src));
  assert.ok(!/preAscensionScript|postAscensionScript/.test(src));
});
console.log("Don State preference static gate: " + passed + " passed.");
