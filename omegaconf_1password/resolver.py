"""An OmegaConf resolver that reads 1Password secret references."""

from __future__ import annotations

import subprocess
from threading import Lock

from omegaconf import OmegaConf

__all__ = (
    "DEFAULT_RESOLVER_NAME",
    "OnePasswordError",
    "clear_cache",
    "op_read",
    "register",
)

#: The name the resolver is registered under, so configs say ``${op:...}``.
DEFAULT_RESOLVER_NAME = "op"

_PREFIX = "op://"
_cache: dict[str, str] = {}
_cache_lock = Lock()


class OnePasswordError(RuntimeError):
    """Raised when a secret reference cannot be read."""


def _run_op(reference: str, timeout: float) -> str:
    try:
        completed = subprocess.run(
            ["op", "read", "--no-newline", reference],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - depends on the machine
        raise OnePasswordError("the 1Password CLI (`op`) is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise OnePasswordError(f"timed out after {timeout}s reading {reference}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        reason = detail[-1] if detail else f"`op` exited {completed.returncode}"
        raise OnePasswordError(f"could not read {reference}: {reason}")
    return completed.stdout


def op_read(reference: str, default: str | None = None, *, timeout: float = 30.0, cache: bool = True) -> str:
    """Read one ``op://`` secret reference.

    Args:
        reference: A reference of the form ``op://vault/item/field``.
        default: Returned instead of raising when the reference cannot be read.
            Supplying one turns a missing secret into a usable config rather
            than a failure, which suits optional backends.
        timeout: Seconds to wait for the 1Password CLI.
        cache: Reuse a previously read value for the same reference. Resolving
            a config can touch the same reference repeatedly, and every miss
            costs a subprocess call.

    Returns:
        The secret value.

    Raises:
        OnePasswordError: If the reference is malformed, or cannot be read and
            no default was supplied.
    """
    if not isinstance(reference, str) or not reference.startswith(_PREFIX):
        raise OnePasswordError(f"{reference!r} is not an {_PREFIX} secret reference")

    if cache:
        with _cache_lock:
            hit = _cache.get(reference)
        if hit is not None:
            return hit

    try:
        value = _run_op(reference, timeout)
    except OnePasswordError:
        if default is not None:
            return default
        raise

    if cache:
        with _cache_lock:
            _cache[reference] = value
    return value


def clear_cache() -> None:
    """Forget every cached secret.

    Worth calling after rotating a credential, or in a long-lived process that
    should not hold secrets longer than it needs them.
    """
    with _cache_lock:
        _cache.clear()


def register(name: str = DEFAULT_RESOLVER_NAME, *, replace: bool = True) -> None:
    """Register the resolver with OmegaConf.

    Args:
        name: The resolver name, so ``op`` gives ``${op:op://vault/item/field}``.
        replace: Overwrite an existing resolver of the same name. Registering
            twice is otherwise an error, which makes imports order-dependent.
    """
    OmegaConf.register_new_resolver(name, op_read, replace=replace)
