"""hulpscript om een werkzeug pbkdf2-hash te genereren voor DM_PASSWORD_HASH."""

import sys

from werkzeug.security import generate_password_hash


def main() -> None:
    """Lees plaintext wachtwoord uit argv en print de pbkdf2-hash."""
    if len(sys.argv) != 2:
        print("gebruik: python scripts/hash_password.py \"jouwwachtwoord\"")
        sys.exit(1)

    plaintext = sys.argv[1]
    hashed = generate_password_hash(plaintext, method="pbkdf2:sha256")
    print(f"DM_PASSWORD_HASH={hashed}")
    print(
        "\n(kopieer bovenstaande waarde naar replit secrets,"
        " inclusief de hash maar zonder de 'DM_PASSWORD_HASH=' prefix)"
    )


if __name__ == "__main__":
    main()
