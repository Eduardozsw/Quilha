# Quilha Desktop

App Tauri sobre a API local do Quilha (`serve`). Reúne numa janela o que antes só existia na CLI:
conversa, competências, vagas, currículos por perfil, estudos, candidaturas, e-mails e operação.

O app sobe o backend numa porta livre de 127.0.0.1, com um token novo a cada execução, e encerra o
processo ao fechar a janela. O log do backend fica na pasta de logs do app (`backend.log`); o caminho
aparece na tela se o backend não responder.

- **Em desenvolvimento** (`tauri dev`), o backend é o `.venv/bin/hermes` da raiz do projeto, e a
  configuração e o banco são os da raiz (como na CLI).
- **No app instalado**, o backend é o binário congelado que vai junto em `backend/`, e configuração e banco
  ficam na pasta de dados do usuário (ver "Instalar" no README da raiz).

## Pré-requisitos (uma vez)

```bash
sudo pacman -S --needed rust webkit2gtk-4.1 base-devel curl wget file openssl \
  appmenu-gtk-module libappindicator-gtk3 librsvg xdotool
cd .. && uv sync          # o app usa .venv/bin/hermes
cd desktop && npm install
```

## Rodar

```bash
npm run tauri dev         # a primeira compilação do Rust demora alguns minutos
```

`HERMES_ROOT` aponta para outro checkout do projeto Python, se precisar.

## Só a interface, no navegador

Útil para mexer no visual sem compilar Rust:

```bash
HERMES_API_TOKEN=dev uv run quilha serve --port 8765        # na raiz do projeto
VITE_HERMES_PORTA=8765 VITE_HERMES_TOKEN=dev npx vite       # aqui; abre em localhost:1420
```

## Gerar o instalador

Os instaladores oficiais saem do GitHub Actions (`.github/workflows/release.yml`) ao criar uma tag `v*`, num
release em rascunho. Para gerar localmente, no sistema em que você está (PyInstaller não faz build cruzado):

```bash
# 1. backend congelado, na raiz do projeto
uv sync --group empacotamento
uv run --group empacotamento pyinstaller packaging/quilha-backend.spec --noconfirm
HERMES_HOME=$(mktemp -d) dist/quilha-backend/quilha-backend diagnostico   # schema e PDF, sem LLM

# 2. para dentro do Tauri e o instalador
rm -rf desktop/src-tauri/backend && mkdir -p desktop/src-tauri/backend
cp -a dist/quilha-backend/. desktop/src-tauri/backend/
cd desktop && npm run tauri build -- --bundles appimage   # ou deb, nsis, msi, dmg
```

O build de release falha de propósito se `src-tauri/backend/` não tiver o binário (`build.rs`). Os
instaladores ficam em `src-tauri/target/release/bundle/`.

## Verificar

```bash
npm run typecheck
(cd src-tauri && cargo check)
```
