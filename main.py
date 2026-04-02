import aiohttp
import time

from astrbot.api.all import *

@register("astrbot_plugin_feish_calendar", "nonpricklycactus", "飞书日历插件", "1.0.4", "https://gentlecactus.top")
class AkashaCalendarPlugin(Star):
    # 🚀 兼容 V4 的依赖注入机制，带上 config: dict = None
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.tenant_access_token = ""
        self.token_expire_time = 0

    async def _get_valid_token(self) -> str:
        """动态获取配置与 Token (支持网页后台热更新)"""
        app_id = self.config.get("app_id", "")
        app_secret = self.config.get("app_secret", "")
        
        if not app_id or not app_secret:
            logger.error("WebUI 中未配置飞书的 App ID 或 Secret")
            return ""

        current_time = int(time.time())
        if self.tenant_access_token and current_time < self.token_expire_time - 300:
            return self.tenant_access_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == 0:
                            self.tenant_access_token = data.get("tenant_access_token")
                            self.token_expire_time = current_time + data.get("expire", 7200)
                            return self.tenant_access_token
        except Exception as e:
            logger.error(f"获取飞书 Token 发生异常: {e}")
        return ""

    async def _ensure_calendar_id(self) -> str:
        """确保 calendar_id 存在，如果为空则自动创建或查找现有日历"""
        calendar_id = self.config.get("calendar_id", "")
        
        if calendar_id:
            return calendar_id
        
        token = await self._get_valid_token()
        if not token:
            logger.error("无法获取有效的飞书 Token，无法创建日历")
            return ""
        
        # 首先检查是否已存在名为 "AstrBot Calendar" 的日历
        existing_calendar_id = await self._find_existing_calendar(token)
        if existing_calendar_id:
            logger.info(f"找到现有日历: {existing_calendar_id}")
            # 更新配置中的 calendar_id
            await self._update_config_calendar_id(existing_calendar_id)
            return existing_calendar_id
        
        # 创建新日历
        new_calendar_id = await self._create_calendar(token)
        if new_calendar_id:
            logger.info(f"创建新日历成功: {new_calendar_id}")
            # 更新配置中的 calendar_id
            await self._update_config_calendar_id(new_calendar_id)
            return new_calendar_id
        
        logger.error("无法创建或找到日历")
        return ""

    async def _find_existing_calendar(self, token: str) -> str:
        """查找已存在的 AstrBot 日历"""
        url = "https://open.feishu.cn/open-apis/calendar/v4/calendars"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=30) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == 0:
                            calendars = data.get("data", {}).get("calendar_list", [])
                            for calendar in calendars:
                                if calendar.get("summary") == "AstrBot Calendar":
                                    return calendar.get("calendar_id", "")
        except Exception as e:
            logger.error(f"查找现有日历时发生异常: {e}")
        
        return ""

    async def _create_calendar(self, token: str) -> str:
        """创建新的飞书日历"""
        url = "https://open.feishu.cn/open-apis/calendar/v4/calendars"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "summary": "AstrBot Calendar",
            "description": "AstrBot 自动创建的日历，用于管理日程事件",
            "permissions": "private",  # 私有日历
            "color": -1,  # 默认颜色
            "summary_alias": "AstrBot"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("code") == 0:
                            return data.get("data", {}).get("calendar", {}).get("calendar_id", "")
                        else:
                            logger.error(f"创建日历失败: {data.get('msg', '未知错误')}")
                    else:
                        logger.error(f"创建日历 HTTP 错误: {resp.status}")
        except Exception as e:
            logger.error(f"创建日历时发生异常: {e}")
        
        return ""

    async def _update_config_calendar_id(self, calendar_id: str):
        """更新配置中的 calendar_id"""
        try:
            # 更新内存中的配置
            self.config["calendar_id"] = calendar_id
            
            # 尝试通过上下文更新配置（如果支持）
            if hasattr(self.context, 'update_config'):
                await self.context.update_config("astrbot_plugin_feish_calendar", {"calendar_id": calendar_id})
                logger.info(f"已更新配置中的 calendar_id: {calendar_id}")
            else:
                logger.warning("上下文不支持 update_config 方法，请在 WebUI 中手动更新 calendar_id")
        except Exception as e:
            logger.error(f"更新配置 calendar_id 时发生异常: {e}")

    @llm_tool(name="create_feishu_event")
    async def create_event(self, event: AstrMessageEvent, title: str, start_timestamp: str, end_timestamp: str) -> str:
        """
        在主人的飞书日历中创建一个新的日程。必须在获得主人明确同意后调用。
        
        Args:
            title (str): 日程标题
            start_timestamp (str): 开始时间的 Unix 时间戳（精确到秒的字符串）
            end_timestamp (str): 结束时间的 Unix 时间戳（精确到秒的字符串）
        """
        token = await self._get_valid_token()
        if not token:
            return "❌ 系统异常：无法获取飞书 API 鉴权 Token，请检查后台配置。"

        # 确保 calendar_id 存在，如果为空则自动创建或查找
        calendar_id = await self._ensure_calendar_id()
        if not calendar_id:
            return "❌ 系统异常：无法获取或创建日历，请检查飞书应用权限。"

        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        payload = {
            "summary": title,
            "start_time": {"timestamp": start_timestamp},
            "end_time": {"timestamp": end_timestamp}
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
                    res_data = await resp.json()
                    if res_data.get("code") == 0:
                        event_id = res_data["data"]["event"]["event_id"]
                        return f"✅ 成功写入日历！\n- 事件ID: {event_id}\n- 日历ID: {calendar_id}"
                    else:
                        error_msg = res_data.get('msg', '未知错误')
                        return f"❌ 创建失败，飞书 API 报错：{error_msg}"
        except Exception as e:
            return f"❌ 创建日历时发生网络异常: {e}"

    @llm_tool(name="delete_feishu_event")
    async def delete_event(self, event: AstrMessageEvent, event_id: str) -> str:
        """
        删除一个已存在的飞书日历日程。用于计划变更或取消时。
        
        Args:
            event_id (str): 之前创建日程时系统返回的唯一事件 ID。
        """
        token = await self._get_valid_token()
        if not token:
            return "❌ 系统异常：无法获取飞书 API 鉴权 Token。"

        # 确保 calendar_id 存在，如果为空则自动创建或查找
        calendar_id = await self._ensure_calendar_id()
        if not calendar_id:
            return "❌ 系统异常：无法获取或创建日历，请检查飞书应用权限。"

        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {token}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers, timeout=30) as resp:
                    res_data = await resp.json()
                    if res_data.get("code") == 0:
                        return f"✅ 清理完成: 事件 {event_id} 已成功移除。"
                    else:
                        error_msg = res_data.get('msg', '未知错误')
                        return f"❌ 删除失败，飞书 API 报错：{error_msg}"
        except Exception as e:
            return f"❌ 删除日历时发生网络异常: {e}"