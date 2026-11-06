# Plano de Ação: Automação GNS3 - Projeto STI/UFCG

Este documento define o roteiro de execução (Milestones) para automatizar a criação, configuração e validação da infraestrutura de rede L2/L3 no GNS3, utilizando Python (`gns3fy`, `netmiko`).

---

## 🎯 Objetivo Principal
Implementar 100% da topologia e das configurações da "Atividade Módulo 3" via código, garantindo idempotência e aprovação nos testes de conectividade e segurança.

---

## 🗺️ Milestones e Tarefas (Tasks)

### Milestone 1: Setup do Ambiente e Base de Código
**Objetivo:** Preparar o ambiente local de automação e garantir comunicação autenticada com o servidor GNS3.
- [x] **Task 1.1:** Inicializar repositório e ambiente virtual (`venv`).
- [x] **Task 1.2:** Instalar dependências (`gns3fy`, `requests`, `netmiko`, `jinja2`, `python-dotenv`).
- [x] **Task 1.3:** Criar arquivo `.env` para centralizar variáveis (URL e versão da API do GNS3, `GNS3_ACCESS_TOKEN`, host de console e credenciais padrão dos switches).
- [x] **Task 1.4:** Ler o `access_token` da variável `GNS3_ACCESS_TOKEN` do `.env` e enviá-lo no header `Authorization: Bearer <access_token>` em todas as chamadas do `gns3fy` (`api_version=3`); o token não deve ser hardcoded nem solicitado pelo script.
- [x] **Task 1.5:** Escrever script de teste de conexão autenticada com a API do GNS3 (`http://localhost:3080`) — implementado como `setup_lab.py --check` e validado contra o servidor local (GNS3 3.1.0a6, projeto `uasc`, 14 nós).

> **Pré-requisito técnico (API v3 + token no `.env`):** O servidor local roda GNS3 3.1.0a6 e expõe `/v3/*`; `/v2/*` responde 404 e `/v3/projects` exige autenticação (401 `Not authenticated`). O `gns3fy 0.8.0` aponta para `/v2` por padrão, então o conector deve ser criado com `api_version=3` e usar o header `Authorization: Bearer <access_token>`. A autenticação ocorre exclusivamente pelo `access_token` lido de `GNS3_ACCESS_TOKEN` no `.env`; não há login por usuário/senha nem obtenção de token dentro do script.

### Milestone 2: Orquestração Lógica (Topologia via `gns3fy`)
**Objetivo:** Criar os equipamentos e cabeamentos no GNS3 sem intervenção manual na interface gráfica.
- [ ] **Task 2.1:** Desenvolver o script de criação do projeto (`infra/create_project.py`), incluindo verificação de idempotência (checar se o projeto já existe).
- [ ] **Task 2.2:** Automatizar o provisionamento de nós: 4 Switches EXOS e 10 VPCS (Hosts).
- [ ] **Task 2.3:** Automatizar a criação de links (cabeamento) de acordo com o mapa de portas do projeto (ex: SW-LACINA porta 22 <-> SW-LSD porta 22).
- [ ] **Task 2.4:** Criar rotina para iniciar (start) todos os nós do projeto via API.

### Milestone 3: Provisionamento de Configurações (Via `Netmiko` e `Jinja2`)
**Objetivo:** Aplicar configurações L2 e L3 nos switches EXOS e IPs nos VPCS.
- [ ] **Task 3.1:** Desenvolver templates Jinja2 baseados nas normas do STI (Criação de VLANs, associação de portas Tagged/Untagged, roteamento, DHCP).
- [ ] **Task 3.2:** Escrever script Netmiko (`config/configure_switches.py`) para injetar as configurações no `SW-LACINA` (Core/L3).
- [ ] **Task 3.3:** Injetar configurações nos switches de acesso (`SW-LSD`, `SW-LSI`, `SW-LIAD`), configurando rotas padrão de gerência.
- [ ] **Task 3.4:** Criar script/rotina para configurar os IPs estáticos dos VPCS (ADM, NVR, CAM) e ativar o DHCP nos demais.

### Milestone 4: Automação dos Testes de Aceite
**Objetivo:** Executar e validar programaticamente os 6 testes exigidos na proposta.
- [ ] **Task 4.1:** Script para checar atribuição de IPs via DHCP nos hosts dinâmicos.
- [ ] **Task 4.2:** Script de validação de Ping para o Gateway (Teste 2).
- [ ] **Task 4.3:** Script de validação de roteamento Inter-VLANs (Teste 3).
- [ ] **Task 4.4:** Script de validação da rede de CFTV (Teste 4 e Teste 5 - Isolamento, garantindo que o ping falhe ao tentar acessar outras sub-redes).
- [ ] **Task 4.5:** Validação de transporte de tronco com mudança temporal de IP (Teste 6).

### Milestone 5: Gestão de Mudanças (Day 2 Operations)
**Objetivo:** Criar fluxos de código para os 3 chamados (tickets) de mudança previstos.
- [ ] **Task 5.1:** Script Chamado 1: Provisionar novo PC `PC-LACINA-SALA` na porta 4 do `SW-LIAD` e reconfigurar a VLAN local.
- [ ] **Task 5.2:** Script Chamado 2: Suspender link rompido (SW-LACINA <-> SW-LIAD) via API e configurar novo tronco de contingência via `SW-LSI`.
- [ ] **Task 5.3:** Script Chamado 3: Migrar porta do PC da sala emprestada para o LSI e limpar a VLAN `LIAD` residual do `SW-LSI`.

---

## ✅ Critérios de Aceite (Definition of Done)

Para que uma Milestone seja considerada concluída, as seguintes condições devem ser atendidas:
1. **Idempotência:** A execução repetida do mesmo script não deve causar erros, duplicar nós ou corromper a configuração atual.
2. **Modularidade:** Nenhum hardcode de senhas; uso de templates estruturados.
3. **Isolamento Confirmado:** A VLAN `Cameras` (60) deve estar provada como inacessível pelas demais redes (Falha no ping para hosts externos confirmada).
4. **Resiliência de Enlaces:** A rede deve manter a conectividade total mesmo após a aplicação do Chamado 2 (rompimento de link).

---

## 🛠️ Estratégia de Validação

1. **Validação de API (Milestone 2):** Utilizar `requests` para consultar os endpoints do GNS3 Server (`/v2/projects/{id}/nodes`) e garantir que a contagem de nós e links corresponde exatamente à topologia proposta.
2. **Validação de CLI (Milestone 3):** O script `netmiko` deve capturar a saída de comandos de validação (`show vlan`, `show ipconfig`, `show fdb`) e fazer um *assert* contra os valores esperados.
3. **Validação End-to-End (Milestone 4):** A biblioteca `netmiko` ou rotinas via console de gerência farão parse dos resultados de comandos `ping` executados a partir dos VPCS. Um retorno contendo `timeout` ou `unreachable` será tratado como **SUCESSO** no teste de isolamento (CFTV) e como **FALHA** nos testes de comunicação Inter-VLAN.