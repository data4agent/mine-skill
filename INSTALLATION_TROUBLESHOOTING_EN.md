# Installation troubleshooting

## Issue: `npm install -g @aspect/awp-wallet` returns 404

### Symptoms

```
npm error 404 Not Found - GET https://registry.npmjs.org/@aspect%2fawp-wallet
npm error 404  '@aspect/awp-wallet@*' is not in this registry.
```

### Cause

`@aspect/awp-wallet` is **not published** on the public npm registry (or the documented name is outdated). The CLI source lives in the **`awp-wallet`** package (see `package.json`); install from GitHub or a local checkout.

### Fix (Windows / general)

From a sibling directory to `mine` (or any folder):

```bash
git clone https://github.com/awp-core/awp-wallet.git
cd awp-wallet
npm install
npm install -g .
awp-wallet --version
```

Or use the official installer (requires bash, git, openssl):

```bash
git clone https://github.com/awp-core/awp-wallet.git
cd awp-wallet && bash install.sh
```

On **Windows**, run the above in **Git Bash** or **WSL**. On Linux/macOS you can also use `install.sh` alone.

---

## Issue: awp-wallet is missing after installing the Skill

### Symptoms

After installing the mine skill, runtime errors such as:

```
ERROR: awp-wallet not found
```

Or:

```
Agent identity — not available
Fix: Install awp-wallet: npm install -g @aspect/awp-wallet
```

*(Ignore the `npm install -g @aspect/...` hint in older messages — that package does not exist on npm.)*

### Causes

1. **Node.js not installed** — awp-wallet needs Node.js 20+
2. **npm permission issues** — global installs blocked
3. **Network issues** — cannot reach npm or GitHub
4. **Bootstrap skipped** — installed through another path
5. **PATH** — awp-wallet is installed but not on `PATH`

### Solutions

## Method 1: Automatic fix (recommended)

Run the fix script; it detects and repairs common issues:

```bash
cd mine
python scripts/fix_installation.py
```

Or run the check script directly:

```bash
python scripts/post_install_check.py
```

This will:

- Check Python, Node.js, npm, and awp-wallet
- Install missing pieces where possible
- Apply default environment variables
- Verify the installation

Example output:

```
================================================================================
Mine Skill - Post-Install Check
================================================================================

✓ Python version: Python 3.12
✓ Node.js: Node.js v20.10.0
✓ npm: npm 10.2.3
⚠ awp-wallet: awp-wallet not found

================================================================================
Attempting Auto-Fix
================================================================================

→ Installing awp-wallet...
  ✓ awp-wallet installed successfully

================================================================================
✓ All checks passed!
================================================================================
```

## Method 2: Re-run Bootstrap

```bash
# Windows
.\scripts\bootstrap.ps1

# Linux / macOS
bash scripts/bootstrap.sh
```

Bootstrap runs the full install flow (it may still try npm; if that fails, use Method 3 or the 404 section above).

## Method 3: Manual installation

### Step 1: Confirm Node.js

```bash
node --version
npm --version
```

If missing, install from https://nodejs.org.

**Recommended:** Node.js 20 LTS or newer.

### Step 2: Install awp-wallet (official)

Do **not** use `npm install -g @aspect/awp-wallet` (404). Use one of:

**A — Clone and global install from source**

```bash
git clone https://github.com/awp-core/awp-wallet.git
cd awp-wallet
npm install
npm install -g .
cd ..
```

**B — `install.sh` (Linux/macOS or Git Bash / WSL on Windows)**

```bash
git clone https://github.com/awp-core/awp-wallet.git
cd awp-wallet && bash install.sh
```

### Step 3: Verify

```bash
awp-wallet --version
```

You should see a version line such as `0.15.1` (exact number may vary).

### Step 4: Initialize the wallet

```bash
awp-wallet init
```

Follow the prompts to set a password.

### Step 5: Unlock the wallet

```bash
awp-wallet unlock --duration 3600
```

Copy the `sessionToken` from the output.

### Step 6: Environment variables

```bash
export AWP_WALLET_TOKEN=wlt_xxx  # paste from the previous step
```

## FAQ

### Q1: `npm install` fails with permission error (EACCES)

**Windows:**

```powershell
# Run PowerShell as Administrator, then install from a local clone:
cd path\to\awp-wallet
npm install
npm install -g .
```

**Linux / macOS:**

```bash
# Prefer nvm; avoid sudo for global npm installs
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash
source ~/.bashrc
nvm install 20
nvm use 20
cd awp-wallet  # your clone
npm install
npm install -g .
```

### Q2: npm registry timeouts

You can set a mirror (e.g. in China):

```bash
npm config set registry https://registry.npmmirror.com
```

Then retry `npm install` inside the `awp-wallet` clone before `npm install -g .`.

### Q3: awp-wallet installed but command not found

**Check the global link:**

```bash
npm list -g awp-wallet
```

**Locate the binary:**

```bash
# Windows
where awp-wallet

# Linux / macOS
which awp-wallet
```

**Set `AWP_WALLET_BIN` manually if needed:**

Windows (PowerShell):

```powershell
$env:AWP_WALLET_BIN = "C:\Users\<username>\AppData\Roaming\npm\awp-wallet.cmd"
```

Linux / macOS:

```bash
export AWP_WALLET_BIN="$(npm root -g)/../bin/awp-wallet"
```

### Q4: Node.js version too old

```bash
node --version  # need >= v20.0.0
```

Upgrade:

- **Windows:** download from https://nodejs.org  
- **macOS:** `brew upgrade node`  
- **Linux (nvm):** `nvm install 20 && nvm use 20 && nvm alias default 20`

### Q5: Python virtual environment missing

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
pip install -r requirements-core.txt

# Linux / macOS
source .venv/bin/activate
pip install -r requirements-core.txt
```

## Diagnostic commands

### Full diagnostics

```bash
python scripts/run_tool.py doctor
```

Returns JSON with checks and suggested fixes. If tools still suggest the old npm scoped package, use the **official awp-wallet install** commands in this document instead.

### Agent status

```bash
python scripts/run_tool.py agent-status
```

Minimal JSON for agents:

```json
{
  "ready": false,
  "state": "missing_wallet",
  "message": "awp-wallet not installed",
  "next_action": "Install awp-wallet from GitHub (see INSTALLATION_TROUBLESHOOTING_EN.md)",
  "next_command": "git clone https://github.com/awp-core/awp-wallet.git && cd awp-wallet && bash install.sh"
}
```

## Verify installation

```bash
python scripts/post_install_check.py
```

Expected success block:

```
================================================================================
✓ All checks passed!
================================================================================

Next steps:
  1. Initialize wallet: awp-wallet init
  2. Unlock wallet:    awp-wallet unlock --duration 3600
  3. Start mining:     python scripts/run_tool.py run-worker 60 1
```

## Still stuck?

### Collect diagnostics

```bash
python --version
node --version
npm --version

echo $PATH          # Linux / macOS
echo $env:PATH      # Windows

npm config list
npm list -g --depth=0

npm list -g awp-wallet
which awp-wallet    # Linux / macOS
where awp-wallet    # Windows
```

### Open an issue

Include OS version, steps taken, full errors, and `post_install_check.py` output.  
(Replace the placeholder URL in your fork if needed.)

## Quick reference

| Issue | What to run |
|------|-------------|
| Check and fix | `python scripts/fix_installation.py` |
| Re-run bootstrap | `bash scripts/bootstrap.sh` or `.\scripts\bootstrap.ps1` |
| Diagnostics | `python scripts/run_tool.py doctor` |
| Install awp-wallet CLI | `git clone https://github.com/awp-core/awp-wallet.git` then `bash install.sh` or `npm install && npm install -g .` |
| Initialize wallet | `awp-wallet init` |
| Unlock wallet | `awp-wallet unlock --duration 3600` |

## Prevention

Before installing the mine skill:

1. Node.js 20+ installed  
2. Python 3.11+ installed  
3. npm can install packages (permissions OK)  
4. Network can reach GitHub and npm (for dependencies)

End-to-end example:

```bash
node --version    # >= v20.0.0
python --version  # >= 3.11

# Install awp-wallet first (see top of this doc)
git clone https://github.com/awp-core/awp-wallet.git
cd awp-wallet && bash install.sh && cd ..

openclaw install mine
cd ~/.openclaw/extensions/mine   # adjust path if different
python scripts/post_install_check.py

awp-wallet init
awp-wallet unlock --duration 3600

python scripts/run_tool.py run-worker 60 1
```

## Related docs

- [AWP_WALLET_AUTO_INSTALL.md](docs/AWP_WALLET_AUTO_INSTALL.md) — awp-wallet install notes  
- [EIP712_CONFIGURATION.md](docs/EIP712_CONFIGURATION.md) — EIP-712 signing  
- [SKILL.md](SKILL.md) — skill usage  
