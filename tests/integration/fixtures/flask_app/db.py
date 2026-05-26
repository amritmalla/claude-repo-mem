_USERS = {"alice": {"pw": "secret"}}


def find_user(user):
    return _USERS.get(user)
