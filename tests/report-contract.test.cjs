"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {
  DON_SOURCES, DON_REPORT_ROUTES, nodeAddress, sourceDirectory,
  reportFilePath, validateReport, projectReports, parseDonReportCommand
} = require("../.report-build/report-contract.js");
const main = fs.readFileSync("src/main.ts", "utf8");
const prefs = fs.readFileSync("src/report-preferences.ts", "utf8");
const cli = fs.readFileSync("src/don-report.ts", "utf8");
const build = fs.readFileSync("build.mjs", "utf8");
const scope = {playerId:"12345",day:"20261030",life:32};
const node = {domain:"inventory",subject:"item/13",metric:"quantity"};
const address = nodeAddress(scope,node);
const base = {
  schema:"don-report-v1",id:"philter0001",address,scope,node,
  source:"philter",state:"observed",evidence:"cached",value:2,
  observedAt:"2026-10-30T20:45:00-05:00",reason:null,receiptId:null
};
let n=0;
function check(name,fn){fn();n++;console.log("PASS",name)}
function fails(name,fn,message){check(name,()=>assert.throws(fn,e=>e.message===message))}
check("all eight producers allowlisted",()=>assert.equal(DON_SOURCES.length,8));
check("stable address includes player, rollover, life and node",()=>assert.equal(address,"donstate:v1:12345:20261030:32:inventory:item/13:quantity"));
check("source paths partition by producer, player, day and life",()=>assert.equal(reportFilePath(base),"d_data/d_philter/12345/20261030/life-32/philter0001.json"));
check("no leading slash or cross-profile host path",()=>assert.ok(!sourceDirectory("greenbox").startsWith("/")));
check("valid observation is accepted",()=>assert.doesNotThrow(()=>validateReport(base)));

fails("path traversal is rejected",()=>nodeAddress(scope,{...node,subject:"../../secrets"}),"DON_REPORT_INVALID_ADDRESS");
fails("unscoped player rejected",()=>nodeAddress({...scope,playerId:"."},node),"DON_REPORT_INVALID_ADDRESS");
fails("unscoped day rejected",()=>nodeAddress({...scope,day:"2026-10-30"},node),"DON_REPORT_INVALID_ADDRESS");
fails("negative ascensions rejected",()=>nodeAddress({...scope,life:-1},node),"DON_REPORT_INVALID_ADDRESS");
fails("non-observation cannot claim a value",()=>validateReport({...base,state:"known_unknown"}),"DON_REPORT_NONOBSERVED_VALUE");
fails("credential-like values rejected",()=>validateReport({...base,value:"pwd=secret"}),"DON_REPORT_UNSAFE_VALUE");
fails("raw URLs rejected",()=>validateReport({...base,value:"https://example.net/account"}),"DON_REPORT_UNSAFE_VALUE");
check("observed and corroborated facts project unchanged",()=>{
 const p=projectReports([base,{...base,id:"greenbox0001",source:"greenbox"}],address);
 assert.equal(p.state,"observed");assert.equal(p.value,2);assert.equal(p.conflicts.length,0);
});
check("conflicting source values never overwrite silently",()=>{
 const p=projectReports([base,{...base,id:"greenbox0001",source:"greenbox",value:3}],address);
 assert.equal(p.state,"conflict");assert.equal(p.value,null);
 assert.equal(p.conflicts.length,2);
});
check("ignored and unknown stay distinct",()=>{
 for(const state of ["ignored","known_unknown","unobserved"]){
  const p=projectReports([{...base,value:null,state}],address);
  assert.equal(p.state,state);
 }
});
check("unknown cannot discard a grounded observation",()=>{
 const p=projectReports([base,{...base,id:"untrusted2",source:"accountval",
   state:"known_unknown",value:null}],address);
 assert.equal(p.state,"observed");
});
check("duplicate receipt is idempotent",()=>{
 const p=projectReports([base,base],address);
 assert.equal(p.contributors.length,1);
});
fails("same receipt changed conflicts",()=>projectReports([base,{...base,value:4}],address),"DON_REPORT_IDEMPOTENCY_CONFLICT");
fails("cross-node report rejects",()=>projectReports([base],"donstate:v1:12345:20261030:33:inventory:item/13:quantity"),"DON_REPORT_SCOPE_MIX");
check("all six route names and owners indexed",()=>{
 assert.deepEqual(Object.entries(DON_REPORT_ROUTES).map(([k,v])=>[k,v.owner]),[
  ["item_value","accountval"],["item_new","philter"],["skills_current","greenbox"],
  ["organ_state","consume"],["relay_state","chit"],["spading_state","excavator"]
 ]);
});
check("quiet/diff/print are parsed but cannot trigger shell execution",()=>{
 assert.deepEqual(parseDonReportCommand("item_new --quiet --diff"),{
  route:"item_new",arguments:[],quiet:true,diff:true,print:false
 });
});
fails("injected separator rejected",()=>parseDonReportCommand("item_new; use 1"),"DON_REPORT_INVALID_COMMAND");
fails("unknown action rejected",()=>parseDonReportCommand("ascend now"),"DON_REPORT_UNKNOWN_COMMAND");
check("all collection defaults off",()=>{
 for(const key of ["collectionEnabled","relayCaptureEnabled","recordEnabled",
   "diffEnabled","printChanges","notifyDiff"]){
  assert.ok(prefs.includes(`["donReport_${key}", "false"]`));
 }
 assert.ok(prefs.includes('...DON_SOURCES.map('));
});
check("report commands precede all KoLFix mutation handlers",()=>{
 assert.ok(main.indexOf("if (config.reportStatus || config.reportInit || config.reportVerify)") <
   main.indexOf("const propertyManager = new PropertiesManager()"));
 assert.ok(main.includes('pref.startsWith("donReport_")'));
});
check("standalone report script packaged but never auto-executed",()=>{
 assert.ok(build.includes('don_report: "src/don-report.ts"'));
 assert.ok(!main.includes('import "./don-report"'));
});
check("no imported execution or journal mutation in report CLI",()=>{
 assert.ok(!/\b(?:visitUrl|cliExecute|setProperty|buy|adventure|appendBufferToFile|bufferToFile|Kmail)\s*\(/.test(cli));
 assert.ok(!cli.includes("writeFileSync"));
});
console.log("Don Report contract: " + n + " scenarios passed; no live KoL requests.");

