"""Tests for the 1Password OmegaConf resolver.

The 1Password CLI is replaced with a stub script on PATH, so these run
anywhere, including CI with no 1Password account.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest
from omegaconf import OmegaConf

from omegaconf_1password import (
    DEFAULT_RESOLVER_NAME,
    OnePasswordError,
    __version__,
    clear_cache,
    op_read,
    register,
)

KNOWN = "op://Vault/Item/credential"
UNKNOWN = "op://Vault/Missing/credential"
SECRET = "s3cr3t-value"

STUB = """#!/usr/bin/env bash
# Records each invocation so tests can assert on caching.
echo "$@" >> "$OP_STUB_CALLS"
if [[ "$1" == "read" ]]; then
  case "$3" in
    *Missing*) echo "[ERROR] item not found" >&2; exit 1 ;;
    *Slow*) sleep 5; printf 'too-late' ;;
    *) printf '%s' "$OP_STUB_SECRET" ;;
  esac
  exit 0
fi
exit 0
"""


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture(name="op_stub")
def fixture_op_stub(tmp_path, monkeypatch):
    """Put a fake `op` on PATH and report where it logs its calls."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "op"
    stub.write_text(STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    calls = tmp_path / "calls.log"
    calls.touch()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("OP_STUB_CALLS", str(calls))
    monkeypatch.setenv("OP_STUB_SECRET", SECRET)
    return calls


def call_count(calls: Path) -> int:
    return len([line for line in calls.read_text().splitlines() if line.strip()])


def test_version():
    assert __version__


def test_reads_a_reference(op_stub):
    assert op_read(KNOWN) == SECRET


def test_rejects_anything_that_is_not_a_reference(op_stub):
    for bad in ("Vault/Item/credential", "https://example.com", "", None):
        with pytest.raises(OnePasswordError, match="secret reference"):
            op_read(bad)
    assert call_count(op_stub) == 0, "a malformed reference should never shell out"


def test_missing_reference_raises(op_stub):
    with pytest.raises(OnePasswordError, match="could not read"):
        op_read(UNKNOWN)


def test_missing_reference_can_fall_back_to_a_default(op_stub):
    assert op_read(UNKNOWN, "fallback") == "fallback"


def test_repeated_reads_are_cached(op_stub):
    assert op_read(KNOWN) == SECRET
    assert op_read(KNOWN) == SECRET
    assert call_count(op_stub) == 1, "the second read should come from the cache"


def test_caching_can_be_disabled(op_stub):
    op_read(KNOWN, cache=False)
    op_read(KNOWN, cache=False)
    assert call_count(op_stub) == 2


def test_clear_cache_forces_a_reread(op_stub):
    op_read(KNOWN)
    clear_cache()
    op_read(KNOWN)
    assert call_count(op_stub) == 2


def test_failures_are_not_cached(op_stub):
    assert op_read(UNKNOWN, "fallback") == "fallback"
    assert op_read(UNKNOWN, "fallback") == "fallback"
    assert call_count(op_stub) == 2, "a failed read should be retried, not remembered"


def test_timeout_is_reported(op_stub):
    with pytest.raises(OnePasswordError, match="timed out"):
        op_read("op://Vault/Slow/credential", timeout=0.3)


def test_resolver_resolves_in_a_config(op_stub):
    register()
    cfg = OmegaConf.create({"token": f"${{{DEFAULT_RESOLVER_NAME}:{KNOWN}}}"})
    assert cfg.token == SECRET


def test_resolver_supports_a_default(op_stub):
    register()
    cfg = OmegaConf.create({"token": f"${{{DEFAULT_RESOLVER_NAME}:{UNKNOWN},fallback}}"})
    assert cfg.token == "fallback"


def test_unresolved_config_keeps_the_reference_not_the_secret(op_stub):
    """What gets written to disk must stay a reference.

    Hydra saves the composed config with interpolations unresolved, so a saved
    config holds the op:// reference rather than the secret. That property is
    the main reason to prefer this over exporting secrets into the environment.
    """
    register()
    cfg = OmegaConf.create({"token": f"${{{DEFAULT_RESOLVER_NAME}:{KNOWN}}}"})
    dumped = OmegaConf.to_yaml(cfg, resolve=False)

    assert KNOWN in dumped
    assert SECRET not in dumped
    assert call_count(op_stub) == 0, "dumping unresolved should not read any secret"


def test_registering_twice_is_allowed(op_stub):
    register()
    register()
    cfg = OmegaConf.create({"token": f"${{{DEFAULT_RESOLVER_NAME}:{KNOWN}}}"})
    assert cfg.token == SECRET


def test_resolver_can_be_registered_under_another_name(op_stub):
    register("onepassword")
    cfg = OmegaConf.create({"token": f"${{onepassword:{KNOWN}}}"})
    assert cfg.token == SECRET


def test_missing_cli_is_reported(monkeypatch, tmp_path):
    """A machine without the CLI should say so, not fail obscurely."""
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(OnePasswordError, match="not installed"):
        op_read(KNOWN)


def test_console_usage_matches_the_readme(op_stub):
    """The README's example should work as written."""
    script = (
        "from omegaconf import OmegaConf\n"
        "from omegaconf_1password import register\n"
        "register()\n"
        f'cfg = OmegaConf.create({{"token": "${{op:{KNOWN}}}"}})\n'
        "print(cfg.token)\n"
    )
    result = subprocess.run(["python", "-c", script], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert SECRET in result.stdout
