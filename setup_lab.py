import json
import time
from gns3fy import Gns3Connector, Project

# 1. Conectar ao servidor GNS3
# Troque por http://<IP_DO_SERVIDOR>:3080 se estiver rodando em outra máquina
server_url = "http://localhost:3080" 
server = Gns3Connector(url=server_url)

# 2. Definir o nome do projeto carregado
# IMPORTANTE: Este nome deve ser exatamente o nome do projeto que aparece na 
# interface do GNS3 após você importar o arquivo da pasta /base_topology/
nome_do_projeto = "uasc" 

print(f"Tentando conectar ao servidor {server_url} e carregar o projeto '{nome_do_projeto}'...")

try:
    lab = Project(name=nome_do_projeto, connector=server)
    lab.get()
    print(f"Sucesso: Projeto '{lab.name}' (ID: {lab.project_id}) localizado!")
except Exception as e:
    print(f"\nERRO: O projeto '{nome_do_projeto}' não foi encontrado no GNS3.")
    print("Passo de verificação: Você já importou o arquivo .gns3project da pasta base_topology na interface gráfica (File > Import Portable Project)?")
    exit(1)

# 3. Abrir o projeto e iniciar os nós
if lab.status != "opened":
    print("Abrindo o projeto no GNS3...")
    lab.open()

print("Iniciando todos os roteadores e switches...")
lab.start_nodes()

# Pausa breve para garantir que as portas Telnet estejam ativas
time.sleep(3)

# 4. Mapear as portas de console para a automação (Netmiko)
inventario = {}
print("\n--- Mapeamento de Portas de Console (Telnet) ---")

# Atualiza os dados dos nós a partir do servidor
lab.get()

for node in lab.nodes:
    nome = node.name
    porta = node.console
    status = node.status
    
    # Registra apenas nós que possuem porta de console mapeada
    if porta:
        inventario[nome] = {
            "device_type": "cisco_ios_telnet", # Ajuste conforme o SO real (ex: extreme_exos)
            "host": "127.0.0.1",               # IP do servidor GNS3
            "port": porta,
            "status": status
        }
        print(f"Equipamento: {nome:15} | Status: {status:7} | Console: {porta}")

# 5. Salvar o inventário para os scripts da pasta /config/ usarem
caminho_inventario = "inventario_gns3.json"
with open(caminho_inventario, "w") as f:
    json.dump(inventario, f, indent=4)

print(f"\nPronto! Inventário salvo em '{caminho_inventario}'.")
print("Os scripts de configuração (Netmiko) agora podem ler este arquivo para se conectar aos equipamentos.")