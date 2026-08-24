from python.plain import plain_target  # G346_R1_IMPORT


def consume_plain() -> int:
    return plain_target(4)  # G346_R1_CALL


# plain_target is intentionally mentioned in prose.  # G346_R1_NOISE_COMMENT

