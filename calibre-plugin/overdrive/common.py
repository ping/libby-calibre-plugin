#
# Copyright (C) 2023 github.com/ping
#
# This file is part of the OverDrive Libby Plugin by ping
# OverDrive Libby Plugin for calibre / libby-calibre-plugin
#
# See https://github.com/ping/libby-calibre-plugin for more
# information
#

from collections.abc import Callable
from functools import wraps

MAX_PAGEABLE = 100


def pageable(fn: Callable):
    """
    Indicates that the function supports paging, and validates the pageSize keyword
    argument.

    :param fn:
    :return:
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        page = kwargs.get("page")
        if page is not None:
            if page <= 0:
                raise ValueError("page must be a positive int")
            kwargs["page"] = int(page)
        per_page = kwargs.get("perPage")
        if per_page is not None:
            if per_page > MAX_PAGEABLE:
                raise ValueError(f"perPage cannot be greater than {MAX_PAGEABLE}")
            if per_page <= 0:
                raise ValueError("perPage must be a positive int")
            kwargs["perPage"] = int(per_page)
        return fn(*args, **kwargs)

    return wrapper
