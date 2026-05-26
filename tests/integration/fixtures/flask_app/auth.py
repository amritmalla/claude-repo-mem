from db import find_user


def verify_user(user, pw):
    record = find_user(user)
    if record is None:
        return False
    return record["pw"] == pw


def issue_token(user):
    return f"token-for-{user}"
