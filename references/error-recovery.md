# Error Recovery Reference

Mine tries to recover automatically when the failure is safe and bounded. Otherwise it should stop and surface a concrete operator action.

## Authentication and platform errors

| Scenario | Runtime behavior | Operator action |
|---|---|---|
| `401` with `MISSING_HEADERS` | Fail fast | Configure wallet signing and token |
| `401` with `UNAUTHORIZED`, `TOKEN_EXPIRED`, or `SESSION_EXPIRED` | Renew the wallet session once and retry | Re-run `awp-wallet unlock --duration 3600` if renewal fails |
| `401` with `UNTRUSTED_HOST` | No auto-fix | Get the wallet allow-listed for that environment |
| `403` | Stop affected action | Check permissions or wallet eligibility |
| `404` on occupancy endpoint | Graceful fallback | None |
| `404` on claim endpoints | Treat as no work available | None |
| `404` on status, settlement, or reward endpoints | Return empty data | None |
| `409` duplicate submission | Skip item | None |
| `429` | Cool down the dataset and continue with others when possible | Wait for recovery or reduce pressure |
| `500+` or timeout | Retry with backoff up to three times | Investigate if repeated |

## Wallet recovery

Preferred recovery command:

```bash
awp-wallet unlock --duration 3600
```

If the wallet binary is missing, re-run bootstrap or install `awp-wallet` from GitHub manually.

## Crawler failures

| Scenario | Recovery |
|---|---|
| Partial batch failure | Submit good records, preserve error artifacts |
| Full batch failure | Record the failure and continue to the next eligible work item |
| Auth-required crawler state | Pause until browser/session auth is completed |
| Crash in subprocess | Surface artifact paths and continue if safe |

## Recovery principles

- finish the current batch before pause or stop takes effect
- isolate rate limits and cooldowns per dataset where possible
- keep retries bounded
- prefer specific operator actions over generic "retry later" advice
