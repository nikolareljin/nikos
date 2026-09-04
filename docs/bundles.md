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
inside a role and never appear in `site.yml` at all, and those are spread
across roles rather than gathered in one:

| Tag | Declared in |
| --- | --- |
| `ai-gemini`, `ai-copilot-cli`, `ai-node` | `roles/cloud-ai-cli/tasks/main.yml` |
| `ai-claude`, `ai-vision` | `roles/agent-dev/tasks/main.yml` |
| `ai-runner` | `roles/dev-tools/tasks/main.yml` |
| `ai-vscode` | `roles/editors/tasks/main.yml` |
| `ollama-models`, `ollama-reasoning`, `ollama-coding`, `ollama-text`, `ollama-vision`, `ollama-embedding` | `roles/ai-stack/tasks/main.yml` |

That is thirteen tags `site.yml` never mentions. It carries the other
twenty-one names, two of which — `always` and `never` — are Ansible keywords
rather than bundles. So reading `site.yml` finds a list missing well over a
third of what exists, and grepping the roles finds the rest only if you
already know which roles to open. Only
`ansible-playbook site.yml -i inventory/local --list-tags` sees all of them,
which is why that is what any check of this list has to run. The inventory is
not optional: `site.yml` targets the `local` group and `ansible.cfg` sets no
default inventory, so the command fails without it.

```
$ ansible-playbook site.yml -i inventory/local --list-tags
      TASK TAGS: [act, ai-claude, ai-copilot-cli, ai-gemini, ai-local,
      ai-node, ai-runner, ai-vision, ai-vscode, always, bitnet, bun,
      education, fabric, java, k8s-tools, mistral-rs, monitoring, music,
      neovim, network, never, ollama-coding, ollama-embedding, ollama-models,
      ollama-reasoning, ollama-text, ollama-vision, openclaw, podman,
      postgres, qdrant, redis, zsh]
```

With that in mind, two things decide whether a bundle lands on a machine, and
they are not the same thing. **How the playbook treats the tag** decides what
happens when nothing says otherwise. **What the installer preselects** decides
what usually does say otherwise. A manifest has to carry both, because the two
disagree today and reading only one of them gives the wrong answer.

Taking the playbook first.

**Always.** Roles carried in `site.yml` with no role-level tag — `base`,
`desktop`, `theming`, `github-setup`, `editors`, `cloud-ai-cli`, `agent-dev`,
`dev-tools`. Tags select tasks, not roles by name, and Ansible does not give a
role an implicit tag named after it, so a role with no tag on it cannot be
named in `--tags` or `--skip-tags`, and it always runs. `docs/debugging.md`
told people to re-run theming with `--tags theming`; that command selects the
`always` tasks and nothing else, and exits cleanly having done nothing. It now
points at `nikos setup`, which re-runs everything while honouring the saved
`--skip-tags`. That is
deliberate: those roles are what makes a machine NikOS rather than a stock
Xubuntu. They are not bundles and must not be offered as if they were.

Four of them do contain individually tagged tasks — `editors`, `cloud-ai-cli`,
`agent-dev` and `dev-tools` each hold one of the AI sub-tools above. Skipping
that tag drops those tasks; the rest of the role still runs. The role is what
is unconditional here, not every task in it.

**Skip to remove.** A plain tag, carrying no `never`: `network`, `music`,
`education` and `ai-local` on roles in `site.yml`, and `ai-gemini`,
`ai-claude`, `ai-copilot-cli`, `ai-runner`, `ai-vscode`, `ai-node` and
`ai-vision` on tasks inside the roles named in the table above. A plain tag
runs unless it is named in `--skip-tags`, so a bare `ansible-playbook site.yml`
installs all of them. Declining one at the prompt is what puts it in
`--skip-tags`.

**Named to run.** Declared `tags: [never, <name>]`, so they never run unless asked
for by name: `neovim`, `java`, `podman`, `openclaw`, `bun`, `redis`,
`postgres`, `zsh`, `act`, `fabric`, `k8s-tools`, `qdrant`, `bitnet`,
`mistral-rs` and `monitoring` on roles in `site.yml`, and `ollama-models` plus
the five per-family tags `ollama-reasoning`, `ollama-coding`, `ollama-text`,
`ollama-vision` and `ollama-embedding` on tasks inside `roles/ai-stack`. Each
model task carries `ollama-models` and its own family tag, so `--tags
ollama-models` pulls every model and `--tags ollama-coding` pulls one family.
Accepting one puts it in `--tags` on a **second** playbook run, because
`--tags` restricts a run to tagged tasks and a single run carrying it would
skip everything untagged — which is to say, the whole system.

Two tags are not bundles and are offered by nothing.

`ai-node` is derived. `install.sh` adds it to `--skip-tags` unless `ai-gemini`
or `ai-claude` was chosen, because those are what need it. It shares its tasks
with `ai-gemini` and `openclaw`, so those tasks run if any of the three is
wanted.

`ai-vision` is not derived and not offered either, which looks like an
oversight rather than a decision. It is a plain tag on four `roles/agent-dev`
tasks, so it always installs, and no selector mentions it and nothing can
decline it. A manifest is where that becomes visible; it is listed here so it
is not lost, not fixed here.

## What the installer preselects

"Skip to remove" is the playbook's behaviour and says nothing about what a
person is offered. `install.sh` has its own defaults, and for three bundles
they are the opposite:

| Bundle | Playbook | Installer default |
| --- | --- | --- |
| `network`, `music`, `education` | skip to remove | **off** — `off` in the checklist, `[y/N]` in text mode |
| `ai-local`, `ai-gemini`, `ai-claude`, `ai-copilot-cli`, `ai-runner`, `ai-vscode` | skip to remove | **on** — `on` in the checklist, `[Y/n]` in text mode |
| `ai-node` | skip to remove | derived from `ai-gemini`/`ai-claude` |
| `ai-vision` | skip to remove | **never offered** — always installs |
| everything under "Named to run" | never unless named | **off** |
| `ollama-reasoning` and the other four families | never unless named | offered by `scripts/nikos` only, absent from `install.sh` |

So `network`, `music` and `education` install on a bare `ansible-playbook`
run and do not install through `install.sh`, which adds each unselected one
to `--skip-tags` in `_build_tag_args`. Neither behaviour is wrong; they are
answers to different questions, and a document or a selector that reports one
as the other is telling somebody their machine has something it does not.

This is exactly what a manifest has to encode: the tag, its playbook default,
and the offered default, as three separate fields. Deriving one from another
would bake in the assumption that just failed.

## Why a manifest

The list is currently written four times: in `site.yml`, in both selectors in
`install.sh`, and in `scripts/nikos`. Every one of them has to agree, and
nothing checks that they do.

The failure that follows is quiet. Add a role to `site.yml` and forget one of
the other three, and the bundle is simply never offered — no error, no warning,
just a choice that silently is not there. The same shape as #53, where a
selection was made and silently not installed.

It has already happened twice, and both are visible above. `scripts/nikos`
accepts `ollama-reasoning` and the four other model families; `install.sh`
offers none of them, so they exist only for someone who reads `nikos add`'s
usage line. And `ai-vision` is in neither, so it installs on every machine
without appearing in any list of what a machine gets. Nothing is broken in
either case, which is the point: nothing reported them.

A single manifest fixes that, and lets anything else that offers these choices
read them instead of keeping a fifth copy.

## Shape

`bundles.yml` at the repository root:

```yaml
- tag: network
  name: Network tools
  description: Diagnostics and capture tools.
  playbook: skip-to-remove
  offered: false

- tag: ai-gemini
  name: Gemini CLI
  description: Google's Gemini command-line client.
  playbook: skip-to-remove
  offered: true

- tag: ollama-models
  name: Local Ollama models
  description: Downloads model weights. Several gigabytes.
  playbook: named-to-run
  offered: false
  weight: heavy

- tag: neovim
  name: Neovim
  description: Neovim with the NikOS configuration.
  playbook: named-to-run
  offered: false
```

- `tag` — the Ansible tag, exactly as the playbook declares it, whether that
  is on a role in `site.yml` or on tasks inside a role.
- `playbook` — `skip-to-remove` for a plain tag, `named-to-run` for a
  `never`-tagged one. This decides which list the answer goes in: declining a
  `skip-to-remove` bundle produces a `--skip-tags` entry, accepting a
  `named-to-run` one produces a `--tags` entry on the second pass. It has to
  match the playbook, and `--list-tags` is what can check that.
- `offered` — whether a selector preselects it. `network`, `music` and
  `education` are `skip-to-remove` and `offered: false`, which is the pair
  that reads as a contradiction until you know they answer different
  questions. Nothing can derive this field; it is a product decision and
  belongs written down.
- `weight: heavy` — costs gigabytes. Anything offering these choices should say
  so before the download starts, not after.

`install.sh` and `scripts/nikos` read it instead of their inline lists, taking
each checklist default from `offered`, and a test asserts every `tag` appears
in `ansible-playbook site.yml -i inventory/local --list-tags`, so the manifest
cannot drift from the playbook it describes. The test can only check
`playbook`; `offered` is checked by being the one place it is written.

The check has to be `--list-tags` rather than a grep of `site.yml`. Most of the
AI tags and `ollama-models` are declared on tasks inside roles and never appear
in `site.yml`, so a `site.yml` check would reject a correct manifest.

## What this does not change

Which roles are optional, what each installs, and the two-pass run. Those are
already true. The manifest only writes the list down once.
