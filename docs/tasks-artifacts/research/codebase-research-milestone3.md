# Research: Milestone 3 — Provisionamento de Configurações

Snapshot: 2026-11-06. O working tree estava limpo em `163e0dc` (`feat: Milestone 2`) antes das alterações desta milestone. Este documento complementa `codebase-research-milestone2.md`.

## Summary

A Milestone 3 foi implementada em `infra/provisionar.py` (1.264 linhas), com plano declarativo em `infra/config/plano_rede.json` (147 linhas), nove templates Jinja2 em `infra/templates/` e 12 testes unitários em `tests/test_provisionar.py`. O script consome o `inventario_gns3.json` do Milestone 2, faz *readiness check* por polling, lê o estado com `show vlan` antes de escrever (ADR 003), aplica somente as diferenças de VLAN/porta, injeta SVIs, DHCP, IPs de gerência e rotas padrão, e valida tudo com `show vlan`, `show ipconfig`, `show iproute` e `show ip`. A execução real provisionou 4 switches e 10 VPCS e a reexecução de `--check` passou em todos os 14 nós.

## 1. Checklist da consulta (Milestone 3)

| Área verificada | Estado | Evidência |
|:--|:--|:--|
| Task 3.1 — templates Jinja2 | Implementado | `infra/templates/exos/*.j2`, `infra/templates/vpcs/*.j2` |
| Task 3.2 — readiness check | Implementado | `conectar()` em `infra/provisionar.py:829` |
| Task 3.3 — configuração do core | Implementado e validado no GNS3 | `processar_switch()` e `validar_exos()` |
| Task 3.4 — switches de acesso | Implementado e validado no GNS3 | `infra/templates/exos/gerencia.j2` |
| Task 3.5 — VPCS fixos e DHCP | Implementado e validado no GNS3 | `infra/templates/vpcs/`, `validar_vpcs()` |
| Read-before-write | Implementado | `ler_estado_switch()`, `calcular_comandos_portas()` |
| Plano declarativo | Implementado | `infra/config/plano_rede.json` |
| Testes unitários | Implementado | `tests/test_provisionar.py` (12 testes) |
| Documentação da milestone | Atualizada | `docs/features/plan.md:30-36`, `:55`, `:62` |

## 2. Arquivos criados

| Arquivo | Linhas | Papel |
|:--|--:|:--|
| `infra/config/plano_rede.json` | 147 | Fonte da verdade de VLANs, redes, portas, hosts e troncos |
| `infra/templates/exos/switch.j2` | 13 | Composição da configuração de um switch EXOS |
| `infra/templates/exos/vlans.j2` | 4 | Criação das VLANs ausentes |
| `infra/templates/exos/portas.j2` | 4 | Comandos de portas já calculados pelo diff |
| `infra/templates/exos/svi.j2` | 5 | SVIs e `enable ipforwarding` |
| `infra/templates/exos/dhcp.j2` | 6 | Escopos DHCP e portas de atendimento |
| `infra/templates/exos/gerencia.j2` | 3 | IP de gerência e rota padrão dos acessos |
| `infra/templates/vpcs/estatico.j2` | 4 | IP fixo, com gateway opcional |
| `infra/templates/vpcs/dhcp.j2` | 3 | `ip dhcp` + `save` |
| `infra/provisionar.py` | 1.264 | Orquestração, diff, Netmiko, validação e CLI |
| `tests/test_provisionar.py` | 152 | Testes de plano, renderização e read-before-write |

## 3. Plano declarativo (`plano_rede.json`)

O plano separa os dados da sintaxe EXOS (ADR 002) e é validado antes de qualquer conexão.

### 3.1 VLANs e redes

As sete VLANs seguem os IDs múltiplos de 10 e os nomes sem espaços/acentos. Cada VLAN tem uma rede VLSM com gateway opcional e flag de DHCP:

| VLAN | ID | Rede | Gateway | DHCP |
|:--|:-:|:--|:--|:-:|
| `LSD` | 10 | `172.20.1.128/25` | `172.20.1.129` | sim |
| `LACINA` | 20 | `172.20.1.0/25` | `172.20.1.1` | sim |
| `LSI` | 30 | `172.20.2.0/26` | `172.20.2.1` | sim |
| `LIAD` | 40 | `172.20.2.64/26` | `172.20.2.65` | sim |
| `WiFi` | 50 | `172.20.0.0/24` | `172.20.0.1` | sim |
| `Cameras` | 60 | `172.20.2.128/27` | — | não |
| `Gerencia` | 70 | `172.20.2.160/28` | `172.20.2.161` | não |

A faixa DHCP é derivada do gateway até o último endereço útil, sem hardcode:
`LACINA` `.2`–`.126`, `LSD` `.130`–`.254`, `LSI` `.2`–`.62`, `LIAD` `.66`–`.126`, `WiFi` `.2`–`.254`.

### 3.2 Switches e troncos

| Switch | Papel | Gerência | Troncos |
|:--|:--|:--|:--|
| `SW-LACINA` | core | SVI `Gerencia` = `172.20.2.161/28` | 22, 23, 24 |
| `SW-LSD` | acesso | `172.20.2.162/28` | 22 |
| `SW-LSI` | acesso | `172.20.2.163/28` | 23 |
| `SW-LIAD` | acesso | `172.20.2.164/28` | 24 |

Sem `vlans` explícitas, o tronco transporta todas as VLANs, reproduzindo os comandos da Etapa 2 de `docs/docs.md`. A validação cruzada com `infra/topologia.py` garante que cada tronco e cada porta de acesso existem no cabeamento L1 do Milestone 2.

### 3.3 Hosts

As portas de acesso são derivadas dos hosts, sem duplicação:

| Host | Switch:porta | VLAN | Modo | IP |
|:--|:--|:--|:--|:--|
| `PC-LACINA` | `SW-LACINA:1` | `LACINA` | DHCP | — |
| `WIFI-1` | `SW-LACINA:2` | `WiFi` | DHCP | — |
| `ADM` | `SW-LACINA:3` | `Gerencia` | estático | `172.20.2.165/28` |
| `PC-LSD` | `SW-LSD:1` | `LSD` | DHCP | — |
| `NVR` | `SW-LSD:2` | `Cameras` | estático | `172.20.2.129/27` |
| `PC-LSI` | `SW-LSI:1` | `LSI` | DHCP | — |
| `PC-LIAD-SALA` | `SW-LSI:2` | `LIAD` | DHCP | — |
| `PC-LIAD` | `SW-LIAD:1` | `LIAD` | DHCP | — |
| `WIFI-2` | `SW-LIAD:2` | `WiFi` | DHCP | — |
| `CAM` | `SW-LIAD:3` | `Cameras` | estático | `172.20.2.130/27` |

`NVR` e `CAM` não declaram gateway, preservando o isolamento L2 da VLAN 60.

## 4. Validação do plano

`validar_plano()` (`infra/provisionar.py:475`) executa antes de conectar e rejeita:

- VLAN sem nome válido, ID não múltiplo de 10, ID 1/4095 ou duplicado;
- rede inválida (`ip_network(strict=True)`), gateway fora da rede ou em rede/broadcast;
- DHCP sem gateway;
- VLAN sem entrada em `redes`;
- switch com papel diferente de `core`/`acesso`, ou sem exatamente um core;
- IP de gerência de acesso fora de `Gerencia`, colidindo com o gateway ou duplicado;
- host em switch/VLAN inexistente, porta duplicada ou divergente do mapa L1;
- IP estático fora da sub-rede, ou gateway diferente do gateway da VLAN;
- host DHCP em VLAN sem escopo;
- porta usada como acesso e tronco simultaneamente;
- tronco que não existe no mapa L1;
- `Cameras` com gateway ou DHCP.

## 5. Renderização e read-before-write

O fluxo por switch é:

1. `conectar()` tenta Netmiko até o prompt e `show version` responderem (readiness).
2. `ler_estado_switch()` executa `show vlan` e `show vlan <nome>` para cada VLAN.
3. `montar_contexto_switch()` calcula:
   - `vlans_ausentes` (somente criação);
   - `comandos_portas` (somente mudanças de untagged/tagged);
   - SVIs/ipforwarding e escopos DHCP (idempotentes por natureza);
   - IP de gerência e rota padrão nos acessos.
4. O template `exos/switch.j2` gera os comandos.
5. `aplicar_exos()` envia o bloco com `send_config_set`.
6. `validar_exos()` relê o estado e compara com o plano.

`_parse_detalhe_vlan()` interpreta `Untag:` e `Tag:` de `show vlan <nome>`, além de `Primary IP` e `IPv4 Forwarding`. `_ler_comando()` repete leituras quando o console devolve saída truncada — problema observado uma vez no proxy de console do GNS3.

## 6. Execução real (2026-11-06)

### 6.1 Primeira execução (switches e hosts)

```bash
.venv/bin/python -m infra.provisionar
```

Resultado: `EXIT=0`, 4 switches e 10 hosts provisionados e validados.

- `SW-LACINA`: 66 comandos (7 VLANs, 3 acessos, 3 troncos × 7 VLANs, 6 SVIs, 5 escopos DHCP, `save`).
- `SW-LSD`, `SW-LSI`, `SW-LIAD`: 23–25 comandos cada, incluindo IP de gerência e rota padrão.

### 6.2 Reexecução idempotente

```bash
.venv/bin/python -m infra.provisionar --skip-hosts
```

| Switch | Comandos aplicados | Leitura |
|:--|--:|:--|
| `SW-LACINA` | 29 | `disable clipaging` + 12 SVIs/ipforwarding + 15 DHCP + `save` |
| `SW-LSD` | 4 | `disable clipaging` + `configure vlan Gerencia ipaddress` + `iproute add default` + `save` |
| `SW-LSI` | 4 | idem |
| `SW-LIAD` | 4 | idem |

VLANs e portas não foram reenviadas: `comandos_portas` ficou vazio. As SVIs e escopos DHCP são reaplicados, mas o EXOS os trata de forma idempotente.

### 6.3 Validação final

```bash
.venv/bin/python -m infra.provisionar --check
```

Resultado: `EXIT=0`, 4 switches e 10 hosts com `OK: estado validado` / `OK: host validado`.

O `--check` confirma:

- IDs e existência das 7 VLANs;
- portas de acesso untagged na VLAN correta e fora da `Default`;
- troncos tagged em todas as VLANs e sem untagged;
- SVIs e `ipforwarding` das seis VLANs roteadas no core;
- `Cameras` sem IP e sem `ipforwarding` no core;
- IP de gerência e rota padrão dos três acessos;
- IP/gateway dos VPCS estáticos e leases DHCP dentro da sub-rede correta.

### 6.4 Evidências de conectividade e segurança

Leases DHCP observados (`show ip`):

| Host | IP | Gateway |
|:--|:--|:--|
| `PC-LACINA` | `172.20.1.5/25` | `172.20.1.1` |
| `PC-LSD` | `172.20.1.133/25` | `172.20.1.129` |
| `PC-LSI` | `172.20.2.5/26` | `172.20.2.1` |
| `PC-LIAD` | `172.20.2.70/26` | `172.20.2.65` |
| `PC-LIAD-SALA` | `172.20.2.69/26` | `172.20.2.65` |
| `WIFI-1` | `172.20.0.5/24` | `172.20.0.1` |
| `WIFI-2` | `172.20.0.6/24` | `172.20.0.1` |

Pings executados manualmente durante a verificação:

| Origem → destino | Resultado |
|:--|:--|
| `PC-LACINA` → `172.20.1.1` | sucesso |
| `PC-LSD` → `172.20.1.129` | sucesso |
| `PC-LSI` → `172.20.2.1` | sucesso |
| `PC-LIAD` / `PC-LIAD-SALA` → `172.20.2.65` | sucesso |
| `PC-LACINA` → `PC-LSD`/`PC-LSI`/`PC-LIAD` | sucesso (TTL 63) |
| `CAM` → `NVR` | sucesso |
| `PC-LACINA` → `CAM`/`NVR` | `Destination host unreachable` (esperado) |

## 7. CLI de `infra/provisionar.py`

| Opção | Efeito |
|:--|:--|
| `--inventario` | Caminho do inventário (padrão: `inventario_gns3.json`) |
| `--plano` | Caminho do plano (padrão: `infra/config/plano_rede.json`) |
| `--templates` | Diretório de templates |
| `--only` | Nós separados por vírgula |
| `--skip-switches` | Não configura switches |
| `--skip-hosts` | Não configura VPCS |
| `--check` | Valida sem alterar |
| `--dry-run` | Renderiza sem conectar |
| `--verbose` | Imprime o bloco renderizado |
| `--timeout` | Espera máxima de boot por nó (padrão: 600 s) |
| `--check-timeout` | Timeout de cada tentativa de conexão (padrão: 20 s) |
| `--poll` | Intervalo entre tentativas (padrão: 5 s) |

O script falha se o inventário não existir, se algum nó estiver ausente/incompleto ou se o campo `status` não for `started` — mitigando o risco 1 apontado no research do Milestone 2.

## 8. Testes unitários

```bash
.venv/bin/python -m unittest discover -v
# Ran 12 tests ... OK
```

Cobrem: validação do plano real, rejeição de câmeras com gateway, ID de VLAN inválido e host fora do mapa L1; renderização do core/acesso/VPCS; ausência de IP/forwarding em `Cameras`; portas já corretas sem comandos; migração de porta na `Default`; compressão de portas; e faixas/portas dos escopos DHCP.

## 9. Pontos de atenção e riscos

| # | Observação | Impacto |
|--:|:--|:--|
| 1 | `save configuration` é enviado em toda execução, mesmo sem mudanças de porta/VLAN | Gravação desnecessária, sem impacto funcional |
| 2 | SVIs e escopos DHCP são reaplicados a cada execução | Idempotente no EXOS, mas gera tráfego de console |
| 3 | O firewall DHCP real não é lido diretamente | A versão EXOS 32.6.3.126 não expôs `show dhcp`; a validação é indireta pelos leases dos VPCS |
| 4 | IPs DHCP variam (`.5`, `.133`, `.69`, `.70` etc.) | Milestone 4 não pode assumir `.2`/`.130`/`.66` fixos |
| 5 | `--check` não renova leases | Se o lease expirar, o host pode aparecer sem IP até um `ip dhcp` |
| 6 | Console do GNS3 pode truncar leituras | Mitigado por `_ler_comando()` com até 3 tentativas |
| 7 | Plano exige todas as VLANs nos troncos, como nos comandos da Etapa 2 | Divergências futuras de topologia devem atualizar `plano_rede.json` |
| 8 | Sem validação de `show fdb` | A estratégia original citava `show fdb`, mas a prova de forwarding foi feita por ping DHCP/inter-VLAN |

## 10. O que existe e o que não existe após a Milestone 3

| Item | Estado |
|:--|:--|
| Templates Jinja2 | Existem |
| Plano declarativo de VLANs/IPs | Existe |
| Readiness check | Existe |
| Provisionamento do core e acessos | Existe e validado |
| Provisionamento dos VPCS | Existe e validado |
| Validação por `show vlan`/`show ipconfig`/`show iproute`/`show ip` | Existe |
| Testes unitários | Existem (12) |
| Testes de aceite automatizados (Milestone 4) | Não existem |
| Chamados de Day 2 (Milestone 5) | Não existem |

## 11. Referências principais

- `infra/provisionar.py`
- `infra/config/plano_rede.json`
- `infra/templates/exos/`, `infra/templates/vpcs/`
- `tests/test_provisionar.py`
- `docs/features/plan.md:30-36`, `:55`, `:62`
- `docs/docs.md:85-369` (comandos EXOS e IPs dos VPCS)
- `infra/topologia.py` (mapa L1 usado na validação cruzada)
- `inventario_gns3.json` (14 consoles, artefato local ignorado)
- `docs/tasks-artifacts/research/codebase-research-milestone2.md`
