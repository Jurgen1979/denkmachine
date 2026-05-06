"""hulpscript om een secret key te genereren voor DM_SECRET_KEY."""

import secrets


def main() -> None:
    """Genereer een willekeurige secret key."""
    secret_key = secrets.token_hex(32)
    print(f"DM_SECRET_KEY={secret_key}")
    print("\n(kopieer bovenstaande waarde naar replit secrets)")


if __name__ == "__main__":
    main()
