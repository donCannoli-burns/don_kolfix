# Don Kolfix Security Gate (host-only, optional, recommended)

A **separate Python 3.11+ standard-library companion** to `don_kolfix`. It does not modify ASH, KoLmafia preferences, JVM networking, saved settings, or Git remotes. This is an initial defensive implementation, not a transparent packet interception product.

## Three trust boundaries

| Boundary | Default | Current behavior |
| --- | --- | --- |
| `don_kolfix` local Git → GitHub | **ON after hook installation** | Local `pre-push` blocks outgoing committed objects with protected paths/credential patterns, including secrets from commits later deleted; hosted CI runs an independent scan. |
| `don_kolfix` diagnostic/log export → KoLmafia | **OFF** | Explicit stdin/stdout **redacted-copy** operation. Never modifies the original gameplay or authentication traffic. Enable only when integrating a logging/reporting consumer that deliberately uses the redacted copy. |
| KoLmafia → external outbound traffic | **OFF** | A reserved `explicit-proxy` policy flag only. There is no installed proxy, no transparent capture, no MITM CA and no outbound enforcement yet. Do not claim coverage until an explicitly configured local proxy is added and tested. |

The first boundary is a leak-prevention gate. It does **not scrub or mutate Git objects**: found secrets block the push, so the developer can rotate the credentials and remove them from the outgoing commit history. Automatically replacing bytes inside a commit would invalidate hashes and could corrupt code. The scrubber is designed for *diagnostic copies*, not source-code rewriting.

### Install with ordinary Python 3 (default; no Conda or pip required)

The host companion requires **Python 3.11 or newer** and the **Python standard library only**. You do not need to install Conda, activate an environment, download dependencies, or change the KoLmafia Java runtime. Run these in your Linux terminal, not the KoLmafia gCLI:

```bash
cd ~/repos/donCannoli-burns/don_kolfix
python3 --version                     # Python 3.11+
python3 -m unittest discover -s tests -p 'test_kolfix_security_gate.py' -v
python3 tools/security/kolfix_security.py install-hook
python3 tools/security/kolfix_security.py status
python3 tools/security/kolfix_security.py scan --index
```

If your operating system's `python3` is older than 3.11, use a locally installed `python3.11` or later, or the optional Conda path below; **do not replace or upgrade your system Python just to use this tool**.

### Fast install with pipx or pip (same scanner, no Conda)

**Recommended for people who just want a command:** install [pipx](https://pipx.pypa.io/) once using your OS package manager, then from a checked-out source repository:

```bash
cd don_kolfix
pipx install .
kolfix-security install-hook
kolfix-security status
kolfix-security scan --index
```

`pipx` isolates the utility and provides a `kolfix-security` executable. It does **not** install KoLmafia, modify the game runtime, publish credentials, or install a Git hook until `install-hook` is explicitly called. The hook uses the absolute Python interpreter inside pipx's own environment and executes `python -m kolfix_security` so it does not depend on a script under the Git checkout.

After this change is **merged into `main`**, the source checkout can be skipped:

```bash
pipx install 'git+https://github.com/donCannoli-burns/don_kolfix.git@main'
cd /path/to/your/git/repository
kolfix-security install-hook
```

**This is source-based installation, not a PyPI release.** Do not use `pipx install don-kolfix-security` or `pip install don-kolfix-security` until the maintainers explicitly publish and verify that distribution name. Check the source and pinned revision before running an installer from GitHub.

With ordinary `pip`, install into a virtual environment (particularly on PEP 668-managed Linux distributions):

```bash
python3 -m venv ~/.venvs/don-kolfix-security
~/.venvs/don-kolfix-security/bin/python -m pip install ./
~/.venvs/don-kolfix-security/bin/kolfix-security install-hook
```

`pipx install .` and `pip install .` require an initial setuptools/wheel build environment. The actual `kolfix-security` tool has **zero runtime pip dependencies**. An offline/no-pip install using `python3 tools/security/kolfix_security.py` remains fully supported.

To switch an existing source/Conda-installed managed hook to the pipx executable, use `kolfix-security rebind-hook`. It verifies the exact existing hook before changing it. Do not delete an existing custom hook or run `pipx run ... install-hook`: a temporary pipx-run interpreter can disappear and leave pushes blocked. Removing the pipx environment also leaves its Git hook installed; pushes then fail closed until safely rebound.

### Optional Conda environment


If you already use Conda and prefer environment isolation, both options run the exact same scanner:

```bash
cd ~/repos/donCannoli-burns/don_kolfix
conda env create -f tools/security/environment.yml
conda run -n don-kolfix-security python tools/security/kolfix_security.py install-hook
conda run -n don-kolfix-security python tools/security/kolfix_security.py status
```

**No dependency on Conda is embedded in the installed hook.** It pins the exact `sys.executable` used by `install-hook`: system Python when run with `python3`, Conda Python when run via `conda run`. An ordinary `git push` needs neither an activated environment nor `conda` in `PATH`. If that pinned interpreter is removed, pushes fail closed until the hook is safely rebound.

### Switch an existing hook between Conda and system Python

If the gate is **already installed** through Conda, pipx/pip, or ordinary Python, rebind it without deleting or overwriting a foreign hook. This operation checks the current hook's exact managed format and rejects unrelated or modified hook scripts:

```bash
# Prefer system Python 3.11+ going forward:
python3 tools/security/kolfix_security.py rebind-hook
python3 tools/security/kolfix_security.py status

# Or bind back to the optional Conda interpreter:
conda run -n don-kolfix-security python tools/security/kolfix_security.py rebind-hook
```

`install-hook` is opt-in. Once installed, the hook runs on every ordinary `git push`, even when no flags are supplied. It is **fail-closed** if the selected interpreter disappears, Git object reads fail or credentials are found. It refuses to replace an existing `pre-push` hook or interfere with custom `core.hooksPath`. Integrate manually if you already have a hook chain.

Because Git's `--no-verify`, disabling `core.hooksPath`, alternate Git clients and direct API writes can bypass local hooks, use the repo's **`security-credentials`** GitHub Actions job as a **required status check** in a GitHub branch ruleset for protected branches. The workflow adds this check as a release-build prerequisite, but making it mandatory on a branch requires a repository owner to configure that branch ruleset. Do not claim a 100% enforced remote gate without it.

### Inspect before a push

```bash
python3 tools/security/kolfix_security.py scan --index
python3 tools/security/kolfix_security.py scan --revision 'origin/main..HEAD'
```

A zero exit code means no supported credential pattern was found in the scanned scope; no scanner is perfect. Failure output contains rule IDs and **SHA-256 fingerprints of filenames**, never raw credential values or potentially sensitive filenames. Use a local filename-to-hash lookup to identify a finding without printing secrets to shared logs. Oversized/encrypted/over-expanded ZIP inputs are blocked for manual review.

No `player_backup/`, `.kolmafia/`, `settings/` files or protected credential artifacts should be committed. `.gitignore` is not adequate once an artifact is already tracked. The security tool never deletes or rewrites such material.

### Optional KoLmafia diagnostic scrubber (OFF by default)

```bash
python3 tools/security/kolfix_security.py policy --kolmafia-scrubber on
# Example: redact a separately captured TEST log, not the transport used for game requests.
python3 tools/security/kolfix_security.py scrub < diagnostic.log > diagnostic.redacted.log
python3 tools/security/kolfix_security.py policy --kolmafia-scrubber off
```

This is an explicit redacted-output filter. **Do not replace the live KoLmafia HTTP request or response with scrubbed bytes**: the KoL session/password fields are necessary for valid game interactions, and modifying them can break the client. A later integration may copy observed data to a redaction/recording sink while forwarding original bytes untouched.

### Privileged, time-limited two-direction diagnostic lease (experimental)

The lease helper has **no privilege to intercept packets**. It authorizes sanitized metadata records from explicitly instrumented call sites only. Runtime entries include timestamps, plane, direction/event, decision and counts; **no passwords, cookies, payloads, URLs, game pages or token values**. Logs live in `.git/kolfix-security-audit.jsonl` (0600) and are **developer convenience logs, not tamper-proof audit evidence**. No log starts merely because a lease is enabled.

Never execute a user-writable repository file as root. Install the dedicated helper as a **root-owned, non-writable** file:

```bash
sudo install -o root -g root -m 0755 \
  tools/security/kolfix_security_lease.py \
  /usr/local/libexec/don-kolfix-security-lease

# Grant a single bounded diagnostic window (max 30 minutes, tied to sudo caller UID):
sudo /usr/local/libexec/don-kolfix-security-lease enable --minutes 30 --planes push,kolmafia
sudo /usr/local/libexec/don-kolfix-security-lease status

# The grant expires automatically; to restart, sudo is required again.
sudo /usr/local/libexec/don-kolfix-security-lease disable
```

The host tool reads `/run/don-kolfix-security/lease-$UID.json` only if root owns it and it is not writable by other users. The root helper refuses execution unless its own source file and ancestor directories are root-owned and non-writable. No background timers are needed: every event checks its timestamp before recording. A lease doesn't start recording all KoLmafia outbound calls; instrumented input/output sinks are a separate, explicit future integration. Explicit request/response marker calls can use:

```bash
python3 tools/security/kolfix_security.py record --plane kolmafia --direction request --outcome observed
python3 tools/security/kolfix_security.py record --plane kolmafia --direction response --outcome observed
```

These commands require the active root-owned lease and record only a timestamp, plane, direction, outcome, PID and count. Outbound markers additionally require the `explicit-proxy` policy toggle; **the toggle does not itself create or start a proxy**.

**Advanced setting (configuration only, no runtime egress change):**

```bash
python3 tools/security/kolfix_security.py policy --outbound-plane explicit-proxy
python3 tools/security/kolfix_security.py policy --outbound-plane off
```

Future proxy scope: an opt-in, loopback-only explicit proxy with domain allowlist, metadata-only HTTPS CONNECT logging, no TLS decryption, and hard fail-closed behavior. Docker loopback is **not** host loopback. Do not set global JVM proxies, iptables, nftables, root CA bundles or firewall rules in this version.

### Limitations

- No pattern list can detect every secret. Scanner results are a preflight, not a substitute for credential rotation or reviewing the Git history.
- GitHub Actions scans selected revision ranges; it cannot prevent an already received push from reaching GitHub object storage. Protected branch rules can reject updates to protected refs. For pre-upload protection, keep the local hook enabled.
- The scanner reads compressed ZIP entries without extracting them, and rejects archives beyond fixed resource budgets. Unsupported archive formats and obfuscated secrets need additional manual scanning.
- Running the host script or hooking Git does not automatically watch KoLmafia/JVM. The optional outbound mode isn't implemented until a separate audited proxy integration is completed.
- Avoid running any KoLmafia gameplay actions during installation/testing. All bundled tests use temporary local Git repositories.

## Offline verification

```bash
python3 -m unittest discover -s tests -p 'test_kolfix_security_gate.py' -v
python3 -m py_compile tools/security/kolfix_security.py tools/security/kolfix_security_lease.py
```
