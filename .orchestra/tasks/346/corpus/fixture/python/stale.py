def stale_target() -> str:  # G346_R6_OLD_DEF
    return "old"


def stale_consumer() -> str:
    return stale_target()  # G346_R6_OLD_CALL

