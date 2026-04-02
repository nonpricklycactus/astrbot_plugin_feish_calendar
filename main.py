import aiohttp
import time

from astrbot.api import llm_tool, logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register


@register("astrbot_plugin_feish_calendar", "nonpricklycactus", "飞书日历插件", "1.0.5")
class AkashaCalendarPlugin(Star):
    # 明确列出插件提供的工具列表，便于框架识别和管理
    TOOLS = [
        "create_feishu_event",
        "delete_feishu_event",
    ]

    # 🚀 兼容 V4 的依赖注入机制，带上 config: dict = None
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.tenant_access_token = ""
        self.token_expire_time = 0
        logger.info(f"飞书日历插件初始化完成，插件ID: astrbot_plugin_feish_calendar，配置: {list(self.config.keys())}")

    async def initialize(self):
        """插件初始化完成后的回调"""
        logger.info("飞书日历插件已激活，工具已注册")

    async def terminate(self):
        """插件终止时的回调"""
        logger.info("飞书日历插件已终止")

    async def _get_valid_token(self) -> str:
        """动态获取配置与 Token (支持网页后台热更新)"""
        app_id = self.config.get("app_id", "")
        app_secret = self.config.get("app_secret", "")

        if not app_id or not app_secret:
            logger.error("WebUI 中未配置飞书的 App ID 或 Secret")
            return ""

        current_time = int(time.time())
        if self.tenant_access_token and current_time < self.token_expire_time - 300:
            logger.info(f"使用缓存的Token，过期时间: {self.token_expire_time - current_time}秒后")
            return self.tenant_access_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        try:
            async with aiohttp.ClientSession() as session:
                logger.info(f"请求飞书Token: app_id={app_id[:8]}...")
                async with session.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=15) as resp:
                    response_text = await resp.text()
                    logger.info(f"获取Token响应状态: {resp.status}")
                    
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"获取TokenAPI响应数据: {data}")
                        
                        if data.get("code") == 0:
                            self.tenant_access_token = data.get("tenant_access_token")
                            expire_time = data.get("expire", 7200)
                            self.token_expire_time = current_time + expire_time
                            logger.info(f"成功获取Token，过期时间: {expire_time}秒")
                            return self.tenant_access_token
                        else:
                            error_msg = data.get('msg', '未知错误')
                            error_code = data.get('code', '未知')
                            logger.error(f"获取Token失败，飞书 API 报错: {error_msg}, 错误码: {error_code}")
                    else:
                        logger.error(f"获取TokenHTTP错误: {resp.status}, 响应: {response_text[:500]}")
        except Exception as e:
            logger.error(f"获取飞书 Token 发生异常: {e}")
        return ""

    async def _ensure_calendar_id(self) -> str:
        """确保 calendar_id 存在，如果为空则自动创建或查找现有日历"""
        calendar_id = self.config.get("calendar_id", "")

        if calendar_id:
            logger.info(f"使用配置中的calendar_id: {calendar_id}")
            return calendar_id

        token = await self._get_valid_token()
        if not token:
            logger.error("无法获取有效的飞书 Token，无法创建日历")
            return ""

        # 首先检查是否已存在名为 "AstrBot Calendar" 的日历
        existing_calendar_id = await self._find_existing_calendar(token)
        if existing_calendar_id:
            logger.info(f"找到现有AstrBot日历: {existing_calendar_id}")
            # 更新配置中的 calendar_id
            await self._update_config_calendar_id(existing_calendar_id)
            return existing_calendar_id

        # 尝试查找主日历作为备选
        primary_calendar_id = await self._find_primary_calendar(token)
        if primary_calendar_id:
            logger.info(f"使用主日历作为备选: {primary_calendar_id}")
            # 更新配置中的 calendar_id
            await self._update_config_calendar_id(primary_calendar_id)
            return primary_calendar_id

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
                    response_text = await resp.text()
                    logger.info(f"查找日历响应状态: {resp.status}")
                    
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"查找日历API响应数据，日历数量: {len(data.get('data', {}).get('calendar_list', []))}")
                        
                        if data.get("code") == 0:
                            calendars = data.get("data", {}).get("calendar_list", [])
                            logger.info(f"查找日历列表: {[cal.get('summary', '无名称') for cal in calendars[:5]]}")
                            for calendar in calendars:
                                calendar_summary = calendar.get("summary", "")
                                if calendar_summary == "AstrBot Calendar":
                                    calendar_id = calendar.get("calendar_id", "")
                                    logger.info(f"找到匹配的AstrBot日历: {calendar_summary}, ID: {calendar_id}")
                                    return calendar_id
                        else:
                            logger.error(f"查找日历API错误: {data.get('msg', '未知错误')}, 错误码: {data.get('code')}")
                    else:
                        logger.error(f"查找日历HTTP错误: {resp.status}, 响应: {response_text[:500]}")
        except Exception as e:
            logger.error(f"查找现有日历时发生异常: {e}")

        return ""

    async def _find_primary_calendar(self, token: str) -> str:
        """查找主日历作为备选方案"""
        url = "https://open.feishu.cn/open-apis/calendar/v4/calendars"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=30) as resp:
                    response_text = await resp.text()
                    logger.info(f"查找主日历响应状态: {resp.status}")
                    
                    if resp.status == 200:
                        data = await resp.json()
                        
                        if data.get("code") == 0:
                            calendars = data.get("data", {}).get("calendar_list", [])
                            # 查找第一个非空日历作为主日历（通常第一个是主日历）
                            for calendar in calendars:
                                calendar_id = calendar.get("calendar_id", "")
                                if calendar_id:
                                    summary = calendar.get("summary", "未命名日历")
                                    logger.info(f"找到主日历备选: {summary}, ID: {calendar_id}")
                                    return calendar_id
                        else:
                            logger.error(f"查找主日历API错误: {data.get('msg', '未知错误')}, 错误码: {data.get('code')}")
                    else:
                        logger.error(f"查找主日历HTTP错误: {resp.status}, 响应: {response_text[:500]}")
        except Exception as e:
            logger.error(f"查找主日历时发生异常: {e}")

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
            "permissions": "public",  # 公共日历，便于查找和访问
            "color": -1,  # 默认颜色
            "summary_alias": "AstrBot",
            "type": "shared",  # 共享日历类型
            "role": "owner"  # 应用作为日历所有者
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
                    response_text = await resp.text()
                    logger.info(f"创建日历响应状态: {resp.status}, 响应: {response_text[:500]}")
                    
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"创建日历API响应数据: {data}")
                        
                        if data.get("code") == 0:
                            calendar_id = data.get("data", {}).get("calendar", {}).get("calendar_id", "")
                            if calendar_id:
                                logger.info(f"成功创建日历，calendar_id: {calendar_id}")
                                return calendar_id
                            else:
                                logger.error(f"创建日历成功但未返回 calendar_id，响应数据: {data}")
                        else:
                            error_msg = data.get('msg', '未知错误')
                            logger.error(f"创建日历失败，飞书 API 报错: {error_msg}, 错误码: {data.get('code')}")
                    else:
                        logger.error(f"创建日历 HTTP 错误: {resp.status}, 响应: {response_text[:500]}")
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

    async def _verify_calendar_access(self, token: str, calendar_id: str) -> bool:
        """验证日历访问权限和类型"""
        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=30) as resp:
                    response_text = await resp.text()
                    logger.info(f"验证日历访问响应状态: {resp.status}")
                    
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"日历信息API响应: {data}")
                        
                        if data.get("code") == 0:
                            calendar_info = data.get("data", {}).get("calendar", {})
                            calendar_type = calendar_info.get("type", "")
                            calendar_summary = calendar_info.get("summary", "")
                            calendar_role = calendar_info.get("role", "")
                            
                            logger.info(f"日历信息: 类型={calendar_type}, 名称={calendar_summary}, 角色={calendar_role}")
                            
                            # 验证日历类型和角色
                            if calendar_type in ["primary", "shared"] and calendar_role in ["owner", "writer"]:
                                logger.info(f"日历访问权限验证通过: {calendar_id}")
                                return True
                            else:
                                logger.warning(f"日历权限可能不足: 类型={calendar_type}, 角色={calendar_role}")
                                return False
                        else:
                            logger.error(f"获取日历信息失败: {data.get('msg', '未知错误')}")
                            return False
                    else:
                        logger.error(f"验证日历访问HTTP错误: {resp.status}, 响应: {response_text[:500]}")
                        return False
        except Exception as e:
            logger.error(f"验证日历访问时发生异常: {e}")
            return False

    @llm_tool(name="create_feishu_event")
    async def create_event(self, event: AstrMessageEvent, title: str, start_timestamp: str, end_timestamp: str):
        """
        在主人的飞书日历中创建一个新的日程。必须在获得主人明确同意后调用。
        
        Args:
            title (string): 日程标题
            start_timestamp (string): 开始时间的 Unix 时间戳（精确到秒的字符串）
            end_timestamp (string): 结束时间的 Unix 时间戳（精确到秒的字符串）
        """
        logger.info(f"飞书日历插件: 调用 create_feishu_event 工具，标题: {title}")
        token = await self._get_valid_token()
        if not token:
            yield event.plain_result("❌ 系统异常：无法获取飞书 API 鉴权 Token，请检查后台配置。")
            return

        # 确保 calendar_id 存在，如果为空则自动创建或查找
        calendar_id = await self._ensure_calendar_id()
        if not calendar_id:
            yield event.plain_result("❌ 系统异常：无法获取或创建日历，请检查飞书应用权限。")
            return
        
        # 验证日历访问权限
        logger.info(f"验证日历访问权限: {calendar_id}")
        has_access = await self._verify_calendar_access(token, calendar_id)
        if not has_access:
            logger.warning(f"日历访问权限验证失败，继续尝试创建事件")
            # 不立即返回，继续尝试创建事件

        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        # 飞书日历API要求时间戳为字符串格式（秒级）
        try:
            # 验证时间戳格式
            start_ts = int(start_timestamp)
            end_ts = int(end_timestamp)
            
            # 确保结束时间晚于开始时间
            if end_ts <= start_ts:
                end_ts = start_ts + 3600  # 默认1小时
            
            # 根据官方文档，时间戳必须是秒级，不是毫秒级
            payload = {
                "summary": title,
                "description": f"AstrBot自动创建的日程: {title}",
                "start_time": {
                    "timestamp": str(start_ts),  # 秒级时间戳
                    "timezone": "Asia/Shanghai"  # 添加时区
                },
                "end_time": {
                    "timestamp": str(end_ts),  # 秒级时间戳
                    "timezone": "Asia/Shanghai"  # 添加时区
                },
                "visibility": "default",  # 默认可见性，跟随日历权限
                "attendee_ability": "can_see_others",  # 参与者可以看到其他参与者
                "free_busy_status": "busy"  # 忙碌状态
            }
            logger.info(f"创建事件Payload: {payload}")
        except ValueError as e:
            logger.error(f"时间戳格式错误: {start_timestamp}, {end_timestamp}, 错误: {e}")
            yield event.plain_result("❌ 时间戳格式错误，请提供有效的Unix时间戳（秒）")
            return

        try:
            async with aiohttp.ClientSession() as session:
                logger.info(f"创建日历事件请求: URL={url}, Headers={headers}, Payload={payload}")
                async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
                    response_text = await resp.text()
                    logger.info(f"创建日历事件响应状态: {resp.status}, 响应: {response_text[:500]}")
                    
                    if resp.status == 200:
                        res_data = await resp.json()
                        logger.info(f"创建日历事件API响应数据: {res_data}")
                         
                        if res_data.get("code") == 0:
                            event_id = res_data.get("data", {}).get("event", {}).get("event_id", "")
                            event_summary = res_data.get("data", {}).get("event", {}).get("summary", title)
                            if event_id:
                                # 提供更详细的成功信息，包括查看指导
                                # 查询事件详细信息进行验证
                                event_info = await self._get_event_info(token, calendar_id, event_id)
                                
                                if event_info:
                                    event_visibility = event_info.get("visibility", "unknown")
                                    event_start_time = event_info.get("start_time", {}).get("timestamp", "unknown")
                                    event_end_time = event_info.get("end_time", {}).get("timestamp", "unknown")
                                    
                                    logger.info(f"事件验证成功: visibility={event_visibility}, start={event_start_time}, end={event_end_time}")
                                    
                                    success_msg = f"""✅ 成功创建日历事件！
• 事件标题: {event_summary}
• 事件ID: {event_id}
• 日历ID: {calendar_id}
• 可见性: {event_visibility}
• 开始时间: {event_start_time} (UTC秒)
• 结束时间: {event_end_time} (UTC秒)

📅 **查看说明**:
1. 登录飞书客户端或网页版
2. 在日历侧边栏中查找 "AstrBot Calendar"（可能需要手动订阅）
3. 如果找不到，可能是日历权限问题，请检查飞书应用权限设置
4. 确保查看的时间范围包含事件时间（时间戳: {event_start_time} - {event_end_time}）
5. 如需验证，可使用事件ID在飞书日历中搜索"""
                                else:
                                    success_msg = f"""✅ 事件创建API调用成功！
• 事件标题: {event_summary}
• 事件ID: {event_id}
• 日历ID: {calendar_id}

⚠️ 注意：事件创建成功，但查询验证失败。
请在飞书客户端中查看日历，如不可见，请检查：
1. 日历权限设置（日历需为public或shared）
2. 飞书应用权限（需要calendar:calendar和calendar:calendar.event权限）
3. 时间范围是否正确"""
                                
                                yield event.plain_result(success_msg)
                                logger.info(f"成功创建日历事件: event_id={event_id}, calendar_id={calendar_id}, summary={event_summary}")
                            else:
                                error_msg = "API返回成功但未包含event_id"
                                logger.error(f"{error_msg}, 响应数据: {res_data}")
                                yield event.plain_result(f"❌ 创建失败: {error_msg}\n\nAPI响应: {res_data}")
                        else:
                            error_msg = res_data.get('msg', '未知错误')
                            error_code = res_data.get('code', '未知')
                            logger.error(f"创建日历事件失败，飞书 API 报错: {error_msg}, 错误码: {error_code}")
                            yield event.plain_result(f"❌ 创建失败，飞书 API 报错：{error_msg} (错误码: {error_code})")
                    else:
                        logger.error(f"创建日历事件HTTP错误: {resp.status}, 响应: {response_text[:500]}")
                        yield event.plain_result(f"❌ 创建失败，HTTP 错误: {resp.status}")
        except Exception as e:
            logger.error(f"创建日历时发生网络异常: {e}")
            yield event.plain_result(f"❌ 创建日历时发生网络异常: {e}")

    async def _get_event_info(self, token: str, calendar_id: str, event_id: str) -> dict:
        """获取事件详细信息"""
        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events/{event_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=30) as resp:
                    response_text = await resp.text()
                    logger.info(f"获取事件信息响应状态: {resp.status}")
                    
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"事件信息API响应: {data}")
                        
                        if data.get("code") == 0:
                            event_info = data.get("data", {}).get("event", {})
                            return event_info
                        else:
                            logger.error(f"获取事件信息失败: {data.get('msg', '未知错误')}")
                            return {}
                    else:
                        logger.error(f"获取事件信息HTTP错误: {resp.status}, 响应: {response_text[:500]}")
                        return {}
        except Exception as e:
            logger.error(f"获取事件信息时发生异常: {e}")
            return {}

    @llm_tool(name="delete_feishu_event")
    async def delete_event(self, event: AstrMessageEvent, event_id: str):
        """
        删除一个已存在的飞书日历日程。用于计划变更或取消时。
        
        Args:
            event_id (string): 之前创建日程时系统返回的唯一事件 ID。
        """
        logger.info(f"飞书日历插件: 调用 delete_feishu_event 工具，事件ID: {event_id}")
        token = await self._get_valid_token()
        if not token:
            logger.error("删除事件失败: 无法获取Token")
            yield event.plain_result("❌ 系统异常：无法获取飞书 API 鉴权 Token。")
            return

        # 确保 calendar_id 存在，如果为空则自动创建或查找
        calendar_id = await self._ensure_calendar_id()
        if not calendar_id:
            logger.error(f"删除事件失败: 无法获取calendar_id，事件ID: {event_id}")
            yield event.plain_result("❌ 系统异常：无法获取或创建日历，请检查飞书应用权限。")
            return

        url = f"https://open.feishu.cn/open-apis/calendar/v4/calendars/{calendar_id}/events/{event_id}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            async with aiohttp.ClientSession() as session:
                logger.info(f"删除日历事件请求: URL={url}, Headers={headers}")
                async with session.delete(url, headers=headers, timeout=30) as resp:
                    response_text = await resp.text()
                    logger.info(f"删除日历事件响应状态: {resp.status}, 响应: {response_text[:500]}")
                    
                    if resp.status == 200:
                        res_data = await resp.json()
                        logger.info(f"删除日历事件API响应数据: {res_data}")
                        
                        if res_data.get("code") == 0:
                            yield event.plain_result(f"✅ 清理完成: 事件 {event_id} 已成功移除。")
                            logger.info(f"成功删除日历事件: event_id={event_id}, calendar_id={calendar_id}")
                        else:
                            error_msg = res_data.get('msg', '未知错误')
                            error_code = res_data.get('code', '未知')
                            logger.error(f"删除日历事件失败，飞书 API 报错: {error_msg}, 错误码: {error_code}")
                            yield event.plain_result(f"❌ 删除失败，飞书 API 报错：{error_msg} (错误码: {error_code})")
                    else:
                        logger.error(f"删除日历事件HTTP错误: {resp.status}, 响应: {response_text[:500]}")
                        yield event.plain_result(f"❌ 删除失败，HTTP 错误: {resp.status}")
        except Exception as e:
            logger.error(f"删除日历时发生网络异常: {e}")
            yield event.plain_result(f"❌ 删除日历时发生网络异常: {e}")