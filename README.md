# AI Trending News Platform

一个基于 Bing 和 MSN 搜索结果的热点事件发布管理平台。

## 功能特点

- 登录认证系统
- 热点事件搜索和预览
- 自动从 Bing 和 MSN 获取内容
- 事件管理（发布/删除）
- 发布前预览功能
- Bing 每日图片作为登录背景

## 安装部署

# 自动更新并安装
./update.sh

# 或手动安装
pip3 install -r requirements.txt

python3 app.py


5. 访问平台：
- 地址：http://localhost:5000
- 用户名：admin
- 密码：password


## 技术栈

- 后端：Flask
- 数据库：SQLite + SQLAlchemy
- 前端：HTML, CSS, JavaScript
- 外部 API：
  - Bing 搜索
  - MSN 新闻
  - Bing 每日图片 API

## 开发说明

### 环境要求

- Python 3.x
- pip3
- 虚拟环境 (推荐)

### 忽略文件

项目已配置 `.gitignore` 忽略以下文件：
- Python 缓存文件 (`__pycache__/`)
- 虚拟环境文件 (`venv/`, `ENV/`)
- 数据库文件 (`*.db`, `*.sqlite3`)
- IDE 配置文件 (`.idea/`, `.vscode/`)
- 生成的事件文件 (`static/events/*`)
- 系统文件 (`.DS_Store`, `Thumbs.db`)

## 使用说明

1. 登录系统
   - 使用默认账户登录
   - 登录页面背景自动获取 Bing 每日图片

2. 管理热点事件
   - 在搜索框输入关键词
   - 点击"生成预览"查看效果
   - 预览页面可选择发布或取消
   - 已发布的事件可以删除

## 注意事项

- 确保 `static/events` 目录存在且有写入权限
- 首次运行会自动创建数据库和管理员账户
- 所有生成的事件页面都保存在 `static/events` 目录下

## License

[MIT License](LICENSE)