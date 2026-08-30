import math
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 24
MAX_PAGE_SIZE = 100


class Page(BaseModel, Generic[T]):
    """
    Generic pagination envelope shared by every directory list endpoint
    (institutions, companies — see routes/institutions.py, routes/companies.py).
    One shape everywhere rather than each endpoint inventing its own.
    """

    items: list[T]
    page: int
    page_size: int
    total: int
    total_pages: int

    @classmethod
    def of(cls, items: list[T], *, page: int, page_size: int, total: int) -> "Page[T]":
        return cls(items=items, page=page, page_size=page_size, total=total, total_pages=max(1, math.ceil(total / page_size)) if page_size else 1)
