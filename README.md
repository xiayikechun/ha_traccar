# ha_traccar

> Home Assistant 自定义集成：将 Traccar 服务器中的设备接入 Home Assistant，提供实时位置追踪、围栏状态、里程、海拔、地址等实体，并针对国内使用场景增加了 **WGS84 → GCJ02（高德）坐标转换**、**中国时区时间格式化** 与 **按需逆地理编码** 能力。

本集成连接方式为 `local_push`——位置变化由 Traccar 主动推送，而非定时轮询。本文档包含完整的安装指南与功能原理详解。近期修复了订阅重连、字段缺失异常、SSL 校验等问题（见[更新记录](#更新记录)）。

---

## 目录

- [功能特性](#功能特性)
- [安装](#安装)
- [配置](#配置)
- [架构与数据流](#架构与数据流)
- [核心功能详解](#核心功能详解)
- [实体清单](#实体清单)
- [服务](#服务)
- [内部机制](#内部机制)
- [依赖与兼容性](#依赖与兼容性)
- [调试](#调试)
- [已知问题与自动化](#已知问题与自动化)
- [更新记录](#更新记录)
- [致谢与来源](#致谢与来源)

---

## 功能特性

- 📡 **实时位置推送**：通过 Traccar subscribe 订阅设备与位置事件，位置变化即时刷新实体。
- 🗺️ **围栏支持（多围栏）**：同时支持设备处于多个围栏，提供围栏名称、围栏列表、围栏数量等属性。
- 🚗 **车辆数据**：速度（km/h）、海拔（m）、车机总里程（km）、本次里程（km）。
- 🌐 **高德坐标**：自动将 GPS 原始坐标（WGS84）转换为高德坐标（GCJ02），方便直接用于高德/国内地图卡片。
- 🕒 **中国时区时间**：最后定位时间统一格式化为 `YYYY-MM-DD HH:MM:SS`（UTC+8）。
- 📍 **按需逆地理编码**：通过服务 `ha_traccar.update_address` 主动向 Traccar 请求一次地址解析，避免持续调用。
- 🟢 **在线状态判断**：优先根据最后定位时间（5 分钟内）判断在线，回退到设备 status 字段。
- 🧩 **配置界面**：支持 UI 配置流程，无需编辑 YAML。
- 🔌 **动态属性传感器**：自动为设备上报的任意 `attributes` 字段创建传感器，常用字段默认启用。

---

## 安装

### 方式一：HACS（推荐）

1. 打开 HACS → **集成** → 右上角菜单 → **自定义存储库**。
2. 添加本仓库地址，类别选择 **Integration**。
3. 搜索 **Traccar 服务器** 并下载。
4. 重启 Home Assistant。

### 方式二：手动安装

1. 下载本仓库代码。
2. 将 `custom_components/ha_traccar` 文件夹完整复制到 HA 配置目录下的 `custom_components/`，最终路径：`<config>/custom_components/ha_traccar/`。
3. 确认目录结构：

```text
custom_components/ha_traccar/
├── __init__.py
├── binary_sensor.py
├── config_flow.py
├── const.py
├── coordinator.py
├── device_tracker.py
├── entity.py
├── helpers.py
├── manifest.json
├── sensor.py
├── services.yaml
├── strings.json
└── translations/
    ├── en.json
    └── zh-Hans.json
```

4. 重启 Home Assistant。

---

## 配置

1. 进入 **设置 → 设备与服务 → 添加集成**。
2. 搜索 **Traccar 服务器**。
3. 填写以下信息：

| 字段 | 说明 | 默认值 |
| --- | --- | --- |
| 主机 | Traccar 服务器主机名或 IP | — |
| 端口 | Traccar 服务端口 | 8082 |
| 用户名 | 登录 Traccar 的用户名（邮箱） | — |
| 密码 | 登录密码 | — |
| 启用 SSL | 使用 https 连接 | 关闭 |
| 校验 SSL 证书 | 是否校验证书（自签名证书可关闭） | 开启 |

4. 提交后集成调用 `client.get_server()` 验证连通性，成功后创建条目。

> 同一 `host:port` 只允许配置一次，重复添加会提示「该服务器已配置」。

---

## 架构与数据流

```text
┌─────────────────────────────────────────────────────────────────┐
│                         Traccar 服务器                          │
│   /api/devices   /api/positions   /api/geofences   WebSocket    │
└───────────┬─────────────────────────────┬───────────────────────┘
            │ REST（首次/全量）            │ subscribe（增量推送）
            ▼                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              pytraccar ApiClient（专用 aiohttp session）         │
└───────────┬─────────────────────────────┬───────────────────────┘
            │                             │
            ▼                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                  TraccarServerCoordinator                       │
│  • _async_update_data()    拉取设备/位置/围栏，构建内存数据       │
│  • handle_subscription_data()  合并 WebSocket 增量数据          │
│  • async_request_address() 逆地理编码 + 地址覆盖缓存             │
│  • _address_overrides     地址覆盖字典（设备 ID → 地址）          │
└───────────┬─────────────────────────────────────────────────────┘
            │ dispatcher 信号：ha_traccar_<device_id>
            ▼
┌─────────────────────────────────────────────────────────────────┐
│  实体平台                                                        │
│  device_tracker  → 实时位置 + 丰富属性                           │
│  binary_sensor   → 围栏存在性                                    │
│  sensor          → 围栏 / 里程 / 海拔 / 地址 / 动态属性           │
└─────────────────────────────────────────────────────────────────┘
```

数据分两条路径进入系统：

1. **全量拉取**：集成加载时 `async_config_entry_first_refresh()` 通过 REST 拉取全部设备、位置、围栏，建立协调器内存数据。
2. **增量推送**：后台任务持续运行 `coordinator.subscribe()` 订阅 WebSocket 事件，收到设备/位置变化后就地更新内存数据并通过 dispatcher 信号通知实体刷新。

---

## 核心功能详解

### 实时位置推送

通过 pytraccar 的 `client.subscribe()` 建立长连接，回调 `handle_subscription_data()` 按 `deviceId` 把设备与位置更新合并进协调器数据，并对受影响的设备发送 `ha_traccar_<device_id>` 信号。每个实体订阅该信号后调用 `async_write_ha_state()` 刷新——**无需轮询**，位置变化即时反映。

订阅断开或异常时每 10 秒重连一次（循环重试，不会累积递归深度）；重连失败仅首次记录错误日志，避免刷屏。

### 多围栏支持

原版只取第一个围栏，本版本完整支持设备同时处于多个围栏：

- 通过 `get_geofences(geofences, position["geofenceIds"])` 拿到全部匹配围栏。
- `device_tracker` 提供 `geofence`（逗号连接）、`in_geofence`（布尔）、`geofence_list`（列表）、`geofence_count`（数量）。
- `binary_sensor`（`presence`）与 `sensor.设备名_围栏` 同样附带围栏列表/数量属性。

### 高德坐标转换（WGS84 → GCJ02）

国内地图使用 GCJ02 坐标，GPS 原始坐标是 WGS84，直接显示会有几百米偏移。集成内置标准 GCJ02 转换算法 `wgs84_to_gcj02()`（含地球半径与偏心率修正），且仅对中国境内坐标生效，境外坐标原样返回。

**设计取舍**：`device_tracker` 的 `latitude`/`longitude` 保持**原始 WGS84**供 HA 地图与历史使用；转换后坐标放在 `gaode_lat`/`gaode_lon` 属性中，专门给国内地图卡片调用。

### 中国时区时间格式化

时间取值优先级 `fixTime` → `deviceTime` → `serverTime`，解析后统一 `astimezone(+08:00)` 格式化为 `YYYY-MM-DD HH:MM:SS`，写入 `device_tracker` 的 `time` 属性。

### 按需逆地理编码

`ha_traccar.update_address` 服务按需触发，不会持续调用地址接口。内部流程：

1. 从实体注册表拿到 `device_tracker` 实体的 `unique_id`
2. 遍历协调器，按设备 `uniqueId` 找到对应设备
3. 用当前经纬度请求 `GET {host}:{port}/api/server/geocode?latitude=...&longitude=...`（Basic Auth，30 秒超时）
4. 解析响应：JSON 取 `address` 字段，纯文本直接用正文；204 视为无地址
5. 结果存入 `_address_overrides[device_id]` 并刷新实体

地址展示优先级：位置自带 `address` > 服务缓存的地址。**依赖**：Traccar 服务端需配置可用的 geocoder。

### 在线状态判断

1. **优先按定位时间**：最后定位时间与当前 UTC 时间差 **< 300 秒**判为在线。
2. **回退到设备状态**：无有效定位时间时，用 `device["status"] == "online"` 判断。

### 里程与车辆数据

Traccar 的 `position.attributes` 携带车辆数据，换算后输出：

| 原始数据（属性） | 输出属性 | 换算 |
| --- | --- | --- |
| `totalDistance`（米） | `total_distance`（km） | ÷1000，保留 2 位 |
| `distance`（米） | `trip_distance`（km） | ÷1000，保留 2 位 |
| `speed`（m/s） | `speed`（km/h） | ×3.6，保留 1 位 |
| `altitude`（米） | `altitude`（米） | 保留 1 位 |

对应传感器：`sensor.设备名_车机里程`（`total_increasing`）、`sensor.设备名_本次里程`、`sensor.设备名_海拔`。

### 动态属性传感器

集成启动及每次数据推送时扫描 `position.attributes`，为**每个新出现的字段**自动创建 `sensor.设备名_attr_字段名`，用 `tracked_attributes` 按设备去重。

**默认启用**的常用字段（`DEFAULT_ENABLED_ATTRIBUTES`）：

- 通用：`motion`、`ignition`、`blocked`、`alarm`、`status`、`sat`、`hdop`、`course`
- 里程：`totalDistance`、`distance`、`odometer`、`hours`
- 电源/油量：`batteryLevel`、`power`、`charge`、`fuelLevel`
- 传感器：`rpm`、`temp`、`adc1`、`adc2`
- IO：`in1~in4`、`out1~out4`

其他字段创建的传感器默认**禁用**，可在 HA 实体设置中按需启用。值为 `dict`/`list` 的复杂字段不作为 state，放入 `raw_value` 属性。

---

## 实体清单

实体 ID 由设备名称生成：转小写 → 去除标点 → 空格替换为下划线（如 `BinYue` → `binyue`）。

### device_tracker（每个设备一个）

| 属性 | 说明 |
| --- | --- |
| `address` | 位置自带地址，或服务缓存的地址 |
| `category` / `motion` | 设备类别 / 是否运动 |
| `traccar_id` / `tracker` | Traccar 内部 ID / 固定 `ha_traccar` |
| `geofence` / `in_geofence` | 围栏名称（逗号连接）/ 是否在围栏内 |
| `geofence_list` / `geofence_count` | 围栏列表 / 数量 |
| `online` | 在线状态 |
| `speed` / `altitude` | 速度 km/h / 海拔 m |
| `total_distance` / `trip_distance` | 总里程 / 本次里程（km） |
| `gaode_lat` / `gaode_lon` | 高德坐标（GCJ02） |
| `time` | 最后定位时间（UTC+8 字符串） |

### binary_sensor（每个设备一个）

`binary_sensor.设备名_in_geofence`：设备类别 `presence`，是否在任意围栏内。

### sensor（每设备 5 个固定 + 动态属性）

| 实体 | 设备类别 / 状态类别 | 单位 |
| --- | --- | --- |
| `sensor.设备名_geofence` | — | — |
| `sensor.设备名_total_distance` | distance / total_increasing | km |
| `sensor.设备名_trip_distance` | distance / measurement | km |
| `sensor.设备名_altitude` | distance / measurement | m |
| `sensor.设备名_address` | — | — |
| `sensor.设备名_attr_*` | 动态属性传感器 | 依字段而定 |

---

## 服务

### `ha_traccar.update_address`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `entity_id` | 是 | 要更新地址的 `device_tracker` 实体 |

```yaml
action: ha_traccar.update_address
target:
  entity_id: device_tracker.binyue
```

适用场景：车辆进入围栏后触发一次地址解析，用于通知内容或卡片展示。

---

## 内部机制

### 数据模型

协调器数据是以 Traccar 设备数字 ID 为键的字典，每个值：

```python
{
    "device":     DeviceModel,        # 设备信息
    "geofence":   GeofenceModel|None, # 第一个围栏（兼容属性）
    "geofences":  list[GeofenceModel],# 全部围栏
    "position":   PositionModel,      # 最新位置
}
```

### 健壮性处理

- **可选字段安全取值**：`speed`、`altitude`、`accuracy`、`attributes` 可能缺失或为 `None`，全部用 `.get()` 并提供默认值，避免 `round(None)` 异常。
- **坐标空值保护**：经纬度为 `None` 时跳过坐标转换。
- **地址覆盖缓存**：`_address_overrides` 按设备 ID 存储，重载后失效（不持久化）。
- **订阅任务生命周期**：由 `entry.async_create_background_task()` 创建，卸载时由 HA 自动取消；捕获 `CancelledError` 正常退出。

### 实体 ID 说明

实体 ID 在平台加载时被显式设置。**手动改过的实体 ID 在重载后可能被覆盖**。如需长期自定义，建议修改 Traccar 中的设备名称后重载。另外设备名重复会导致实体 ID 冲突，请保证 Traccar 设备名唯一。

---

## 依赖与兼容性

| 项目 | 要求 |
| --- | --- |
| Home Assistant | 2023.x 及以上（建议最新稳定版） |
| pytraccar | `2.1.1`（由集成自动安装） |
| Traccar 服务端 | 需开放设备/位置/围栏读取权限 |
| 逆地理编码 | 服务端需配置 geocoder（按需使用） |

### 已知依赖冲突（重要）

本集成固定依赖 `pytraccar==2.1.1`（用户名+密码认证）。新版 Home Assistant 已内置 `pytraccar==3.0.0`，该版本将认证方式改为 **Token**、最低要求 Python 3.13，两者**代码不兼容**，不能只改版本号。因此：

- 在内置 pytraccar 3.x 的 HA 版本上，可能出现依赖冲突或认证失败。
- 官方 `hassfest` 校验会因此报 `REQUIREMENTS` 冲突，故本仓库 CI 仅启用 HACS 校验。
- 迁移到 3.0.0 需改造配置流程为 Token 认证，属破坏性变更，当前版本暂未处理。

---

## 调试

在 `configuration.yaml` 开启日志：

```yaml
logger:
  default: warning
  logs:
    custom_components.ha_traccar: debug
```

常见日志含义：

- `Error while subscribing to Traccar`：订阅失败，10 秒后自动重试（仅首次记录）
- `Geocode API returned ...`：逆地理编码接口返回非 200
- `Traccar geocode returned 204`：服务端无法解析出地址
- `Discovered N new attribute(s)`：发现新设备属性并创建传感器

---

## 已知问题与自动化

### GitHub Actions 自动化

- **校验**（`.github/workflows/validate.yml`）：push / PR / 每日定时运行 HACS 仓库校验。
- **发布**（`.github/workflows/release.yml`）：推送形如 `v2.2.3` 的 tag 时，自动校验 tag 与 `manifest.json` 版本一致，然后创建 GitHub Release。

发布新版本流程：

1. 修改 `manifest.json` 的 `version`；
2. 提交并推送到 `main`；
3. 打同名 tag 并推送：`git tag vX.Y.Z && git push origin vX.Y.Z`；
4. Actions 自动创建 Release。

---

## 更新记录

1. **订阅递归栈溢出**：`subscribe()` 原用递归重试，长期断线会累积递归层数最终 `RecursionError`；改为 `while` 循环重试，捕获其他异常与取消信号，连接正常关闭后延迟重连避免紧密循环。
2. **SSL 校验不一致**：逆地理编码原使用 HA 共享 session，忽略「校验 SSL 证书」配置，自签名证书环境会失败；改为复用按配置创建的专用 session。
3. **字段缺失导致实体异常**：`speed`/`altitude`/`accuracy`/`attributes` 原用直接索引并 `round()`，设备未上报时抛异常；改为安全取值。
4. **坐标转换健壮性**：经纬度为 `None` 时跳过 WGS84→GCJ02 转换。
5. **服务调用健壮性**：`update_address` 遍历协调器数据及 `uniqueId` 时改用安全访问。
6. **清理未使用导入**：移除 `coordinator.py` 中未使用的 `get_first_geofence` 与 `async_get_clientsession`。
7. **文档格式修复**：README 中多余代码块标记导致章节无法渲染，已修正。
8. **元数据完善**：`manifest.json` 补充 `integration_type`、`issue_tracker`，修正 `codeowners`，版本升至 2.2.3。

---

## 致谢与来源

- 原始集成思路：Home Assistant 官方 `traccar_server`（codeowner @ludeeus）
- Traccar 服务端：<https://www.traccar.org/>
- Python 客户端：`pytraccar`（@ludeeus）

如遇问题，请附上调试日志与 Traccar 版本提交 Issue。
