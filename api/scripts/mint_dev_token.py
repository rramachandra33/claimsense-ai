"""Print a development token for one of the users in data/identity/users.json.

    CLAIMSENSE_JWT_SECRET=... uv run python scripts/mint_dev_token.py alice

Development only: real deployments use Amazon Cognito tokens (open question 9).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from claimsense_api.auth import make_dev_token  # noqa: E402

USERS_FILE = Path(__file__).resolve().parents[2] / "data" / "identity" / "users.json"


def main():
    if len(sys.argv) != 2:
        print("usage: mint_dev_token.py <user_id>")
        sys.exit(1)
    user_id = sys.argv[1]
    users = {u["user_id"]: u for u in json.loads(USERS_FILE.read_text())["users"]}
    if user_id not in users:
        print(f"unknown user {user_id}; known: {', '.join(users)}")
        sys.exit(1)
    print(make_dev_token(user_id, users[user_id]["group"]))


if __name__ == "__main__":
    main()
