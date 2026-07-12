from uuid import UUID, uuid4


def new_id() -> str:
    """Return a canonical random UUID for a persisted domain record."""
    return str(uuid4())


def validate_id(value: str) -> str:
    """Validate and normalize a persisted UUID string."""
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{value!r} is not a valid UUID") from exc
    canonical = str(parsed)
    if canonical != value:
        raise ValueError(f"{value!r} is not a canonical valid UUID")
    return canonical
