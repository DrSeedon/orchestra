"""Collapse integers into a compact human-readable range string.

Contract (this docstring is the spec):
  humanize_ranges(nums) accepts any iterable of ints. The input may be
  unsorted and may contain duplicates; both must be tolerated.

  Consecutive runs of THREE OR MORE integers collapse to "a-b".
  A run of exactly two stays as two separate entries, "a,b".
  Entries are joined with "," in ascending order.
  An empty input returns "".
"""


def humanize_ranges(nums):
    nums = list(nums)
    if not nums:
        return ""

    parts = []
    start = nums[0]
    prev = nums[0]

    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append((start, prev))
        start = prev = n
    parts.append((start, prev))

    out = []
    for a, b in parts:
        if a == b:
            out.append(str(a))
        else:
            out.append(f"{a}-{b}")
    return ",".join(out)
