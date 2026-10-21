# ha_traccar

> Home Assistant 自定义集成：将 Traccar 服务器中的设备接入 Home Assistant，提供实时位置追踪、围栏状态、里程、海拔、地址等实体，并针对国内使用场景增加了 **WGS84 → GCJ02（高德）坐标转换**、**中国时区时间格式化** 与 **按需逆地理编码** 能力。

本集成基于 Home Assistant 官方 traccar_server 集成思路修改而来，iot_class 为 local_push，通过 Traccar 的 WebSocket 订阅实现位置实时推送。

---

## 功能特性

- 📡 **实时位置推送**：通过 Traccar subscribe 订阅设备与位置事件，位置变化即时刷新实体。
- 🗺️ **围栏支持（多围栏）**：同时支持设备处于多个围栏，提供围栏名称、围栏列表、围栏数量等属性。
- 🚗 **车辆数据**：速度（km/h）、海拔（m）、车机总里程（km）、本次里程（km）。
- 🌐 **高德坐标**：自动将 GPS 原始坐标（WGS84）转换为高德坐标（GCJ02），方便直接用于高德/国内地图卡片。
- 🕒 **中国时区时间**：最后定位时间统一格式化为 YYYY-MM-DD HH:MM:SS（UTC+8）。
- 📍 **按需逆地理编码**：通过服务 ha_traccar.update_address 主动向 Traccar 请求一次地址解析，避免持续调用。
- 🟢 **在线状态判断**：优先根据最后定位时间（5 分钟内）判断在线，回退到设备 status 字段。
- 🧩 **配置界面**：支持 UI 配置流程，无需编辑 YAML。

---

## 前置要求

- Home Assistant 2023.x 及以上（建议使用最新稳定版）。
- 可访问的 Traccar 服务器（默认端口 8082），且账号具备读取设备、位置、围栏的权限。
- Traccar 服务端已配置逆地理编码（geocoder），否则 update_address 服务可能返回空地址。

依赖库：pytraccar==2.1.1（由集成自动安装）。

---

## 安装

### 方式一：HACS（推荐）

1. 打开 HACS → **集成** → 右上角菜单 → **自定义存储库**。
2. 添加本仓库地址，类别选择 **Integration**。
3. 搜索 **Traccar 服务器** 并下载。
4. 重启 Home Assistant。

### 方式二：手动安装

1. 下载本仓库代码。
2. 将 ha_traccar 文件夹完整复制到 Home Assistant 的 custom_components 目录下，最终路径为：`<config>/custom_components/ha_traccar/`
3. 确认目录结构如下：

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

4. 提交后集成会尝试访问 /api/server 验证连通性，成功后即创建条目。

注意：同一 host:port 只允许配置一次，重复添加会提示「该服务器已配置」。

---

## 实体说明

实体 ID 由设备名称自动生成：设备名转小写、去除标点、空格替换为下划线。例如设备名为 BinYue，则生成 device_tracker.binyue。

⚠️ 实体 ID 在集成加载时被显式设置。若你在 HA 中手动重命名了实体 ID，重新加载集成后可能被覆盖；如需长期自定义，建议重命名 **设备名称** 后重载集成。

### device_tracker

每个 Traccar 设备生成一个 device_tracker 实体，source_type 为 gps，并强制刷新。

**状态属性：**

| 属性 | 说明 |
| --- | --- |
| address | 位置自带地址，否则使用 update_address 服务缓存的结果 |
| category | 设备类别 |
| motion | 是否运动 |
| traccar_id | Traccar 内部设备 ID |
| tracker | 固定为 ha_traccar |
| geofence | 当前围栏名称，多个用逗号连接；无围栏时为「不在围栏」 |
| in_geofence | 是否在任意围栏内（布尔值） |
| geofence_list | 围栏名称列表 |
| geofence_count | 围栏数量 |
| online | 在线状态（最后定位 5 分钟内，或设备 status 为 online） |
| speed | 速度，km/h（保留 1 位） |
| altitude | 海拔，米（保留 1 位） |
| total_distance | 车机总里程，km（保留 2 位） |
| trip_distance | 本次里程，km（保留 2 位） |
| gaode_lat / gaode_lon | 高德坐标（GCJ02） |
| time | 最后定位时间，格式 YYYY-MM-DD HH:MM:SS（UTC+8） |

### binary_sensor

| 实体 | 设备类别 | 说明 |
| --- | --- | --- |
| binary_sensor.设备名_in_geofence | presence | 是否在任意围栏内 |

属性：geofence、geofence_list、geofence_count。

### sensor

| 实体 | 设备类别 / 状态类别 | 单位 | 说明 |
| --- | --- | --- | --- |
| sensor.设备名_geofence | — | — | 当前围栏名称，无围栏时为「不在围栏」 |
| sensor.设备名_total_distance | distance / total_increasing | km | 车机总里程 |
| sensor.设备名_trip_distance | distance / measurement | km | 本次里程 |
| sensor.设备名_altitude | distance / measurement | m | 海拔 |
| sensor.设备名_address | — | — | 位置地址（或服务缓存地址） |


---

```markdown
---

## 服务

### ha_traccar.update_address

主动向 Traccar 请求一次逆地理编码，并刷新对应设备的 address 属性与地址传感器。

请求路径：GET /api/server/geocode?latitude=...&longitude=...（使用配置中的账号做 Basic Auth）。

**字段：**

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| entity_id | 是 | 要更新的 device_tracker 实体 |

**示例（自动化）：**

```yaml
automation:
  - alias: "车辆到达后更新地址"
    trigger:
      - platform: state
        entity_id: device_tracker.binyue
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.attributes.in_geofence }}"
    action:
      - service: ha_traccar.update_address
        target:
          entity_id: device_tracker.binyue
```

服务仅接受 device_tracker 实体；内部通过实体的 unique_id 与 Traccar 设备的 uniqueId 匹配。若找不到设备会记录警告日志。

---

坐标与时间说明

· 坐标转换：device_tracker 的 latitude / longitude 保持原始 WGS84 坐标，供 HA 地图与历史记录使用；额外属性 gaode_lat / gaode_lon 为转换后的 GCJ02 坐标，可直接用于高德地图卡片。转换算法仅在国境范围内生效，境外坐标原样返回。
· 时间：time 属性由 fixTime → deviceTime → serverTime 依次取值，统一转换为 UTC+8 字符串。
· 在线判断：优先使用最后定位时间与当前 UTC 时间差（< 300 秒为在线），无有效时间时回退到设备 status。

---

调试

在 configuration.yaml 中开启日志：

```yaml
logger:
  default: warning
  logs:
    custom_components.ha_traccar: debug
```

可看到订阅数据、地址请求 URL 与响应状态、坐标请求参数等调试信息。常见日志：

· Error while subscribing to Traccar：订阅失败，集成会在 10 秒后自动重试（仅首次记录错误）。
· Geocode API returned...：逆地理编码返回非 200。
· Traccar geocode returned 204：Traccar 无法解析出地址。

---

已知限制与注意事项

· 集成使用 local_push，位置更新依赖 Traccar WebSocket 订阅；服务器不可达时实体可能保持旧值。
· update_address 依赖 Traccar 服务端已配置可用的 geocoder，本集成不做本地逆地理编码。
· 实体 ID 由设备名称生成，多设备同名会导致实体 ID 冲突，请在 Traccar 中保证设备名唯一。
· 关闭「校验 SSL 证书」会使用不安全的 CookieJar，仅建议在自签名证书的内网环境使用。
· 集成不会自动创建「里程清零」类服务，里程数据直接来自 Traccar 位置属性 totalDistance / distance。

---

文件结构

文件 作用
init.py 集成入口、客户端与协调器创建、服务注册、后台订阅任务
config_flow.py UI 配置流程与连通性校验
coordinator.py 数据协调器、订阅处理、逆地理编码请求与地址缓存
entity.py 实体基类、设备信息、调度器信号订阅
device_tracker.py 设备追踪实体、WGS84→GCJ02、时间格式化、属性组装
binary_sensor.py 围栏存在性二进制传感器
sensor.py 围栏、总里程、本次里程、海拔、地址传感器
helpers.py 设备与围栏查找辅助函数
const.py 常量与服务名
services.yaml / strings.json / translations 服务与界面本地化

---

致谢

· 原始集成：Home Assistant traccar_server（codeowner @ludeeus）。
· Traccar 服务端：https://www.traccar.org/
· Python 客户端：pytraccar

如遇问题，请附上 调试日志 与 Traccar 版本 提交 Issue。

```