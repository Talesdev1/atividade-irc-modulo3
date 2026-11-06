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
- [ ] **Task 3.1:** Desenvolver templates Jinja2 baseados nas normas do STI (VLANs, portas Tagged/Untagged, roteamento, DHCP).
- [ ] **Task 3.2 (Readiness Check):** Implementar rotina de *polling* (Wait-for-Boot) no Netmiko para aguardar o SO EXOS carregar completamente antes de enviar comandos.
- [ ] **Task 3.3:** Ler o `inventario_gns3.json` e injetar as configurações no `SW-LACINA` (Core/L3) via Netmiko.
- [ ] **Task 3.4:** Injetar configurações nos switches de acesso (`SW-LSD`, `SW-LSI`, `SW-LIAD`), definindo as rotas padrão de gerência.
- [ ] **Task 3.5:** Configurar IPs estáticos dos VPCS fixos (ADM, NVR, CAM) e ativar DHCP nos demais (via Netmiko, modo terminal).

### Milestone 4: Automação dos Testes de Aceite
**Objetivo:** Validar os 6 testes exigidos pela UFCG executando comandos automatizados nos VPCS via Telnet.
- [ ] **Task 4.1:** Validar DHCP fazendo parse do comando `ip dhcp` nos hosts dinâmicos via Netmiko.
- [ ] **Task 4.2:** Validar conectividade (Teste 2) com o Gateway disparando `ping` e lendo a resposta de sucesso no console.
- [ ] **Task 4.3:** Validar roteamento Inter-VLANs (Teste 3) executando pings cruzados entre laboratórios.
- [ ] **Task 4.4:** Validar isolamento CFTV (Testes 4 e 5), assegurando ping ok CAM->NVR e confirmando falha (`timeout` ou erro) de outras redes para a VLAN 60.
- [ ] **Task 4.5:** Validar transporte de tronco simulando troca temporal de IP e Gateway (Teste 6).

### Milestone 5: Gestão de Mudanças (Day 2 Operations)
**Objetivo:** Automatizar chamados reais usando abordagem híbrida (API para links/nós + CLI para configuração e desativação L2).
- [ ] **Task 5.1 (Chamado 1):** Usar `gns3fy` para adicionar o nó VPCS `PC-LACINA-SALA` e linká-lo à porta 4 do `SW-LIAD`. Usar Netmiko para associar a porta à VLAN LACINA no switch.
- [ ] **Task 5.2 (Chamado 2):** Simular rompimento do cabo LACINA-LIAD via CLI (Netmiko) enviando `disable port 24` nos dois switches. Em seguida, usar API para ligar o novo cabo de contingência entre `SW-LSI` e `SW-LIAD` e Netmiko para reconfigurar os troncos.
- [ ] **Task 5.3 (Chamado 3):** Migrar virtualmente o PC-LIAD-SALA, reconfigurando no Netmiko a porta de acesso do `SW-LSI` e removendo a VLAN `LIAD` residual.

---

### Diretrizes Arquiteturais Críticas
1. **Fonte da Verdade:** O arquivo `.gns3project` dita os nós da topologia base; o mapa em `infra/topologia.py` dita o cabeamento L1 inicial (acessos e troncos).
2. **Dinamicidade:** Nenhum script Netmiko deve ter portas Telnet com *hardcode*. O arquivo `inventario_gns3.json` é de leitura obrigatória.
3. **Robustez CLI:** Todos os scripts de configuração devem prever o tempo de boot dos equipamentos (Readiness Check) para evitar falhas de conexão.

## 🛠️ Estratégia de Validação

1. **Validação de API (Milestone 2):** Executar `infra/setup_lab.py --validate` para comparar, via API v3 do GNS3, os nomes/tipos dos nós com o `project.gns3` embutido em `base_topology/uasc.gns3project` e os 13 enlaces (10 acessos + 3 troncos) com o mapa de `infra/topologia.py`. A execução local validou 14 nós e 13 links, com todos os nós `started` e o `inventario_gns3.json` exportado com 14 consoles.
2. **Validação de CLI (Milestone 3):** O script `netmiko` deve capturar a saída de comandos de validação (`show vlan`, `show ipconfig`, `show fdb`) e fazer um *assert* contra os valores esperados.
3. **Validação End-to-End (Milestone 4):** A biblioteca `netmiko` ou rotinas via console de gerência farão parse dos resultados de comandos `ping` executados a partir dos VPCS. Um retorno contendo `timeout` ou `unreachable` será tratado como **SUCESSO** no teste de isolamento (CFTV) e como **FALHA** nos testes de comunicação Inter-VLAN.