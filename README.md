# NikOS — Neural Innovation for Knowledge OS

> Light system. Heavy thinking.

A curated Ubuntu 24.04 LTS setup for AI coding and development.
Built on Xfce + Nordic theme. Powered by Ollama, aider, VS Code, and the full AI dev stack.

**Version:** 0.1.0

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/nikolareljin/nikos-os/main/install.sh | bash
```

## What's included

- **Desktop:** Xfce 4 + Nordic GTK theme (Nord palette)
- **AI tools:** Ollama (`qwen2.5-coder:7b`), aider, Claude Code, LangChain, LlamaIndex
- **IDE:** VS Code with Continue, GitLens, Copilot, Nord theme
- **Python:** Miniforge + `nikos-ai` conda env (PyTorch, Jupyter, transformers)
- **CLIs:** Gemini CLI, GitHub Copilot CLI, Claude Code
- **Dev tools:** distrodeck install-tools (bat, eza, fzf, lazygit, gh, rust, go, docker…)
- **GitHub:** First-run wizard for auth, SSH key, and git identity

## Update

```bash
nikos update
```

## Optional apps

```bash
nikos add network    # nmap, wireshark, network manager extras
nikos add music      # LMMS, Ardour, Audacity
nikos add education  # LibreOffice, draw.io, Anki
```

## Commands

```
nikos setup          # run full playbook (first install)
nikos update         # ansible-pull + re-run (idempotent)
nikos add <name>     # install optional role
nikos status         # show installed roles, Ollama models
nikos doctor         # check for broken configs
```

## License

MIT
