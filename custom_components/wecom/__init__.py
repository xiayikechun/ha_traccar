"""企业微信通知插件，支持多实例、别名、图文消息等。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from functools import partial
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_CORP_ID,
    CONF_CORP_SECRET,
    CONF_AGENT_ID,
    CONF_APP_NAME,
    CONF_CONFIG_ENTRY_ID,
    CONF_APP_NAME_PARAM,
    SERVICE_SEND_MESSAGE,
    MSG_TYPE_TEXT,
    MSG_TYPE_MARKDOWN,
    MSG_TYPE_NEWS,
    API_GET_TOKEN,
    API_SEND_MESSAGE,
    TOKEN_EXPIRE_TIME,
)

_LOGGER = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#                            服务参数校验架构
# --------------------------------------------------------------------------- #
ARTICLE_SCHEMA = vol.Schema(
    {
        vol.Required("title"): cv.string,
        vol.Optional("description", default=""): cv.string,
        vol.Required("url"): cv.string,
        vol.Optional("picurl", default=""): cv.string,
    }
)

SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        # news 类型可以不带 message，其他类型需要
        vol.Optional("message", default=""): cv.string,
        vol.Optional("message_type", default=MSG_TYPE_TEXT): vol.In(
            [MSG_TYPE_TEXT, MSG_TYPE_MARKDOWN, MSG_TYPE_NEWS]
        ),
        vol.Optional("touser"): cv.string,
        vol.Optional("toparty"): cv.string,
        vol.Optional("totag"): cv.string,
        vol.Optional("safe", default=0): vol.Coerce(int),
        vol.Optional("enable_duplicate_check", default=0): vol.Coerce(int),
        vol.Optional("duplicate_check_interval", default=1800): vol.Coerce(int),
        vol.Optional(CONF_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(CONF_APP_NAME_PARAM): cv.string,
        vol.Optional("articles"): vol.All(cv.ensure_list, [ARTICLE_SCHEMA]),
    },
    extra=vol.ALLOW_EXTRA,
)


# --------------------------------------------------------------------------- #
#                            企业微信 API 封装
# --------------------------------------------------------------------------- #
class WeComAPI:
    """企业微信 API 封装：token 缓存、消息发送、失效自动重试。"""

    # 这些 errcode 表示 access_token 已失效，需要强制刷新
    _TOKEN_INVALID_ERRCODES = {40014, 42001, 42007, 41001}

    def __init__(self, corp_id: str, corp_secret: str, agent_id: str) -> None:
        self.corp_id = corp_id
        self.corp_secret = corp_secret
        self.agent_id = agent_id
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

    async def get_access_token(
        self, session: aiohttp.ClientSession, *, force_refresh: bool = False
    ) -> str:
        """获取有效的 access_token（带缓存）。"""
        if (
            not force_refresh
            and self._access_token
            and self._token_expires_at
            and datetime.now() < self._token_expires_at
        ):
            return self._access_token

        params = {"corpid": self.corp_id, "corpsecret": self.corp_secret}
        try:
            async with session.get(API_GET_TOKEN, params=params) as resp:
                data = await resp.json()
        except aiohttp.ClientError as err:
            _LOGGER.error("请求企业微信 API 出错: %s", err)
            raise HomeAssistantError(f"请求企业微信 API 出错: {err}") from err

        if data.get("errcode") != 0:
            msg = data.get("errmsg", "未知错误")
            _LOGGER.error("获取企业微信 access_token 失败: %s", msg)
            raise HomeAssistantError(f"获取 token 失败: {msg}")

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", TOKEN_EXPIRE_TIME))
        # 提前 5 分钟过期，避免边界失效
        self._token_expires_at = datetime.now() + timedelta(
            seconds=max(expires_in - 300, 60)
        )
        _LOGGER.debug("成功获取 access_token，有效期 %d 秒", expires_in)
        return self._access_token

    def _build_msg_body(
        self,
        message: str,
        message_type: str,
        touser: str | None,
        toparty: str | None,
        totag: str | None,
        safe: int,
        enable_duplicate_check: int,
        duplicate_check_interval: int,
        articles: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        """构造消息体，做基本参数校验。"""
        if not any((touser, toparty, totag)):
            raise HomeAssistantError("必须指定 touser、toparty 或 totag 中的至少一个")

        body: dict[str, Any] = {
            "agentid": self.agent_id,
            "msgtype": message_type,
            "safe": safe,
            "enable_duplicate_check": enable_duplicate_check,
            "duplicate_check_interval": duplicate_check_interval,
        }
        if touser:
            body["touser"] = touser
        if toparty:
            body["toparty"] = toparty
        if totag:
            body["totag"] = totag

        if message_type in (MSG_TYPE_TEXT, MSG_TYPE_MARKDOWN):
            if not message:
                raise HomeAssistantError(f"{message_type} 类型消息内容不能为空")
            body[message_type] = {"content": message}
        elif message_type == MSG_TYPE_NEWS:
            if not articles:
                raise HomeAssistantError("发送 news 类型消息时必须提供 articles 参数")
            body["news"] = {
                "articles": [
                    {
                        "title": article["title"],
                        "description": article.get("description", ""),
                        "url": article["url"],
                        "picurl": article.get("picurl", ""),
                    }
                    for article in articles
                ]
            }
        else:
            raise HomeAssistantError(f"不支持的消息类型: {message_type}")

        return body

    async def send_message(
        self,
        session: aiohttp.ClientSession,
        message: str = "",
        message_type: str = MSG_TYPE_TEXT,
        touser: str | None = None,
        toparty: str | None = None,
        totag: str | None = None,
        safe: int = 0,
        enable_duplicate_check: int = 0,
        duplicate_check_interval: int = 1800,
        articles: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """发送消息；如果 token 失效则自动刷新一次重试。"""
        body = self._build_msg_body(
            message,
            message_type,
            touser,
            toparty,
            totag,
            safe,
            enable_duplicate_check,
            duplicate_check_interval,
            articles,
        )

        last_errmsg = ""
        for attempt in range(2):
            token = await self.get_access_token(session, force_refresh=attempt > 0)
            url = f"{API_SEND_MESSAGE}?access_token={token}"

            try:
                async with session.post(url, json=body) as resp:
                    result = await resp.json()
            except aiohttp.ClientError as err:
                _LOGGER.error("发送消息时请求异常: %s", err)
                raise HomeAssistantError(f"请求异常: {err}") from err

            errcode = result.get("errcode")
            if errcode == 0:
                _LOGGER.debug("消息发送成功: %s", result)
                return result

            last_errmsg = result.get("errmsg", "未知错误")

            if errcode in self._TOKEN_INVALID_ERRCODES and attempt == 0:
                _LOGGER.warning(
                    "access_token 可能已失效 (errcode=%s)，强制刷新后重试", errcode
                )
                self._access_token = None
                self._token_expires_at = None
                continue

            _LOGGER.error(
                "发送企业微信消息失败: %s (errcode=%s)", last_errmsg, errcode
            )
            raise HomeAssistantError(f"发送失败: {last_errmsg}")

        # 理论不会走到这里
        raise HomeAssistantError(f"发送失败: {last_errmsg}")


# --------------------------------------------------------------------------- #
#                            运行时数据
# --------------------------------------------------------------------------- #
class WeComRuntime:
    """把 entry_id -> API 实例 和 别名 -> entry_id 分开管理，避免键冲突。"""

    def __init__(self) -> None:
        self.api_map: dict[str, WeComAPI] = {}
        self.alias_map: dict[str, str] = {}

    def resolve_entry_id(
        self, entry_id: str | None, alias: str | None
    ) -> str:
        """根据 app_name 或 config_entry_id 定位配置条目。"""
        if alias:
            if alias not in self.alias_map:
                raise HomeAssistantError(
                    f"未找到别名为 '{alias}' 的应用，请检查配置或改用 config_entry_id"
                )
            return self.alias_map[alias]

        if entry_id:
            if entry_id not in self.api_map:
                raise HomeAssistantError(f"未找到配置条目 ID: {entry_id}")
            return entry_id

        if not self.api_map:
            raise HomeAssistantError("没有已配置的企业微信应用")

        return next(iter(self.api_map))


# --------------------------------------------------------------------------- #
#                            服务处理
# --------------------------------------------------------------------------- #
async def _async_handle_send_message(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    runtime: WeComRuntime | None = hass.data.get(DOMAIN)
    if runtime is None:
        raise HomeAssistantError("企业微信集成尚未初始化")

    entry_id = runtime.resolve_entry_id(
        call.data.get(CONF_CONFIG_ENTRY_ID),
        call.data.get(CONF_APP_NAME_PARAM),
    )
    api = runtime.api_map[entry_id]

    await api.send_message(
        session=async_get_clientsession(hass),
        message=call.data.get("message", ""),
        message_type=call.data.get("message_type", MSG_TYPE_TEXT),
        touser=call.data.get("touser"),
        toparty=call.data.get("toparty"),
        totag=call.data.get("totag"),
        safe=call.data.get("safe", 0),
        enable_duplicate_check=call.data.get("enable_duplicate_check", 0),
        duplicate_check_interval=call.data.get("duplicate_check_interval", 1800),
        articles=call.data.get("articles"),
    )


# --------------------------------------------------------------------------- #
#                            集成生命周期
# --------------------------------------------------------------------------- #
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """根据配置条目设置集成，支持多实例与别名映射。"""
    runtime = hass.data.get(DOMAIN)
    if runtime is None:
        runtime = WeComRuntime()
        hass.data[DOMAIN] = runtime

    # data 与 options 合并，options 优先（这样 OptionsFlow 修改也能生效）
    config: dict[str, Any] = {**entry.data, **entry.options}

    runtime.api_map[entry.entry_id] = WeComAPI(
        corp_id=config[CONF_CORP_ID],
        corp_secret=config[CONF_CORP_SECRET],
        agent_id=config[CONF_AGENT_ID],
    )

    alias = config.get(CONF_APP_NAME)
    if alias:
        runtime.alias_map[alias] = entry.entry_id

    # 全局服务只注册一次
    if not hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SEND_MESSAGE,
            partial(_async_handle_send_message, hass),
            schema=SEND_MESSAGE_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """卸载配置条目时清理别名、API 实例及全局服务。"""
    runtime: WeComRuntime | None = hass.data.get(DOMAIN)
    if runtime is None:
        return True

    config: dict[str, Any] = {**entry.data, **entry.options}
    alias = config.get(CONF_APP_NAME)
    if alias and runtime.alias_map.get(alias) == entry.entry_id:
        runtime.alias_map.pop(alias, None)

    runtime.api_map.pop(entry.entry_id, None)

    # 没有任何实例时移除服务并清理域数据
    if not runtime.api_map:
        if hass.services.has_service(DOMAIN, SERVICE_SEND_MESSAGE):
            hass.services.async_remove(DOMAIN, SERVICE_SEND_MESSAGE)
        hass.data.pop(DOMAIN, None)

    return True