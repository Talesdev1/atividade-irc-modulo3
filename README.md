# Laboratório UASC — Automação GNS3 (EXOS + VPCS)

Automação do laboratório de redes do STI/UFCG no GNS3: descoberta dos nós, provisionamento dos switches ExtremeXOS (VLANs, L3, DHCP, portas) e execução dos 6 testes de aceite nos VPCS.

A topologia física **não** é criada pelos scripts — ela já existe em `base_topology/uasc.gns3project`. O papel da automação é **configurar** os nós existentes.

## Estrutura

```
base_topology/          Topologia inicial (.gns3project) já importada no GNS3
infra/
  setup_lab.py          Abre o projeto, inicia os nós e exporta o inventário
  provisionar.py        Configura switches EXOS e VPCS via Netmiko + Jinja2
  testes_aceite.py      Executa os 6 testes de aceite nos consoles dos VPCS
  topologia.py          Mapa L1 (enlaces/portas) usado nas validações
  config/plano_rede.json  Plano declarativo (fonte da verdade: VLANs, redes, hosts)
  templates/            Templates Jinja2 (exos/ e vpcs/)
setup_lab.py            Atalho para infra/setup_lab.py
inventario_gns3.json    Inventário de consoles (gerado, não editar à mão)
docs/                   Documentação, ADRs e artefatos das milestones
tests/                  Testes unitários (não precisam do GNS3)
```

## Pré-requisitos

- GNS3 Server rodando (padrão `http://localhost:3080`, API v3) com a imagem do EXOS importada
- Python 3.10+ e as dependências do projeto:

```bash
cd /home/talesrb/Projetos/irc/modulo3
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # depois edite os valores
```

Variáveis do `.env`: `GNS3_SERVER_URL`, `GNS3_API_VERSION`, `GNS3_PROJECT_NAME`, `GNS3_ACCESS_TOKEN`, `GNS3_CONSOLE_HOST`, `EXOS_USERNAME`, `EXOS_PASSWORD`.

## Fluxo de execução

Execute sempre nesta ordem:

```bash
# 0. Ambiente
source .venv/bin/activate

# 1. Abrir o projeto no GNS3, iniciar os nós e regravar o inventário
python setup_lab.py

# 2. Configurar os switches e hosts (idempotente)
python -m infra.provisionar

# 3. Conferir o estado sem alterar nada
python -m infra.provisionar --check

# 4. Rodar os testes de aceite
python -m infra.testes_aceite
```

Se o projeto já estiver aberto e você só quer subir os nós:

```bash
python setup_lab.py --no-links
```

### Referência de comandos

| Comando | O que faz |
| --- | --- |
| `python setup_lab.py` | Abre/inicia o projeto, ajusta o cabeamento L1 e exporta `inventario_gns3.json` |
| `python setup_lab.py --check` | Só valida a conexão e o projeto (sem abrir/iniciar/exportar) |
| `python setup_lab.py --validate` | Compara nós e enlaces com a topologia base e o mapa L1 |
| `python setup_lab.py --no-start` | Abre e exporta o inventário sem iniciar os nós |
| `python -m infra.provisionar --dry-run` | Renderiza a configuração sem conectar no GNS3 |
| `python -m infra.provisionar --check` | Lê `show vlan`, `show ipconfig`, `show iproute` e `show ip` e só valida |
| `python -m infra.provisionar --only SW-LACINA,PC-LACINA` | Aplica somente nos nós indicados |
| `python -m infra.provisionar --skip-hosts` / `--skip-switches` | Pula hosts ou switches |
| `python -m infra.provisionar --verbose` | Imprime os blocos de configuração renderizados |
| `python -m infra.testes_aceite --only 1,2` | Roda apenas os testes escolhidos |
| `python -m infra.testes_aceite --json /tmp/aceite.json` | Grava o relatório da bateria em JSON |
| `python -m infra.testes_aceite --verbose` | Mostra a saída bruta dos pings que falharem |
| `python -m unittest discover -s tests -v` | Testes unitários (offline, 31 testes) |

### Ordem de aplicação

O `provisionar` aplica o **core primeiro** (`SW-LACINA`), porque os hosts dinâmicos dependem do DHCP. Depois os switches de acesso e, por fim, os VPCS. Falhas são isoladas por nó: um erro não interrompe os demais, e o resultado final lista os nós com problema (exit code `1`).

## Testes de aceite

Rodam via Telnet nos consoles dos VPCS, com parsing de texto (ADR 004). Exit code `0` = todos aprovados, `1` = alguma falha, `130` = interrompido.

| # | Teste | Critério de sucesso |
| :-: | --- | --- |
| 1 | Endereçamento via DHCP | Cada host dinâmico obtém IP dentro da sub-rede da sua VLAN, com o gateway correto |
| 2 | Conectividade com o gateway | Todos os hosts com gateway pingam o gateway da própria VLAN |
| 3 | Roteamento inter-VLAN | `PC-LACINA` alcança hosts de outras VLANs (LSD, LSI, LIAD, `PC-LIAD-SALA`) |
| 4 | CFTV: `CAM` → `NVR` | Comunicação L2 dentro da VLAN `Cameras` |
| 5 | Isolamento do CFTV | Nenhum host de laboratório alcança `CAM`/`NVR` (**bloqueio = sucesso**) |
| 6 | Soberania da VLAN L2 | Trocar o IP do `PC-LACINA` para a faixa do LSD **deve** falhar no ping; o host é restaurado via DHCP ao final (**bloqueio = sucesso**) |

> ⚠️ O Teste 6 altera temporariamente o IP do `PC-LACINA`. Se você interromper com `Ctrl+C` no meio, pode sobrar IP manual — rode `ip dhcp` no console desse VPCS.

## Testes unitários

Não precisam do GNS3 e cobrem validação do plano, renderização dos templates, lógica de read-before-write e parsing dos pings:

```bash
python -m unittest discover -s tests -v
```

## Referência rápida de rede

| VLAN | ID | Rede | Gateway | DHCP |
| --- | :-: | --- | --- | :-: |
| `LSD` | 10 | `172.20.1.128/25` | `172.20.1.129` | sim |
| `LACINA` | 20 | `172.20.1.0/25` | `172.20.1.1` | sim |
| `LSI` | 30 | `172.20.2.0/26` | `172.20.2.1` | sim |
| `LIAD` | 40 | `172.20.2.64/26` | `172.20.2.65` | sim |
| `WiFi` | 50 | `172.20.0.0/24` | `172.20.0.1` | sim |
| `Cameras` | 60 | `172.20.2.128/27` | — (isolada L2) | não |
| `Gerencia` | 70 | `172.20.2.160/28` | `172.20.2.161` | não |

Roteamento L3 e DHCP centralizados no `SW-LACINA`. A VLAN `Cameras` nunca recebe IP nem `ipforwarding` (isolamento CFTV).

## Documentação

- `docs/docs.md` — plano de endereçamento, topologia, mapeamento de portas e procedimentos
- `docs/adr/` — decisões de arquitetura (idempotência, testes via VPCS, credenciais)
- `docs/features/plan.md` — milestones e estado de implementação
