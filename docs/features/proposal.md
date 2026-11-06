# Proposta Técnica: Automação e Provisionamento de Infraestrutura de Rede no GNS3

## 1. Objetivo do Projeto
O presente documento estabelece a proposta técnica para a automação do provisionamento, configuração e testes da infraestrutura de rede simulada no GNS3. O objetivo é utilizar práticas de Infraestrutura como Código (IaC) e scripts em Python para orquestrar a topologia padronizada pelo STI da Universidade Federal de Campina Grande (UFCG), reduzindo o esforço manual e garantindo conformidade, segurança e idempotência nas configurações.

## 2. Escopo Arquitetural
A infraestrutura a ser automatizada consiste em uma topologia L2/L3 rodando o sistema operacional EXOS (Extreme Networks) e estações de trabalho simuladas (VPCS). 

A arquitetura baseia-se em um modelo estrela centralizado:
*   **Core / Gateway L3:** O switch `SW-LACINA` atuará como roteador central e servidor DHCP para as redes dinâmicas.
*   **Switches de Acesso:** `SW-LSD`, `SW-LSI` e `SW-LIAD` distribuirão os acessos aos laboratórios.
*   **Enlaces Inter-Switches:** Conexões em tronco (Trunks 802.1Q) transportando tráfego *tagged*.
*   **Isolamento de Segurança:** Garantia de segregação total em Camada 2 para a rede de CFTV (Câmeras e NVR).

## 3. Stack Tecnológico e Ferramentas
A automação será conduzida através de um repositório gerenciado pelo OpenCode, utilizando as seguintes tecnologias:
*   **Simulador de Rede:** GNS3 Server.
*   **Linguagem de Automação:** Python 3.10+.
*   **Orquestração da Topologia (GNS3 API):** Biblioteca `gns3fy` para criação automatizada de nós, links e projetos diretamente via chamadas REST.
*   **Gerência de Configuração:** Biblioteca `netmiko` para injeção de comandos CLI (EXOS) via Telnet/SSH, apoiada por templates `Jinja2`.
*   **Controle de Variáveis Ambientais:** `python-dotenv` para segurança de credenciais e endereçamentos.

## 4. Fases de Implementação

### Fase 1: Setup e Orquestração Base (Infraestrutura)
*   Integração do script Python com a API REST do GNS3.
*   Criação automatizada e idempotente do projeto de rede.
*   Provisionamento de nós virtuais (Switches EXOS e VPCS).
*   Cabeamento lógico (criação de links entre as portas corretas conforme o mapa da topologia).

### Fase 2: Injeção de Configuração de Rede
*   Desenvolvimento de scripts Netmiko para aplicar as parametrizações do plano de endereçamento VLSM (Bloco `172.20.0.0/22`).
*   Configuração automatizada de VLANs (IDs múltiplos de 10) e associação de portas (Access/Trunk).
*   Ativação do roteamento (IP Forwarding) e dos escopos DHCP no `SW-LACINA`.
*   Aplicação das restrições de segurança (remoção de VLAN Default, isolamento da VLAN 60 de CFTV sem Gateway).

### Fase 3: Testes de Aceite Automatizados
*   Scripts de validação para simular o processo de "Testes de Aceite".
*   Verificação automatizada da obtenção de IPs via DHCP.
*   Testes de ping inter-VLANs (roteamento).
*   Validação do bloqueio de tráfego (isolamento) entre os laboratórios e a rede de CFTV.

### Fase 4: Gestão de Mudanças (Day 2 Operations)
*   Criação de fluxos de script para atender a Pedidos de Mudança (ex: realocação de portas, suspensão de cabos rompidos e criação de rotas de contingência via troncos alternativos).
*   Limpeza automatizada de VLANs ociosas nos switches de acesso para otimização de recursos.

## 5. Critérios de Êxito
O projeto será considerado concluído com sucesso quando o OpenCode for capaz de gerar os scripts que reproduzem, do zero e sem intervenção manual na interface gráfica, a topologia completa, operante e aprovada em todos os 6 testes de conectividade e segurança exigidos pelo STI.