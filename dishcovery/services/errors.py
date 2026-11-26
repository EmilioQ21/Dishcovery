class DishcoveryError(Exception):
    """Expected business error, shown to the user as a message (not a stack trace)."""


class NotFound(DishcoveryError):
    pass


class AuthError(DishcoveryError):
    pass
