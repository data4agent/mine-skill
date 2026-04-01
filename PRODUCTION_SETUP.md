# Production Environment Setup

## Overview

The production environment (`https://sd76fip34meovmfu5ftlg.apigateway-ap-southeast-1.volceapi.com`) requires wallet address whitelisting before mining can begin.

## Configuration

### Environment Variables

```bash
# Production URL
export PLATFORM_BASE_URL=https://sd76fip34meovmfu5ftlg.apigateway-ap-southeast-1.volceapi.com

# EIP-712 Signature Parameters (same as test environment)
export EIP712_DOMAIN_NAME=aDATA
export EIP712_CHAIN_ID=8453
export EIP712_VERIFYING_CONTRACT=0x0000000000000000000000000000000000000000

# Wallet Configuration
export AWP_WALLET_BIN=C:/nvm4w/nodejs/awp-wallet.cmd
export AWP_WALLET_TOKEN=wlt_xxx  # From: awp-wallet unlock --duration 3600
```

### EIP-712 Configuration ✓ Verified

The production environment uses the **same EIP-712 parameters** as the test environment:

| Parameter | Value |
|-----------|-------|
| Domain Name | `aDATA` |
| Chain ID | `8453` |
| Verifying Contract | `0x0000000000000000000000000000000000000000` |

## Whitelist Registration

### Error: UNTRUSTED_HOST

When connecting with a non-whitelisted wallet address, you'll receive:

```json
HTTP 401 Unauthorized
{
  "error": {
    "code": "UNTRUSTED_HOST",
    "message": "untrusted host"
  }
}
```

This means your wallet address is not yet whitelisted on production.

### How to Register

**Contact the platform administrators** to register your wallet address:

1. Get your wallet address:
   ```bash
   awp-wallet receive
   ```

2. Provide your wallet address to the platform team for whitelisting

3. Once whitelisted, you can start mining on production

### Verification

After whitelisting, verify access:

```bash
python scripts/run_tool.py doctor
# Should show: ✓ Platform Service — accessible

python -c "
import os
import sys
sys.path.insert(0, 'scripts')
sys.path.insert(0, 'lib')

from platform_client import PlatformClient
from signer import WalletSigner

signer = WalletSigner(
    wallet_bin=os.environ['AWP_WALLET_BIN'],
    session_token=os.environ['AWP_WALLET_TOKEN']
)

client = PlatformClient(
    base_url=os.environ['PLATFORM_BASE_URL'],
    token=os.environ['AWP_WALLET_TOKEN'],
    signer=signer,
    eip712_chain_id=8453,
    eip712_domain_name='aDATA',
    eip712_verifying_contract='0x0000000000000000000000000000000000000000'
)

client.send_miner_heartbeat(client_name='mine-agent')
print('✓ Heartbeat successful - wallet is whitelisted')
"
```

## Test vs Production

| Aspect | Test Environment | Production Environment |
|--------|------------------|------------------------|
| URL | `http://101.47.73.95` | `https://sd76fip34meovmfu5ftlg.apigateway-ap-southeast-1.volceapi.com` |
| Protocol | HTTP | HTTPS |
| Wallet Whitelist | ✓ Open | ⚠ Restricted |
| EIP-712 Config | Same | Same |
| API Endpoints | 45 endpoints | 45 endpoints |

## Migration Checklist

- [ ] Test mining works on test environment
- [ ] Get wallet address from `awp-wallet receive`
- [ ] Submit wallet address for production whitelist
- [ ] Wait for whitelist confirmation
- [ ] Update `.env` with production URL
- [ ] Verify heartbeat succeeds
- [ ] Start production mining

## Troubleshooting

### 401 UNTRUSTED_HOST
**Cause:** Wallet address not whitelisted  
**Solution:** Contact platform team to add your wallet address

### 401 UNAUTHORIZED (different from UNTRUSTED_HOST)
**Cause:** EIP-712 configuration mismatch  
**Solution:** Verify EIP712_* environment variables match production requirements

### Connection Timeout
**Cause:** Network issues or blocked access  
**Solution:** Check firewall/proxy settings, verify URL is accessible

## Current Status (2026-04-01)

✓ **Configuration Verified**
- Production URL accessible
- EIP-712 parameters confirmed: `aDATA` + Chain ID `8453`
- API endpoints verified (45 endpoints)

⚠ **Wallet Whitelisting Required**
- Test wallet `0x9915FFAF0dF84Dd26cb35f5D1329501919A8055d` not yet whitelisted
- Produces `UNTRUSTED_HOST` error as expected

**Next Steps:**
1. Contact platform team with wallet address for whitelisting
2. Test again after whitelisting approval
3. Begin production mining
