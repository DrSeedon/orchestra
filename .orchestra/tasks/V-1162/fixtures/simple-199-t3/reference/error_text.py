def err_text(error):
    messages = []
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        messages.append(str(current))
        current = current.__cause__
    return ": ".join(messages)
