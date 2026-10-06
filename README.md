# omegaconf-1password

A 1Password secret reference resolver for OmegaConf and Hydra

[![Build Status](https://github.com/1kbgz/omegaconf-1password/actions/workflows/build.yaml/badge.svg?branch=main&event=push)](https://github.com/1kbgz/omegaconf-1password/actions/workflows/build.yaml)
[![codecov](https://codecov.io/gh/1kbgz/omegaconf-1password/branch/main/graph/badge.svg)](https://codecov.io/gh/1kbgz/omegaconf-1password)
[![License](https://img.shields.io/github/license/1kbgz/omegaconf-1password)](https://github.com/1kbgz/omegaconf-1password)
[![PyPI](https://img.shields.io/pypi/v/omegaconf-1password.svg)](https://pypi.python.org/pypi/omegaconf-1password)

## Overview

Read secrets from 1Password directly in an OmegaConf or Hydra config, instead of
exporting them into the environment first.

```yaml
slack:
  bot_token: ${op:op://Developer - Infra/Slack Bot/credential}
  app_token: ${op:op://Developer - Infra/Slack App/credential, }
```

```python
from omegaconf import OmegaConf
from omegaconf_1password import register

register()
cfg = OmegaConf.load("config.yaml")
cfg.slack.bot_token  # read from 1Password on first access
```

Secrets resolve lazily, so only the references a config actually touches are
read. Nothing is written into the process environment, where any child process
could read it. And because Hydra saves its composed config with interpolations
unresolved, a saved config keeps the `op://` reference rather than the secret.

## Install

```bash
pip install omegaconf-1password
```

It calls the [1Password CLI](https://developer.1password.com/docs/cli/), so `op`
has to be installed and signed in. The desktop app integration is the least
friction: 1Password → Settings → Developer → "Integrate with other apps".

## Usage

### Registering

```python
from omegaconf_1password import register

register()              # ${op:...}
register("onepassword") # ${onepassword:...}
```

Registering more than once is fine, so a library can call it at import time
without worrying about ordering.

### Defaults

A second argument is returned when the reference cannot be read, which keeps a
config usable when an optional credential is missing:

```yaml
password: ${op:op://Vault/Item/credential, }
```

### Reading directly

```python
from omegaconf_1password import op_read

token = op_read("op://Vault/Item/credential")
token = op_read("op://Vault/Item/credential", "fallback", timeout=10, cache=False)
```

### Caching

Values are cached per reference, because resolving a config can touch the same
reference repeatedly and every miss is a subprocess call. Call `clear_cache()`
after rotating a credential, or in a long-lived process that should not hold
secrets longer than it needs them. Failed reads are never cached.

### With Hydra

```python
from omegaconf_1password import register

register()

@hydra.main(config_path="conf", config_name="config", version_base=None)
def main(cfg):
    ...
```

## Caveats

- `op` must be authorized in the process that resolves the config. Desktop app
  integration authorizes a terminal session, so a daemon or a non-interactive
  subprocess may need a
  [service account](https://developer.1password.com/docs/service-accounts/)
  token instead.
- Each uncached read spawns `op`, which takes a few hundred milliseconds. Lazy
  resolution keeps that proportional to the secrets a config actually uses.

> [!NOTE]
> This library was generated using [copier](https://copier.readthedocs.io/en/stable/) from the [Base Python Project Template repository](https://github.com/python-project-templates/base).
