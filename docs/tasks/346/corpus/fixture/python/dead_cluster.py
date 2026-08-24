from python.framework import router


def dead_leaf() -> str:  # G346_R5_DEAD_LEAF_DEF
    return "dead"


def dead_root() -> str:  # G346_R5_DEAD_ROOT_DEF
    return dead_leaf()  # G346_R5_DEAD_INTERNAL_EDGE


@router.post("/live")  # G346_R5_LIVE_ROOT_EDGE
def live_root() -> str:  # G346_R5_LIVE_ROOT_DEF
    return "live"

