"""Generate the three values the admin needs, for pasting into .env.

    python make_admin.py

The password is never stored - only a hash of it - so .env cannot give the
password back to anyone who reads the file, and a leaked .env does not hand
over the login.
"""

import getpass
import secrets

from werkzeug.security import generate_password_hash


def main():
    print("Admin credentials for the local app.\n")
    user = input("Username: ").strip()
    if not user:
        print("A username is required.")
        return 1

    password = getpass.getpass("Password: ")
    if len(password) < 8:
        print("Use at least 8 characters.")
        return 1
    if password != getpass.getpass("Repeat it: "):
        print("They do not match.")
        return 1

    print("\nPaste these three lines into .env, then restart python app.py:\n")
    print(f"ADMIN_USER={user}")
    print(f"ADMIN_PASSWORD_HASH={generate_password_hash(password)}")
    # A stable secret, so signing in survives a restart. Random per process
    # would log you out every time the app reloads.
    print(f"SECRET_KEY={secrets.token_hex(32)}")
    print("\n.env is gitignored, so none of this reaches the repository.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
