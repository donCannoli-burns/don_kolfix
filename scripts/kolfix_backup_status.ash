script "kolfix_backup_status.ash";

// Read-only. This file is written by the host-side kolfix-settings utility.
// NEVER invoke shell commands, update KoLmafia prefs, or read settings files.
void main() {
    string [string] snapshot;
    if (!file_to_map("kolfix-backup-status.txt", snapshot) || count(snapshot) == 0) {
        print("[kolfix backup-status] No host-side status snapshot is installed.", "orange");
        print("Run kolfix-settings backup --source <mafia-root> or stage an archive to this installation.");
        return;
    }
    if (snapshot["schema"] != "1" || snapshot["result"] != "success") {
        print("[kolfix backup-status] Unrecognized or incomplete status snapshot.", "red");
        return;
    }

    print("[kolfix backup-status] Last recorded host operation (NOT a live process check)", "blue");
    print("Action: " + snapshot["action"]);
    print("Recorded UTC: " + snapshot["updated_utc"]);
    print("Settings files: " + snapshot["files"]);
    if (snapshot["archive_created_utc"] != "")
        print("Archive created UTC: " + snapshot["archive_created_utc"]);
    if (snapshot["archive_sha256"] != "")
        print("Archive SHA-256: " + snapshot["archive_sha256"]);
    print("Rollback: " + snapshot["rollback"]);
    if (snapshot["rollback_snapshot"] != "")
        print("Rollback snapshot: " + snapshot["rollback_snapshot"]);
    print("For current archive verification or restoration, use the host kolfix-settings command.");
}
