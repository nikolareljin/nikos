# Bundles

A bundle is an optional part of NikOS you can choose at install time: an
editor, a language runtime, a database, a set of local AI tools. The installer
asks; `nikos add <name>` turns one on afterwards.

This describes how the list of bundles is meant to be published, and why it
should be written once rather than in every place that offers it.

The manifest below is not implemented yet. The behaviour it describes already
is — it is what `install.sh` and `scripts/nikos` do today, spread across
several lists.

## What a bundle is, in the playbook

A bundle is an Ansible **tag**, and a tag is attached to tasks rather than to
roles. Some are declared on a role in `site.yml`; others are declared on tasks
inside a role and never appear in `site.yml` at all. `ollama-models` is
declared in `roles/ai-stack/tasks/main.yml`, and every AI sub-tool
(`ai-gemini`, `ai-claude`, `ai-copilot-cli`, `ai-runner`, `ai-vscode`) is the
same. Only `ansible-playbook --list-tags` sees all of them.

With that in mind, a bundle is in one of three states.

**Always.** Roles carrying no tag anywhere — `base`, `desktop`, `theming`,
`github-setup`, `editors`, `cloud-ai-cli`, `agent-dev`, `dev-tools`. Tags
select tasks, not roles by name, so an untagged role cannot be selected or
skipped and always runs. That is deliberate: those roles are what makes a
machine NikOS rather than a stock Xubuntu. They are not bundles and must not be
offered as if they were.

**On by default.** `network`, `music`, `education` and `ai-local`, declared on
roles in `site.yml`; and the AI sub-tools `ai-gemini`, `ai-claude`,
`ai-copilot-cli`, `ai-runner`, `ai-vscode`, declared on tasks inside
`roles/ai-stack`. Declining one adds it to `--skip-tags`.

**Opt-in.** Declared `tags: [never, <name>]`, so they never run unless asked
for by name: `neovim`, `java`, `podman`, `openclaw`, `bun`, `redis`,
`postgres`, `zsh`, `act`, `fabric`, `k8s-tools`, `qdrant`, `bitnet`,
`mistral-rs` and `monitoring` on roles in `site.yml`, and `ollama-models` on
tasks inside `roles/ai-stack`. Accepting one puts it in
`--tags` on a **second** playbook run, because `--tags` restricts a run to
tagged tasks and a single run carrying it would skip everything untagged —
which is to say, the whole system.

`ai-node` is not a bundle and is never offered. It is derived: skipped unless
`ai-gemini` or `ai-claude` was chosen, because those are what need it.

## Why a manifest

The list is currently written four times: in `site.yml`, in both selectors in
`install.sh`, and in `scripts/nikos`. Every one of them has to agree, and
nothing checks that they do.

The failure that follows is quiet. Add a role to `site.yml` and forget one of
the other three, and the bundle is simply never offered — no error, no warning,
just a choice that silently is not there. The same shape as #53, where a
selection was made and silently not installed.

A single manifest fixes that, and lets anything else that offers these choices
read them instead of keeping a fifth copy.

## Shape

`bundles.yml` at the repository root:

```yaml
- tag: network
  name: Network tools
  description: Diagnostics and capture tools.
  default: true

- tag: ollama-models
  name: Local Ollama models
  description: Downloads model weights. Several gigabytes.
  default: false
  weight: heavy

- tag: neovim
  name: Neovim
  description: Neovim with the NikOS configuration.
  default: false
```

- `tag` — the Ansible tag, exactly as the playbook declares it, whether that
  is on a role in `site.yml` or on tasks inside a role.
- `default` — `true` for on-by-default, `false` for `never`-tagged opt-ins.
  This is what decides whether declining produces a `--skip-tags` entry or
  accepting produces a `--tags` entry, so it must match the playbook.
- `weight: heavy` — costs gigabytes. Anything offering these choices should say
  so before the download starts, not after.

`install.sh` and `scripts/nikos` read it instead of their inline lists, and a
test asserts every `tag` appears in `ansible-playbook site.yml --list-tags`, so
the manifest cannot drift from the playbook it describes.

The check has to be `--list-tags` rather than a grep of `site.yml`. Most of the
AI tags and `ollama-models` are declared on tasks inside roles and never appear
in `site.yml`, so a `site.yml` check would reject a correct manifest.

## What this does not change

Which roles are optional, what each installs, and the two-pass run. Those are
already true. The manifest only writes the list down once.
