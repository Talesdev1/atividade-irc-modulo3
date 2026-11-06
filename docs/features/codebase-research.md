# Codebase Research: Módulo 3 (GNS3 / EXOS / STI-UFCG)

Snapshot date: 2026-11-05. Scope: every file in the repository outside `.git/` and `.venv/`, plus the installed runtime environment in `.venv/`. The repository has no commits (`git status` reports "No branch master" and "Ainda não há commits"), so all findings come from the working tree rather than Git history.

## High-Level Summary

The repository currently contains one Python script (`setup_lab.py`), one portable GNS3 project (`base_topology/uasc.gns3project`), and a documentation set under `docs/`. `setup_lab.py` uses `gns3fy` to connect to a local GNS3 server, locate the project named `uasc`, open/start it, and export each node's Telnet console port to `inventario_gns3.json`. The portable project is a ZIP archive whose `project.gns3` defines 14 nodes (4 QEMU EXOS switches and 10 VPCS hosts), 8 drawings, and zero links. The documentation defines the VLSM plan, VLANs, EXOS CLI configuration, acceptance tests, change tickets, implementation milestones, and five ADRs, but there are no `/config/`, template, test, or dependency-manifest files in the tree. The installed virtual environment has `gns3fy 0.8.0` and its application dependencies; `netmiko`, `jinja2`, and `python-dotenv` referenced by the docs are not installed.

## 1. Repository Inventory and State

### 1.1 Files present

| Path | Size | Lines | Role |
|:--|--:|--:|:--|
| `AGENTS.md` | 3,990 B | 49 | Project operating rules, addressing, VLANs, CLI, security |
| `setup_lab.py` | 2,366 B | 65 | Only Python entrypoint; GNS3 project lookup, startup, inventory export |
| `base_topology/uasc.gns3project` | 2,780 B | ZIP | Portable GNS3 project archive |
| `docs/docs.md` | 23,363 B | 639 | Full lab script: VLSM, topology, EXOS commands, tests, change tickets |
| `docs/features/proposal.md` | 3,734 B | 47 | Technical proposal and implementation phases |
| `docs/features/plan.md` | 5,123 B | 64 | Five milestones, all task checkboxes unchecked |
| `docs/adr/adr-001.md` | 879 B | 14 | ADR: Python + `gns3fy` |
| `docs/adr/adr-002.md` | 913 B | 14 | ADR: Netmiko + Jinja2 |
| `docs/adr/adr-003.md` | 878 B | 14 | ADR: Read-Before-Write idempotency |
| `docs/adr/adr-004.md` | 962 B | 16 | ADR: Accept tests via VPCS output parsing |
| `docs/adr/adr-005.md` | 755 B | 12 | ADR: credentials via `python-dotenv` |
| `.gitignore` | 118 B | 5 | Ignores GNS3 heavy files and `*.vmdk` |

### 1.2 Git state

- `git status` reports no commits and lists `.gitignore`, `AGENTS.md`, `base_topology/`, `docs/`, and `setup_lab.py` as untracked.
- `.venv/` does not appear in `git status` because `.venv/.gitignore` contains `*` (`.venv/.gitignore:2`).
- No branch named `master` exists; `git log` exits with code 128.
- This research document itself is `docs/features/codebase-research.md`; it was created during this research and is not part of the pre-existing source set.

### 1.3 Paths referenced by the documentation but not present in the tree

The following paths are mentioned in the docs or `AGENTS.md` and are absent from the working tree:

| Referenced path | Reference | Current tree |
|:--|:--|:--|
| `/config/` | `AGENTS.md:8`, `AGENTS.md:9`, `setup_lab.py:59`, `setup_lab.py:65` | Not present |
| `inventario_gns3.json` | `setup_lab.py:60-62` | Not present (created at runtime) |
| `.env` | `docs/adr/adr-005.md:7` | Not present |
| `.env.example` | `docs/adr/adr-005.md:13` | Not present |
| `/base_topology/projeto_inicial.gns3project` | `AGENTS.md:7` | Actual archive is `base_topology/uasc.gns3project` |
| `infra/create_project.py` | `docs/features/plan.md:23` | Not present |
| `config/configure_switches.py` | `docs/features/plan.md:31` | Not present |
| Jinja2 templates | `docs/features/plan.md:30`, `docs/adr/adr-002.md:9` | Not present |
| Acceptance-test scripts | `docs/features/plan.md:35-41` | Not present |
| Change-ticket scripts | `docs/features/plan.md:43-47` | Not present |

There is no `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile`, `README`, CI configuration, shell script, or test directory in the tree.

## 2. Entrypoint: `setup_lab.py`

`setup_lab.py` is the only Python file. It has no shebang, no command-line arguments, no `if __name__ == "__main__"` guard, and no function definitions; it executes top-level statements sequentially. Run as `python setup_lab.py`, it writes its output relative to the current working directory.

### 2.1 Connection and project selection

```python
import json
import time
from gns3fy import Gns3Connector, Project

server_url = "http://localhost:3080"
server = Gns3Connector(url=server_url)

nome_do_projeto = "uasc"

try:
    lab = Project(name=nome_do_projeto, connector=server)
    lab.get()
except Exception as e:
    print(...)
    exit(1)
```

References: `setup_lab.py:1-3`, `setup_lab.py:7-8`, `setup_lab.py:13`, `setup_lab.py:17-24`.

Behavior in `gns3fy 0.8.0`:

- `Gns3Connector(url="http://localhost:3080")` stores `base_url = "http://localhost:3080/v2"` (`.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:67-76`).
- `Project.get()` with `name` and no `project_id` performs `GET /v2/projects`, iterates the returned projects and assigns the `project_id` of every project whose `name` equals `"uasc"`, then performs `GET /v2/projects/{project_id}` (`.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:1190-1242`).
- `Project.get()` also retrieves stats, nodes, and links by default (`get_stats=True`, `get_nodes=True`, `get_links=True`) (`.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:1236-1242`).
- If the project is not found, `project_id` remains `None`; the subsequent request fails and the script prints the guidance message and exits with status 1 (`setup_lab.py:21-24`).

### 2.2 Open and start sequence

```python
if lab.status != "opened":
    lab.open()

lab.start_nodes()
time.sleep(3)
```

References: `setup_lab.py:27-35`.

Behavior in `gns3fy 0.8.0`:

- `Project.open()` performs `POST /v2/projects/{project_id}/open` (`.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:1333-1346`).
- `Project.start_nodes()` performs `POST /v2/projects/{project_id}/nodes/start`, sleeps for `poll_wait_time` (default 5 seconds), then refreshes nodes via `get_nodes()` (`.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:1454-1473`).
- The script adds another unconditional 3-second pause after `start_nodes()` (`setup_lab.py:34-35`).

### 2.3 Console-port inventory generation

After refreshing the project with `lab.get()` (`setup_lab.py:42`), the script iterates over `lab.nodes` and includes every node whose `console` value is truthy:

```python
for node in lab.nodes:
    nome = node.name
    porta = node.console
    status = node.status

    if porta:
        inventario[nome] = {
            "device_type": "cisco_ios_telnet",
            "host": "127.0.0.1",
            "port": porta,
            "status": status
        }
```

References: `setup_lab.py:44-57`.

Observed values written to the inventory:

- `device_type` is the literal `"cisco_ios_telnet"` for every node, both QEMU EXOS switches and VPCS hosts (`setup_lab.py:52`). The inline comment says `# Ajuste conforme o SO real (ex: extreme_exos)`.
- `host` is the literal `"127.0.0.1"` (`setup_lab.py:53`).
- `port` is the API-reported `node.console` (`setup_lab.py:54`).
- `status` is the API-reported `node.status` (`setup_lab.py:55`).
- Keys are node names (`inventario[nome]`, `setup_lab.py:51`).

The output file is written to the relative path `inventario_gns3.json` with `json.dump(..., indent=4)` (`setup_lab.py:60-62`). The script prints the node name, status, and console port for each included node (`setup_lab.py:57`) and a final confirmation (`setup_lab.py:64-65`).

No file in the tree reads `inventario_gns3.json`; the only reference is the writer in `setup_lab.py`.

## 3. Base Topology: `base_topology/uasc.gns3project`

### 3.1 Archive structure

`base_topology/uasc.gns3project` is a ZIP archive (deflate, uncompressed size 27,516 B, archive size 2,780 B) containing:

| Entry | Size | Notes |
|:--|--:|:--|
| `project.gns3` | 27,516 B / 670 lines | GNS3 topology JSON |
| `project-files/images/` | 0 B | Empty directory entry |

The archive contains no QEMU image; the switch nodes reference `EXOS-VM_v32.6.3.126.qcow2` by filename inside `project.gns3`.

### 3.2 Project metadata

From `project.gns3` inside the archive:

| Field | Value | Line |
|:--|:--|--:|
| `name` | `uasc` | `project.gns3:7` |
| `project_id` | `8c1815f0-9ec0-4ea9-ae3e-d6724b7c1eb8` | `project.gns3:8` |
| `revision` | `9` | `project.gns3:9` |
| `version` | `2.2.61` | `project.gns3:669` |
| `type` | `topology` | `project.gns3:667` |
| `auto_close` | `true` | `project.gns3:2` |
| `auto_open` | `false` | `project.gns3:3` |
| `auto_start` | `false` | `project.gns3:4` |
| `scene_width` | `2000` | `project.gns3:11` |
| `scene_height` | `1000` | `project.gns3:10` |
| `zoom` | `100` | `project.gns3:670` |
| `supplier` | `null` | `project.gns3:16` |
| `variables` | `null` | `project.gns3:668` |

### 3.3 Nodes (14 total)

All nodes use `compute_id: "local"`, `console_type: "telnet"`, `console_auto_start: false`, and `locked: false`.

| Node | Type | Console | Node ID | `project.gns3` line |
|:--|:--|--:|:--|--:|
| `SW-LSD` | `qemu` | 5000 | `81f7c343-c2cd-469d-88ab-3101bcd00f32` | 111 |
| `PC-LSD` | `vpcs` | 5002 | `78c95f50-8b4a-45bc-91d7-0043b11a1144` | 181 |
| `NVR` | `vpcs` | 5004 | `deee729a-7b5a-4115-9b45-e54950aa0dca` | 210 |
| `SW-LACINA` | `qemu` | 5006 | `738e332f-e9c2-44e6-9ecd-bfc93ef361f2` | 239 |
| `PC-LACINA` | `vpcs` | 5008 | `71b7faf0-5392-438f-8f18-5d7815c60c9b` | 309 |
| `WIFI-1` | `vpcs` | 5010 | `d7b48dd9-20d5-46cc-b013-a927ae6dfd01` | 338 |
| `ADM` | `vpcs` | 5012 | `b42ce971-470b-4fff-a767-09a136e4fc2e` | 367 |
| `SW-LSI` | `qemu` | 5014 | `b1df5335-83ba-4b1e-a6ce-b97f15ca98f3` | 396 |
| `PC-LSI` | `vpcs` | 5016 | `72be83c5-fc53-4078-935c-352fe9852ca2` | 466 |
| `PC-LIAD-SALA` | `vpcs` | 5018 | `eaa029fe-2e59-4856-bd30-0e0a5f2142c0` | 495 |
| `SW-LIAD` | `qemu` | 5020 | `fb411b88-fd51-4f07-a8e8-be076b966ba2` | 524 |
| `PC-LIAD` | `vpcs` | 5022 | `a5213959-e392-44a0-b8ab-b16939ea4b43` | 594 |
| `WIFI-2` | `vpcs` | 5024 | `c7f25ae8-a0f7-4019-8493-5c794a4eff6a` | 623 |
| `CAM` | `vpcs` | 5026 | `d2fabd0d-7ba2-4e6a-914e-6e104eb91cc1` | 652 |

Counts: 4 `qemu` nodes (`SW-LSD`, `SW-LACINA`, `SW-LSI`, `SW-LIAD`) and 10 `vpcs` nodes. Console ports are consecutive even numbers from 5000 through 5026.

### 3.4 Switch node properties

All four QEMU switches share the same property block pattern:

| Property | Value | Example line (`SW-LSD`) |
|:--|:--|--:|
| `adapter_type` | `rtl8139` | `project.gns3:117` |
| `adapters` | `13` | `project.gns3:118` |
| `hda_disk_image` | `EXOS-VM_v32.6.3.126.qcow2` | `project.gns3:127` |
| `hda_disk_interface` | `ide` | `project.gns3:129` |
| `linked_clone` | `true` | `project.gns3:145` |
| `ram` | `1024` | `project.gns3:152` |
| `cpus` | `1` | `project.gns3:125` |
| `qemu_path` | `/bin/qemu-system-x86_64` | `project.gns3:151` |
| `options` | `-nographic -cpu host -machine accel=kvm` | `project.gns3:148` |
| `platform` | `x86_64` | `project.gns3:149` |
| `usage` | `Boot up and login is admin with no password.` | `project.gns3:156` |
| `symbol` | `:/symbols/multilayer_switch.svg` | `project.gns3:158` |
| `port_name_format` | `Port{port1}` | `project.gns3:114` |
| `first_port_name` | `Mgmt` | `project.gns3:101` |

The corresponding property blocks for `SW-LACINA`, `SW-LSI`, and `SW-LIAD` start at `project.gns3:244`, `project.gns3:401`, and `project.gns3:529` respectively.

Observed port configuration: each QEMU switch declares `adapters: 13` and `port_segment_size: 0` (`project.gns3:115-118`), while the documented port map uses access ports 1-4 and trunk ports 22-24 (`docs/docs.md:64-81`). The portable project's `links` array is empty (`project.gns3:93`).

### 3.5 Drawings and links

- `topology.links` is an empty array: `"links": []` at `project.gns3:93`. No physical links are defined in the portable project.
- `topology.drawings` contains 8 SVG drawing objects defining four labelled zones: `LSD`, `LACINA`, `LSI`, and `LIAD` (`project.gns3:19-91`).
- `topology.computes` is empty at `project.gns3:18`.

## 4. Documentation Set

### 4.1 `AGENTS.md`

`AGENTS.md` defines the project context and operating constraints:

| Section | Lines | Content summary |
|:--|--:|:--|
| Project context | 1-4 | GNS3, STI/UFCG, EXOS switches, VPCS stations |
| Workflow / initial state | 6-9 | Base topology already mounted; scripts configure existing nodes; discovery before configuration |
| VLSM addressing | 11-19 | Base block `172.20.0.0/22` with seven subnets |
| VLANs | 21-29 | IDs 10, 20, 30, 40, 50, 60, 70 and names |
| L3 topology/routing | 31-35 | `SW-LACINA` central gateway/DHCP; star trunks; redundancy; VLAN cleanup |
| EXOS CLI rules | 37-45 | `disable clipaging`, remove from `Default`, `untagged`/`tagged`, `enable ipforwarding`, `save configuration`, default route |
| Security rules | 47-49 | Camera VLAN L2 isolation; static ADM/NVR/CAM vs DHCP others |

Key values in `AGENTS.md`:

- WiFi `172.20.0.0/24`, gateway `172.20.0.1` (`AGENTS.md:13`).
- LACINA `172.20.1.0/25`, gateway `172.20.1.1` (`AGENTS.md:14`).
- LSD `172.20.1.128/25`, gateway `172.20.1.129` (`AGENTS.md:15`).
- LSI `172.20.2.0/26`, gateway `172.20.2.1` (`AGENTS.md:16`).
- LIAD `172.20.2.64/26`, gateway `172.20.2.65` (`AGENTS.md:17`).
- Cameras `172.20.2.128/27`, no gateway (`AGENTS.md:18`).
- Gerencia `172.20.2.160/28`, gateway `172.20.2.161` (`AGENTS.md:19`).
- VLAN IDs: LSD 10, LACINA 20, LSI 30, LIAD 40, WiFi 50, Cameras 60, Gerencia 70 (`AGENTS.md:23-29`).
- Cameras VLAN has no IP and no `ipforwarding` (`AGENTS.md:48`).

### 4.2 `docs/docs.md`

`docs/docs.md` is the largest document (639 lines) and is organized in four `Etapa` sections plus a final state summary.

| Section | Lines | Contents |
|:--|--:|:--|
| Etapa 1 (Projeto) | 1-54 | VLSM table, VLAN names/IDs, topology and router-switch choice |
| Etapa 2 (Implantação em Bancada) | 55-370 | Port map, trunk map, EXOS commands for all four switches, static and DHCP host commands |
| Etapa 3 (Testes de Aceite) | 372-478 | Six acceptance tests and EXOS diagnostic commands |
| Etapa 4 (Pedidos de Mudança) | 480-637 | Three sequential change tickets and final network state |
| Final state summary | 629-637 | `PC-LACINA-SALA`, `PC-LSI-SALA`, suspended LACINA-LIAD link, active LIAD-LSI-LACINA path |

#### Etapa 1 content

- VLSM table at `docs/docs.md:8-16`.
- Camera isolation note at `docs/docs.md:18`.
- Management IP assignments at `docs/docs.md:19-24`: SW-LACINA `172.20.2.161`, SW-LSD `172.20.2.162`, SW-LSI `172.20.2.163`, SW-LIAD `172.20.2.164`, ADM `172.20.2.165`.
- VLAN table at `docs/docs.md:31-39`.
- Router switch statement: `SW-LACINA` (or `SW-LSD`) at `docs/docs.md:44`.
- Star topology and trunk traffic mapping at `docs/docs.md:45-52`.

#### Etapa 2 content

Port map at `docs/docs.md:64-75`:

| Node | Switch | Port | VLAN | Mode |
|:--|:--|--:|:--|:--|
| PC-LACINA | SW-LACINA | 1 | LACINA (20) | Untagged |
| WIFI-1 | SW-LACINA | 2 | WiFi (50) | Untagged |
| ADM | SW-LACINA | 3 | Gerencia (70) | Untagged |
| PC-LSD | SW-LSD | 1 | LSD (10) | Untagged |
| NVR | SW-LSD | 2 | Cameras (60) | Untagged |
| PC-LSI | SW-LSI | 1 | LSI (30) | Untagged |
| PC-LIAD-SALA | SW-LSI | 2 | LIAD (40) | Untagged |
| PC-LIAD | SW-LIAD | 1 | LIAD (40) | Untagged |
| WIFI-2 | SW-LIAD | 2 | WiFi (50) | Untagged |
| CAM | SW-LIAD | 3 | Cameras (60) | Untagged |

Trunk map at `docs/docs.md:79-81`:

- `SW-LACINA` port 22 ↔ `SW-LSD` port 22.
- `SW-LACINA` port 23 ↔ `SW-LSI` port 23.
- `SW-LACINA` port 24 ↔ `SW-LIAD` port 24.

Switch command blocks:

- `SW-LACINA` (L3 router): `docs/docs.md:91-163`. Creates all seven VLANs, removes ports 1-3 and 22-24 from `Default`, assigns access ports, tags all VLANs on 22-24, configures SVIs and `enable ipforwarding`, configures DHCP scopes, then `save configuration`.
- `SW-LSD`: `docs/docs.md:169-198`. Creates all VLANs, access ports 1 (LSD) and 2 (Cameras), tags all VLANs on trunk 22, sets management IP `172.20.2.162/28`, default route `172.20.2.161`.
- `SW-LSI`: complete block at `docs/docs.md:233-263`; an earlier truncated duplicate starts at `docs/docs.md:204`. Access ports 1 (LSI) and 2 (LIAD), trunk 23, management IP `172.20.2.163/28`, default route `172.20.2.161`.
- `SW-LIAD`: complete block at `docs/docs.md:299-330`; an earlier truncated duplicate starts at `docs/docs.md:269`. Access ports 1 (LIAD), 2 (WiFi), 3 (Cameras), trunk 24, management IP `172.20.2.164/28`, default route `172.20.2.161`.

Observed duplicated/truncated text in `docs/docs.md`:

- `docs/docs.md:229` ends with `configure vlan Gerencia ipaddress 172.2Aqui estão os comandos para concluir a **Etapa 2**:`, truncating the `SW-LSI` block.
- `docs/docs.md:295` ends with `configure vlan Gerencia ipaddress 1Para evitar erros de repetição no console, aqui estão as configurações finais compactadas para o **SW-LIAD** e para as estações fixas (VPCS):`, truncating the `SW-LIAD` block.
- Code-fence markers around these sections alternate between three-backtick and four-backtick forms at `docs/docs.md:204`, `docs/docs.md:234`, `docs/docs.md:263`, `docs/docs.md:269`, `docs/docs.md:301`, and `docs/docs.md:330`.

Static host commands at `docs/docs.md:334-358`:

- ADM: `ip 172.20.2.165/28 172.20.2.161` (`docs/docs.md:341`).
- NVR: `ip 172.20.2.129/27` with no gateway (`docs/docs.md:348`).
- CAM: `ip 172.20.2.130/27` with no gateway (`docs/docs.md:355`).

Dynamic host commands at `docs/docs.md:362-369`: `ip dhcp` and `save` for `PC-LSD`, `PC-LACINA`, `PC-LSI`, `PC-LIAD-SALA`, `PC-LIAD`, `WIFI-1`, `WIFI-2`.

#### Etapa 3 content

Six acceptance tests:

1. DHCP address assignment at `docs/docs.md:381-391`.
2. Gateway connectivity at `docs/docs.md:395-406`.
3. Inter-VLAN routing at `docs/docs.md:410-418`.
4. CAM-to-NVR L2 connectivity at `docs/docs.md:422-429`.
5. Camera-network isolation at `docs/docs.md:433-440`.
6. Trunk flexibility with temporary IP change at `docs/docs.md:444-466`.

Diagnostic commands listed at `docs/docs.md:470-477`: `show vlan`, `show ipconfig`, `show iproute`, `show fdb`.

#### Etapa 4 content

- Chamado 1: add `PC-LACINA-SALA` on `SW-LIAD` port 4, assign VLAN LACINA (`docs/docs.md:487-519`).
- Chamado 2: suspend the `SW-LACINA` port 24 ↔ `SW-LIAD` port 24 trunk and create a contingency trunk `SW-LIAD` port 22 ↔ `SW-LSI` port 22 (`docs/docs.md:523-582`).
- Chamado 3: rename `PC-LIAD-SALA` to `PC-LSI-SALA`, move `SW-LSI` port 2 from LIAD to LSI, delete LIAD VLAN ports 22 and 23, and delete VLAN LIAD from `SW-LSI` (`docs/docs.md:586-625`).
- Final summary at `docs/docs.md:629-637`.

### 4.3 `docs/features/proposal.md`

- Project objective: IaC and Python automation for GNS3 (`docs/features/proposal.md:3-4`).
- Architecture: `SW-LACINA` as core/L3/DHCP; `SW-LSD`, `SW-LSI`, `SW-LIAD` as access; 802.1Q trunks; CFTV L2 isolation (`docs/features/proposal.md:6-13`).
- Stack: GNS3 Server, Python 3.10+, `gns3fy`, `netmiko`, `jinja2`, `python-dotenv` (`docs/features/proposal.md:15-21`).
- Phases 1-4: orchestration, configuration injection, automated acceptance tests, change management (`docs/features/proposal.md:23-45`).
- Success criterion: reproduce the full topology "from zero and without manual GUI intervention" and pass all six tests (`docs/features/proposal.md:47-48`).

### 4.4 `docs/features/plan.md`

Five milestones, all checkboxes unchecked (`[ ]`):

| Milestone | Lines | Tasks |
|:--|--:|:--|
| 1: Environment and codebase setup | 14-19 | venv, dependencies, `.env`, GNS3 connection test |
| 2: Logical orchestration via `gns3fy` | 21-26 | `infra/create_project.py`, 4 switches + 10 VPCS, links, start nodes |
| 3: Configuration via Netmiko/Jinja2 | 28-33 | templates, `config/configure_switches.py`, access-switch configs, VPCS IPs |
| 4: Automated acceptance tests | 35-41 | DHCP, gateway ping, inter-VLAN, CFTV isolation, trunk transport |
| 5: Day 2 change management | 43-47 | tickets 1-3 scripts |

Definition of Done at `docs/features/plan.md:51-57`; validation strategy at `docs/features/plan.md:61-65`.

### 4.5 ADRs

| ADR | Title | Status | Decision | Consequence noted |
|:--|:--|:--|:--|:--|
| `docs/adr/adr-001.md` | Python + `gns3fy` | Aceito | Python scripts with `gns3fy` and direct `requests` calls (`adr-001.md:8-9`) | Flexible API access; manual idempotency (`adr-001.md:13-15`) |
| `docs/adr/adr-002.md` | Netmiko + Jinja2 | Aceito | Netmiko for console/Telnet/SSH; Jinja2 templates (`adr-002.md:8-9`) | Prompt/pagination handling; template separation (`adr-002.md:13`) |
| `docs/adr/adr-003.md` | Read-Before-Write | Aceito | GET before POST for projects/nodes/links; `show vlan` before creating VLANs (`adr-003.md:8-9`) | Prevents duplicates; more network calls (`adr-003.md:13-15`) |
| `docs/adr/adr-004.md` | Acceptance tests via output parsing | Aceito | Netmiko to VPCS consoles; parse ping text (`adr-004.md:8-9`) | Lightweight topology; string-parsing caveat (`adr-004.md:13-15`) |
| `docs/adr/adr-005.md` | Credentials via env vars | Aceito | `python-dotenv` and a local `.env` ignored by Git (`adr-005.md:7`) | Portability; manual `.env` setup (`adr-005.md:11-13`) |

### 4.6 Cross-document differences (factual comparison)

| Topic | One statement | Another statement |
|:--|:--|:--|
| Script scope | `AGENTS.md:7-8`: topology already mounted; scripts must not create nodes/links from zero; goal is to configure existing nodes | `docs/features/proposal.md:48` and `docs/features/plan.md:22-25`: automate creation of project, nodes, and links from zero without GUI |
| Base project filename | `AGENTS.md:7`: `/base_topology/projeto_inicial.gns3project` | Actual file: `base_topology/uasc.gns3project` |
| Central L3 switch | `AGENTS.md:32`: routing/DHCP centralized exclusively on `SW-LACINA` | `docs/docs.md:44`: `SW-LACINA` (or `SW-LSD`) defined as central router |
| `.env` ignore | `docs/adr/adr-005.md:7`: `.env` ignored via `.gitignore` | `.gitignore:1-5` contains no `.env` pattern |
| Dependencies | `docs/features/plan.md:17` and `docs/adr/adr-002.md:9`: `netmiko`, `jinja2`, `python-dotenv` | `.venv` contains only `gns3fy 0.8.0` and its dependencies |
| Credentials/config | `docs/adr/adr-005.md:7`: URL/credentials in `.env` | `setup_lab.py:7` hardcodes `http://localhost:3080`; no `dotenv` import |
| Node creation | `docs/features/plan.md:24`: provision 4 switches and 10 VPCS | Base project already contains exactly 4 QEMU switches and 10 VPCS nodes; links are zero |

## 5. Runtime Environment

### 5.1 Virtual environment

`.venv/pyvenv.cfg` records:

- `home = /usr/bin`
- `include-system-site-packages = false`
- `version = 3.14.9`
- `executable = /usr/bin/python3.14`
- `command = /usr/bin/python -m venv /home/talesrb/Projetos/irc/modulo3/.venv`

### 5.2 Installed packages

`pip list` inside `.venv`:

| Package | Version |
|:--|:--|
| certifi | 2026.10.23 |
| charset-normalizer | 3.5.2 |
| gns3fy | 0.8.0 |
| idna | 3.20 |
| pip | 26.2.2 |
| pydantic | 1.10.27 |
| requests | 2.34.2 |
| typing_extensions | 4.16.0 |
| urllib3 | 2.8.0 |

`netmiko`, `jinja2`, `python-dotenv`, and `pytest` are not installed. There is no dependency manifest pinning these versions outside the `.venv` contents.

### 5.3 `gns3fy` API methods used by `setup_lab.py`

| Script call | Library implementation |
|:--|:--|
| `Gns3Connector(url=...)` | `.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:67-76` |
| `Project(name=..., connector=...)` | `.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:1106-1185` |
| `lab.get()` | `.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:1190-1242` |
| `lab.open()` | `.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:1333-1346` |
| `lab.start_nodes()` | `.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:1454-1473` |
| `node.console`, `node.status`, `node.name` | `.venv/lib/python3.14/site-packages/gns3fy/gns3fy.py:749-785` |

## 6. Cross-Component Connections and Data Flows

### 6.1 Current runtime flow

```
base_topology/uasc.gns3project (ZIP)
        |
        | manual import into GNS3 (not scripted; docs/AGENTS describe base topology as pre-mounted)
        v
GNS3 server at http://localhost:3080/v2
        ^
        | GET /projects, GET /projects/{id}, POST /open, POST /nodes/start
        |
setup_lab.py
        |
        | writes JSON
        v
inventario_gns3.json  (node name -> device_type, host, port, status)
        |
        | intended consumer per setup_lab.py:59 and :65
        v
/config/ scripts (not present in tree)
```

### 6.2 Data contracts

`inventario_gns3.json` schema, as constructed in `setup_lab.py:51-56`:

```json
{
  "<node name>": {
    "device_type": "cisco_ios_telnet",
    "host": "127.0.0.1",
    "port": "<node.console>",
    "status": "<node.status>"
  }
}
```

Given the 14 nodes in the base project and the `if porta:` filter at `setup_lab.py:50`, a successful run against the imported project would produce 14 inventory entries (console ports 5000-5026).

### 6.3 Documentation-to-code mapping

| Documentation data | Code location that consumes it |
|:--|:--|
| Project name `uasc` | `setup_lab.py:13` |
| GNS3 server URL | `setup_lab.py:7` |
| Node console ports | Read dynamically from GNS3 API (`setup_lab.py:44-47`); values match `project.gns3` lines per node |
| VLSM subnets and gateways (`AGENTS.md:11-19`, `docs/docs.md:8-16`) | Not consumed by any Python file in the tree |
| VLAN IDs/names (`AGENTS.md:21-29`, `docs/docs.md:31-39`) | Not consumed by any Python file in the tree |
| Port map and trunks (`docs/docs.md:64-81`) | Not encoded in the base topology (`project.gns3:93` links is empty) and not consumed by any Python file |
| EXOS command blocks (`docs/docs.md:91-330`) | Not stored in templates or scripts in the tree |
| Acceptance tests (`docs/docs.md:381-466`) | No test code in the tree |
| Change tickets (`docs/docs.md:487-625`) | No change-management code in the tree |
| ADR choices (`docs/adr/*.md`) | Only `gns3fy` and `requests` are present in `.venv`; Netmiko, Jinja2, and python-dotenv are absent |

### 6.4 Base-topology naming vs documentation

- Base topology contains `PC-LIAD-SALA` (`project.gns3:495`), which matches the Etapa 2 port map (`docs/docs.md:72`) and Chamado 3 (`docs/docs.md:592`).
- Base topology does not contain `PC-LACINA-SALA`; that node is introduced as a future change in Chamado 1 (`docs/docs.md:493-494`).
- All 14 base-topology node names match the names used in `docs/docs.md` and `AGENTS.md`; the switch names match exactly (`SW-LACINA`, `SW-LSD`, `SW-LSI`, `SW-LIAD`).

## 7. Present vs Referenced-but-Absent Artifacts

| Artifact | Present today | Reference |
|:--|:--|:--|
| GNS3 inventory/startup script | Yes: `setup_lab.py` | — |
| Portable base topology | Yes: `base_topology/uasc.gns3project` | — |
| Project rules | Yes: `AGENTS.md` | — |
| Lab design/configuration document | Yes: `docs/docs.md` | — |
| Proposal and milestone plan | Yes: `docs/features/proposal.md`, `docs/features/plan.md` | — |
| ADRs 001-005 | Yes: `docs/adr/` | — |
| Python virtual environment | Yes: `.venv/` with Python 3.14.9 | — |
| `/config/` automation scripts | No | `AGENTS.md:8`, `setup_lab.py:59` |
| `inventario_gns3.json` | No (runtime output) | `setup_lab.py:60-62` |
| `.env` / `.env.example` | No | `docs/adr/adr-005.md:7,13` |
| Netmiko/Jinja2/python-dotenv packages | No | `docs/features/plan.md:17`, `docs/adr/adr-002.md:9` |
| Jinja2 templates | No | `docs/features/plan.md:30` |
| `infra/create_project.py` | No | `docs/features/plan.md:23` |
| `config/configure_switches.py` | No | `docs/features/plan.md:31` |
| Acceptance-test scripts | No | `docs/features/plan.md:35-41` |
| Change-ticket scripts | No | `docs/features/plan.md:43-47` |
| Physical links in base topology | No (`"links": []`) | `project.gns3:93` |
| QEMU EXOS image file in archive | No; only the filename reference | `project.gns3:127` |
