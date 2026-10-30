/**
 * Idempotent KoLmafia installer for the standard ~/.kolmafia profile.
 *
 * Never unlink, overwrite, or replace a pre-existing KoLmafia script path.
 * If the existing symlink already resolves to our built directory, install
 * is complete. Otherwise stop and ask for an operator inspection.
 *
 * The original create-kolmafia-script installer remains responsible for
 * creating a new link if no standard-profile destination exists.
 */
import { spawnSync } from "node:child_process";
import { lstatSync, realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import process from "node:process";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const source = join(root, "dist", "scripts", "kolfix");
const destination = join(homedir(), ".kolmafia", "scripts", "kolfix");
const checkOnly = process.argv.includes("--check");

try {
  if (!statSync(source).isDirectory()) {
    throw new Error("Build output is not a directory");
  }
} catch (error) {
  console.error("Missing build output: " + source);
  console.error("Run yarn build successfully before yarn install-mafia.");
  process.exitCode = 1;
  process.exit();
}

let existing;
try {
  existing = lstatSync(destination);
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

if (existing) {
  let matches = false;
  if (existing.isSymbolicLink()) {
    try {
      matches = realpathSync(destination) === realpathSync(source);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
  if (matches) {
    console.log("KoLmafia kolfix already linked to current build; no reinstallation needed.");
    console.log(destination);
    process.exit(0);
  }
  console.error("Refusing to replace an existing KoLmafia script entry:");
  console.error(destination);
  console.error("Inspect with: ls -ld ~/.kolmafia/scripts/kolfix");
  console.error("Inspect with: readlink -f ~/.kolmafia/scripts/kolfix");
  console.error("No existing files or symlinks were changed.");
  process.exit(1);
}

if (checkOnly) {
  console.log("No installed kolfix entry at standard path: " + destination);
  console.log("Run yarn install-mafia only when you intend to create one.");
  process.exit(0);
}

const installer = join(root, "node_modules", ".bin", "create-kolmafia-script");
const child = spawnSync(installer, ["--install"], { cwd: root, stdio: "inherit" });
if (child.error) {
  console.error(child.error);
  process.exit(1);
}
process.exit(child.status === null ? 1 : child.status);
