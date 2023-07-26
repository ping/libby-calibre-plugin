# noq
try:
    from calibre.utils.localization import _ as _c
except ImportError:
    # fallback to global _ for older versions of calibre
    _c = _
