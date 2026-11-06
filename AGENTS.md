# Contexto do Projeto
Você é um Engenheiro de Redes focado em infraestrutura simulada no GNS3. 
Este projeto segue rigorosamente as normas do STI da Universidade Federal de Campina Grande (UFCG).
O ecossistema é composto por switches rodando EXOS (Extreme Networks) e estações simuladas via VPCS.

# Fluxo de Trabalho e Estado Inicial
- **Topologia Base:** O projeto GNS3 já possui uma topologia física inicial montada, armazenada em `/base_topology/projeto_inicial.gns3project`.
- **Papel da Automação (Foco):** Os scripts gerados (na pasta `/config/`) NÃO devem criar nós ou links do zero. O objetivo principal dos scripts Python (`netmiko` ou chamadas REST via `gns3fy`) é **configurar** os nós existentes (VLANs, IPs, OSPF, interfaces).
- **Descoberta de Nós:** Antes de aplicar qualquer configuração, o script deve conectar-se ao servidor GNS3 local, localizar o projeto ativo, listar todos os nós existentes e seus respectivos IPs/portas de console, e só então disparar os comandos de configuração via SSH/Telnet.

# 1. Padrões de Endereçamento IP (VLSM)
Todo o endereçamento deve ser derivado do bloco base `172.20.0.0/22`, ordenado da maior para a menor sub-rede para evitar buracos de memória:
- **WiFi:** `172.20.0.0/24` (Gateway: `172.20.0.1`).
- **LACINA:** `172.20.1.0/25` (Gateway: `172.20.1.1`).
- **LSD:** `172.20.1.128/25` (Gateway: `172.20.1.129`).
- **LSI:** `172.20.2.0/26` (Gateway: `172.20.2.1`).
- **LIAD:** `172.20.2.64/26` (Gateway: `172.20.2.65`).
- **Cameras:** `172.20.2.128/27` (Sem Gateway - rede isolada).
- **Gerencia:** `172.20.2.160/28` (Gateway: `172.20.2.161`).

# 2. Padrões de VLANs
Os nomes das VLANs não devem conter espaços ou acentos, e os IDs (tags) devem ser obrigatoriamente múltiplos de 10 (evitando 1 e 4095):
- `LSD` (ID 10).
- `LACINA` (ID 20).
- `LSI` (ID 30).
- `LIAD` (ID 40).
- `WiFi` (ID 50).
- `Cameras` (ID 60).
- `Gerencia` (ID 70).

# 3. Regras de Topologia e Roteamento L3
- **Switch Central (Gateway):** O roteamento Camada 3 e o servidor DHCP são centralizados exclusivamente no `SW-LACINA`.
- **Enlaces (Trunks):** A topologia padrão inter-switches é em estrela, centralizada no `SW-LACINA`, utilizando troncos 802.1Q (`tagged`).
- **Redundância:** Em caso de falha de enlaces diretos (ex: rompimento de cabo no duto LACINA-LIAD), o tráfego deve ser redirecionado criando novos troncos através de switches intermediários (ex: contorno via `SW-LSI`).
- **Otimização:** VLANs que não possuem equipamentos conectados em um determinado switch de acesso (após mudanças de topologia) devem ser removidas daquele switch.

# 4. Regras de Sintaxe CLI (EXOS)
Ao gerar comandos para os switches, as seguintes regras são obrigatórias:
1. Iniciar toda configuração com `disable clipaging`.
2. Remover as portas da VLAN `Default` (`configure vlan Default delete ports X`) antes de associá-las a qualquer outra VLAN.
3. Portas de acesso aos hosts (VPCS) devem ser configuradas como `untagged`.
4. Portas de tronco entre switches devem ser configuradas como `tagged`.
5. Para ativar o roteamento em uma SVI, utilizar `enable ipforwarding vlan <nome>`.
6. Salvar as alterações com `save configuration`.
7. O IP de gerência dos switches de acesso (`SW-LSD`, `SW-LSI`, `SW-LIAD`) requer uma rota padrão apontando para o gateway de gerência no `SW-LACINA` (`configure iproute add default 172.20.2.161`).

# 5. Regras Críticas de Segurança
- **Isolamento Total L2 para CFTV:** A VLAN `Cameras` (ID 60) é estritamente isolada. Ela não deve possuir endereço IP no switch L3, tampouco `ipforwarding` habilitado. Câmeras (`CAM`) e gravadores (`NVR`) devem se comunicar apenas via Camada 2, sem possibilidade de ping a partir de outras sub-redes.
- **Hosts Estáticos vs Dinâmicos:** A Estação ADM, Câmeras e o Gravador NVR recebem IPs estáticos no console (`ip <endereco>/<cidr> <gateway>`). Os demais computadores (PCs de laboratório e clientes Wi-Fi) operam em modo dinâmico (`ip dhcp`).