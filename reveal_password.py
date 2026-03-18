#!/usr/bin/env python3
"""
reveal_password.py

Standalone CLI to decrypt and display stored portal passwords.
Usage:
    python reveal_password.py                      # print all sites + passwords
    python reveal_password.py --site workday_google  # print one site's password
    python reveal_password.py --master               # print the master password only
"""
import argparse
import getpass
import os
import sys
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parent))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reveal stored portal passwords (decrypted).",
    )
    parser.add_argument("--site", help="Show password for a specific site key only")
    parser.add_argument("--master", action="store_true", help="Show the master password only")
    args = parser.parse_args()

    # Ensure encryption key is available
    from dotenv import load_dotenv
    load_dotenv()

    import config
    if not config.ENCRYPTION_KEY:
        key = getpass.getpass("ENCRYPTION_KEY not found in .env. Enter it now: ").strip()
        if not key:
            print("No key provided. Aborting.")
            sys.exit(1)
        os.environ["ENCRYPTION_KEY"] = key
        # Reload config to pick up the env var
        import importlib
        importlib.reload(config)

    from agent import password_manager

    if args.master:
        master = password_manager.get_master()
        if master:
            print(f"\nMaster password: {master}\n")
        else:
            print("No master password stored yet.")
        return

    if args.site:
        pw = password_manager.retrieve_password(args.site)
        if pw:
            print(f"\n{args.site}: {pw}\n")
        else:
            print(f"No password found for site: {args.site}")
            sites = password_manager.list_sites()
            if sites:
                print(f"Available sites: {', '.join(sites)}")
        return

    # Print all
    sites = password_manager.list_sites()
    if not sites:
        print("No passwords stored yet.")
        return

    print("\nStored passwords:")
    print("-" * 50)
    for site in sites:
        pw = password_manager.retrieve_password(site)
        print(f"  {site:<30} {pw}")
    print()


if __name__ == "__main__":
    main()
