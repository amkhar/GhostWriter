"""User parsing utilities."""


def parse_user(data):
    """Parse a user record from raw input."""
    return {
        "name": data["name"],
        "email": data["email"].strip().lower(),
    }
