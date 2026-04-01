# Security Model

Mine is designed so that signing keys stay inside `awp-wallet` and never move into the Mine repository or runtime config.

## Core rules

1. Private keys and seed phrases must stay inside `awp-wallet`.
2. Mine may hold a short-lived wallet session token, but it must not persist raw wallet secrets.
3. Signed platform requests use EIP-712 typed data built in `scripts/signer.py`.
4. User-facing output should never print full session tokens or private material.

## Wallet interaction

Mine uses subprocess calls to `awp-wallet` for:

| Command | Purpose |
|---|---|
| `awp-wallet receive` | Discover the wallet address |
| `awp-wallet unlock --duration 3600` | Obtain a session token |
| `awp-wallet sign-typed-data --token <token> --data <json>` | Sign a request payload |

## Token handling

- `AWP_WALLET_TOKEN` is the direct environment variable path
- `AWP_WALLET_TOKEN_SECRET_REF` is the secret-provider path
- `AWP_WALLET_TOKEN_EXPIRES_AT` may be set so the runtime can reason about renewal

The runtime attempts one renewal when it sees an expired-session style `401`.

## EIP-712 domain handling

The signature domain is configurable through environment variables:

- `EIP712_DOMAIN_NAME`
- `EIP712_CHAIN_ID`
- `EIP712_VERIFYING_CONTRACT`

Current code defaults are generic:

- name: `Platform Service`
- chain ID: `1`
- verifying contract: zero address

Current project guidance for the aDATA platform recommends:

- name: `aDATA`
- chain ID: `8453`
- verifying contract: zero address

## `MINER_ID` nuance

`MINER_ID` is not the signing identity. The signing identity is the wallet address returned by `awp-wallet receive`.

At the moment:

- helper scripts still require `MINER_ID`
- some low-level platform calls derive miner identity directly from the wallet signer address

Treat `MINER_ID` as helper-layer configuration, not as proof of ownership.

## Do not do these things

- do not commit `.env` files with live wallet tokens
- do not print full `AWP_WALLET_TOKEN` values in logs
- do not copy private keys into config files or shell history
- do not treat bearer tokens or wallet session tokens as durable credentials
