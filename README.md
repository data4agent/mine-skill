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
python scripts/run_tool.py doctor
python scripts/run_tool.py agent-status
python scripts/run_tool.py agent-start
```

Windows:

```powershell
./scripts/bootstrap.ps1
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

Defaults now cover the normal OpenClaw happy path:

- `PLATFORM_BASE_URL` defaults to testnet
- `MINER_ID` defaults to `mine-agent` for helper compatibility

Required for authenticated mining:

- 默认情况下不需要手动设置；Mine 会优先从本地状态恢复钱包会话，必要时自动 `init + unlock`
- 只有在接入外部 Secret 管理或自定义宿主时，才需要 `AWP_WALLET_TOKEN` 或 `AWP_WALLET_TOKEN_SECRET_REF`

Signature configuration is also auto-managed now:

- Mine 会优先尝试从平台拉取 `GET /api/public/v1/signature-config`
- 拉取成功后会覆盖本地默认值，并写入本地 worker state 缓存
- 如果平台暂时不可达，才回退到内置 aDATA 默认值
- `doctor` / `bootstrap` 会明确显示当前签名配置来源是 `platform` 还是 `fallback`
- 只有在特殊兼容场景下，才需要手动覆盖 `EIP712_*`

Registration is also auto-managed now:

- Mine 会在启动链路检查当前钱包是否已经在 AWP 注册
- 若未注册，会自动尝试 gasless 自注册，本质是 `setRecipient(self)`
- 自动注册成功后继续启动；若仍未完成，`doctor` 会显示当前注册状态
- 如需切换 AWP 接口，可通过 `AWP_API_URL` 覆盖默认 `https://api.awp.sh/api`

Important nuance: low-level platform status calls derive the miner identity from the wallet address. `MINER_ID` is now just a helper-layer compatibility default and does not need to be configured manually in the common case.

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
```

## Windows LinkedIn auto-login

On Windows, LinkedIn `--auto-login` now uses a local visible Chrome/Edge window instead of the Linux-only `Xvfb/x11vnc/noVNC` stack.

- first run may install or verify `agent-browser`
- system Chrome/Edge is preferred; pinned browser fallback is still supported
- the crawler opens the LinkedIn login page in a local browser window and waits for a valid browser session before exporting cookies
- common failures still include LinkedIn CAPTCHA, missing Chrome/Edge, or a busy CDP port such as `9222`

Recommended preflight on Windows:

```powershell
python auto-browser/scripts/vrd.py check
python auto-browser/scripts/vrd.py start
python auto-browser/scripts/vrd.py status
```
