"""Dead code module — function never called anywhere."""

def orphan_complex_logic(data: dict) -> dict:
    """A complex function that nobody calls.

    This should have 0 affected when changed.
    """
    result = {}
    for key, value in data.items():
        if isinstance(value, int):
            result[key] = value * 2
        elif isinstance(value, str):
            result[key] = value.upper()
        else:
            result[key] = str(value)
    return result


def used_function():
    """This one IS called by someone."""
    return "I am used"
