#!/usr/bin/env python3
"""Quick fix for incomplete mine skill installation.

Run this if:
- Skill installation completed but awp-wallet is missing
- Bootstrap failed partway through
- You need to verify and repair the installation
"""

import subprocess
import sys
from pathlib import Path


def main():
    """Run post-install check which includes auto-fix."""
    script_dir = Path(__file__).parent
    check_script = script_dir / "post_install_check.py"

    if not check_script.exists():
        print(f"ERROR: {check_script} not found")
        print("Are you in the mine skill directory?")
        sys.exit(1)

    print("Running installation check and auto-fix...")
    print()

    try:
        result = subprocess.run([sys.executable, str(check_script)])
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
