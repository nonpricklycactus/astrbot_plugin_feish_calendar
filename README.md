# AstrBot 飞书日历插件

这是一个为 AstrBot 设计的飞书日历插件，支持自动创建、删除和管理飞书日历中的日程。

## 功能特性

- **自动创建日历**：当 `calendar_id` 为空时，自动创建飞书日历并回填配置
- **日程管理**：支持创建和删除飞书日历日程
- **智能回填**：自动检测已存在的日历，避免重复创建
- **Token 管理**：自动处理飞书 API Token 的获取和刷新

## 安装配置

### 1. 前置要求

- 已安装 AstrBot
- 拥有飞书开放平台应用权限
- 应用需要具备日历相关 API 权限

### 2. 配置参数

在 AstrBot 插件配置中设置以下参数：

| 参数名 | 类型 | 说明 | 默认值 |
|--------|------|------|--------|
| `app_id` | string | 飞书应用的 App ID (cli_ 开头) | 空 |
| `app_secret` | password | 飞书应用的 App Secret | 空 |
| `calendar_id` | string | 日历 ID (feishu.cn_ 开头)，为空时自动创建 | 空 |

### 3. 飞书应用配置

1. 登录 [飞书开放平台](https://open.feishu.cn/)
2. 创建企业自建应用
3. 为应用添加以下权限：
   - `calendar:calendar:readonly` (查看日历)
   - `calendar:calendar:write` (写入日历)
   - `calendar:event:readonly` (查看日程)
   - `calendar:event:write` (写入日程)
4. 发布应用并获取 `app_id` 和 `app_secret`

## 使用方法

### 创建日程

插件提供 `create_feishu_event` 工具，用于在飞书日历中创建新日程：

```python
# 通过 LLM 工具调用
await create_feishu_event(
    title="团队会议",
    start_timestamp="1672531200",  # Unix 时间戳（秒）
    end_timestamp="1672534800"
)
```

### 删除日程

插件提供 `delete_feishu_event` 工具，用于删除已存在的日程：

```python
# 通过 LLM 工具调用
await delete_feishu_event(
    event_id="event_123456"  # 之前创建时返回的事件 ID
)
```

## 自动日历创建功能

当 `calendar_id` 配置为空时，插件会自动执行以下操作：

1. **检查现有日历**：查询用户已有的日历列表
2. **智能匹配**：查找名为 "AstrBot Calendar" 的日历
3. **自动创建**：如果不存在则创建新日历
4. **配置回填**：将创建的日历 ID 自动保存到配置中

## 错误处理

- **Token 失效**：自动刷新 Tenant Access Token
- **网络异常**：提供友好的错误提示
- **权限不足**：提示检查应用权限配置
- **日历不存在**：自动创建新日历

## 版本历史

- **v1.0.4** (当前版本)
  - 添加自动日历创建功能
  - 完善 README 文档

- **v1.0.3** 
  - 初始版本，支持基本的日程创建和删除

## 开发说明

### 项目结构

```
astrbot_plugin_feish_calendar/
├── main.py              # 主插件逻辑
├── metadata.yaml        # 插件元数据
├── _conf_schema.json    # 配置 schema
├── README.md           # 本文档
└── LICENSE             # 许可证文件
```

### API 接口

插件使用飞书开放平台的以下 API：

- `POST /auth/v3/tenant_access_token/internal` - 获取访问令牌
- `GET /calendar/v4/calendars` - 获取日历列表
- `POST /calendar/v4/calendars` - 创建日历
- `POST /calendar/v4/calendars/{calendar_id}/events` - 创建日程
- `DELETE /calendar/v4/calendars/{calendar_id}/events/{event_id}` - 删除日程

## 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

## 作者

- **nonpricklycactus** - 插件开发者
- 项目主页: https://gentlecactus.top

## 问题反馈

如遇到问题或有功能建议，请通过以下方式反馈：

1. 在 GitHub 仓库提交 Issue
2. 通过飞书联系作者
3. 查看飞书开放平台文档获取 API 相关帮助