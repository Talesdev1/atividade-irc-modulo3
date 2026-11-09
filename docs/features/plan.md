# Plano de Ação: Automação GNS3 - Projeto STI/UFCG

Este documento define o roteiro de execução (Milestones) para automatizar a criação, configuração e validação da infraestrutura de rede L2/L3 no GNS3, utilizando Python (`gns3fy`, `netmiko`).

---

## 🎯 Objetivo Principal
Implementar 100% da topologia e das configurações da "Atividade Módulo 3" via código, garantindo idempotência e aprovação nos testes de conectividade e segurança.

---

### Milestone 1: Setup do Ambiente e Base de Código
**Objetivo:** Preparar o ambiente local de automação e garantir comunicação autenticada com o servidor GNS3.
- [x] **Task 1.1:** Inicializar repositório e ambiente virtual (`venv`).
- [x] **Task 1.2:** Instalar dependências (`gns3fy`, `requests`, `netmiko`, `jinja2`, `python-dotenv`).
- [x] **Task 1.3:** Criar arquivo `.env` para centralizar variáveis (URL e versão da API do GNS3, `GNS3_ACCESS_TOKEN`, host de console e credenciais padrão dos switches).
- [x] **Task 1.4:** Ler o `access_token` da variável `GNS3_ACCESS_TOKEN` do `.env` e enviá-lo no header `Authorization: Bearer <access_token>` em todas as chamadas do `gns3fy` (`api_version=3`); o token não deve ser hardcoded nem solicitado pelo script.
- [x] **Task 1.5:** Escrever script de teste de conexão autenticada com a API do GNS3 (`http://localhost:3080`) — implementado como `setup_lab.py --check` e validado contra o servidor local (GNS3 3.1.0a6, projeto `uasc`, 14 nós).

> **Pré-requisito técnico (API v3 + token no `.env`):** O servidor local roda GNS3 3.1.0a6 e expõe `/v3/*`; `/v2/*` responde 404 e `/v3/projects` exige autenticação (401 `Not authenticated`). O `gns3fy 0.8.0` aponta para `/v2` por padrão, então o conector deve ser criado com `api_version=3` e usar o header `Authorization: Bearer <access_token>`. A autenticação ocorre exclusivamente pelo `access_token` lido de `GNS3_ACCESS_TOKEN` no `.env`; não há login por usuário/senha nem obtenção de token dentro do script.

### Milestone 2: Orquestração Lógica e Descoberta (Base `.gns3project`)
**Objetivo:** Carregar a topologia base pré-desenhada, inicializar os equipamentos via API e mapear dinamicamente as portas de console.
- [x] **Task 2.1:** Estruturar o diretório `base_topology/` para armazenar o arquivo `.gns3project` inicial e configurar o `.gitignore` (ignorando discos virtuais pesados).
- [x] **Task 2.2:** Criar o script de orquestração (`infra/setup_lab.py`) para conectar à API e localizar o projeto ativo (ex: `uasc`). O `setup_lab.py` da raiz permanece como atalho de compatibilidade para o comando do Milestone 1.
- [x] Task 2.3: Automatizar a criação do cabeamento inicial (links L1) via API (gns3fy), conectando as portas de acesso dos VPCS e os troncos 802.1Q entre os switches conforme o mapa de portas padrão (ex: SW-LACINA portas 22-24). O mapa fica em `infra/topologia.py`; o script expande os adaptadores dos switches quando necessário e não duplica links existentes.
- [x] **Task 2.4:** Implementar a rotina para iniciar todos os nós simultaneamente via API (`lab.start_nodes()`), aguardando o estado `started` por polling.
- [x] **Task 2.5:** Extrair as portas de console (Telnet) alocadas pelo GNS3 para cada nó e exportar para o arquivo `inventario_gns3.json`.

### Milestone 3: Provisionamento de Configurações (Netmiko + Jinja2)
**Objetivo:** Aplicar configurações L2 e L3 nos switches EXOS e IPs nos VPCS, consumindo o inventário dinâmico.
- [x] **Task 3.1:** Desenvolver templates Jinja2 baseados nas normas do STI (VLANs, portas Tagged/Untagged, roteamento, DHCP) em `infra/templates/exos/` e `infra/templates/vpcs/`, alimentados pelo plano declarativo `infra/config/plano_rede.json`.
- [x] **Task 3.2 (Readiness Check):** Implementar rotina de *polling* (Wait-for-Boot) no Netmiko para aguardar o SO EXOS carregar completamente antes de enviar comandos (`conectar()` em `infra/provisionar.py`, validando `show version`/prompt).
- [x] **Task 3.3:** Ler o `inventario_gns3.json` e injetar as configurações no `SW-LACINA` (Core/L3) via Netmiko, com *read-before-write* (`show vlan`) e validação por `show vlan`/`show ipconfig`.
- [x] **Task 3.4:** Injetar configurações nos switches de acesso (`SW-LSD`, `SW-LSI`, `SW-LIAD`), definindo as rotas padrão de gerência e validando-as com `show iproute`.
- [x] **Task 3.5:** Configurar IPs estáticos dos VPCS fixos (ADM, NVR, CAM) e ativar DHCP nos demais (via Netmiko, modo terminal), validando com `show ip`.

### Milestone 4: Automação dos Testes de Aceite
**Objetivo:** Validar os 6 testes exigidos pela UFCG executando comandos automatizados nos VPCS via Telnet.
- [x] **Task 4.1:** Validar DHCP fazendo parse do comando `ip dhcp` nos hosts dinâmicos via Netmiko (`infra/testes_aceite.py`, Teste 1: sub-rede, máscara e gateway conferidos contra `plano_rede.json`).
- [x] **Task 4.2:** Validar conectividade (Teste 2) com o Gateway disparando `ping` e lendo a resposta de sucesso no console (todos os hosts com gateway, inclusive `ADM`).
- [x] **Task 4.3:** Validar a conectividade de todos os nós entre si (Teste 3) executando pings em malha completa entre os 8 hosts com gateway (28 pares: inter-VLANs via `SW-LACINA` + par intra-VLAN `PC-LIAD` ↔ `PC-LIAD-SALA` atravessando tronco), excluindo `CAM`/`NVR` por isolamento.
- [x] **Task 4.4:** Validar isolamento CFTV (Testes 4 e 5), assegurando ping ok CAM->NVR e confirmando falha (`timeout` ou `ICMP unreachable`) das redes de laboratório para a VLAN 60, a partir de `PC-LACINA` e `PC-LSD`.
- [x] **Task 4.5:** Validar a soberania da VLAN (Teste 6): trocar o IP do `PC-LACINA` para a faixa do LSD **deve** resultar em falha de ping, provando que o isolamento L2 não é burlado por reconfiguração do host; ao final o DHCP é restaurado e revalidado.

### Milestone 5: Gestão de Mudanças (Day 2 Operations)
**Objetivo:** Automatizar chamados reais usando abordagem híbrida (API para links/nós + CLI para configuração e desativação L2).
- [ ] **Task 5.1 (Chamado 1):** Usar `gns3fy` para adicionar o nó VPCS `PC-LACINA-SALA` e linká-lo à porta 4 do `SW-LIAD`. Usar Netmiko para associar a porta à VLAN LACINA no switch.
- [ ] **Task 5.2 (Chamado 2):** Simular rompimento do cabo LACINA-LIAD via CLI (Netmiko) enviando `disable port 24` nos dois switches. Em seguida, usar API para ligar o novo cabo de contingência entre `SW-LSI` e `SW-LIAD` e Netmiko para reconfigurar os troncos.
- [ ] **Task 5.3 (Chamado 3):** Migrar virtualmente o PC-LIAD-SALA, reconfigurando no Netmiko a porta de acesso do `SW-LSI` e removendo a VLAN `LIAD` residual.

---

### Diretrizes Arquiteturais Críticas
1. **Fonte da Verdade:** O arquivo `.gns3project` dita os nós da topologia base; o mapa em `infra/topologia.py` dita o cabeamento L1 inicial (acessos e troncos); `infra/config/plano_rede.json` dita VLANs, sub-redes, portas de acesso/tronco e endereçamento dos hosts.
2. **Dinamicidade:** Nenhum script Netmiko deve ter portas Telnet com *hardcode*. O arquivo `inventario_gns3.json` é de leitura obrigatória.
3. **Robustez CLI:** Todos os scripts de configuração devem prever o tempo de boot dos equipamentos (Readiness Check) para evitar falhas de conexão.

## 🛠️ Estratégia de Validação

1. **Validação de API (Milestone 2):** Executar `infra/setup_lab.py --validate` para comparar, via API v3 do GNS3, os nomes/tipos dos nós com o `project.gns3` embutido em `base_topology/uasc.gns3project` e os 13 enlaces (10 acessos + 3 troncos) com o mapa de `infra/topologia.py`. A execução local validou 14 nós e 13 links, com todos os nós `started` e o `inventario_gns3.json` exportado com 14 consoles.
2. **Validação de CLI (Milestone 3):** `python -m infra.provisionar --check` lê `show vlan`, `show ipconfig`, `show iproute` e `show ip` e compara com o plano: IDs de VLAN, portas untagged/tagged, SVIs/ipforwarding, ausência de IP/forwarding na VLAN `Cameras`, IP de gerência + rota padrão dos switches de acesso e IP/gateway dos VPCS. O mesmo script já executou `--dry-run` (renderização) e o provisionamento real idempotente, com 4 switches e 10 hosts validados.
3. **Validação End-to-End (Milestone 4):** `python -m infra.testes_aceite` conecta aos VPCS via console (Netmiko), dispara `ip dhcp`/`ping` e faz parse das respostas. Ping respondido exige a linha `84 bytes from <ip>`; ausência de resposta com `timeout`, `host not reachable` ou `ICMP unreachable` caracteriza bloqueio. O bloqueio é **SUCESSO** nos Testes 5 e 6 (isolamento L2/CFTV) e **FALHA** nos Testes 2, 3 e 4 (comunicação esperada). A execução local aprovou os 6 testes, com `--json` disponível para relatório.