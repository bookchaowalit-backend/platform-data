"""Service-owned shared data primitives; no lake-state migration."""

from ._sentry import init_sentry as _init_sentry

_init_sentry()
