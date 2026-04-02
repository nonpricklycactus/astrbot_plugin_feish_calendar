import asyncio
import aiohttp
import time
from datetime import datetime

from astrbot.api import llm_tool, logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, register


@register("astrbot_plugin_feish_calendar", "nonpricklycactus", "飞书日历插件", "1.0.8")
class AkashaCalendarPlugin(Star):
    # 明确列出插件提供的工具列表
    TOOLS = [
        "create_feishu_event",
        "delete_feishu_event",
        "delete_feishu_calendar"  
    ]

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        # 增加 strip() 防止 WebUI 复制粘贴带空格引发玄学权限 Bug
        self.calendar_name = self.config.get("calendar_name", "AstrBot Calendar").strip()
        self.calendar_id = self.config.get("calendar_id", "").strip()
        self.tenant_access_token = ""
        self.token_expire_time = 0
        
        # 🚀 优化点 1: 全局会话与并发锁初始化
        self._session: aiohttp.ClientSession = None
        self._token_lock = asyncio.Lock()
        self._calendar_lock = asyncio.Lock()
        
        logger.info(f"飞书日历插件初始化完成，当前挂载日历名: {self.calendar_name}")

    async def _get_session(self) -> aiohttp.ClientSession:
        """惰性初始化并全局复用 ClientSession，利用底层 TCP 连接池 (Keep-Alive)"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def terminate(self):
        """插件终止时的回调，优雅释放网络资源"""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("飞书日历插件已终止，网络连接池已释放")

    async def _get_valid_token(self) -> str:
        """动态获取飞书 Token (带并发锁防护)"""
        app_id = self.config.get("app_id", "").strip()
        app_secret = self.config.get("app_secret", "").strip()

        if not app_id or not app_secret:
            logger.error("WebUI 中未配置飞书的 App ID 或 Secret")
            return ""

        current_time = int(time.time())
        # 第一层检查：无锁快速返回
        if self.tenant_access_token and current_time < self.token_expire_time - 300:
            return self.tenant_access_token

        # 🚀 优化点 2: 引入并发锁，防止高并发下多个协程同时去刷 Token
        async with self._token_lock:
            # 第二层检查 (Double-Checked Locking)：防止等待锁期间被其他协程刷新
            if self.tenant_access_token and current_time < self.token_expire_time - 300:
                return self.tenant_access_token

            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            session = await self._get_session()
            try:
                async with session.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=15) as resp:
                    data = await resp.json()
                    if data.get("code") == 0:
                        self.tenant_access_token = data.get("tenant_access_token")
                        self.token_expire_time = current_time + data.get("expire", 7200)
                        logger.info("✅ 成功获取 Tenant Access Token")
                        return self.tenant_access_token
                    else:
                        logger.error(f"获取Token失败: {data.get('msg')}")
            except Exception as e:
                logger.error(f"获取飞书 Token 发生异常: {e}")
                
        return ""

    async def _init_calendar(self, token: str) -> tuple[str, bool]:
        """初始化逻辑：查找同名日历 -> 找不到则创建 (带并发锁防护)"""
        # 第一层检查
        if self.calendar_id:
            return self.calendar_id, False

        # 🚀 优化点 3: 引入日历锁，防止大模型并发调用时创建出多个同名日历
        async with self._calendar_lock:
            # 第二层检查
            if self.calendar_id:
                return self.calendar_id, False

            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            list_url = "https://open.feishu.cn/open-apis/calendar/v4/calendars"
            session = await self._get_session()

            # 1. 查找现有同名日历
            try:
                async with session.get(list_url, headers=headers, timeout=15) as resp:
                    list_data = await resp.json()
                    if list_data.get("code") == 0:
                        calendars = list_data.get("data", {}).get("calendar_list", [])
                        for cal in calendars:
                            if cal.get("summary") == self.calendar_name:
                                self.calendar_id = cal.get("calendar_id")
                                logger.info(f"✅ 发现现有日历: {self.calendar_name} ({self.calendar_id})")
                                return self.calendar_id, False
            except Exception as e:
                logger.error(f"查找现有日历异常: {e}")

            # 2. 创建新日历
            logger.info(f"🚀 正在为机器人创建全新公开日历: {self.calendar_name}")
            payload = {
                "summary": self.calendar_name,
                "description": "由 AstrBot 自动管理的公开日程日历",
                "permissions": "public" 
            }
            try:
                async with session.post(list_url, headers=headers, json=payload, timeout=15) as resp:
                    res_data = await resp.json()
                    if res_data.get("code") == 0:
                        self.calendar_id = res_data["data"]["calendar"]["calendar_id"]
                        logger.info(f"🎉 日历创建成功！ID: {self.calendar_id}")
                        return self.calendar_id, True
            except Exception as e:
                logger.error(f"创建日历异常: {e}")

        return "", False

    def _parse_to_timestamp(self, time_str: str) -> int:
        """防呆设计：兼容纯数字 Unix 时间戳和 YYYY-MM-DD HH:MM:SS 字符串"""
        try:
            return int(time_str)
        except ValueError:
            dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            return int(dt.timestamp())

    @llm_tool(name="create_feishu_event")
    async def create_event(self, event: AstrMessageEvent, title: str, start_timestamp: str, end_timestamp: str):
        """
        在飞书日历中创建一个新的日程。

        Args:
            title (str): 日程标题
            start_timestamp (str): 开始时间。接受 Unix时间戳秒数 或 "YYYY-MM-DD HH:MM:SS" 格式
            end_timestamp (str): 结束时间。接受 Unix时间戳秒数 或 "YYYY-MM-DD HH:MM:SS" 格式
        """
        logger.info(f"工具调用: create_feishu_event, 标题={title}")
        token = await self._get_valid_token()
        if not token:
            yield event.plain_result("❌ 系统异常：无法获取飞书 API 鉴权 Token，请检查后台配置。")
            return

        calendar_id, is_newly_created = await self._init_calendar(token)
        if not calendar_id:
            yield event.plain_result("❌ 系统异常：无法获取或创建日历。")
            return

        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        try:
            start_ts = self._parse_to_timestamp(start_timestamp)
            end_ts = self._parse_to_timestamp(end_timestamp)
            if end_ts <= start_ts:
                end_ts = start_ts + 3600  

            payload = {
                "summary": title,
                "start_time": {"timestamp": str(start_ts), "timezone": "Asia/Shanghai"},
                "end_time": {"timestamp": str(end_ts), "timezone": "Asia/Shanghai"}
            }
        except ValueError as e:
            msg = f"❌ 时间解析错误: {e}\n请提供有效的 Unix 时间戳或 'YYYY-MM-DD HH:MM:SS' 格式的时间。"
            logger.error(msg)
            yield event.plain_result(msg)
            return

        session = await self._get_session()
        try:
            async with session.post(url, headers=headers, json=payload, timeout=15) as resp:
                res_data = await resp.json()
                if res_data.get("code") == 0:
                    event_id = res_data.get("data", {}).get("event", {}).get("event_id", "")
                    success_msg = f"✅ 成功创建日历事件！\n• 标题: {title}\n• 事件ID: {event_id}\n• 日历ID: {calendar_id}"

                    if is_newly_created:
                        applink = "https://applink.feishu.cn/client/calendar/open"
                        subscribe_info = (
                            f"\n\n🔔 **新日历订阅提醒**\n"
                            f"系统为您自动创建了默认日历「{self.calendar_name}」。\n"
                            f"👉 快捷打开日历: {applink}\n"
                            f"🔍 **操作指引**：在飞书日历中搜索并订阅该日历ID `{calendar_id}`，即可看到同步的日程！"
                        )
                        success_msg += subscribe_info

                    yield event.plain_result(success_msg)
                else:
                    error_msg = res_data.get('msg', '未知错误')
                    yield event.plain_result(
                        f"❌ 创建失败，飞书 API 报错：{error_msg} (错误码: {res_data.get('code')})")
        except Exception as e:
            yield event.plain_result(f"❌ 创建日程时发生网络异常: {e}")

    @llm_tool(name="delete_feishu_event")
    async def delete_event(self, event: AstrMessageEvent, event_id: str):
        """
        删除一个已存在的飞书日历日程（单个事件）。

        Args:
            event_id (str): 之前创建日程时系统返回的唯一事件 ID。
        """
        logger.info(f"工具调用: delete_feishu_event, 事件ID={event_id}")
        token = await self._get_valid_token()
        if not token:
            yield event.plain_result("❌ 系统异常：无法获取飞书 API 鉴权 Token。")
            return

        calendar_id, _ = await self._init_calendar(token)
        if not calendar_id:
            yield event.plain_result("❌ 系统异常：未找到绑定的日历ID，无法执行删除。")
            return

        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {token}"}
        session = await self._get_session()

        try:
            async with session.delete(url, headers=headers, timeout=15) as resp:
                res_data = await resp.json()
                if res_data.get("code") == 0:
                    yield event.plain_result(f"✅ 清理完成: 事件 {event_id} 已成功移除。")
                else:
                    yield event.plain_result(
                        f"❌ 删除失败，飞书 API 报错：{res_data.get('msg')} (错误码: {res_data.get('code')})")
        except Exception as e:
            yield event.plain_result(f"❌ 删除日历时发生网络异常: {e}")

    @llm_tool(name="delete_feishu_calendar")
    async def delete_calendar(self, event: AstrMessageEvent, calendar_id: str):
        """
        彻底删除整个飞书日历（危险操作，只有创建该日历的机器人才有权限执行）。

        Args:
            calendar_id (str): 日历的唯一 ID。
        """
        logger.info(f"工具调用: delete_feishu_calendar, 日历ID={calendar_id}")
        token = await self._get_valid_token()
        if not token:
            yield event.plain_result("❌ 无法获取 Token。")
            return

        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        session = await self._get_session()

        try:
            async with session.delete(url, headers=headers, timeout=15) as resp:
                res_data = await resp.json()
                if res_data.get("code") == 0:
                    async with self._calendar_lock:
                        if self.calendar_id == calendar_id:
                            self.calendar_id = ""
                    yield event.plain_result(
                        f"✅ 日历 `{calendar_id}` 已成功从飞书服务器永久删除。你可以要求重新创建日程，系统会自动生成新日历。")
                else:
                    msg = f"❌ 删除失败！原因: {res_data.get('msg')} (错误码: {res_data.get('code')})"
                    if res_data.get('code') == 92007:
                        msg += "\n💡 提示：该应用没有此日历的管理权限，或者该日历已被手动删除。"
                    yield event.plain_result(msg)
        except Exception as e:
            yield event.plain_result(f"❌ 删除日历时发生异常: {e}")
