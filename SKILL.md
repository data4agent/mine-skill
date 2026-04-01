---
name: mine
description: Agent-first autonomous mining skill for Data Mining WorkNet. Uses the built-in Mine runtime for crawling, enrichment, schema handling, and submission signing through awp-wallet, and exposes a guided mining workflow with clear status updates, recovery hints, and portable command entrypoints that work across agents.
bootstrap: ./scripts/bootstrap.sh
windows_bootstrap: ./scripts/bootstrap.ps1
smoke_test: ./scripts/smoke_test.py
requires:
  skills: []
  bins:
    - python3
    - awp-wallet
  anyBins:
    - python
    - py
  env:
    - PLATFORM_BASE_URL
    - MINER_ID
---

# Mine

Use this skill when the goal is to operate the Mine mining workflow end to end:

- start autonomous mining work
- check mining status, epoch progress, or reward state
- process task payload files
- export or submit Core payloads
- bootstrap or verify the local Mine runtime

---

## Command entrypoint

All runtime actions should go through `scripts/run_tool.py`.

Preferred commands:

- `python scripts/run_tool.py first-load`
- `python scripts/run_tool.py start-working`
- `python scripts/run_tool.py check-status`
- `python scripts/run_tool.py list-datasets`
- `python scripts/run_tool.py run-worker`
- `python scripts/run_tool.py run-once`
- `python scripts/run_tool.py heartbeat`
- `python scripts/run_tool.py process-task-file <taskType> <taskJsonPath>`
- `python scripts/run_tool.py export-core-submissions <inputPath> <outputPath> <datasetId>`

This keeps `mine` portable across agents without requiring a plugin host.

---

## First-load experience contract

When this skill loads for the first time, the preferred user experience is:

1. show a short welcome
2. show a security note
3. run a dependency check
4. give 3 clear quick-start actions
5. avoid overwhelming the user with low-level implementation detail

Use this exact interaction style or something better:

### Welcome

**Welcome to Mine** — the data service WorkNet.

Your agent mines the internet for structured data and earns `$aMine`.
Crawl, clean, structure, submit — with the agent handling the workflow for you.

### Quick start

- `start working` — begin autonomous mining
- `check status` — see credit score, epoch status, and reward-related state
- `list datasets` — inspect active datasets before starting

End the first-load message with:

> Or just tell me what you'd like to do.

### Security

**Security:** your private keys never leave awp-wallet.
Mine only uses time-limited session tokens for signing.
No seed phrase or private key should be stored in config, environment text output, or sent to the platform.

---

## Dependency check

### Version check

Always surface version readiness as its own explicit check before long-running mining work:

1. `Mine runtime version`
   - current project checkout is the active runtime surface
2. `Python version`
   - Mine needs Python 3.11+
3. `Wallet session freshness`
   - unlocked session must still be valid for signing

Good version-check tone:

- `Mine runtime version — project checkout ready`
- `Python version — 3.11+ ready`
- `Wallet session — ready`

Always present dependency results in a concrete, actionable way.
Do not say only “missing dependency” or “please install”.

### Dependencies to verify

1. **AWP Wallet**
   - installed
   - reachable on PATH or explicit config path
   - unlocked or ready to unlock

2. **Mine runtime**
   - runtime present inside this project
   - Python runtime available
   - environment bootstrapped enough to run Mine crawler commands

3. **Platform Service base URL**
   - use environment variable `PLATFORM_BASE_URL` when set
   - if the user is on the test setup, it is acceptable to explain the testnet default

### Good dependency-check success tone

- `AWP Wallet — installed, unlocked`
- `Mine runtime — installed (Python 3.11+ ready)`
- `Platform Service base URL — configured`
- `All dependencies ready.`

### Good dependency-check failure tone

When a dependency is missing, give the user the exact next steps.

For example:

- `AWP Wallet — missing`
  - suggest install path or binary setup
- `Mine runtime — not ready`
  - tell the user to bootstrap this project runtime
- Python too old
  - explicitly say Mine needs Python 3.11+
- platform base URL missing
  - explain whether Mine will use the current testnet default or needs explicit config

Always include a recovery close like:

> Run these commands, then say `check again` and I’ll re-verify.

If wallet renewal is needed, it is valid to instruct:

```bash
awp-wallet unlock --duration 3600
```

---

## Intent routing

When the user expresses an intent, route to the matching action and command.

| Intent | Action | Command | Confirm? |
| --- | --- | --- | --- |
| Start autonomous mining | **A1** | `python scripts/run_tool.py start-working` | First run: yes |
| Check miner status / credit score | **Q1** | `python scripts/run_tool.py check-status` | No |
| List active datasets | **Q2** | `python scripts/run_tool.py list-datasets` | No |
| Check epoch progress | **Q3** | `python scripts/run_tool.py check-status` | No |
| Check submission history | **Q4** | `python scripts/run_tool.py check-status` | No |
| Check mining log | **Q5** | read `output/agent-runs/` artifacts | No |
| Answer PoW challenge | **M1** | handled within `run-worker` / `run-once` | No |
| Check dedup availability | **M2** | handled within `run-worker` / `run-once` | No |
| Configure mining preferences | **C1** | environment variables or `mine.json` | — |
| Pause / resume mining | **A2** | `python scripts/run_tool.py pause` / `resume` | No |
| Stop mining | **A3** | `python scripts/run_tool.py stop` | Yes |

### Routing rules

- If the user is vague or says "start", route to **A1**.
- If the user asks about status, credit, epoch, or rewards, route to **Q1**/**Q3**.
- If the user says "pause", "stop", or "resume", route to **A2**/**A3** directly.
- **A3** (stop) always requires user confirmation before executing.
- **M1** and **M2** are internal workflow steps, not user-facing commands. They run automatically during **A1**.
- For **C1**, guide the user through environment variables (`MINE_CONFIG_PATH`, stop conditions) rather than exposing raw config files.

---

## Runtime model

`mine` is the primary skill/runtime project.

- crawler runtime root: this repository by default
- request signing: `awp-wallet`
- platform connectivity: `PLATFORM_BASE_URL`
- discovery may use `generic` or `generic/page` inputs as compatibility fallbacks when needed

Mine should feel like a guided product, not a loose collection of tools.

---

## Command priority

When choosing runtime commands, prefer this order:

1. `python scripts/run_tool.py run-worker`
   - primary autonomous worker
   - best choice for normal mining work

2. `python scripts/run_tool.py run-once`
   - debug or single-pass execution
   - good when validating one cycle

3. `python scripts/run_tool.py process-task-file`
   - use when a local payload JSON is already available
   - useful for offline or claim-bypassed execution

4. `python scripts/run_tool.py heartbeat`
   - use when only heartbeat verification is needed

5. `python scripts/run_tool.py run-loop`
   - use when repeated loop execution is explicitly requested

6. `python scripts/run_tool.py export-core-submissions`
   - use for conversion/export workflows only

Do not make the user infer this order.
If the user is vague, prefer `python scripts/run_tool.py run-worker`.

---

## Start-working experience

The target UX for `start working` is:

1. confirm heartbeat and registration state
2. show current credit score / tier if available
3. show current epoch and time remaining if available
4. discover active datasets
5. let the user choose datasets on first run if multiple are available
6. confirm the plan before starting the long-running workflow

Good confirmation language:

- `Mining wiki-articles + arxiv-papers.`
- `Target: 80 submissions this epoch.`
- `Say pause or stop anytime.`

---

## Progress feedback contract

Mine should provide visible progress through the full pipeline.
Do not let the user sit through a long black box.

Preferred stage language:

- `finding URLs`
- `dedup check`
- `preflight`
- `PoW`
- `crawling`
- `structuring`
- `submitting`

Batch-level updates are preferred over silence.

At the end of a batch, show a compact status summary:

- records discovered
- records crawled successfully
- records failed
- records structured
- records submitted

If possible, also show epoch progress and basic forecast information.

---

## Control language

Mine should support clear control semantics:

- `pause`
- `resume`
- `stop`

### Pause

Preferred behavior:

- finish the current batch
- save state
- report session progress

### Resume

Preferred behavior:

- restore saved state
- confirm restored epoch progress
- continue from the next batch

### Stop

Preferred behavior:

- finish the current batch
- stop starting new work
- return a session summary

Always explain that the **current batch** is finished before pausing or stopping.

---

## Error recovery guidance

Mine should feel resilient and specific.

### Token/session recovery

If signing requests fail because the wallet session is stale or expired:

- explain that the session token likely expired
- suggest or run:

```bash
awp-wallet unlock --duration 3600
```

Do not describe this as just “retry signing”.

### 429 rate limiting

If the platform returns `429`:

- say that rate limiting happened
- cool down the affected dataset
- continue with other eligible work if available
- surface the retry window if known

### AUTH_REQUIRED

If crawler output indicates `AUTH_REQUIRED`:

- explicitly say login or browser confirmation is needed
- move the item into pending/retry state
- tell the user what needs to be completed before retry

### Occupancy / dedup fallback

If the occupancy check endpoint is unavailable or returns 404:

- do not crash the session
- treat the URL as available and proceed with crawling (optimistic fallback)
- log the fallback internally but do not alarm the user unless it affects >10% of URLs in a batch
- this is expected behavior during platform upgrades or when the endpoint is not yet deployed

---

## Bootstrap and verification

Preferred local checks:

- `./scripts/bootstrap.sh`
- `./scripts/bootstrap.cmd`
- `python scripts/verify_env.py --profile minimal --json`
- `python scripts/host_diagnostics.py --json`
- `python scripts/smoke_test.py --json`

If the user needs environment setup help, guide them toward bootstrapping the local Python runtime and awp-wallet rather than any plugin packaging flow.

---

## FAQ

### Gas fees

**Q: Does submitting data require gas fees?**

A: No. Data submissions to the Platform Service are off-chain API calls. You do not need ETH in your wallet to submit crawled data.

**Q: Does claiming $aMine rewards require gas?**

A: Reward claiming may require on-chain transactions depending on the platform's settlement mechanism. Check the platform documentation for current settlement details. During testnet, rewards are tracked off-chain.

**Q: Do I need ETH in my wallet to mine?**

A: No ETH is required for the mining workflow itself. The wallet is used only for EIP-712 request signing (off-chain). Gas is only needed if you later bridge rewards or perform on-chain operations.

### Wallet address and Miner ID

**Q: What is the relationship between my wallet address and Miner ID?**

A: They are separate identifiers:

- **Wallet address** (`0x...`) — Your cryptographic identity for request signing. Derived from your private key via awp-wallet. Used to authenticate API requests.
- **Miner ID** — A human-readable identifier for your mining client (e.g., `my-miner-001`). Used by the platform to track your submissions, credit score, and rewards.

**Q: Can one wallet address run multiple miners?**

A: Yes. You can run multiple mining clients with different Miner IDs, all signing with the same wallet address. Each Miner ID maintains its own credit score and submission history.

**Q: Can I switch wallet addresses while keeping my Miner ID?**

A: This depends on platform policy. Generally, Miner IDs are associated with wallet addresses at registration. Contact platform support if you need to migrate a Miner ID to a new wallet.

**Q: Why do I need both?**

A: The wallet address provides cryptographic authentication (proving you control the private key). The Miner ID provides operational flexibility (naming, tracking, multi-client setups).

### PoW challenges

**Q: What types of PoW challenges are supported?**

A: The current solver supports:

| Type | Description | Implementation |
|------|-------------|----------------|
| `content_understanding` | LLM-answerable questions | Requires Mine Gateway LLM |
| `structured_extraction` | Schema-based extraction | Requires Mine Gateway LLM |
| `math` / `arithmetic` | Basic math expressions | Local evaluation |
| `sha256_nonce` / `hashcash` | Hash prefix mining | Local computation |

**Q: What happens if a challenge type is unsupported?**

A: The item is skipped with status `challenge_received_but_unsolved`. It will not block other work.

**Q: How do LLM-based challenges work?**

A: They route through the Mine Gateway (`OPENCLAW_GATEWAY_BASE_URL`). If the gateway is not configured, LLM challenges will fail. Configure the gateway in your environment or `mine.json` for full PoW support.

**Q: What is the roadmap for PoW?**

A: Current implementation handles the most common challenge types. Additional types may be added as the platform evolves. The solver is designed to be extensible — new challenge handlers can be added to `pow_solver.py`.

### Network selection

**Q: How do I choose between testnet and mainnet?**

A: Set `PLATFORM_BASE_URL` explicitly:

- **Testnet:** `http://101.47.73.95`
- **Mainnet:** TBD (will be announced when available)

The install script no longer defaults to testnet. You must explicitly choose your network.

**Q: What happens if I forget to set the URL?**

A: The worker will fail with a clear error asking you to set `PLATFORM_BASE_URL`. This prevents accidental connections to the wrong network.
