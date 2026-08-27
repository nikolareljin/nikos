# NikOS — Neural Innovation for Knowledge OS

> **Light system. Heavy thinking.**

[![Lint](https://github.com/nikolareljin/nikos/actions/workflows/lint.yml/badge.svg)](https://github.com/nikolareljin/nikos/actions/workflows/lint.yml)
[![Dry-run Test](https://github.com/nikolareljin/nikos/actions/workflows/test.yml/badge.svg)](https://github.com/nikolareljin/nikos/actions/workflows/test.yml)

A curated Xubuntu / Ubuntu 24.04 LTS setup for AI coding and development.  
One command turns a fresh Ubuntu install into a fully configured AI workstation — Xubuntu desktop with Nordic theme, local and cloud AI stack, developer tools, and GitHub integration all pre-configured.

**Version:** 0.6.1 · **License:** MIT · **Author:** Nikola Reljin

> One file, the Plymouth boot splash, is GPL-3.0-or-later rather than MIT, because it is derived from Xubuntu's theme. See [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

<img src="./assets/logo.png" />

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/nikolareljin/nikos/main/install.sh | bash
```

The installer clones the full repo (with submodules) to `~/.local/share/nikos`, moves it to
the **newest release tag**, presents a `dialog`-based TUI to select optional bundles, then
runs the Ansible playbook behind a per-role progress gauge.
The TUI follows the controlling terminal rather than stdin, so the one-liner above gets it too —
`curl ... | bash` leaves the script's own bytes on stdin, which is not a terminal on any machine.
Set `NIKOS_USE_DIALOG=0` to force the plain-prompt fallback.

Pass `--ref <branch-or-tag>` to install something other than the latest release.

Coming from Xubuntu, log out and back in. Coming from Ubuntu, reboot: the installer moves
the display manager from GDM3 to LightDM and sets the default session to Xubuntu, and
neither applies while the GNOME session that started the installer is running. The
installer tells you which one you need when it finishes.

**Clone locally (for development or offline use):**

```bash
git clone --recurse-submodules https://github.com/nikolareljin/nikos
cd nikos
bash install.sh          # installs the latest release tag, not this checkout
bash install.sh --dev    # installs this checkout, uncommitted changes included
```

`--dev` runs the tree it was launched from and never touches
`~/.local/share/nikos`, so testing a branch cannot break a working install.

At the end, you should end up with something like: 

<img width="1920" height="1080" alt="image" src="https://github.com/user-attachments/assets/570e5927-9a05-42c0-909c-474a8204aa7b" />


---

## What's included

### Desktop
| Component | Choice |
|---|---|
| Desktop environment | Xubuntu (Xfce 4) |
| GTK theme | Nordic (Nord palette) |
| Icon theme | Papirus-Dark |
| Login screen | LightDM + Nordic greeter |
| Boot splash | Plymouth — NikOS logo on Nord dark |
| GRUB theme | Nordic |
| Wallpaper | NikOS logo on Nord dark |
| Terminal font | JetBrains Mono |

### AI stack
| Tool | Purpose |
|---|---|
| [Ollama](https://ollama.ai) | Local LLM runtime — `qwen2.5-coder:7b` pre-pulled |
| [aider](https://aider.chat) | AI pair programmer in the terminal |
| [Miniforge](https://github.com/conda-forge/miniforge) | Python distribution (conda) |
| `nikos-ai` conda env | Python 3.11-3.13 + PyTorch CPU + Jupyter + transformers + pandas |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Prebuilt binaries — `llama-server`, `llama-cli` |
| Retrieval stack | Chroma, Qdrant client, sentence-transformers |
| Image analysis | OpenCV, Pillow, scikit-image, timm, Tesseract OCR |
| [Claude Code](https://github.com/anthropics/claude-code) | Anthropic's AI coding CLI |
| [Gemini CLI](https://github.com/google-gemini/gemini-cli) | Google Gemini in the terminal |
| GitHub Copilot CLI | `gh copilot` extension |
| LangChain + LlamaIndex | Agent framework libraries |
| [ai-runner](https://github.com/nikolareljin/ai-runner) | Simple UI for local Ollama models |

### Local models

One model is pulled by default: `qwen2.5-coder:7b` (4.7 GB). The rest are
grouped by what they are for, each with its own tag, so a laptop can take one
group without the others:

```bash
nikos add ollama-reasoning   # ~23 GB  deepseek-r1, qwen3, phi4
nikos add ollama-coding      # ~34 GB  deepseek-coder-v2, qwen2.5-coder, qwen3-coder
nikos add ollama-text        # ~22 GB  granite4, llama3.1, gemma3, mistral
nikos add ollama-vision      # ~13 GB  granite3.2-vision, minicpm-v, qwen2.5vl
nikos add ollama-embedding   # ~1.3 GB embeddinggemma, qwen3-embedding
nikos add ollama-models      # ~93 GB  every group
```

Nothing is pulled unless you ask for the tag. Models load on demand, so this is
disk and bandwidth rather than idle memory.

### IDE
| Tool | Detail |
|---|---|
| VS Code | Installed via Microsoft apt repo |
| Continue | AI code completion |
| GitLens | Git history in editor |
| GitHub Copilot | AI suggestions |
| [Leak Lock](https://marketplace.visualstudio.com/items?itemName=nikolareljin.leak-lock) | Secret detection and leak prevention in VS Code |
| Nord theme | `arcticicestudio.nord-visual-studio-code` |
| Python + Jupyter | Official MS extensions |

### Developer tools
Installed via [distrodeck](https://github.com/nikolareljin/distrodeck):
`bat` · `eza` · `fzf` · `lazygit` · `gh` · `rust` · `go` · `docker` · and more

Additional tools installed directly:
| Tool | Command | Purpose |
|---|---|---|
| [image-view](https://github.com/nikolareljin/image-view) | `image-view` | Terminal image preview (Rust) |
| [git-lantern](https://github.com/nikolareljin/git-lantern) | `lantern` | Repo dashboard — local + GitHub status |

### GitHub integration
- `gh` CLI pre-installed
- First-login wizard: authenticates GitHub, generates SSH key, configures git identity
- Optional dotfiles pull from your GitHub repo

---

## Commands

```
nikos setup          # run full playbook (first install)
nikos update         # move to the newest release, then re-run the playbook
nikos update --ref X # update to a specific branch or tag instead
nikos add network    # install optional: nmap, wireshark, OpenVPN
nikos add music      # install optional: LMMS, Ardour, Audacity
nikos add education  # install optional: LibreOffice, draw.io, Anki
nikos add neovim     # install optional: Neovim + starter lazy.nvim config
nikos add java       # install optional: OpenJDK 21
nikos add podman     # install optional: Podman
nikos add bun        # install optional: Bun JavaScript runtime
nikos add postgres   # install optional: PostgreSQL + pgvector
nikos add redis      # install optional: Redis
nikos add qdrant     # install optional: Qdrant vector database
nikos add zsh        # install optional: Zsh + Starship
nikos add k8s-tools  # install optional: kubectl + Helm
nikos add act        # install optional: local GitHub Actions runner
nikos add fabric     # install optional: Fabric AI pattern CLI
nikos add openclaw   # install optional: OpenClaw LLM gateway CLI
nikos add monitoring # install optional: Netdata
nikos add bitnet     # install optional: BitNet.cpp 1-bit inference (bitnet-cli)
nikos add mistral-rs # install optional: mistral.rs Rust LLM server
nikos add ollama-*   # install optional: a model group (see Local models above)
nikos status         # show version, Ollama models, conda envs
nikos doctor         # check for broken configs and missing tools
nikos log [N]        # tail the latest playbook log
```

`nikos update` reads its target from what is checked out: a release install
advances to the newest release only when that release is genuinely newer, and a
branch install stays on its branch. An update never downgrades.

---

## Customization

Create `vars/local.yml` before running the playbook to override defaults without
editing tracked files:

```yaml
nikos_timezone: "Europe/London"     # override this for your timezone
ollama_default_model: "qwen2.5-coder:7b"  # model to pre-pull
nikos_desktop_flavor: "xubuntu-minimal"   # or xubuntu-full / xfce
nikos_remove_gnome: false           # true purges GNOME instead of keeping it selectable
nikos_vscode_extensions:            # add/remove VS Code extensions
  - "Continue.continue"
  - ...
```

To add optional bundles after install:

```bash
nikos add network
nikos add music
nikos add education
nikos add postgres
nikos add ollama-models
```

See [docs/customization.md](docs/customization.md) for full details.

---

## Ecosystem

NikOS is the workstation layer of a broader AI development toolkit maintained by Nikola Reljin:

| Repo | Purpose |
|---|---|
| [nikolareljin/nikos](https://github.com/nikolareljin/nikos) | This repo — workstation setup |
| [nikolareljin/distrodeck](https://github.com/nikolareljin/distrodeck) | Cross-distro CLI tool installer (used by dev-tools role) |
| [nikolareljin/ai-runner](https://github.com/nikolareljin/ai-runner) | Local Ollama model runner with simple UI |
| [nikolareljin/finetorch](https://github.com/nikolareljin/finetorch) | Rust-native LLM finetuning — LoRA/QLoRA, dataset prep, training on a single GPU |
| [nikolareljin/shrink-llm](https://github.com/nikolareljin/shrink-llm) | LLM compression — quantization, pruning, knowledge distillation for mobile/edge |
| [nikolareljin/image-view](https://github.com/nikolareljin/image-view) | Terminal image preview CLI (pre-installed on NikOS) |
| [nikolareljin/git-lantern](https://github.com/nikolareljin/git-lantern) | Repo dashboard CLI — local + GitHub branch status (pre-installed on NikOS) |

### AI modeling workflow

NikOS provides the development environment. The modeling pipeline runs on top of it:

```
finetorch  →  train a custom model (LoRA/QLoRA, single GPU)
    ↓
shrink-llm →  compress for deployment (quantize, prune, distill)
    ↓
Ollama     →  serve locally on NikOS
    ↓
ai-runner  →  interact via simple UI
aider / Claude Code / Continue  →  use in code
```

---

## Documentation

**[nikolareljin.github.io/nikos](https://nikolareljin.github.io/nikos/)** — overview, install guide and the full inventory.

- [Installation guide](docs/install.md) — detailed install, requirements, troubleshooting
- [Customization](docs/customization.md) — vars, roles, optional bundles
- [Debugging](docs/debugging.md) — `nikos doctor`, common issues, logs
- [Development](docs/development.md) — adding roles, testing, contributing

---

## License

MIT — Copyright © 2026 Nikola Reljin
