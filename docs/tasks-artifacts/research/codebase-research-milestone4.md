# Research: Milestone 4 — Automação dos Testes de Aceite

Snapshot: 2026-11-06. O working tree estava limpo em `1bfae11` (`feat: Milestone 3`) antes das alterações desta milestone. Este documento complementa `codebase-research-milestone3.md`.

## Summary

A Milestone 4 foi implementada em `infra/testes_aceite.py` (530 linhas), com 19 testes unitários adicionais em `tests/test_testes_aceite.py` (total do projeto: 31). O runner reutiliza o inventário dinâmico do Milestone 2, o plano declarativo e os helpers de conexão/leitura do `infra/provisionar.py`, mantendo uma sessão Telnet por VPCS durante a bateria. Os 6 testes de aceite foram executados ao vivo e aprovados, com relatório JSON opcional.

O ponto mais relevante foi a **correção do Teste 6**: o roteiro original esperava sucesso no ping, mas o comportamento correto (e o observado) é de **falha**, pois a troca manual de IP não burla o isolamento da VLAN. O `docs/docs.md` foi corrigido.

## 1. Checklist da consulta (Milestone 4)

| Área verificada | Estado | Evidência |
|:--|:--|:--|
| Task 4.1 — DHCP | Implementado e validado no GNS3 | `teste_1_dhcp()` |
| Task 4.2 — gateway | Implementado e validado no GNS3 | `teste_2_gateway()` |
| Task 4.3 — inter-VLAN | Implementado e validado no GNS3 | `teste_3_inter_vlan()` |
| Task 4.4 — CFTV e isolamento | Implementado e validado no GNS3 | `teste_4_cftv()`, `teste_5_isolamento()` |
| Task 4.5 — Teste 6 | Implementado e validado, com expectativa corrigida | `teste_6_soberania_vlan()` |
| Sessões dinâmicas | Implementado | `Sessoes` (inventário, sem porta fixa) |
| Relatório | Implementado | `--json` |
| Testes unitários | Implementado | `tests/test_testes_aceite.py` (19 testes) |
| Documentação | Atualizada | `docs/features/plan.md`, `docs/docs.md` |

## 2. Arquivos criados/alterados

| Arquivo | Linhas | Papel |
|:--|--:|:--|
| `infra/testes_aceite.py` | 530 | Runner dos 6 testes, parsing de ping, sessões e CLI |
| `tests/test_testes_aceite.py` | 146 | Testes de parsing, seleção, gateways e hosts necessários |
| `docs/features/plan.md` | — | Tasks 4.1–4.5 concluídas e estratégia de validação |
| `docs/docs.md` | — | Teste 6 com resultado esperado corrigido e justificativa técnica |

## 3. Desenho do runner

### 3.1 Sessões

`Sessoes` abre uma conexão Netmiko por VPCS sob demanda e a reutiliza por toda a bateria. O readiness é exatamente o do Milestone 3 (`conectar()`), que valida prompt `VPCS` e `show ip`. Nenhuma porta é hardcoded: tudo vem de `inventario_gns3.json`.

### 3.2 Parsing de ping

O console VPCS tem três formatos relevantes:

| Situação | Exemplo |
|:--|:--|
| sucesso | `84 bytes from 172.20.1.1 icmp_seq=1 ttl=64 time=1.727 ms` |
| bloqueio por roteador | `*172.20.1.1 icmp_seq=1 ttl=64 time=0.504 ms (ICMP type:3, code:1, Destination host unreachable)` |
| sem ARP | `host (172.20.1.129) not reachable` |
| timeout | `172.20.2.130 icmp_seq=1 timeout` |

`interpretar_ping()` exige a linha `84 bytes from <destino>` para sucesso — o IP precisa coincidir, evitando falso positivo quando outro host responde. A ausência dessa linha somada a `timeout`, `unreachable`, `not reachable` ou `no route to host` caracteriza bloqueio. Sem marcador, o resultado é inconclusivo e o teste reprova.

### 3.3 Semântica dos testes

| # | Origem | Destino | Esperado |
|:-:|:--|:--|:--|
| 1 | cada host DHCP | servidor DHCP da VLAN | IP dentro da sub-rede, máscara e gateway do plano |
| 2 | cada host com gateway (inclui `ADM`) | gateway da VLAN | sucesso |
| 3 | `PC-LACINA` | `PC-LSD`, `PC-LSI`, `PC-LIAD`, `PC-LIAD-SALA` | sucesso |
| 4 | `CAM` | `NVR` | sucesso (L2, VLAN 60) |
| 5 | `PC-LACINA`, `PC-LSD` | `CAM`, `NVR` | bloqueio |
| 6 | `PC-LACINA` com IP do LSD | gateway do LSD | bloqueio + DHCP restaurado |

Os IPs de destino do Teste 3 vêm dos leases coletados no Teste 1 (com leitura sob demanda como fallback), nunca de endereços fixos.

### 3.4 Teste 6

```text
ip 172.20.1.250/25 172.20.1.129   # IP da faixa LSD numa porta da VLAN LACINA
ping 172.20.1.129                 # DEVE falhar
ip dhcp                           # restauração garantida em finally
```

O IP temporário é validado contra o plano: precisa pertencer à sub-rede do LSD e **não** à sub-rede da VLAN do host. A restauração roda em `finally` e revalida o gateway; se falhar, o teste reprova, mas nunca mascara a exceção original.

## 4. Correção do Teste 6 no roteiro

O `docs/docs.md` previa **sucesso** no ping. A verificação ao vivo mostrou `host (172.20.1.129) not reachable`. Causa:

1. O `PC-LACINA` está na porta 1 do `SW-LACINA`, `untagged` na VLAN `LACINA` (20).
2. `172.20.1.250/25` pertence à sub-rede do LSD, mas `172.20.1.129` é a SVI da VLAN `LSD` (10).
3. O ARP é enviado na VLAN 20, onde o endereço não existe; o EXOS 32.6.3.126 não possui proxy ARP dinâmico (`enable iparp proxy` é comando inválido).
4. Mesmo com ARP respondido, a resposta do core para `172.20.1.250` sairia pela rota conectada `172.20.1.128/25` em direção à VLAN 10, sem voltar ao PC.

Logo, a falha é o comportamento **correto** e comprova a soberania da VLAN L2. Para o ping funcionar seria necessário mover a porta 1 para a VLAN `LSD` — exatamente o cenário de mudança do Milestone 5.

## 5. Execução real (2026-11-06)

```bash
.venv/bin/python -m infra.testes_aceite --json /tmp/opencode/aceite.json
```

Resultado: `EXIT=0`, `Testes de aceite: 6/6 aprovados.`

| Teste | Evidência |
|:--|:--|
| 1 | 7 leases válidos: `.5/25`, `.5/24`, `.133/25`, `.5/26`, `.69/26`, `.70/26`, `.6/24` |
| 2 | 8 pings ao gateway, todos com resposta |
| 3 | 4 pings inter-VLAN, todos com resposta |
| 4 | `CAM -> NVR` com resposta |
| 5 | 4 pings para `CAM`/`NVR` bloqueados |
| 6 | IP temporário aceito, ping bloqueado, DHCP restaurado em `172.20.1.5/25` |

## 6. CLI de `infra/testes_aceite.py`

| Opção | Efeito |
|:--|:--|
| `--inventario` | Caminho do inventário (padrão: `inventario_gns3.json`) |
| `--plano` | Caminho do plano (padrão: `infra/config/plano_rede.json`) |
| `--only` | Testes separados por vírgula (ex.: `1,3,5`) |
| `--contagem` | Pacotes por ping (padrão: 3) |
| `--ip-teste6` | IP temporário do Teste 6 (padrão: `172.20.1.250/25`) |
| `--json` | Grava o relatório da execução |
| `--verbose` | Imprime a saída bruta dos pings que falharem |
| `--timeout` / `--check-timeout` / `--poll` | Readiness e conexão, como no Milestone 3 |

O runner valida o plano e só exige no inventário os hosts necessários aos testes selecionados (ex.: `--only 4` exige apenas `CAM` e `NVR`).

## 7. Testes unitários

```bash
.venv/bin/python -m unittest discover -v
# Ran 31 tests ... OK
```

Cobrem: sucesso, `ICMP unreachable`, `timeout`, `host not reachable` e saída inconclusiva; rejeição de resultado positivo de outro IP; seleção e ordenação de testes; gateways de hosts DHCP/estáticos; hosts necessários por teste; e a premissa pedagógica do Teste 6 (IP temporário em sub-rede distinta da VLAN do host).

## 8. Pontos de atenção e riscos

| # | Observação | Impacto |
|--:|:--|:--|
| 1 | O Teste 1 renova o lease de todos os hosts dinâmicos | IPs podem mudar entre execuções; o runner não assume endereços fixos |
| 2 | `172.20.1.250` está dentro da faixa DHCP do LSD | Risco baixo de conflito; `--ip-teste6` permite trocar |
| 3 | O `ping` do VPCS envia 5 pacotes por padrão | O runner usa `-c 3` para reduzir o tempo |
| 4 | Saída do console depende do prompt `VPCS>` | Mitigado pelo readiness do Milestone 3 |
| 5 | Teste 6 altera temporariamente o `PC-LACINA` | Restauração garantida em `finally` e revalidada |
| 6 | Testes 5 e 6 dependem de ausência de resposta | Um roteador que respondesse ICMP com sucesso faria o teste reprovar corretamente |

## 9. O que existe e o que não existe após a Milestone 4

| Item | Estado |
|:--|:--|
| Testes de aceite automatizados | Existem e foram aprovados (6/6) |
| Relatório JSON | Existe |
| Testes unitários | Existem (31 no projeto) |
| Chamados de Day 2 (Milestone 5) | Não existem |

## 10. Referências principais

- `infra/testes_aceite.py`
- `infra/provisionar.py` (helpers reutilizados)
- `infra/config/plano_rede.json`
- `tests/test_testes_aceite.py`
- `docs/features/plan.md` (Milestone 4 e estratégia de validação)
- `docs/docs.md` (Teste 6 corrigido)
- `inventario_gns3.json` (14 consoles, artefato local ignorado)
