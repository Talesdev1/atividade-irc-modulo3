# Research: Milestone 2 — Orquestração Lógica e Descoberta

Snapshot: 2026-11-06. Antes da criação deste documento, o working tree estava limpo e o HEAD em `163e0dc` (`feat: Milestone 2`).
Este documento atualiza o levantamento da Milestone 1 (`docs/tasks-artifacts/research/codebase-research-milestone1.md`) com as alterações efetivamente commitadas na Milestone 2.

## Summary

A Milestone 2 foi commitada em `163e0dc` e está registrada como concluída em `docs/features/plan.md:22-28`, com as Tasks 2.1 a 2.5 marcadas `[x]`. O commit adicionou o pacote `infra/`, com a orquestração em `infra/setup_lab.py` (678 linhas) e o mapa de cabeamento em `infra/topologia.py` (73 linhas), e reduziu o `setup_lab.py` da raiz de 294 para 12 linhas, mantendo-o apenas como atalho de compatibilidade (`setup_lab.py:1-12`). O script agora lê o `project.gns3` embutido no `.gns3project`, valida os 14 nós, expande os adaptadores dos switches quando necessário, cria de forma idempotente os 13 enlaces L1 (10 acessos + 3 troncos), inicia todos os nós via `lab.start_nodes()` e exporta 14 consoles para `inventario_gns3.json`. A execução local de `--check --validate` retornou código 0, com 14 nós, 13 links e todos os nós `started`.

## 1. Checklist da consulta (Milestone 2)

| Área verificada | Estado atual | Evidência |
|:--|:--|:--|
| Task 2.1 — `base_topology/` e `.gitignore` | Arquivo base versionado; discos e artefatos ignorados | `base_topology/uasc.gns3project`; `.gitignore:1-11` |
| Task 2.2 — script de orquestração | Implementação movida para `infra/setup_lab.py`; raiz mantém atalho | `infra/setup_lab.py:1-678`; `setup_lab.py:1-12` |
| Task 2.3 — cabeamento L1 via API | Mapa declarativo com 10 acessos + 3 troncos; criação idempotente | `infra/topologia.py:35-55`; `infra/setup_lab.py:399-495` |
| Task 2.4 — iniciar todos os nós | `lab.start_nodes(poll_wait_time=5)` + polling até `started` | `infra/setup_lab.py:498-524` |
| Task 2.5 — inventário de consoles | Exportação atômica de 14 entradas para `inventario_gns3.json` | `infra/setup_lab.py:543-571`; `inventario_gns3.json` |
| Validação de nós e links | `--validate` compara nós com o arquivo base e links com o mapa | `infra/setup_lab.py:219-344` |
| Documentação da milestone | Tasks 2.1–2.5 e estratégia de validação atualizadas | `docs/features/plan.md:22-28`, `:55-56`, `:61` |

## 2. Estado do repositório e do histórico Git

Commits existentes no momento do levantamento:

| Commit | Data | Mensagem |
|:--|:--|:--|
| `163e0dc` | 2026-11-06 02:22:27 -0300 | `feat: Milestone 2` |
| `476f0f8` | 2026-11-06 01:49:52 -0300 | `update plan.md` |
| `cfbe999` | 2026-11-05 23:32:24 -0300 | `feat: milestone 1 Setup do Ambiente e Base de Código` |
| `d06e965` | 2026-11-05 23:09:43 -0300 | `initial setup` |

O commit `163e0dc` alterou cinco arquivos, com o seguinte balanço de linhas (`git show --numstat 163e0dc`):

| Arquivo | Adições | Remoções | Leitura |
|:--|--:|--:|:--|
| `docs/features/plan.md` | 6 | 5 | Tasks e validação atualizadas |
| `infra/__init__.py` | 1 | 0 | Marca o diretório como pacote |
| `infra/setup_lab.py` | 678 | 0 | Nova implementação da orquestração |
| `infra/topologia.py` | 73 | 0 | Mapa do cabeamento L1 |
| `setup_lab.py` | 5 | 287 | Reduzido de 294 para 12 linhas |

Arquivos rastreados relevantes após a Milestone 2:

- `infra/__init__.py`, `infra/setup_lab.py`, `infra/topologia.py`
- `setup_lab.py`
- `docs/features/plan.md`
- `base_topology/uasc.gns3project`

Artefatos locais não versionados:

- `inventario_gns3.json` (3.290 bytes) — ignorado por `.gitignore:8`.
- `infra/__pycache__/`, `__pycache__/` e `*.pyc` — ignorados por `.gitignore:10-11`.
- `.venv/` — o `.venv/.gitignore` interno ignora todo o conteúdo.
- `.env` — ignorado por `.gitignore:8`; contém URL, token e credenciais.

Antes da criação deste documento, `git status --porcelain` retornava vazio; a única entrada não rastreada passa a ser o próprio arquivo de research.

## 3. Reorganização de arquivos

| Item | Antes da Milestone 2 | Depois da Milestone 2 |
|:--|:--|:--|
| Script principal | `setup_lab.py` com 294 linhas | `infra/setup_lab.py` com 678 linhas |
| Compatibilidade | — | `setup_lab.py` com 12 linhas, delegando para `infra.setup_lab.main` |
| Mapa de cabeamento | Inexistente | `infra/topologia.py` com 73 linhas |
| Pacote Python | Inexistente | `infra/__init__.py` |
| Validação de nós/links | Inexistente | `validar_topologia()`, `validar_enlaces()`, `validar_estado()` |
| Criação de links | Inexistente | `garantir_adaptadores()` e `garantir_enlaces()` |
| Inicialização | `node.start()` em laço | `lab.start_nodes()` em uma chamada |

O `setup_lab.py` da raiz preserva o comando histórico do Milestone 1 (`python setup_lab.py ...`) e apenas importa `main` do pacote:

```python
from infra.setup_lab import main

if __name__ == "__main__":
    raise SystemExit(main())
```

A implementação anterior já tinha resolução de configuração, autenticação Bearer, localização do projeto, início de nós e exportação de inventário. A Milestone 2 preservou esses comportamentos e acrescentou leitura/validação da topologia base, cabeamento L1, validação de links e início em lote.

## 4. `infra/topologia.py` — fonte do cabeamento L1

O arquivo declara o mapa como fonte da verdade do cabeamento inicial (`infra/topologia.py:35-55`), separado do `.gns3project`, que continua sendo a fonte dos nós.

### 4.1 Estruturas e constantes

| Item | Conteúdo | Evidência |
|:--|:--|:--|
| `SWITCHES` | `SW-LACINA`, `SW-LSD`, `SW-LSI`, `SW-LIAD` | `infra/topologia.py:11` |
| `PORTA_VPCS` | `Ethernet0` | `infra/topologia.py:12` |
| `Enlace` | Dataclass imutável com `no_a`, `porta_a`, `no_b`, `porta_b`, `tipo` | `infra/topologia.py:15-24` |
| `Enlace.descricao` | Formata `A porta <-> B porta (tipo)` para logs e erros | `infra/topologia.py:26-32` |
| `ENLACES_INICIAIS` | Tupla com os 13 enlaces | `infra/topologia.py:35-55` |

### 4.2 Acessos dos VPCS (10 enlaces)

O mapa reproduz exatamente a tabela de `docs/docs.md:64-75`:

| VPCS | Switch | Porta | VLAN de destino |
|:--|:--|:-:|:--|
| `PC-LACINA` | `SW-LACINA` | `Port1` | `LACINA` (20) |
| `WIFI-1` | `SW-LACINA` | `Port2` | `WiFi` (50) |
| `ADM` | `SW-LACINA` | `Port3` | `Gerencia` (70) |
| `PC-LSD` | `SW-LSD` | `Port1` | `LSD` (10) |
| `NVR` | `SW-LSD` | `Port2` | `Cameras` (60) |
| `PC-LSI` | `SW-LSI` | `Port1` | `LSI` (30) |
| `PC-LIAD-SALA` | `SW-LSI` | `Port2` | `LIAD` (40) |
| `PC-LIAD` | `SW-LIAD` | `Port1` | `LIAD` (40) |
| `WIFI-2` | `SW-LIAD` | `Port2` | `WiFi` (50) |
| `CAM` | `SW-LIAD` | `Port3` | `Cameras` (60) |

A VLAN não é usada pelo cabeamento; ela entra na configuração EXOS da Milestone 3. O mapa físico só declara nó e porta.

### 4.3 Troncos 802.1Q (3 enlaces)

| Lado A | Lado B |
|:--|:--|
| `SW-LACINA:Port22` | `SW-LSD:Port22` |
| `SW-LACINA:Port23` | `SW-LSI:Port23` |
| `SW-LACINA:Port24` | `SW-LIAD:Port24` |

A topologia em estrela é centralizada no `SW-LACINA`, conforme `docs/docs.md:77-81`.

### 4.4 Cálculo de adaptadores

`adaptadores_necessarios()` (`infra/topologia.py:57-73`) percorre o mapa e, para cada porta de switch no formato `PortN`, exige `N + 1` adaptadores. O `+1` existe porque o adaptador 0 é a porta `Mgmt`.

Resultado para o mapa atual:

| Switch | Maior porta usada | Adaptadores necessários |
|:--|:-:|--:|
| `SW-LACINA` | `Port24` | 25 |
| `SW-LSD` | `Port22` | 23 |
| `SW-LSI` | `Port23` | 24 |
| `SW-LIAD` | `Port24` | 25 |

Os valores coincidem com o estado observado via API após a expansão.

## 5. `infra/setup_lab.py` — implementação da orquestração

### 5.1 Estrutura e constantes

| Item | Conteúdo | Evidência |
|:--|:--|:--|
| `RAIZ` | `Path(__file__).resolve().parents[1]` | `infra/setup_lab.py:41` |
| `BASE_TOPOLOGY_PADRAO` | `<raiz>/base_topology` | `infra/setup_lab.py:42` |
| `INVENTARIO_PADRAO` | `<raiz>/inventario_gns3.json` | `infra/setup_lab.py:43` |
| `HTTP_TIMEOUT` | 10 s | `infra/setup_lab.py:44` |
| `DEVICE_TYPES` | `qemu` → `extreme_exos_telnet`; `vpcs` → `generic_telnet` | `infra/setup_lab.py:47-50` |

O import do mapa usa caminho relativo quando o script é importado como pacote e fallback absoluto quando executado diretamente (`infra/setup_lab.py:28-39`).

### 5.2 Configuração e autenticação

O comportamento herdado da Milestone 1 foi mantido:

- `carregar_configuracao()` resolve CLI > ambiente > `.env` > padrão e carrega `<raiz>/.env` (`infra/setup_lab.py:118-142`).
- `criar_conector()` cria `Gns3Connector` com `api_version` configurável e injeta `Authorization: Bearer <token>` na sessão (`infra/setup_lab.py:145-152`).
- `verificar_token()` faz `GET /projects` e distingue HTTP 401 de outros erros (`infra/setup_lab.py:155-167`).
- `localizar_projeto()` busca o projeto por nome e instancia `Project` (`infra/setup_lab.py:170-177`).

Não há token, usuário ou senha hardcoded no código.

### 5.3 Leitura e validação da topologia base

`localizar_base_topology()` aceita um arquivo `.gns3project` ou um diretório com exatamente um arquivo, falhando com mensagem explícita em caso de ausência ou ambiguidade (`infra/setup_lab.py:180-199`).

`ler_topologia_base()` abre o `.gns3project` como ZIP, lê `project.gns3` e extrai apenas `name` e `node_type` dos nós (`infra/setup_lab.py:202-216`). O dataclass `TopologiaBase` guarda o caminho e o dicionário de nós (`infra/setup_lab.py:66-71`).

`validar_topologia()` compara os nomes e tipos dos nós do GNS3 com o arquivo base e reporta ausentes, extras e tipos divergentes (`infra/setup_lab.py:219-247`). A contagem de links do arquivo base não é usada, porque o arquivo base tem 0 links e o cabeamento é definido pelo mapa.

### 5.4 Cabeamento L1

O fluxo de cabeamento tem duas etapas.

**Adaptadores (`garantir_adaptadores`, `infra/setup_lab.py:399-440`):**

1. Percorre `adaptadores_necessarios()`.
2. Relê os nós do projeto e localiza o switch por nome.
3. Se `properties.adapters` já é suficiente, não faz nada.
4. Se o switch está `started`, para o nó e aguarda `stopped`.
5. Copia as propriedades atuais, altera apenas `adapters` e envia via `node.update(properties=...)`.
6. Relê o nó e confirma que todas as portas do mapa existem.
7. Não reinicia o switch nessa etapa; o início posterior fica a cargo de `iniciar_nos()`.

**Enlaces (`garantir_enlaces`, `infra/setup_lab.py:443-495`):**

1. Relê nós e links.
2. Resolve cada porta do mapa para `(node_id, adapter_number, port_number)` com `_endpoint()` (`infra/setup_lab.py:250-265`).
3. Identifica links por um `frozenset` dos dois endpoints, independente da ordem (`infra/setup_lab.py:268-277`).
4. Monta o mapa esperado (`infra/setup_lab.py:280-299`).
5. Ignora links que já existem.
6. Detecta portas já ocupadas por outros links e recusa a criação em caso de conflito.
7. Cria apenas os links faltantes com `lab.create_link(...)`.
8. Ao final, relê os links e falha se houve conflito.

A criação é idempotente: uma segunda execução encontra os 13 links e imprime `Cabeamento inicial já está completo.`

### 5.5 Inicialização e consoles

`iniciar_nos()` (`infra/setup_lab.py:498-524`) calcula os nós que não estão `started`, dispara `lab.start_nodes(poll_wait_time=5)` e faz polling até todos estarem `started` ou até o timeout. Falhas de start são apenas avisadas em `stderr`; o fluxo continua.

`aguardar_consoles()` (`infra/setup_lab.py:527-540`) faz polling até todos os nós exporem `node.console`. Se o timeout expirar, também apenas avisa.

### 5.6 Inventário

`montar_inventario()` (`infra/setup_lab.py:543-561`) gera uma entrada por nó com console:

| Campo | Origem |
|:--|:--|
| `node_id` | API do GNS3 |
| `node_type` | API do GNS3 |
| `console_type` | API do GNS3 |
| `device_type` | `DEVICE_TYPES[node_type]` |
| `host` | `GNS3_CONSOLE_HOST` ou host da URL |
| `port` | console alocada pelo GNS3 |
| `status` | estado no momento da coleta |

Nós sem console são ignorados com aviso. `gravar_inventario()` (`infra/setup_lab.py:564-571`) grava em arquivo temporário e faz `replace` atômico, com `indent=2`, `sort_keys=True` e newline final.

### 5.7 Fluxo de `main()`

`main()` (`infra/setup_lab.py:574-678`) executa:

1. Parse dos argumentos e carregamento da configuração.
2. Falha se `GNS3_ACCESS_TOKEN` estiver vazio.
3. Cria o conector, valida o token e localiza o projeto.
4. Imprime projeto, status, quantidade de nós e links.
5. Em `--check`, opcionalmente valida e lista os nós, sem abrir, criar links, iniciar ou exportar.
6. Abre o projeto se necessário e aguarda `opened`.
7. Se `--no-links` não foi informado, garante adaptadores e enlaces.
8. Se `--validate`, valida nós e links.
9. Se `--no-start` não foi informado, inicia os nós.
10. Aguarda consoles, monta o inventário, grava e imprime a tabela.

Opções de CLI (`infra/setup_lab.py:74-115`):

| Opção | Efeito |
|:--|:--|
| `--server` | Sobrepõe `GNS3_SERVER_URL` |
| `--project` | Sobrepõe `GNS3_PROJECT_NAME` |
| `--console-host` | Sobrepõe `GNS3_CONSOLE_HOST` |
| `--output` | Caminho do inventário |
| `--base-topology` | Arquivo ou diretório da topologia base |
| `--check` | Apenas conexão, projeto, validação opcional e listagem |
| `--validate` | Compara nós com a base e links com o mapa |
| `--no-links` | Não cria/ajusta o cabeamento inicial |
| `--no-start` | Não inicia os nós |
| `--timeout` | Espera máxima para abrir/iniciar (padrão 60 s) |

## 6. Verificação em execução (2026-11-06)

Comando executado:

```bash
.venv/bin/python setup_lab.py --check --validate
```

Resultado: código de saída 0 e as duas validações aprovadas.

- Projeto `uasc`, ID `fc2f0519-4df5-4263-93e3-7a17d8d8221c`, `status=opened`.
- 14 nós e 13 links no GNS3.
- Nós: `base=uasc.gns3project (14 nó(s)) x GNS3 (14 nó(s))` — OK.
- Cabeamento: `mapa=13 enlace(s) x GNS3=13 enlace(s)` — OK.

Adaptadores observados via API:

| Switch | `properties.adapters` | Portas expostas | Status |
|:--|--:|--:|:--|
| `SW-LACINA` | 25 | 25 | `started` |
| `SW-LSD` | 23 | 23 | `started` |
| `SW-LSI` | 24 | 24 | `started` |
| `SW-LIAD` | 25 | 25 | `started` |

Links observados via API, todos correspondentes ao mapa:

```text
ADM:Ethernet0 <-> SW-LACINA:Port3
CAM:Ethernet0 <-> SW-LIAD:Port3
NVR:Ethernet0 <-> SW-LSD:Port2
PC-LACINA:Ethernet0 <-> SW-LACINA:Port1
PC-LIAD:Ethernet0 <-> SW-LIAD:Port1
PC-LIAD-SALA:Ethernet0 <-> SW-LSI:Port2
PC-LSD:Ethernet0 <-> SW-LSD:Port1
PC-LSI:Ethernet0 <-> SW-LSI:Port1
SW-LACINA:Port22 <-> SW-LSD:Port22
SW-LACINA:Port23 <-> SW-LSI:Port23
SW-LACINA:Port24 <-> SW-LIAD:Port24
WIFI-1:Ethernet0 <-> SW-LACINA:Port2
WIFI-2:Ethernet0 <-> SW-LIAD:Port2
```

Inventário exportado (`inventario_gns3.json`), 14 entradas:

| Nó | Tipo | `device_type` | Console |
|:--|:--|:--|--:|
| `ADM` | vpcs | `generic_telnet` | 5014 |
| `CAM` | vpcs | `generic_telnet` | 5030 |
| `NVR` | vpcs | `generic_telnet` | 5005 |
| `PC-LACINA` | vpcs | `generic_telnet` | 5010 |
| `PC-LIAD` | vpcs | `generic_telnet` | 5026 |
| `PC-LIAD-SALA` | vpcs | `generic_telnet` | 5021 |
| `PC-LSD` | vpcs | `generic_telnet` | 5003 |
| `PC-LSI` | vpcs | `generic_telnet` | 5019 |
| `SW-LACINA` | qemu | `extreme_exos_telnet` | 5007 |
| `SW-LIAD` | qemu | `extreme_exos_telnet` | 5023 |
| `SW-LSD` | qemu | `extreme_exos_telnet` | 5000 |
| `SW-LSI` | qemu | `extreme_exos_telnet` | 5016 |
| `WIFI-1` | vpcs | `generic_telnet` | 5012 |
| `WIFI-2` | vpcs | `generic_telnet` | 5028 |

As portas de console estão na faixa `5000`–`5030` e são alocadas dinamicamente pelo GNS3; nenhuma aparece hardcoded no código.

A primeira execução da Milestone 2, registrada no histórico da sessão, ajustou os quatro switches de 13 adaptadores para os valores acima e criou os 13 links. A execução seguinte encontrou o cabeamento completo e não criou links duplicados, confirmando a idempotência.

## 7. Compatibilidade com GNS3 3.x e `gns3fy 0.8.0`

- O servidor local expõe `/v3/*`, então o conector usa `api_version=3` e header Bearer.
- O `gns3fy 0.8.0` aponta para `/v2` por padrão; o parâmetro `api_version` corrige isso.
- `node.stop()` contra o GNS3 3.x pode receber resposta 2xx sem corpo; o `gns3fy` tenta decodificar JSON e levanta `JSONDecodeError`. `_parar_no()` captura essa exceção específica para permitir a expansão de adaptadores (`infra/setup_lab.py:377-386`).
- `lab.create_link()` já verifica portas ocupadas e acrescenta o novo link a `lab.links`; o script reforça a checagem com seu próprio mapa de endpoints.
- Os `device_type` do inventário foram conferidos no Netmiko 4.8.0 instalado: `extreme_exos_telnet` e `generic_telnet` existem no mapa de plataformas Telnet. Ainda não há código Netmiko que os consuma.

## 8. Documentação atualizada

`docs/features/plan.md` recebeu as seguintes mudanças:

- Tasks 2.2, 2.4 e 2.5 marcadas como concluídas.
- Nova Task 2.3 para o cabeamento L1, com referência a `infra/topologia.py`, expansão de adaptadores e idempotência (`docs/features/plan.md:26`).
- Fonte da verdade redefinida: `.gns3project` para os nós; `infra/topologia.py` para o cabeamento (`docs/features/plan.md:55`).
- Estratégia de validação da Milestone 2 passou a citar `infra/setup_lab.py --validate`, 14 nós e 13 links (`docs/features/plan.md:61`).

Observação de forma: a Task 2.3 não usa negrito no rótulo, ao contrário das demais (`docs/features/plan.md:26`). O arquivo também termina sem newline. Nenhum dos dois afeta a execução.

## 9. Pontos de atenção e riscos

| # | Observação | Impacto | Evidência |
|--:|:--|:--|:--|
| 1 | Falha em `lab.start_nodes()` é capturada e apenas gera aviso | O script pode terminar com código 0 e inventário contendo nós `stopped`/`suspended` | `infra/setup_lab.py:505-524`, `:657-664` |
| 2 | Timeout de consoles também é apenas aviso | Nós sem console são omitidos do inventário, mas o código de saída continua 0 | `infra/setup_lab.py:527-540`, `:543-561` |
| 3 | `--no-links` não desativa `--validate` | Se a topologia foi alterada de propósito, `--no-links` evita a criação, mas `--validate` ainda acusa links ausentes/extras | `infra/setup_lab.py:644-655`, `:302-331` |
| 4 | Adaptadores só crescem | Switches nunca são reduzidos; portas extras permanecem expostas após mudanças de topologia | `infra/setup_lab.py:404-406` |
| 5 | Busca do projeto por nome | Nomes duplicados no servidor podem levar ao projeto errado; não há validação de unicidade | `infra/setup_lab.py:170-177` |
| 6 | Sem testes automatizados | A validação é de integração contra o GNS3 local; não há testes unitários para o mapa, validação ou conflitos | ausência de `tests/` |
| 7 | Sem modo dry-run | Ajustar adaptadores exige parar switches; não há simulação prévia das mudanças | `infra/setup_lab.py:399-440` |
| 8 | Inventário é um snapshot | O campo `status` reflete o instante da coleta e pode ficar desatualizado | `infra/setup_lab.py:543-561` |

O ponto 1 é o mais relevante para a Milestone 3: um inventário gerado com nós parados pode levar a falhas de conexão Netmiko. O consumidor do inventário deve validar o campo `status` ou o orquestrador deve falhar quando nem todos os nós estiverem `started`.

## 10. O que existe e o que não existe no código após a Milestone 2

| Item | Estado em 2026-11-06 | Evidência |
|:--|:--|:--|
| Orquestração do projeto GNS3 | Existe | `infra/setup_lab.py:574-678` |
| Mapa de cabeamento L1 | Existe | `infra/topologia.py:35-55` |
| Criação idempotente de links | Existe | `infra/setup_lab.py:443-495` |
| Expansão de adaptadores | Existe | `infra/setup_lab.py:399-440` |
| Validação de nós contra `.gns3project` | Existe | `infra/setup_lab.py:202-247` |
| Validação de links contra o mapa | Existe | `infra/setup_lab.py:302-331` |
| Início em lote e polling | Existe | `infra/setup_lab.py:498-524` |
| Inventário de consoles | Existe no código e como arquivo local ignorado | `infra/setup_lab.py:543-571`; `.gitignore:8` |
| Atalho de compatibilidade na raiz | Existe | `setup_lab.py:1-12` |
| Templates Jinja2 | Não existem | nenhum arquivo de template |
| Código Netmiko | Não existe | nenhum `import netmiko` no código do projeto |
| Configuração EXOS | Não existe | depende da Milestone 3 |
| Endereçamento dos VPCS | Não existe | depende da Milestone 3 |
| Testes automatizados | Não existem | nenhum diretório `tests/` |
| Scripts de aceite (Milestone 4) | Não existem | `docs/features/plan.md:38-44` |
| Scripts de chamados (Milestone 5) | Não existem | `docs/features/plan.md:46-50` |

## 11. Referências principais

- `infra/setup_lab.py:1-678`
- `infra/topologia.py:1-73`
- `setup_lab.py:1-12`
- `infra/__init__.py:1`
- `docs/features/plan.md:22-28`, `:55-56`, `:61`
- `docs/docs.md:64-81` (mapa de portas e troncos)
- `.gitignore:1-11`
- `inventario_gns3.json` (artefato local, 14 entradas)
- `base_topology/uasc.gns3project` (`project.gns3`, 14 nós, 0 links)
- `docs/tasks-artifacts/research/codebase-research-milestone1.md`
- `gns3fy 0.8.0`: `Project.start_nodes()` em `gns3fy.py:1454-1470`; `Project.create_link()` em `gns3fy.py:1741-1817`
- Netmiko 4.8.0: `extreme_exos_telnet` e `generic_telnet` presentes em `netmiko.ssh_dispatcher.telnet_platforms`
