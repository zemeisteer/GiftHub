def rate_limit(limit: int, key=None):
    """
    Decorator for configuring rate limit and key in different functions.

    :param limit:
    :param key:
    :return:
    """

    def decorator(func):
        func.throttling_rate_limit = limit
        if key:
            func.throttling_key = key
        return func

    return decorator
