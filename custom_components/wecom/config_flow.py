"""企业微信插件的配置流程，支持多实例与自定义别名。"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    CONF_CORP_ID,
    CONF_CORP_SECRET,
    CONF_AGENT_ID,
    CONF_DEFAULT_TOUSER,
    CONF_APP_NAME,
    API_GET_TOKEN,
)

_LOGGER = logging.getLogger(__name__)


def _build_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """配置 / 选项通用的表单结构。"""
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_CORP_ID, default=defaults.get(CONF_CORP_ID, "")
            ): str,
            vol.Required(
                CONF_CORP_SECRET, default=defaults.get(CONF_CORP_SECRET, "")
            ): str,
            vol.Required(
                CONF_AGENT_ID, default=defaults.get(CONF_AGENT_ID, "")
            ): str,
            vol.Optional(
                CONF_DEFAULT_TOUSER,
                default=defaults.get(CONF_DEFAULT_TOUSER, ""),
            ): str,
            vol.Optional(
                CONF_APP_NAME, default=defaults.get(CONF_APP_NAME, "")
            ): str,
        }
    )


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    """校验凭据：尝试获取 access_token，返回标题。"""
    session = async_get_clientsession(hass)
    params = {
        "corpid": data[CONF_CORP_ID],
        "corpsecret": data[CONF_CORP_SECRET],
    }

    try:
        async with session.get(API_GET_TOKEN, params=params) as resp:
            result = await resp.json()
    except aiohttp.ClientError as err:
        _LOGGER.error("连接企业微信 API 失败: %s", err)
        raise ValueError("网络连接失败，请检查网络") from err

    if result.get("errcode") != 0:
        errmsg = result.get("errmsg", "未知错误")
        _LOGGER.error("企业微信凭据验证失败: %s", errmsg)
        raise ValueError(errmsg)

    title = (
        data.get(CONF_APP_NAME)
        or f"企业微信 ({data[CONF_CORP_ID]}) - {data[CONF_AGENT_ID]}"
    )
    return {"title": title}


class WeComConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """企业微信配置流程。"""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except ValueError as err:
                errors["base"] = str(err)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("配置验证时发生意外错误")
                errors["base"] = "unknown"
            else:
                unique_id = (
                    f"{user_input[CONF_CORP_ID]}_{user_input[CONF_AGENT_ID]}"
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input),
            errors=errors,
            description_placeholders={
                "corp_id": "企业ID",
                "corp_secret": "应用的Secret",
                "agent_id": "应用AgentId",
                "default_touser": "默认接收成员ID（可选）",
                "app_name": "应用别名（可选，用于快速识别）",
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "WeComOptionsFlowHandler":
        return WeComOptionsFlowHandler()


class WeComOptionsFlowHandler(config_entries.OptionsFlow):
    """处理选项更新：修改别名 / 凭据等，并自动 reload。"""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except ValueError as err:
                return self.async_show_form(
                    step_id="init",
                    data_schema=_build_schema(user_input),
                    errors={"base": str(err)},
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("选项更新时发生意外错误")
                return self.async_show_form(
                    step_id="init",
                    data_schema=_build_schema(user_input),
                    errors={"base": "unknown"},
                )

            # 更新配置条目（含标题），并触发重新加载让运行时数据同步
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, **user_input},
                title=info["title"],
            )
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(title="", data={})

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(current),
        )