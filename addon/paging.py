"""Deterministic offset pagination shared by listing commands."""


def paginate(items: list, params: dict) -> tuple[list, dict]:
    """Return one page and its metadata. Without paging parameters, return everything and no metadata."""
    limit = params.get("limit")
    offset = params.get("offset")
    if limit is None and offset is None:
        return items, {}
    offset = offset or 0
    page = items[offset:] if limit is None else items[offset : offset + limit]
    end = offset + len(page)
    return page, {
        "total": len(items),
        "count": len(page),
        "offset": offset,
        "next_offset": end if end < len(items) else None,
    }
