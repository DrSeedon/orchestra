# quota-headroom-bar

- Raw provider quota windows may omit the synthetic `id`; `_usageProviderWindows` adds duration, so matching quota-map windows must allow a missing id and use duration/reset.
