# EIP-712 Signature Configuration

Mine uses EIP-712 typed data signing for platform API authentication. This document explains how to configure the signature domain parameters.

## Environment Variables

Set these environment variables to customize the EIP-712 domain:

```bash
# EIP-712 domain name (default: "Platform Service")
export EIP712_DOMAIN_NAME="aDATA"

# EIP-712 chain ID for domain (default: 1)
export EIP712_CHAIN_ID="92"

# EIP-712 verifying contract address (default: "0x0000000000000000000000000000000000000000")
export EIP712_VERIFYING_CONTRACT="0x0000000000000000000000000000000000000000"
```

### Windows

```cmd
set EIP712_DOMAIN_NAME=aDATA
set EIP712_CHAIN_ID=92
set EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000
```

## Default Values

If not set, these defaults are used:

| Parameter | Default Value |
|-----------|--------------|
| `EIP712_DOMAIN_NAME` | `"Platform Service"` |
| `EIP712_CHAIN_ID` | `1` |
| `EIP712_VERIFYING_CONTRACT` | `"0x0000000000000000000000000000000000000000"` |

## EIP-712 Domain Structure

The typed data includes this domain:

```json
{
  "name": "aDATA",
  "version": "1",
  "chainId": 92,
  "verifyingContract": "0x0000000000000000000000000000000000000000"
}
```

## Chain ID Notes

**Important:** The `EIP712_CHAIN_ID` is for the EIP-712 domain signature and is **separate** from blockchain chain IDs:

- `EIP712_CHAIN_ID=92` - Used in the EIP-712 domain for signature verification
- Chain ID 8453 - Base mainnet (used for on-chain operations, not EIP-712 domain)

The EIP-712 chain ID is a signature domain parameter and does not need to match any actual blockchain's chain ID.

## Testing

Test your configuration:

```bash
# Unix/Linux/macOS
bash scripts/test_eip712_config.sh

# Windows
scripts\test_eip712_config.cmd
```

Or test directly with Python:

```bash
python scripts/test_eip712_signature.py
```

## Example Platform Configurations

### aDATA Platform (Example)

```bash
export EIP712_DOMAIN_NAME="aDATA"
export EIP712_CHAIN_ID="92"
export EIP712_VERIFYING_CONTRACT="0x0000000000000000000000000000000000000000"
export PLATFORM_BASE_URL="http://101.47.73.95"
```

### Default Platform Service

```bash
# No need to set EIP712_* variables - defaults will be used
export PLATFORM_BASE_URL="http://your-platform-url"
```

## Verification

After setting these variables, the signature headers will include:

```
X-Chain-Id: 92
X-Signature: 0x... (signed with domain chainId: 92)
```

The platform should verify signatures using the same domain parameters.

## Troubleshooting

### Signature Verification Failed (401)

If you get 401 errors with `INVALID_SIGNATURE` or `SIGNATURE_MISMATCH`:

1. Verify the platform expects these exact parameters
2. Check that `EIP712_CHAIN_ID` matches what the platform expects
3. Ensure `EIP712_DOMAIN_NAME` is exactly as the platform requires (case-sensitive)
4. Confirm `EIP712_VERIFYING_CONTRACT` address format is correct

### Token Expired

If you get `TOKEN_EXPIRED` or `SESSION_EXPIRED`:

- The agent will automatically attempt to renew the session
- If auto-renewal fails, check that awp-wallet is accessible

## Architecture

The EIP-712 signature flow:

```
WorkerConfig (env vars)
    ↓
    eip712_chain_id: 92
    eip712_domain_name: "aDATA"
    eip712_verifying_contract: "0x0..."
    ↓
PlatformClient
    ↓
    _eip712_chain_id
    ↓
WalletSigner.build_auth_headers(chain_id=92)
    ↓
    build_typed_data(
        chain_id=92,
        domain_name="aDATA",
        verifying_contract="0x0..."
    )
    ↓
awp-wallet sign-typed-data
    ↓
X-Signature header
```

## Reference

- EIP-712: https://eips.ethereum.org/EIPS/eip-712
- Implementation: `scripts/signer.py`
- Configuration: `scripts/run_models.py` (WorkerConfig)
- Client: `lib/platform_client.py`
