# **Etapa 1 (Projeto)** 
Consiste no planejamento completo do **endereçamento IP (VLSM)**, na **definição da topologia e enlaces entre os switches**, e na **padronização das VLANs e roteamento L3** antes de iniciar a configuração prática no GNS3.

---
### 1. Plano de Endereçamento VLSM (Bloco `172.20.0.0/22`)
Seguindo as normas do STI da UFCG, utilizou-se o bloco alocado **`172.20.0.0/22`**. As sub-redes foram ordenadas **da maior para a menor** para garantir o correto alinhamento de bloco e evitar buracos de memória:

| Rede         | Hosts | Necessidade (Hosts + GW) | Sub-rede (Prefix) | Endereço de Rede  | Máscara           | Gateway        | Faixa Útil (DHCP/Fixo)                 | Broadcast      |
| :----------- | :---: | :----------------------: | :---------------: | :---------------- | :---------------- | :------------- | :------------------------------------- | :------------- |
| **Wi-Fi**    |  180  |           181            |    `/24` (254)    | `172.20.0.0/24`   | `255.255.255.0`   | `172.20.0.1`   | `172.20.0.2` – `172.20.0.254`          | `172.20.0.255` |
| **LACINA**   |  100  |           101            |    `/25` (126)    | `172.20.1.0/25`   | `255.255.255.128` | `172.20.1.1`   | `172.20.1.2` – `172.20.1.126`          | `172.20.1.127` |
| **LSD**      |  70   |            71            |    `/25` (126)    | `172.20.1.128/25` | `255.255.255.128` | `172.20.1.129` | `172.20.1.130` – `172.20.1.254`        | `172.20.1.255` |
| **LSI**      |  40   |            41            |    `/26` (62)     | `172.20.2.0/26`   | `255.255.255.192` | `172.20.2.1`   | `172.20.2.2` – `172.20.2.62`           | `172.20.2.63`  |
| **LIAD**     |  36   |            37            |    `/26` (62)     | `172.20.2.64/26`  | `255.255.255.192` | `172.20.2.65`  | `172.20.2.66` – `172.20.2.126`         | `172.20.2.127` |
| **Cameras**  |  21   |       21 (sem GW)        |    `/27` (30)     | `172.20.2.128/27` | `255.255.255.224` | **Nenhum**     | `172.20.2.129` – `172.20.2.158` (Fixo) | `172.20.2.159` |
| **Gerencia** |   6   |        7 (6 + GW)        |    `/28` (14)     | `172.20.2.160/28` | `255.255.255.240` | `172.20.2.161` | `172.20.2.162` – `172.20.2.174` (Fixo) | `172.20.2.175` |

- **Regra de Isolamento de Câmeras:** A VLAN `Cameras` **não possui gateway** no switch que roteia, garantindo o isolamento exigido pelo STI (câmeras conversam apenas com o NVR).
- **IPs de Gerência dos Switches:**
    - **SW-LACINA (Roteador L3 / Gateway):** `172.20.2.161`
    - **SW-LSD:** `172.20.2.162`
    - **SW-LSI:** `172.20.2.163`
    - **SW-LIAD:** `172.20.2.164`
    - **Estação ADM:** `172.20.2.165`

---
### 2. Definição das VLANs (Nomes e IDs)

De acordo com as normas da EXOS e do STI, utilizam-se nomes sem espaços/acentos e IDs múltiplos de 10 (evitando IDs 1 e 4095):

| Nome da VLAN | ID (Tag) | Finalidade                                                   |
| :----------- | :------: | :----------------------------------------------------------- |
| `LSD`        |   `10`   | Computadores do laboratório LSD                              |
| `LACINA`     |   `20`   | Computadores do laboratório LACINA                           |
| `LSI`        |   `30`   | Computadores do laboratório LSI                              |
| `LIAD`       |   `40`   | Computadores do LIAD (inclui o PC na sala emprestada no LSI) |
| `WiFi`       |   `50`   | Tráfego dos clientes wireless via APs                        |
| `Cameras`    |   `60`   | Câmeras de segurança e gravador NVR                          |
| `Gerencia`   |   `70`   | Gerenciamento dos switches e estação ADM                     |

---
### 3. Topologia e Escolha do Switch Roteador (L3)

1. **Switch Roteador:** O **`SW-LACINA`** (ou `SW-LSD`) é definido como o switch central de roteamento Camada 3 (`enable ipforwarding`), onde são configuradas as interfaces de Gateway IP para todas as VLANs de usuários e gerência.
2. **Topologia em Estrela (Centralizada no SW-LACINA):**
    - `SW-LACINA` \(\longleftrightarrow\) `SW-LSD` (Tronco 802.1Q)
    - `SW-LACINA` \(\longleftrightarrow\) `SW-LSI` (Tronco 802.1Q)
    - `SW-LACINA` \(\longleftrightarrow\) `SW-LIAD` (Tronco 802.1Q)
3. **Mapeamento do Tráfego nos Enlaces Tronco (`tagged`):**
    - **Tronco LACINA–LSI:** Transporta VLANs `LSI`, `LIAD` (para a sala emprestada), `Gerencia` e `WiFi`.
    - **Tronco LACINA–LIAD:** Transporta VLANs `LIAD`, `WiFi`, `Cameras` e `Gerencia`.
    - **Tronco LACINA–LSD:** Transporta VLANs `LSD`, `Cameras` (para o NVR) e `Gerencia`.

---
# **Etapa 2 (Implantação em Bancada)** 
Consiste no ligamento físico dos enlaces no GNS3 e na aplicação das configurações EXOS CLI em cada um dos quatro switches.

---

### 1. Mapeamento de Portas e Topologia de Enlaces

Para manter a organização e facilitar os testes de aceite, adotamos o seguinte mapa de portas padronizado:

|Equipamento / Nó|Switch de Destino|Porta no Switch|VLAN Pertencente|Tipo de Porta|
|:--|:--|:-:|:--|:--|
|**PC-LACINA**|`SW-LACINA`|`1`|`LACINA` (ID 20)|Untagged (Access)|
|**WIFI-1**|`SW-LACINA`|`2`|`WiFi` (ID 50)|Untagged (Access)|
|**ADM**|`SW-LACINA`|`3`|`Gerencia` (ID 70)|Untagged (Access)|
|**PC-LSD**|`SW-LSD`|`1`|`LSD` (ID 10)|Untagged (Access)|
|**NVR**|`SW-LSD`|`2`|`Cameras` (ID 60)|Untagged (Access)|
|**PC-LSI**|`SW-LSI`|`1`|`LSI` (ID 30)|Untagged (Access)|
|**PC-LIAD-SALA**|`SW-LSI`|`2`|`LIAD` (ID 40)|Untagged (Access)|
|**PC-LIAD**|`SW-LIAD`|`1`|`LIAD` (ID 40)|Untagged (Access)|
|**WIFI-2**|`SW-LIAD`|`2`|`WiFi` (ID 50)|Untagged (Access)|
|**CAM**|`SW-LIAD`|`3`|`Cameras` (ID 60)|Untagged (Access)|

#### Enlaces Tronco (_Trunks_ 802.1Q) Inter-Switches:

- **`SW-LACINA` (Porta 22) \(\longleftrightarrow\) `SW-LSD` (Porta 22)**
- **`SW-LACINA` (Porta 23) \(\longleftrightarrow\) `SW-LSI` (Porta 23)**
- **`SW-LACINA` (Porta 24) \(\longleftrightarrow\) `SW-LIAD` (Porta 24)**

---

### 2. Comandos de Configuração no EXOS

#### 🟢 2.1. Switch Roteador L3 (`SW-LACINA`)

_Este switch faz o roteamento entre as VLANs, atua como servidor DHCP e é o Gateway da rede._

```
disable clipaging

# 1. Criação das VLANs
create vlan LSD tag 10
create vlan LACINA tag 20
create vlan LSI tag 30
create vlan LIAD tag 40
create vlan WiFi tag 50
create vlan Cameras tag 60
create vlan Gerencia tag 70

# 2. Remoção das portas da VLAN Default
configure vlan Default delete ports 1-3,22-24

# 3. Associação das portas de acesso (Untagged)
configure vlan LACINA add ports 1 untagged
configure vlan WiFi add ports 2 untagged
configure vlan Gerencia add ports 3 untagged

# 4. Configuração dos Troncos (Tagged)
configure vlan LSD add ports 22-24 tagged
configure vlan LACINA add ports 22-24 tagged
configure vlan LSI add ports 22-24 tagged
configure vlan LIAD add ports 22-24 tagged
configure vlan WiFi add ports 22-24 tagged
configure vlan Cameras add ports 22-24 tagged
configure vlan Gerencia add ports 22-24 tagged

# 5. Configuração dos Gateways (SVIs) e Roteamento
configure vlan LACINA ipaddress 172.20.1.1/25
enable ipforwarding vlan LACINA

configure vlan LSD ipaddress 172.20.1.129/25
enable ipforwarding vlan LSD

configure vlan LSI ipaddress 172.20.2.1/26
enable ipforwarding vlan LSI

configure vlan LIAD ipaddress 172.20.2.65/26
enable ipforwarding vlan LIAD

configure vlan WiFi ipaddress 172.20.0.1/24
enable ipforwarding vlan WiFi

configure vlan Gerencia ipaddress 172.20.2.161/28
enable ipforwarding vlan Gerencia

# NOTA: A VLAN Cameras NÃO possui IP nem ipforwarding (Isolamento L2)

# 6. Configuração do Servidor DHCP (Escopos e Portas de Atendimento)
configure vlan LACINA dhcp-address-range 172.20.1.2 - 172.20.1.126
configure vlan LACINA dhcp-options default-gateway 172.20.1.1
enable dhcp ports 1,22-24 vlan LACINA

configure vlan LSD dhcp-address-range 172.20.1.130 - 172.20.1.254
configure vlan LSD dhcp-options default-gateway 172.20.1.129
enable dhcp ports 22-24 vlan LSD

configure vlan LSI dhcp-address-range 172.20.2.2 - 172.20.2.62
configure vlan LSI dhcp-options default-gateway 172.20.2.1
enable dhcp ports 22-24 vlan LSI

configure vlan LIAD dhcp-address-range 172.20.2.66 - 172.20.2.126
configure vlan LIAD dhcp-options default-gateway 172.20.2.65
enable dhcp ports 22-24 vlan LIAD

configure vlan WiFi dhcp-address-range 172.20.0.2 - 172.20.0.254
configure vlan WiFi dhcp-options default-gateway 172.20.0.1
enable dhcp ports 2,22-24 vlan WiFi

save configuration
```

---

#### 🔵 2.2. Switch `SW-LSD`

```
disable clipaging

create vlan LSD tag 10
create vlan LACINA tag 20
create vlan LSI tag 30
create vlan LIAD tag 40
create vlan WiFi tag 50
create vlan Cameras tag 60
create vlan Gerencia tag 70

configure vlan Default delete ports 1,2,22

configure vlan LSD add ports 1 untagged
configure vlan Cameras add ports 2 untagged

configure vlan LSD add ports 22 tagged
configure vlan LACINA add ports 22 tagged
configure vlan LSI add ports 22 tagged
configure vlan LIAD add ports 22 tagged
configure vlan WiFi add ports 22 tagged
configure vlan Cameras add ports 22 tagged
configure vlan Gerencia add ports 22 tagged

# IP de Gerência e Rota Padrão apontando para o SW-LACINA
configure vlan Gerencia ipaddress 172.20.2.162/28
configure iproute add default 172.20.2.161

save configuration
```

---

#### 🟡 2.3. Switch `SW-LSI`

````
disable clipaging

create vlan LSD tag 10
create vlan LACINA tag 20
create vlan LSI tag 30
create vlan LIAD tag 40
create vlan WiFi tag 50
create vlan Cameras tag 60
create vlan Gerencia tag 70

configure vlan Default delete ports 1,2,23

configure vlan LSI add ports 1 untagged
configure vlan LIAD add ports 2 untagged

configure vlan LSD add ports 23 tagged
configure vlan LACINA add ports 23 tagged
configure vlan LSI add ports 23 tagged
configure vlan LIAD add ports 23 tagged
configure vlan WiFi add ports 23 tagged
configure vlan Cameras add ports 23 tagged
configure vlan Gerencia add ports 23 tagged

# IP de Gerência e Rota Padrão apontando para o SW-LACINA
configure vlan Gerencia ipaddress 172.2Aqui estão os comandos para concluir a **Etapa 2**:

---

#### 🟡 2.3. Switch `SW-LSI`
```exos
disable clipaging

create vlan LSD tag 10
create vlan LACINA tag 20
create vlan LSI tag 30
create vlan LIAD tag 40
create vlan WiFi tag 50
create vlan Cameras tag 60
create vlan Gerencia tag 70

configure vlan Default delete ports 1,2,23

configure vlan LSI add ports 1 untagged
configure vlan LIAD add ports 2 untagged

configure vlan LSD add ports 23 tagged
configure vlan LACINA add ports 23 tagged
configure vlan LSI add ports 23 tagged
configure vlan LIAD add ports 23 tagged
configure vlan WiFi add ports 23 tagged
configure vlan Cameras add ports 23 tagged
configure vlan Gerencia add ports 23 tagged

# IP de Gerência e Rota Padrão apontando para o SW-LACINA
configure vlan Gerencia ipaddress 172.20.2.163/28
configure iproute add default 172.20.2.161

save configuration
````

---

#### 🔴 2.4. Switch `SW-LIAD`

````
disable clipaging

create vlan LSD tag 10
create vlan LACINA tag 20
create vlan LSI tag 30
create vlan LIAD tag 40
create vlan WiFi tag 50
create vlan Cameras tag 60
create vlan Gerencia tag 70

configure vlan Default delete ports 1-3,24

configure vlan LIAD add ports 1 untagged
configure vlan WiFi add ports 2 untagged
configure vlan Cameras add ports 3 untagged

configure vlan LSD add ports 24 tagged
configure vlan LACINA add ports 24 tagged
configure vlan LSI add ports 24 tagged
configure vlan LIAD add ports 24 tagged
configure vlan WiFi add ports 24 tagged
configure vlan Cameras add ports 24 tagged
configure vlan Gerencia add ports 24 tagged

# IP de Gerência e Rota Padrão apontando para o SW-LACINA
configure vlan Gerencia ipaddress 1Para evitar erros de repetição no console, aqui estão as configurações finais compactadas para o **SW-LIAD** e para as estações fixas (VPCS):

---

### 🟢 2.4. Configuração do `SW-LIAD`

```exos
disable clipaging
create vlan LSD tag 10
create vlan LACINA tag 20
create vlan LSI tag 30
create vlan LIAD tag 40
create vlan WiFi tag 50
create vlan Cameras tag 60
create vlan Gerencia tag 70

configure vlan Default delete ports 1-3,24

configure vlan LIAD add ports 1 untagged
configure vlan WiFi add ports 2 untagged
configure vlan Cameras add ports 3 untagged

# Adiciona as VLANs na porta de tronco 24
configure vlan LSD add ports 24 tagged
configure vlan LACINA add ports 24 tagged
configure vlan LSI add ports 24 tagged
configure vlan LIAD add ports 24 tagged
configure vlan WiFi add ports 24 tagged
configure vlan Cameras add ports 24 tagged
configure vlan Gerencia add ports 24 tagged

# Gerência e Rota Padrão
configure vlan Gerencia ipaddress 172.20.2.164/28
configure iproute add default 172.20.2.161
save configuration
````

---

### 💻 3. Configuração dos Hosts com IP Fixo (VPCS)

No console de cada um dos hosts fixos no GNS3, execute:

1. **Estação ADM (Conectada no SW-LACINA, porta 3):**
    
    ```
    ip 172.20.2.165/28 172.20.2.161
    save
    ```
    
2. **Gravador NVR (Conectado no SW-LSD, porta 2):** _(Sem gateway configurado para manter o isolamento de câmeras)_
    
    ```
    ip 172.20.2.129/27
    save
    ```
    
3. **Câmera CAM (Conectada no SW-LIAD, porta 3):** _(Sem gateway configurado)_
    
    ```
    ip 172.20.2.130/27
    save
    ```
    

---

### 💻 4. Configuração dos Hosts Dinâmicos (DHCP)

Nos demais PCs do GNS3 (`PC-LSD`, `PC-LACINA`, `PC-LSI`, `PC-LIAD-SALA`, `PC-LIAD`, `WIFI-1`, `WIFI-2`), execute apenas:

```
ip dhcp
save
```

---
# **Etapa 3 (Testes de Aceite)**
É a fase que comprova que a rede projetada e configurada no GNS3 atende rigorosamente a todos os requisitos operacionais e de segurança exigidos pelo STI da UFCG.

Abaixo está o roteiro passo a passo com os comandos que você deve executar no console dos **VPCS** no GNS3, os resultados esperados para cada um dos **6 testes obrigatórios** e a justificativa técnica.

---

### 🧪 Roteiro de Execução dos Testes de Aceite

#### 1️⃣ Teste 1: Solicitação de Endereço IP via DHCP

No console de cada PC de laboratório e cliente Wi-Fi, execute o comando de solicitação dinâmica:

- **Comando:** `ip dhcp` (em `PC-LSD`, `PC-LACINA`, `PC-LSI`, `PC-LIAD`, `PC-LIAD-SALA`, `WIFI-1`, `WIFI-2`).
- **Resultado Esperado:** Cada PC deve obter um IP válido de sua respectiva faixa de sub-rede, com a máscara e o gateway corretos:
    - **PC-LACINA:** ex. `172.20.1.2/25` | GW: `172.20.1.1`
    - **PC-LSD:** ex. `172.20.1.130/25` | GW: `172.20.1.129`
    - **PC-LSI:** ex. `172.20.2.2/26` | GW: `172.20.2.1`
    - **PC-LIAD** e **PC-LIAD-SALA:** ex. `172.20.2.66/26` e `172.20.2.67/26` | GW: `172.20.2.65`
    - **WIFI-1** e **WIFI-2:** ex. `172.20.0.2/24` e `172.20.0.3/24` | GW: `172.20.0.1`

---

#### 2️⃣ Teste 2: Teste de Conectividade com o Gateway

Cada computador deve conseguir alcançar a interface Layer 3 (Gateway) configurada no switch roteador (`SW-LACINA`).

- **Comandos nos VPCS:**
    - No **`PC-LSD`**: `ping 172.20.1.129`
    - No **`PC-LACINA`**: `ping 172.20.1.1`
    - No **`PC-LSI`**: `ping 172.20.2.1`
    - No **`PC-LIAD`**: `ping 172.20.2.65`
    - No **`PC-LIAD-SALA`** _(no SW-LSI)_: `ping 172.20.2.65`
- **Resultado Esperado:** **Sucesso** (respostas com `84 bytes from <gateway_ip>: icmp_seq=1 ttl=64`).
- **Validação Importante:** Confirma que o `PC-LIAD-SALA` (ligado fisicamente ao `SW-LSI`) alcança o gateway do LIAD via tronco 802.1Q.

---

#### 3️⃣ Teste 3: Roteamento Inter-VLAN entre Laboratórios

Testa a capacidade do `SW-LACINA` de rotear tráfego IP entre sub-redes distintas.

- **Comandos no VPCS `PC-LACINA` (`172.20.1.2`):**
    - Ping para o LSD: `ping 172.20.1.130`
    - Ping para o LSI: `ping 172.20.2.2`
    - Ping para o LIAD: `ping 172.20.2.66`
- **Resultado Esperado:** **Sucesso** em todos os pings.

---

#### 4️⃣ Teste 4: Conectividade Interna das Câmeras (CAM \(\rightarrow\) NVR)

A câmera de segurança instalada no `SW-LIAD` deve conseguir gravar dados no NVR instalado no `SW-LSD`.

- **Comando no VPCS `CAM` (`172.20.2.130`):**
    - `ping 172.20.2.129` (IP do NVR)
- **Resultado Esperado:** **Sucesso**.
- **Justificativa:** A comunicação ocorre em Camada 2 (VLAN 60 `Cameras` com tag 60 nos troncos), sem necessidade de passar por roteamento L3.

---

#### 5️⃣ Teste 5: Isolamento de Segurança da Rede de Câmeras

Nenhum computador de laboratório ou estação de trabalho pode conseguir se comunicar com as câmeras ou NVR.

- **Comando no VPCS `PC-LACINA`:**
    - `ping 172.20.2.130` (IP da CAM) ou `ping 172.20.2.129` (IP do NVR)
- **Resultado Esperado:** **NÃO responde** (_host unreachable_ ou _timeout_).
- **Justificativa:** A VLAN 60 `Cameras` não possui IP nem `enable ipforwarding` no switch roteador, garantindo o isolamento L2/L3 exigido pelo contrato de segurança.

---

#### 6️⃣ Teste 6: Teste de Flexibilidade e Transporte do Tronco

Muda-se temporariamente o IP do `PC-LACINA` para a faixa do LSD para provar a **soberania da Camada 2**: alterar manualmente o IP da placa de rede **não burla** o isolamento imposto pela VLAN.

- **Passo 1 (no VPCS `PC-LACINA`):** Configure um IP fixo da faixa do LSD e o gateway do LSD:
    
    ```
    ip 172.20.1.250/25 172.20.1.129
    ```
    
- **Passo 2:** Pingar o gateway do LSD:
    
    ```
    ping 172.20.1.129
    ```
    
- **Resultado Esperado:** **FALHA** (`host not reachable` ou `timeout`).
- **Justificativa:** O `PC-LACINA` está fisicamente na porta 1 do `SW-LACINA`, associada como `untagged` à VLAN `LACINA` (ID 20). O IP `172.20.1.250/25` pertence à sub-rede do LSD, mas o gateway `172.20.1.129` é a SVI da VLAN `LSD` (ID 10). O ARP do PC é enviado na VLAN 20, onde esse endereço não existe, e o roteador não possui proxy ARP dinâmico. Além disso, mesmo que o ARP fosse respondido, a resposta do `SW-LACINA` para `172.20.1.250` sairia pela rota conectada `172.20.1.128/25` em direção à VLAN 10, nunca retornando ao PC. Para que o ping funcionasse, seria necessário mover a porta 1 para a VLAN `LSD` (`configure vlan LACINA delete ports 1` e `configure vlan LSD add ports 1 untagged`).
- **Passo 3 (Restauração):** Retorne o PC ao DHCP normal:
    
    ```
    ip dhcp
    ```
    

---

### 📋 Diagnósticos Úteis no Console EXOS se Algum Teste Falhar:

Se algum teste não responder, execute os comandos de verificação nos switches:

- `show vlan` (verifica se as VLANs estão ativas e com as portas corretas `tagged`/`untagged`).
- `show ipconfig` (confirma os IPs dos gateways no `SW-LACINA`).
- `show iproute` (confirma a tabela de rotas diretamente conectadas).
- `show fdb` (verifica se os switches aprenderam os endereços MAC nas portas).

---
# **Etapa 4 (Pedidos de Mudança)**
Simula o dia a dia de sustentação de rede do STI da UFCG, onde chamados operacionais chegam após a entrada da rede em produção.

Os três pedidos devem ser executados na ordem sequencial exata abaixo.

---

### 🟡 Chamado 1: O LACINA ganha uma sala no LIAD

O LIAD cedeu uma sala ao LACINA. É necessário adicionar uma nova estação de trabalho pertencente à rede do LACINA, mas conectada fisicamente ao switch do LIAD (`SW-LIAD`).

#### 1. Procedimento no GNS3:

1. Adicione um novo nó **VPCS** e altere o nome para **`PC-LACINA-SALA`**.
2. Conecte o `PC-LACINA-SALA` à **Porta 4** do **`SW-LIAD`**.

#### 2. Configuração no `SW-LIAD` (Console EXOS):

Adicione a porta 4 à VLAN `LACINA` (ID 20) como `untagged` (modo de acesso):

```
disable clipaging
configure vlan Default delete ports 4
configure vlan LACINA add ports 4 untagged
save configuration
```

_(Nota: A VLAN `LACINA` já faz parte do tronco na porta 24 para o `SW-LACINA`, permitindo o tráfego)._

#### 3. Configuração e Teste no VPCS `PC-LACINA-SALA`:

No console do `PC-LACINA-SALA`:

```
ip dhcp
save
```

- **Resultado Esperado:** O PC obtém um endereço IP da faixa do LACINA (`172.20.1.X/25`) com Gateway `172.20.1.1`.
- **Teste de Validação:** `ping 172.20.1.2` (pinga o `PC-LACINA` original com sucesso).

---

### 🚨 Chamado 2: Uma obra rompeu um cabo de tronco

A Prefeitura Universitária informa que uma obra no duto rompeu o cabo de tronco que transportava a maior quantidade de VLANs ativas.

#### 1. Identificação do Enlace Rompido:

Comparando os troncos a partir do switch roteador (`SW-LACINA`):

- `SW-LACINA` \(\longleftrightarrow\) `SW-LSD`: carrega `LSD`, `Cameras`, `Gerencia`.
- `SW-LACINA` \(\longleftrightarrow\) `SW-LSI`: carrega `LSI`, `LIAD`, `Gerencia`, `WiFi`.
- **`SW-LACINA` \(\longleftrightarrow\) `SW-LIAD`**: carrega **`LIAD`**, **`WiFi`**, **`Cameras`**, **`Gerencia`** e a nova **`LACINA`** (5 VLANs ativas).

O cabo rompido é o enlace entre a **Porta 24 do `SW-LACINA`** e a **Porta 24 do `SW-LIAD`**.

#### 2. Ação no GNS3:

- Clique com o botão direito no cabo entre `SW-LACINA` e `SW-LIAD` e selecione **Suspend**.
- _(Regra do STI: Nenhum novo cabo pode passar no duto entre LACINA e LIAD)._

#### 3. Solução de Redundância/Desvio de Rota:

Para restabelecer a conectividade do `SW-LIAD` sem usar o duto danificado, cria-se um **novo tronco** entre o **`SW-LIAD`** e o **`SW-LSI`**. O tráfego do LIAD passará pelo LSI para alcançar o switch roteador.

1. No GNS3, passe um novo cabo ligando a **Porta 22 do `SW-LIAD`** à **Porta 22 do `SW-LSI`**.
2. **Configuração no `SW-LIAD` (Console EXOS):**
    
    ```
    disable clipaging
    configure vlan Default delete ports 22
    configure vlan LSD add ports 22 tagged
    configure vlan LACINA add ports 22 tagged
    configure vlan LSI add ports 22 tagged
    configure vlan LIAD add ports 22 tagged
    configure vlan WiFi add ports 22 tagged
    configure vlan Cameras add ports 22 tagged
    configure vlan Gerencia add ports 22 tagged
    save configuration
    ```
    
3. **Configuração no `SW-LSI` (Console EXOS):**
    
    ```
    disable clipaging
    configure vlan Default delete ports 22
    configure vlan LSD add ports 22 tagged
    configure vlan LACINA add ports 22 tagged
    configure vlan LSI add ports 22 tagged
    configure vlan LIAD add ports 22 tagged
    configure vlan WiFi add ports 22 tagged
    configure vlan Cameras add ports 22 tagged
    configure vlan Gerencia add ports 22 tagged
    save configuration
    ```
    

#### 4. Validação do Desvio:

- No `PC-LIAD`, execute `ip dhcp` e `ping 172.20.2.65`.
- Na `CAM` (ligada ao `SW-LIAD`), pingue o `NVR` (`ping 172.20.2.129` no `SW-LSD`).
- **Resultado:** Todos os testes de aceite voltam a passar normalmente contornando pelo `SW-LSI`.

---

### 🟢 Chamado 3: O LIAD devolve a sala ao LSI

O LIAD devolveu a sala emprestada no LSI. O computador que ficava nessa sala passa a integrar a rede do LSI.

#### 1. Procedimento no GNS3:

1. Clique com o botão direito no `PC-LIAD-SALA` (conectado à porta 2 do `SW-LSI`) e altere o hostname para **`PC-LSI-SALA`**.

#### 2. Reconfiguração da Porta no `SW-LSI`:

Mude a porta 2 da VLAN `LIAD` para a VLAN `LSI`:

```
disable clipaging
configure vlan LIAD delete ports 2
configure vlan LSI add ports 2 untagged
save configuration
```

#### 3. Limpeza de VLANs Inúteis no `SW-LSI`:

Como o `SW-LSI` não possui mais nenhum equipamento da VLAN `LIAD`, remova a VLAN `LIAD` do `SW-LSI` para seguir as boas práticas de otimização do STI:

```
configure vlan LIAD delete ports 22,23
delete vlan LIAD
save configuration
```

#### 4. Configuração e Teste no VPCS `PC-LSI-SALA`:

No console do `PC-LSI-SALA`:

```
ip dhcp
save
```

- **Resultado Esperado:** O computador obtém um IP da faixa do LSI (`172.20.2.X/26`) com Gateway `172.20.2.1`.
- **Teste de Validação:** `ping 172.20.2.2` (pinga o `PC-LSI` original).

---

### 📊 Resumo do Estado Final da Rede

Após os 3 pedidos de mudança:

1. **`PC-LACINA-SALA`**: Obtém IP no bloco `172.20.1.0/25` via `SW-LIAD`.
2. **`PC-LSI-SALA`**: Obtém IP no bloco `172.20.2.0/26` via `SW-LSI`.
3. **Tronco Rompido**: Cabo entre `SW-LACINA` e `SW-LIAD` permanece **suspenso**.
4. **Novo Tronco Ativo**: Comunicação do `SW-LIAD` é mantida via tronco `SW-LIAD` \(\longleftrightarrow\) `SW-LSI` \(\longleftrightarrow\) `SW-LACINA`.

---

