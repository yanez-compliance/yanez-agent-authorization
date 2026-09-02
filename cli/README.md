# yanez-authz-cli

The `yanez-authz` command: a thin shell adapter over the `yanez-agent-authorization`
Python SDK for coding agents that can run approved local commands.

```sh
pip install yanez-authz-cli          # pre-release: not on PyPI yet; pip install -e cli
export YANEZ_BASE_URL=https://your-yanez-host
export YANEZ_AGENT_API_KEY=yak_...   # environment only; there is no key flag
yanez-authz --json request --terms-file terms.json
yanez-authz --json wait azr_... --timeout 900
```

`--json` and `--base-url` go before the subcommand. Terms and artifacts come from
files or stdin (`-`), never from the command line. `verify` takes `--expected-sub` to
bind the receipt to the account's YID. Exit codes: 0 answer, 1 failure or
refusal, 2 usage. Full guide: `examples/skill-cli/README.md` in the repository.
