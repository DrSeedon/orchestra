import sys


def dynamic_target() -> str:  # G346_R3_DEF
    return "dynamic"


def dispatch(action: str) -> str:
    return getattr(sys.modules[__name__], action)()  # G346_R3_GETATTR


DYNAMIC_ACTION = "dynamic_target"  # G346_R3_STRING_EDGE
# dynamic_target is also mentioned here but this comment is noise.  # G346_R3_NOISE_COMMENT

