# Mine

Mine is an agent-first mining runtime for signed platform work, crawler execution, and submission export.

## What lives here

- `SKILL.md`: the root skill contract for agent hosts
- `scripts/run_tool.py`: the only public CLI entrypoint
- `crawler/`: the crawler, extraction, enrichment, and output pipeline
- `scripts/`: setup, runtime orchestration, verification, and support utilities
- `references/`: stable agent reference material for commands, protocol, API, security, and recovery
- `docs/`: concise setup and environment guidance for agents

## Quick start

Unix-like:

```bash
./scripts/bootstrap.sh
awp-wallet init
awp-wallet unlock --duration 3600
python scripts/run_tool.py doctor
python scripts/run_tool.py agent-status
python scripts/run_tool.py agent-start
```

Windows:

```powershell
./scripts/bootstrap.ps1
awp-wallet init
awp-wallet unlock --duration 3600
python scripts/run_tool.py doctor
python scripts/run_tool.py agent-status
python scripts/run_tool.py agent-start
```

If you want the worker loop directly instead of the host-oriented background flow:

```bash
python scripts/run_tool.py run-worker 60 0
```

`0` means "run until stopped".

## Environment summary

Required in practice:

- `PLATFORM_BASE_URL`
- `MINER_ID`

Required for authenticated mining:

- `AWP_WALLET_TOKEN` or `AWP_WALLET_TOKEN_SECRET_REF`

Usually required for the known aDATA platform:

- `EIP712_DOMAIN_NAME=aDATA`
- `EIP712_CHAIN_ID=8453`
- `EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000`

Important nuance: low-level platform status calls derive the miner identity from the wallet address, but the current helper scripts and readiness commands still require `MINER_ID` to be set. Keep it as a stable non-empty value until the runtime is simplified.

## Main commands

```bash
python scripts/run_tool.py agent-status
python scripts/run_tool.py agent-start
python scripts/run_tool.py agent-control status
python scripts/run_tool.py agent-control pause
python scripts/run_tool.py agent-control resume
python scripts/run_tool.py agent-control stop
python scripts/run_tool.py doctor
python scripts/run_tool.py first-load
python scripts/run_tool.py run-worker 60 0
python scripts/run_tool.py process-task-file <taskType> <taskJsonPath>
python scripts/run_tool.py export-core-submissions <inputPath> <outputPath> <datasetId>
```

## OpenClaw host flow

For OpenClaw and similar agents, the expected happy path is:

1. bootstrap the repo
2. run `python scripts/run_tool.py agent-status`
3. if ready, run `python scripts/run_tool.py agent-start`
4. keep the chat interactive while mining continues in the background
5. use `python scripts/run_tool.py agent-control status|pause|resume|stop` for follow-up actions

Slash commands such as `/mine-start` should be treated as host aliases that map onto these canonical commands.

## Documentation

- [`docs/AGENT_GUIDE.md`](./docs/AGENT_GUIDE.md): setup, verification, and daily operator workflow
- [`docs/ENVIRONMENT.md`](./docs/ENVIRONMENT.md): environment variables, auth, known platform values, and production notes
- [`references/commands-mining.md`](./references/commands-mining.md): command reference
- [`references/api-platform.md`](./references/api-platform.md): platform API behavior and endpoint reference
- [`references/protocol-miner.md`](./references/protocol-miner.md): worker session persistence model
- [`references/security-model.md`](./references/security-model.md): wallet and token handling rules
- [`references/error-recovery.md`](./references/error-recovery.md): recovery behavior and operator actions

## Verification

```bash
python scripts/run_tool.py --help
python scripts/run_tool.py doctor
python scripts/verify_env.py --profile minimal --json
python scripts/host_diagnostics.py --json
python scripts/smoke_test.py --json
python -m pytest tests -q
```
