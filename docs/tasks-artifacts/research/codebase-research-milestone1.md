# Research: Milestone 1 — Setup do Ambiente e Base de Código

Snapshot: 2026-11-06. Antes da criação deste documento, o working tree estava limpo e o HEAD em `7eae7ec` (`feat: milestone 1 Setup do Ambiente e Base de Código`).
Este documento atualiza o levantamento anterior (`docs/features/codebase-research.md`, snapshot de 2026-11-05) com o estado do código após a Milestone 1.

## Summary

A Milestone 1 está registrada como concluída em `docs/features/plan.md:14-22`, com as Tasks 1.1 a 1.5 marcadas `[x]`. O repositório passou de um script de 65 linhas sem CLI para `setup_lab.py` com 294 linhas, dividido em funções, com `argparse`, `python-dotenv`, autenticação Bearer e `api_version=3` no `gns3fy` (`setup_lab.py:1-294`). Foram adicionados `requirements.txt` com cinco dependências fixadas (`requirements.txt:1-6`) e `.env.example` com as variáveis de ambiente (`.env.example:1-23`), além de `.env` local ignorado pelo Git (`.gitignore:7-11`). O `.venv` contém `gns3fy 0.8.0`, `requests 2.34.2`, `netmiko 4.8.0`, `Jinja2 3.1.6` e `python-dotenv 1.2.4` instalados, em Python 3.14.9 (`.venv/pyvenv.cfg:1-4`). A execução de `.venv/bin/python setup_lab.py --check` contra o servidor local retornou código 0, projeto `uasc` (`status=opened`, 14 nós) e a lista de consoles; não há `inventario_gns3.json` no diretório de trabalho.

## 1. Checklist da consulta (Milestone 1)

| Área verificada | Estado atual | Evidência |
|:--|:--|:--|
| Task 1.1 — repositório e `venv` | Repositório Git com 2 commits; `.venv` com Python 3.14.9 | `git log`; `.venv/pyvenv.cfg:1-4` |
| Task 1.2 — dependências | 5 dependências declaradas e instaladas | `requirements.txt:1-6`; `.venv/bin/pip list` |
| Task 1.3 — `.env` | `.env` local presente e ignorado; `.env.example` versionado | `.env.example:1-23`; `.gitignore:8` |
| Task 1.4 — token Bearer + API v3 | `GNS3_ACCESS_TOKEN` lido do ambiente e enviado em `Authorization: Bearer`; conector criado com `api_version` configurável (padrão 3) | `setup_lab.py:76-110` |
| Task 1.5 — teste de conexão | `setup_lab.py --check` implementado; execução local validada | `setup_lab.py:47-73`, `setup_lab.py:200-206` |
| Documentação da milestone | Tasks 1.1–1.5 marcadas e pré-requisito técnico registrado | `docs/features/plan.md:14-22` |

## 2. Estado do repositório e do histórico Git

Commits existentes:

| Commit | Data | Mensagem | Arquivos alterados |
|:--|:--|:--|:--|
| `d06e965` | 2026-11-05 23:09:43 -0300 | `initial setup` | 13 arquivos, incluindo `setup_lab.py` de 65 linhas |
| `7eae7ec` | 2026-11-05 23:32:24 -0300 | `feat: milestone 1 Setup do Ambiente e Base de Código` | `.env.example`, `.gitignore`, `docs/features/plan.md`, `requirements.txt`, `setup_lab.py` |

O commit `7eae7ec` adicionou `.env.example` (23 linhas) e `requirements.txt` (6 linhas), alterou `.gitignore`, atualizou `docs/features/plan.md` e reescreveu `setup_lab.py` de 65 para 294 linhas.

Arquivos rastreados pelo Git hoje (`git ls-files`):

- `.env.example`, `.gitignore`, `AGENTS.md`, `requirements.txt`, `setup_lab.py`
- `base_topology/uasc.gns3project`
- `docs/docs.md`
- `docs/features/codebase-research.md`, `docs/features/plan.md`, `docs/features/proposal.md`
- `docs/adr/adr-001.md` a `docs/adr/adr-005.md`

Arquivos presentes no diretório de trabalho mas fora do Git:

- `.env` (395 bytes), ignorado por `.gitignore:8`.
- `__pycache__/setup_lab.cpython-314.pyc` (16.346 bytes), ignorado por `.gitignore:10-11`.
- `.venv/` — o arquivo `.venv/.gitignore:2` contém `*`, portanto o conteúdo do ambiente virtual não aparece em `git status`.

Diretório vazio: `docs/tasks-artifacts/` existe no filesystem, sem arquivos e sem entrada no Git.

Antes da criação deste documento, `git status --porcelain` retornava vazio; a única entrada não rastreada passou a ser o próprio diretório `research/`.

## 3. Dependências e ambiente de execução

### 3.1 Manifesto versionado

`requirements.txt:1-6` declara:

| Linha | Pacote | Versão fixada |
|--:|:--|:--|
| 1 | comentário | `# Runtime do laboratório (Python 3.10+)` |
| 2 | `gns3fy` | `0.8.0` |
| 3 | `requests` | `2.34.2` |
| 4 | `netmiko` | `4.8.0` |
| 5 | `Jinja2` | `3.1.6` |
| 6 | `python-dotenv` | `1.2.4` |

### 3.2 Ambiente virtual

`.venv/pyvenv.cfg:1-4` registra:

- `home = /usr/bin`
- `include-system-site-packages = false`
- `version = 3.14.9`
- `executable = /usr/bin/python3.14`

`.venv/bin/pip list` contém 29 pacotes. Os pacotes correspondentes ao manifesto estão instalados nas versões fixadas: `gns3fy 0.8.0`, `requests 2.34.2`, `netmiko 4.8.0`, `Jinja2 3.1.6`, `python-dotenv 1.2.4`. Dependências transitivas presentes incluem `paramiko 5.1.0`, `bcrypt 5.0.0`, `cryptography 50.0.2`, `pyserial 3.5`, `textfsm 2.1.0`, `ntc_templates 9.3.0`, `PyYAML 6.0.3`, `MarkupSafe 3.0.4` e `pydantic 1.10.27`.

O bytecode `__pycache__/setup_lab.cpython-314.pyc` corresponde ao Python 3.14 do `.venv`.

## 4. Configuração por variáveis de ambiente

### 4.1 `.env.example`

`.env.example:1-23` define o contrato de configuração:

| Linha | Variável | Valor de exemplo |
|--:|:--|:--|
| 6 | `GNS3_SERVER_URL` | `http://localhost:3080` |
| 9 | `GNS3_API_VERSION` | `3` |
| 12 | `GNS3_PROJECT_NAME` | `uasc` |
| 15 | `GNS3_ACCESS_TOKEN` | vazio |
| 19 | `GNS3_CONSOLE_HOST` | `127.0.0.1` |
| 22 | `EXOS_USERNAME` | `admin` |
| 23 | `EXOS_PASSWORD` | vazio |

Comentários do arquivo documentam: cópia para `.env` (`.env.example:1-3`), versão da API conforme GNS3 3.x (`/v3`) ou 2.x (`/v2`) (`.env.example:8-9`), origem do projeto em `base_topology/uasc.gns3project` (`.env.example:11-12`), envio do token como `Authorization: Bearer <access_token>` (`.env.example:14-15`), uso de `GNS3_CONSOLE_HOST` pelo Netmiko (`.env.example:17-19`) e uso de `EXOS_USERNAME`/`EXOS_PASSWORD` a partir do Milestone 3 (`.env.example:21-23`).

### 4.2 `.env` local

O `.env` existe no diretório raiz com 395 bytes e as mesmas sete chaves de `.env.example`. Valores não secretos observados:

- `GNS3_SERVER_URL=http://localhost:3080`
- `GNS3_API_VERSION=3`
- `GNS3_PROJECT_NAME=uasc`
- `GNS3_CONSOLE_HOST=127.0.0.1`
- `EXOS_USERNAME=admin`
- `EXOS_PASSWORD` vazio
- `GNS3_ACCESS_TOKEN` preenchido (156 caracteres; valor não transcrito neste documento)

O arquivo é ignorado por `.gitignore:8` e não aparece em `git status`.

### 4.3 `.gitignore`

`.gitignore:7-11` adiciona, em relação à versão inicial:

| Linha | Padrão | Função |
|--:|:--|:--|
| 8 | `.env` | segredo local |
| 9 | `inventario_gns3.json` | artefato gerado em runtime |
| 10 | `__pycache__/` | cache Python |
| 11 | `*.pyc` | bytecode Python |

As regras anteriores para dados pesados do GNS3 permanecem em `.gitignore:1-5`.

## 5. `setup_lab.py` — implementação atual

### 5.1 Estrutura do arquivo

| Linhas | Elemento | Conteúdo |
|--:|:--|:--|
| 1-6 | shebang e docstring | `#!/usr/bin/env python3`; declara que o script localiza o projeto existente e exporta o inventário, sem criar nós ou links |
| 22-24 | constantes de caminho | `RAIZ`, `INVENTARIO_PADRAO = RAIZ / "inventario_gns3.json"`, `HTTP_TIMEOUT = 10` |
| 27-30 | `DEVICE_TYPES` | `{"qemu": "extreme_exos_telnet", "vpcs": "generic_telnet"}` |
| 33-34 | `TokenInvalidoError` | exceção própria derivada de `RuntimeError` |
| 37-43 | `Configuracao` | dataclass `frozen` com `server_url`, `project_name`, `console_host`, `access_token`, `api_version` |
| 47-73 | `parse_args()` | opções `--server`, `--project`, `--console-host`, `--output`, `--check`, `--no-start`, `--timeout` |
| 76-100 | `carregar_configuracao()` | resolve CLI > ambiente > `.env` > padrão; valida `GNS3_API_VERSION` como inteiro |
| 103-110 | `criar_conector()` | instancia `Gns3Connector` e injeta o header Bearer na sessão |
| 113-125 | `verificar_token()` | `GET {base_url}/projects` com timeout 10 s; trata 401 e outros erros HTTP |
| 128-135 | `localizar_projeto()` | `connector.get_project(name=...)`, depois `Project(project_id=...).get()` |
| 138-144 | `aguardar()` | polling genérico com limite de tempo |
| 147-294 | `main()` | fluxo completo de conexão, abertura, start, inventário e impressão |

O arquivo termina com guard `if __name__ == "__main__": raise SystemExit(main())` (`setup_lab.py:293-294`).

### 5.2 Resolução de configuração

`carregar_configuracao()` (`setup_lab.py:76-100`):

- Executa `load_dotenv(RAIZ / ".env")` (`setup_lab.py:78`), carregando o `.env` ao lado do script, independente do diretório de execução.
- `server_url`: `--server` ou `GNS3_SERVER_URL`, padrão `http://localhost:3080` (`setup_lab.py:80`).
- `project_name`: `--project` ou `GNS3_PROJECT_NAME`, padrão `uasc` (`setup_lab.py:81`).
- `console_host`: `--console-host` ou `GNS3_CONSOLE_HOST`; se ausente, usa o hostname extraído de `server_url`, com fallback `127.0.0.1` (`setup_lab.py:82-84`).
- `api_version`: `GNS3_API_VERSION`, padrão `"3"`, convertido com `int()`; valor inválido gera `ValueError` citando o valor recebido (`setup_lab.py:86-92`).
- `access_token`: `GNS3_ACCESS_TOKEN`, com `.strip()` (`setup_lab.py:98`).

### 5.3 Autenticação Bearer e API v3

`criar_conector()` (`setup_lab.py:103-110`):

```python
connector = Gns3Connector(
    url=config.server_url,
    api_version=config.api_version,
)
connector.session.headers["Authorization"] = f"Bearer {config.access_token}"
```

`gns3fy 0.8.0` monta `base_url` como `f"{url.strip('/')}/v{api_version}"` (`.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:79-81`) e cria a `requests.Session` em `_create_session()` (`.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:95-98`). Com `GNS3_API_VERSION=3`, as chamadas vão para `/v3/*`; o header Bearer é aplicado diretamente na sessão antes de qualquer chamada.

`verificar_token()` (`setup_lab.py:113-125`) faz uma chamada explícita `GET {connector.base_url}/projects` com `timeout=HTTP_TIMEOUT` (10 s):

- HTTP 401 → `TokenInvalidoError` com mensagem para atualizar `GNS3_ACCESS_TOKEN` no `.env` (`setup_lab.py:119-123`).
- Outro status não-ok → `RuntimeError` com `HTTP <status>: <trecho do corpo>` (`setup_lab.py:124-125`).

### 5.4 Localização do projeto

`localizar_projeto()` (`setup_lab.py:128-135`):

- `connector.get_project(name=project_name)` percorre `GET /v3/projects` e retorna o primeiro projeto cujo `name` coincide; retorna `None` quando não encontra (`.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:189-207`).
- Quando `None`, o script levanta `LookupError` (`setup_lab.py:130-131`).
- Com o dicionário retornado, cria `Project(project_id=dados["project_id"], connector=connector)` e chama `lab.get()` (`setup_lab.py:133-134`).
- `Project.get()` busca o projeto, e por padrão também `stats`, `nodes` e `links` (`.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:1190-1242`).

### 5.5 Fluxo de `main()`

| Linhas | Etapa | Comportamento |
|--:|:--|:--|
| 148-153 | parse e configuração | erro de `GNS3_API_VERSION` imprime `ERRO` e retorna 1 |
| 155-161 | validação do token | token vazio imprime orientação sobre `.env` e retorna 1 |
| 163-193 | conexão | cria conector, verifica token, localiza projeto; trata `TokenInvalidoError`, `LookupError` e exceção genérica com retorno 1 |
| 195-198 | resumo | imprime nome, ID, status e quantidade de nós |
| 200-206 | modo `--check` | lista nós ordenados por nome com tipo, status e console; retorna 0 sem abrir, iniciar ou gravar inventário |
| 208-221 | abertura | se `lab.status != "opened"`, chama `lab.open()` e aguarda até `--timeout` (padrão 60 s); falha retorna 1 |
| 223-248 | start | seleciona nós com `status != "started"`; com `--no-start` não inicia; falha individual de `node.start()` gera `AVISO` e o fluxo continua; aguarda todos ficarem `started` e emite aviso se o timeout expirar |
| 250-254 | consoles | atualiza nós com `lab.get_nodes()` e aguarda todos exporem `node.console`; o retorno do `aguardar` não é verificado |
| 256-272 | inventário | monta dicionário ordenado por nome; nós sem console geram `AVISO` e são omitidos |
| 274-280 | gravação | cria diretório de saída, escreve `.tmp` e substitui o arquivo final com `Path.replace()` |
| 282-289 | saída | imprime tabela de consoles e caminho do arquivo salvo |
| 293-294 | entrada | `raise SystemExit(main())` |

### 5.6 Contrato do inventário

Cada nó com console gera uma entrada (`setup_lab.py:264-272`):

```json
{
  "<node name>": {
    "node_id": "<node.node_id>",
    "node_type": "<node.node_type>",
    "console_type": "<node.console_type>",
    "device_type": "<DEVICE_TYPES.get(node.node_type)>",
    "host": "<config.console_host>",
    "port": "<node.console>",
    "status": "<node.status>"
  }
}
```

Campos e origem:

| Campo | Origem |
|:--|:--|
| `node_id` | API do GNS3 via `node.node_id` |
| `node_type` | API do GNS3 via `node.node_type` (`qemu` ou `vpcs`) |
| `console_type` | API do GNS3 via `node.console_type` |
| `device_type` | mapa local `DEVICE_TYPES` (`setup_lab.py:27-30`); `None` para tipo não mapeado |
| `host` | `config.console_host`, resolvido por CLI/ambiente/`.env`/hostname da URL |
| `port` | API do GNS3 via `node.console` |
| `status` | API do GNS3 via `node.status` |

A gravação usa `json.dumps(..., indent=2, sort_keys=True, ensure_ascii=False)` e adiciona newline final (`setup_lab.py:276-279`). O caminho padrão é `RAIZ / "inventario_gns3.json"` (`setup_lab.py:23`), absoluto em relação ao diretório do script.

### 5.7 Opções de CLI

`setup_lab.py --help` retorna:

- `--server`, `--project`, `--console-host`: sobrepõem variáveis de ambiente.
- `--output`: caminho do JSON, padrão `inventario_gns3.json` na raiz.
- `--check`: valida conexão e projeto, lista nós, não abre/inicia/exporta.
- `--no-start`: não inicia os nós.
- `--timeout`: espera máxima em segundos, padrão 60.

## 6. Documentação da Milestone 1

`docs/features/plan.md:14-22` registra:

- Objetivo da milestone: ambiente local e comunicação autenticada com o GNS3 (`docs/features/plan.md:15`).
- Task 1.1 marcada `[x]` para repositório e `venv` (`docs/features/plan.md:16`).
- Task 1.2 marcada `[x]` para `gns3fy`, `requests`, `netmiko`, `jinja2`, `python-dotenv` (`docs/features/plan.md:17`).
- Task 1.3 marcada `[x]` para `.env` com URL, versão da API, token, host de console e credenciais EXOS (`docs/features/plan.md:18`).
- Task 1.4 marcada `[x]` para leitura de `GNS3_ACCESS_TOKEN`, header Bearer e `api_version=3`, sem token hardcoded e sem login por usuário/senha (`docs/features/plan.md:19`).
- Task 1.5 marcada `[x]` para `setup_lab.py --check`, com validação declarada contra GNS3 3.1.0a6, projeto `uasc` e 14 nós (`docs/features/plan.md:20`).
- Bloco de pré-requisito técnico registra `/v2/*` com 404, `/v3/projects` com 401 `Not authenticated`, `gns3fy 0.8.0` apontando para `/v2` por padrão e autenticação exclusiva por `access_token` (`docs/features/plan.md:22`).

As Milestones 2 a 5 permanecem com todas as tasks `[ ]` (`docs/features/plan.md:24-50`).

## 7. Verificação em execução (2026-11-06)

Comando executado:

```text
.venv/bin/python setup_lab.py --check
```

Resultado: código de saída `0`.

```text
Conectando ao GNS3 em http://localhost:3080 (projeto 'uasc', API v3)...
Projeto encontrado: uasc (ID f406082d-a2c5-4b38-a229-4256b5871069), status=opened, nós=14
  ADM              type=vpcs   status=stopped  console=5014
  CAM              type=vpcs   status=stopped  console=5030
  NVR              type=vpcs   status=stopped  console=5005
  PC-LACINA        type=vpcs   status=stopped  console=5010
  PC-LIAD          type=vpcs   status=stopped  console=5026
  PC-LIAD-SALA     type=vpcs   status=stopped  console=5021
  PC-LSD           type=vpcs   status=stopped  console=5003
  PC-LSI           type=vpcs   status=stopped  console=5019
  SW-LACINA        type=qemu   status=stopped  console=5022
  SW-LIAD          type=qemu   status=stopped  console=5027
  SW-LSD           type=qemu   status=stopped  console=5017
  SW-LSI           type=qemu   status=stopped  console=5025
  WIFI-1           type=vpcs   status=stopped  console=5012
  WIFI-2           type=vpcs   status=stopped  console=5028
```

Consulta adicional a `GET /v3/version` com o token do `.env` retornou:

```json
{"controller_host":"127.0.0.1","version":"3.1.0a6","local":true}
```

Observações factuais da execução:

- O projeto aberto no servidor tem ID `f406082d-a2c5-4b38-a229-4256b5871069`, diferente do `project_id` gravado no arquivo portátil (`8c1815f0-9ec0-4ea9-ae3e-d6724b7c1eb8`).
- As portas de console atribuídas pelo servidor (`5003` a `5030`) diferem das portas estáticas do `project.gns3` (`5000` a `5026`), exceto onde coincidem por acaso.
- Todos os 14 nós estavam `stopped`; `--check` não executa `open()` nem `start()` (`setup_lab.py:200-206`).
- `inventario_gns3.json` não existe no diretório raiz após a execução de `--check`, pois o modo retorna antes da escrita (`setup_lab.py:206`).

## 8. Base topology permanece inalterada

`base_topology/uasc.gns3project` não foi modificado após o commit inicial (`git log -- base_topology/uasc.gns3project` mostra apenas `d06e965`). O arquivo tem 2.780 bytes e é um ZIP com:

| Entrada | Tamanho | Data no ZIP |
|:--|--:|:--|
| `project.gns3` | 27.516 bytes | 2026-10-27 18:23 |
| `project-files/images/` | 0 bytes | 2026-10-21 15:51 |

No `project.gns3` interno permanecem:

- `name`: `uasc` (`project.gns3:7`).
- `project_id`: `8c1815f0-9ec0-4ea9-ae3e-d6724b7c1eb8` (`project.gns3:8`).
- `links`: `[]` (`project.gns3:93`).
- 14 nós: `SW-LSD`, `PC-LSD`, `NVR`, `SW-LACINA`, `PC-LACINA`, `WIFI-1`, `ADM`, `SW-LSI`, `PC-LSI`, `PC-LIAD-SALA`, `SW-LIAD`, `PC-LIAD`, `WIFI-2`, `CAM`.

A topologia portátil continua sem enlaces físicos e sem imagem QEMU embarcada; os switches QEMU referenciam `EXOS-VM_v32.6.3.126.qcow2` por nome.

## 9. Conexões entre componentes e fluxo de dados

```text
CLI (--server/--project/--console-host/--output/--check/--no-start/--timeout)
        \
         v
.env  -> carregar_configuracao() -> Configuracao
                                      |
                                      v
                         criar_conector(api_version=3)
                         + session header Authorization: Bearer
                                      |
                                      v
                    GNS3 Server http://localhost:3080/v3
                    GET /projects -> GET /projects/{id}
                    POST /projects/{id}/open
                    POST /projects/{id}/nodes/{node_id}/start
                                      |
                                      v
                         inventario_gns3.json
                    (node_id, node_type, console_type,
                     device_type, host, port, status)
                                      |
                                      v
                    nenhum consumidor no repositório hoje;
                    /config/ e templates Jinja2 não existem
```

Conexões observáveis no código atual:

- `.env` → `load_dotenv` → `carregar_configuracao()` (`setup_lab.py:76-100`).
- `Configuracao.access_token` → header `Authorization` (`setup_lab.py:109`).
- `Configuracao.api_version` → `Gns3Connector(base_url=/v3)` (`.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:79-81`).
- `node.node_type` → `DEVICE_TYPES` → campo `device_type` do inventário (`setup_lab.py:27-30`, `setup_lab.py:268`).
- `node.console` → campo `port` do inventário (`setup_lab.py:270`).
- `config.console_host` → campo `host` do inventário (`setup_lab.py:269`).
- `inventario_gns3.json` → apenas o próprio `setup_lab.py` referencia o nome; não há leitor no repositório.

Variáveis `.env` sem consumo pelo código Python atual:

- `EXOS_USERNAME` e `EXOS_PASSWORD`: existem em `.env` e `.env.example:22-23`, mas não são lidas por `setup_lab.py`.
- `GNS3_CONSOLE_HOST`: usada apenas para preencher o campo `host` do inventário; o script não abre conexão Netmiko.

## 10. O que existe e o que não existe no código após a Milestone 1

| Item | Estado em 2026-11-06 | Evidência |
|:--|:--|:--|
| Script de configuração/conexão GNS3 | Existe | `setup_lab.py:1-294` |
| Manifesto de dependências | Existe | `requirements.txt:1-6` |
| Exemplo de variáveis de ambiente | Existe | `.env.example:1-23` |
| `.env` local com token | Existe, não versionado | `.gitignore:8` |
| Autenticação Bearer no `gns3fy` | Existe | `setup_lab.py:103-110` |
| Teste de conexão `--check` | Existe | `setup_lab.py:200-206` |
| Exportação de inventário | Existe no código; arquivo não presente no diretório | `setup_lab.py:256-280`; `ls inventario_gns3.json` |
| Consumidor do inventário | Não existe | busca por `inventario_gns3` encontra apenas escritor, `.gitignore` e research anterior |
| `/config/` | Não existe | `find` no repositório |
| Templates Jinja2 | Não existem | nenhum arquivo de template |
| Código Netmiko | Não existe | nenhum `import netmiko`; `netmiko` apenas instalado |
| Scripts de chamados (Milestone 5) | Não existem | `docs/features/plan.md:46-50` |
| Scripts de testes de aceite (Milestone 4) | Não existem | `docs/features/plan.md:38-44` |
| `infra/create_project.py` | Não existe | `docs/features/plan.md:26` |
| `config/configure_switches.py` | Não existe | `docs/features/plan.md:34` |
| Suíte de testes automatizados | Não existe | nenhum diretório `tests/` ou `pytest` instalado |

## 11. Referências principais

- `setup_lab.py:1-294`
- `requirements.txt:1-6`
- `.env.example:1-23`
- `.gitignore:7-11`
- `docs/features/plan.md:14-22`
- `docs/features/plan.md:24-50`
- `.venv/pyvenv.cfg:1-4`
- `.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:79-81`, `:95-98`, `:189-207`, `:1190-1242`
- `base_topology/uasc.gns3project` (`project.gns3:7-8`, `project.gns3:93`)
- `docs/features/codebase-research.md` (levantamento anterior à Milestone 1)
