"""Plain static symbols plus deliberately similar lexical noise."""


def plain_target(value: int) -> int:  # G346_R1_DEF
    return value + 1


class Unrelated:
    def plain_target(self, value: int) -> int:  # G346_R1_UNRELATED_METHOD
        return value - 1


PLAIN_NAME = "plain_target"  # G346_R1_NOISE_STRING

