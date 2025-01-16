from flask import Flask, request, jsonify, render_template_string, send_from_directory
import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime, timedelta
from models import db, Event, User
from notion_utils import NotionManager
from dotenv import load_dotenv
import re
import signal
import sys

load_dotenv()

app = Flask(__name__, static_folder='static')

# 数据库配置
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trending.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# 确保events目录存在
EVENTS_DIR = 'static/events'
os.makedirs(EVENTS_DIR, exist_ok=True)

# 添加新的配置
GITHUB_PAGES_DIR = 'docs'  # GitHub Pages 默认使用 /docs 目录
os.makedirs(GITHUB_PAGES_DIR, exist_ok=True)

# 配置 Notion
NOTION_TOKEN = os.getenv('NOTION_TOKEN')
NOTION_DATABASE_ID = os.getenv('NOTION_DATABASE_ID')
notion_manager = NotionManager(NOTION_TOKEN, NOTION_DATABASE_ID)

# 创建所有数据库表
def init_db():
    try:
        with app.app_context():
            db.create_all()
            # 创建默认管理员用户
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin', password='password')
                db.session.add(admin)
                db.session.commit()
            print("数据库初始化成功")  # 添加成功日志
    except Exception as e:
        print(f"数据库初始化错误: {str(e)}")  # 添加错误日志

def signal_handler(sig, frame):
    """处理退出信号"""
    print('正在关闭应用...')
    sys.exit(0)

# 注册信号处理器
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

@app.route('/')
def index():
    return send_from_directory('static', 'login.html')

@app.route('/dashboard.html')
def dashboard():
    return send_from_directory('static', 'dashboard.html')

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    user = User.query.filter_by(username=username).first()
    
    if user and user.password == password:
        return jsonify({
            'success': True,
            'message': '登录成功'
        })
    else:
        return jsonify({
            'success': False,
            'message': '用户名或密码错误'
        }), 401

@app.route('/api/search')
def search():
    keyword = request.args.get('keyword')
    
    # 搜索Bing、MSN和百度
    bing_results = search_bing(keyword)
    msn_results = search_msn(keyword)
    baidu_results = search_baidu(keyword)
    
    # 生成结果页面
    page_url = generate_results_page(keyword, bing_results, msn_results, baidu_results)
    
    # 创建 Notion 页面
    content = format_content_for_notion(keyword, bing_results, msn_results, baidu_results)
    notion_page_id = notion_manager.create_page(
        title=keyword,
        content=content,
        url=request.host_url + page_url.lstrip('/')
    )
    
    # 保存到数据库
    event = Event(
        keyword=keyword,
        url=page_url,
        notion_page_id=notion_page_id
    )
    db.session.add(event)
    db.session.commit()
    
    # 删除对应的预览文件
    delete_preview_file(keyword)
    
    return jsonify({
        'url': page_url,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

def format_content_for_notion(keyword, bing_results, msn_results, baidu_results):
    content = ""
    
    if bing_results:
        for result in bing_results:
            content += f"• {result.get('title', '')}\n{result.get('snippet', '')}\n{result.get('link', '')}\n\n"
    
    if msn_results:
        for result in msn_results:
            content += f"• {result.get('title', '')}\n{result.get('snippet', '')}\n{result.get('link', '')}\n\n"
    
    return content.strip()

@app.route('/api/events')
def get_events():
    try:
        events = Event.query.order_by(Event.timestamp.desc()).all()
        return jsonify([event.to_dict() for event in events])
    except Exception as e:
        print(f"获取事件列表错误: {str(e)}")  # 添加错误日志
        return jsonify([])

@app.route('/api/events/<int:event_id>', methods=['DELETE'])
def delete_event(event_id):
    event = Event.query.get_or_404(event_id)
    
    # 删除关联的HTML文件
    if event.url.startswith('/static/events/'):
        file_path = os.path.join(app.static_folder, 'events', os.path.basename(event.url))
        if os.path.exists(file_path):
            os.remove(file_path)
    
    # 从数据库中删除记录
    db.session.delete(event)
    db.session.commit()
    
    return jsonify({'success': True, 'message': '删除成功'})

@app.route('/api/preview')
def preview():
    try:
        keyword = request.args.get('keyword')
        if not keyword:
            return jsonify({'error': 'Keyword is required'}), 400
            
        print(f"Generating preview for keyword: {keyword}")
        
        # 搜索Bing和MSN
        bing_results = search_bing(keyword)
        print(f"Got {len(bing_results)} results from Bing")
        
        msn_results = search_msn(keyword)
        print(f"Got {len(msn_results)} results from MSN")
        
        if not bing_results and not msn_results:
            print("Warning: No results found from either Bing or MSN")
        
        # 生成预览页面
        page_url = generate_preview_page(keyword, bing_results, msn_results)
        print(f"Generated preview page: {page_url}")
        
        return jsonify({
            'url': page_url,
            'bing_count': len(bing_results),
            'msn_count': len(msn_results)
        })
    except Exception as e:
        print(f"Error generating preview: {str(e)}")
        return jsonify({'error': str(e)}), 500

def parse_bing_results(html):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    
    # 打印调试信息
    print("Parsing Bing results...")
    news_items = soup.select('.b_algo')
    print(f"Found {len(news_items)} news items in Bing HTML")
    
    for item in news_items[:10]:
        try:
            title_elem = item.find('h2')
            link_elem = item.find('a')
            snippet_elem = item.find('p')
            
            if title_elem and link_elem:
                title = title_elem.get_text(strip=True)
                link = link_elem.get('href', '')
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''
                
                # 检查是否包含日文字符（假名和汉字）
                if any(ord(c) in range(0x3040, 0x30FF) for c in title + snippet):
                    print(f"Skipping Japanese result: {title}")
                    continue
                
                # 尝试获取图片
                image_url = ''
                img = item.find('img')
                if img and img.get('src'):
                    image_url = img.get('src')
                
                # 尝试获取时间
                time = ''
                time_elem = item.find(class_='news_dt') or item.find(class_='datetime')
                if time_elem:
                    time = time_elem.get_text(strip=True)
                
                results.append({
                    'title': title,
                    'link': link,
                    'snippet': snippet,
                    'image_url': image_url,
                    'time': time
                })
                print(f"Successfully parsed Bing result: {title}")
        except Exception as e:
            print(f"Error parsing Bing result: {str(e)}")
            continue
    
    return results

def parse_msn_results(html):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    
    # 打印调试信息
    print("Parsing MSN results...")
    
    # 尝试多个可能的选择器
    selectors = [
        '.contentCard',
        '.article-card',
        '.news-card',
        '.cardContent'
    ]
    
    news_items = []
    for selector in selectors:
        items = soup.select(selector)
        if items:
            print(f"Found {len(items)} items with selector: {selector}")
            news_items = items
            break
    
    for item in news_items[:10]:
        try:
            # 标题可能在不同的标签中
            title_elem = (
                item.select_one('.title') or 
                item.select_one('h3') or 
                item.select_one('.headline') or
                item.select_one('a[data-t*="title"]')
            )
            
            # 链接可能在不同位置
            link_elem = (
                item.select_one('a[href*="/news"]') or
                item.select_one('a[href*="/zh-cn"]') or
                item.select_one('a')
            )
            
            # 摘要可能有不同的类名
            snippet_elem = (
                item.select_one('.abstract') or
                item.select_one('.description') or
                item.select_one('.caption') or
                item.select_one('p')
            )
            
            if title_elem and link_elem:
                title = title_elem.get_text(strip=True)
                link = link_elem.get('href', '')
                # 确保链接是完整的URL
                if link.startswith('/'):
                    link = 'https://www.msn.cn' + link
                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''
                
                # 尝试获取图片
                image_url = ''
                img = item.find('img')
                if img and img.get('src'):
                    image_url = img.get('src')
                
                # 尝试获取时间
                time = ''
                time_elem = (
                    item.select_one('.pubtime') or
                    item.select_one('.time') or
                    item.select_one('.datetime')
                )
                if time_elem:
                    time = time_elem.get_text(strip=True)
                
                results.append({
                    'title': title,
                    'link': link,
                    'snippet': snippet,
                    'image_url': image_url,
                    'time': time
                })
                print(f"Successfully parsed MSN result: {title}")
        except Exception as e:
            print(f"Error parsing MSN result: {str(e)}")
            continue
    
    return results

def search_bing(keyword):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Cookie': 'MUID=1234567890; SRCHD=AF=NOFORM; SRCHUID=V=2&GUID=1234567890; SRCHUSR=DOB=20240115'
    }
    # 使用必应中国的搜索 URL，添加参数以获取中文结果
    url = f"https://cn.bing.com/search?q={keyword}&ensearch=0&FORM=BEHPTB&setmkt=zh-cn&setlang=zh-cn"
    
    try:
        print(f"Fetching Bing results for keyword: {keyword}")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # 检查响应状态
        print(f"Bing response status: {response.status_code}")
        
        # 确保响应是 UTF-8 编码
        response.encoding = 'utf-8'
        
        results = parse_bing_results(response.text)
        print(f"Found {len(results)} results from Bing")
        return results
    except Exception as e:
        print(f"Error searching Bing: {str(e)}")
        return []

def search_msn(keyword):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }
    
    urls = [
        f"https://www.msn.cn/zh-cn/news/search?q={keyword}",
        f"https://www.msn.cn/zh-cn/news/searchresults?q={keyword}",
        f"https://www.msn.cn/zh-cn/search?q={keyword}&category=news"
    ]
    
    all_results = []
    for url in urls:
        try:
            print(f"Trying MSN URL: {url}")
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()  # 检查响应状态
            print(f"MSN response status: {response.status_code}")
            results = parse_msn_results(response.text)
            if results:
                print(f"Found {len(results)} results from MSN")
                all_results.extend(results)
                break
        except Exception as e:
            print(f"Error searching MSN ({url}): {str(e)}")
            continue
    
    # 去重
    seen = set()
    unique_results = []
    for result in all_results:
        if result['link'] not in seen:
            seen.add(result['link'])
            unique_results.append(result)
    
    return unique_results[:10]

# 在文件顶部添加模板定义
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>{{ keyword }} - 热点事件</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background: #f5f6f7;
        }
        .header {
            background: linear-gradient(to bottom, #4e6ef2, #4662d9);
            color: white;
            padding: 20px;
        }
        .header h1 {
            margin: 0;
            font-size: 24px;
        }
        .update-time {
            color: #999;
            font-size: 14px;
            margin-top: 10px;
        }
        .main-container {
            display: flex;
            max-width: 1200px;
            margin: 20px auto;
            gap: 20px;
        }
        .content {
            flex: 1;
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin-left: 310px;
        }
        .timeline {
            width: 300px;
            background: white;
            border-radius: 8px;
            padding: 20px;
            height: fit-content;
            position: absolute;
	left: 150px;
        }
        .timeline-item {
            position: relative;
            padding-left: 24px;
            margin-bottom: 20px;
        }
        .timeline-item::before {
            content: '';
            position: absolute;
            left: 0;
            top: 8px;
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #4e6ef2;
        }
        .timeline-item::after {
            content: '';
            position: absolute;
            left: 3px;
            top: 16px;
            width: 2px;
            height: calc(100% + 12px);
            background: #e5e5e5;
        }
        .timeline-item:last-child::after {
            display: none;
        }
        .timeline-time {
            font-size: 12px;
            color: #999;
            margin-bottom: 4px;
        }
        .timeline-title {
            font-size: 14px;
            color: #333;
        }
        .tabs {
            background: white;
            padding: 0 20px;
            border-bottom: 1px solid #e3e4e5;
            display: flex;
            gap: 30px;
        }
        .tab {
            padding: 15px 0;
            color: #222;
            font-size: 14px;
            cursor: pointer;
            position: relative;
        }
        .tab.active {
            color: #4e6ef2;
            font-weight: bold;
        }
        .tab.active:after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: #4e6ef2;
        }
        .count {
            color: #999;
            margin-left: 5px;
        }
        .news-item {
            display: flex;
            gap: 15px;
            padding: 15px 0;
            border-bottom: 1px solid #f0f0f0;
        }
        .news-item:last-child {
            border-bottom: none;
        }
        .news-thumbnail {
            width: 120px;
            height: 80px;
            background-size: cover;
            background-position: center;
            background-color: #f5f5f5;
            border-radius: 4px;
            flex-shrink: 0;
        }
        .news-content {
            flex: 1;
        }
        .news-time {
            font-size: 12px;
            color: #999;
            margin-bottom: 4px;
        }
        .news-title {
            color: #222;
            font-size: 16px;
            text-decoration: none;
            display: block;
            margin-bottom: 8px;
        }
        .news-title:hover {
            color: #4e6ef2;
        }
        .news-snippet {
            color: #666;
            font-size: 14px;
            line-height: 1.6;
        }
        .source-tag {
            display: inline-block;
            padding: 2px 8px;
            background: #f5f6f7;
            color: #666;
            font-size: 12px;
            border-radius: 4px;
            margin-bottom: 10px;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>{{ keyword }}</h1>
        <div class="update-time">更新至 {{ timestamp }}</div>
    </div>
    <div class="tabs">
        <div class="tab active">全部 <span class="count">{{ bing_results|length + msn_results|length + baidu_results|length }}</span></div>
        <div class="tab">Bing <span class="count">{{ bing_results|length }}</span></div>
        <div class="tab">MSN <span class="count">{{ msn_results|length }}</span></div>
        <div class="tab">百度 <span class="count">{{ baidu_results|length }}</span></div>
    </div>
    <div class="main-container">
        <div class="content">
            {% if bing_results %}
            <div class="source-tag">Bing搜索结果</div>
            {% for result in bing_results %}
            <div class="news-item">
                <div class="news-thumbnail" style="background-image: url('{{ result.get('image_url', '') }}')"></div>
                <div class="news-content">
                    <div class="news-time">{{ result.get('time', '') }}</div>
                    <a href="{{ result.link }}" class="news-title" target="_blank">{{ result.title }}</a>
                    <div class="news-snippet">{{ result.snippet }}</div>
                </div>
            </div>
            {% endfor %}
            {% endif %}

            {% if msn_results %}
            <div class="source-tag">MSN搜索结果</div>
            {% for result in msn_results %}
            <div class="news-item">
                <div class="news-thumbnail" style="background-image: url('{{ result.get('image_url', '') }}')"></div>
                <div class="news-content">
                    <div class="news-time">{{ result.get('time', '') }}</div>
                    <a href="{{ result.link }}" class="news-title" target="_blank">{{ result.title }}</a>
                    <div class="news-snippet">{{ result.snippet }}</div>
                </div>
            </div>
            {% endfor %}
            {% endif %}

            {% if baidu_results %}
            <div class="source-tag">百度搜索结果</div>
            {% for result in baidu_results %}
            <div class="news-item">
                <div class="news-thumbnail" style="background-image: url('{{ result.get('image_url', '') }}')"></div>
                <div class="news-content">
                    <div class="news-time">{{ result.get('time', '') }}</div>
                    <a href="{{ result.link }}" class="news-title" target="_blank">{{ result.title }}</a>
                    <div class="news-snippet">{{ result.snippet }}</div>
                </div>
            </div>
            {% endfor %}
            {% endif %}
        </div>
        
        <div class="timeline">
            <h3>事件进展</h3>
            {% for event in timeline_events %}
            <div class="timeline-item">
                <div class="timeline-time">{{ event.time }}</div>
                <div class="timeline-title">{{ event.title }}</div>
            </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
"""

# 修改 generate_results_page 函数，使用 TEMPLATE
def generate_results_page(keyword, bing_results, msn_results, baidu_results):
    # 提取时间线事件
    timeline_events = extract_timeline_events(bing_results, msn_results, baidu_results)
    
    # 渲染模板
    html_content = render_template_string(
        TEMPLATE,
        keyword=keyword,
        bing_results=bing_results,
        msn_results=msn_results,
        baidu_results=baidu_results,
        timeline_events=timeline_events,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    # 生成唯一文件名
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{keyword}.html"
    # 同时保存到 EVENTS_DIR 和 GITHUB_PAGES_DIR
    events_filepath = os.path.join(EVENTS_DIR, filename)
    github_filepath = os.path.join(GITHUB_PAGES_DIR, filename)
    
    # 保存文件
    with open(events_filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)
    # 同时保存一份到 GitHub Pages 目录
    with open(github_filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    # 更新索引页面
    generate_index_page()
    
    return f"/static/events/{filename}"

def generate_preview_page(keyword, bing_results, msn_results):
    # 提取时间线事件
    timeline_events = extract_timeline_events(bing_results, msn_results, [])
    
    template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>{{ keyword }} - 预览</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 0;
                background: #f5f6f7;
            }
            .header {
                background: linear-gradient(to bottom, #4e6ef2, #4662d9);
                color: white;
                padding: 20px;
            }
            .header h1 {
                margin: 0;
                font-size: 24px;
            }
            .update-time {
                color: #999;
                font-size: 14px;
                margin-top: 10px;
            }
            .main-container {
                display: flex;
                max-width: 1200px;
                margin: 20px auto;
                gap: 20px;
            }
            .content {
                flex: 1;
                background: white;
                border-radius: 8px;
                padding: 20px;
		margin-left: 310px;
            }
		.timeline {
		    width: 300px;
		    background: white;
		    border-radius: 8px;
		    padding: 20px;
		    height: fit-content;
		    position: absolute;
		    left: 150px;
		}
            .timeline-item {
                position: relative;
                padding-left: 24px;
                margin-bottom: 20px;
            }
            .timeline-item::before {
                content: '';
                position: absolute;
                left: 0;
                top: 8px;
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #4e6ef2;
            }
            .timeline-item::after {
                content: '';
                position: absolute;
                left: 3px;
                top: 16px;
                width: 2px;
                height: calc(100% + 12px);
                background: #e5e5e5;
            }
            .timeline-item:last-child::after {
                display: none;
            }
            .timeline-time {
                font-size: 12px;
                color: #999;
                margin-bottom: 4px;
            }
            .timeline-title {
                font-size: 14px;
                color: #333;
            }
            .tabs {
                background: white;
                padding: 0 20px;
                border-bottom: 1px solid #e3e4e5;
                display: flex;
                gap: 30px;
            }
            .tab {
                padding: 15px 0;
                color: #222;
                font-size: 14px;
                cursor: pointer;
                position: relative;
            }
            .tab.active {
                color: #4e6ef2;
                font-weight: bold;
            }
            .tab.active:after {
                content: '';
                position: absolute;
                bottom: 0;
                left: 0;
                right: 0;
                height: 3px;
                background: #4e6ef2;
            }
            .count {
                color: #999;
                margin-left: 5px;
            }
            .news-item {
                display: flex;
                gap: 15px;
                padding: 15px 0;
                border-bottom: 1px solid #f0f0f0;
            }
            .news-item:last-child {
                border-bottom: none;
            }
            .news-thumbnail {
                width: 120px;
                height: 80px;
                background-size: cover;
                background-position: center;
                background-color: #f5f5f5;
                border-radius: 4px;
                flex-shrink: 0;
            }
            .news-content {
                flex: 1;
            }
            .news-time {
                font-size: 12px;
                color: #999;
                margin-bottom: 4px;
            }
            .news-title {
                color: #222;
                font-size: 16px;
                text-decoration: none;
                display: block;
                margin-bottom: 8px;
            }
            .news-title:hover {
                color: #4e6ef2;
            }
            .news-snippet {
                color: #666;
                font-size: 14px;
                line-height: 1.6;
            }
            .source-tag {
                display: inline-block;
                padding: 2px 8px;
                background: #f5f6f7;
                color: #666;
                font-size: 12px;
                border-radius: 4px;
                margin-bottom: 10px;
            }
            .action-buttons {
                position: fixed;
                top: 20px;
                right: 20px;
                display: flex;
                gap: 10px;
                z-index: 1000;
            }
            .action-btn {
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
                color: white;
            }
            .publish-btn {
                background: #52c41a;
            }
            .publish-btn:hover {
                background: #73d13d;
            }
            .cancel-btn {
                background: #ff4d4f;
            }
            .cancel-btn:hover {
                background: #ff7875;
            }
        </style>
    </head>
    <body>
        <div class="action-buttons">
            <button class="action-btn publish-btn" onclick="publishEvent()">发布</button>
            <button class="action-btn cancel-btn" onclick="cancelPreview()">取消</button>
        </div>

        <div class="header">
            <h1>{{ keyword }}</h1>
            <div class="update-time">更新至 {{ timestamp }}</div>
        </div>
        <div class="tabs">
            <div class="tab active">全部 <span class="count">{{ bing_results|length + msn_results|length }}</span></div>
            <div class="tab">Bing <span class="count">{{ bing_results|length }}</span></div>
            <div class="tab">MSN <span class="count">{{ msn_results|length }}</span></div>
        </div>
        <div class="main-container">
            <div class="content">
                {% if bing_results %}
                <div class="source-tag">Bing搜索结果</div>
                {% for result in bing_results %}
                <div class="news-item">
                    <div class="news-thumbnail" style="background-image: url('{{ result.get('image_url', '') }}')"></div>
                    <div class="news-content">
                        <div class="news-time">{{ result.get('time', '') }}</div>
                        <a href="{{ result.link }}" class="news-title" target="_blank">{{ result.title }}</a>
                        <div class="news-snippet">{{ result.snippet }}</div>
                    </div>
                </div>
                {% endfor %}
                {% endif %}

                {% if msn_results %}
                <div class="source-tag">MSN搜索结果</div>
                {% for result in msn_results %}
                <div class="news-item">
                    <div class="news-thumbnail" style="background-image: url('{{ result.get('image_url', '') }}')"></div>
                    <div class="news-content">
                        <div class="news-time">{{ result.get('time', '') }}</div>
                        <a href="{{ result.link }}" class="news-title" target="_blank">{{ result.title }}</a>
                        <div class="news-snippet">{{ result.snippet }}</div>
                    </div>
                </div>
                {% endfor %}
                {% endif %}
            </div>
            
            <div class="timeline">
                <h3>事件进展</h3>
                {% for event in timeline_events %}
                <div class="timeline-item">
                    <div class="timeline-time">{{ event.time }}</div>
                    <div class="timeline-title">{{ event.title }}</div>
                </div>
                {% endfor %}
            </div>
        </div>
        
        <script>
            async function publishEvent() {
                try {
                    const response = await fetch('/api/search?keyword={{ keyword }}');
                    if (response.ok) {
                        alert('发布成功！');
                        window.location.href = '/dashboard.html';
                    } else {
                        alert('发布失败，请重试');
                    }
                } catch (error) {
                    console.error('发布失败:', error);
                    alert('发布失败，请重试');
                }
            }
            
            async function cancelPreview() {
                try {
                    // 调用删除预览文件的API
                    await fetch('/api/preview/cancel?keyword={{ keyword }}', {
                        method: 'POST'
                    });
                } catch (error) {
                    console.error('删除预览文件失败:', error);
                }
                window.location.href = '/dashboard.html';
            }
        </script>
    </body>
    </html>
    """
    
    # 渲染模板
    html_content = render_template_string(
        template,
        keyword=keyword,
        bing_results=bing_results,
        msn_results=msn_results,
        timeline_events=timeline_events,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    # 生成预览文件
    filename = f"preview_{datetime.now().strftime('%Y%m%d%H%M%S')}_{keyword}.html"
    filepath = os.path.join(EVENTS_DIR, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return f"/static/events/{filename}"

@app.route('/api/events/<int:event_id>/notion', methods=['POST'])
def add_to_notion(event_id):
    event = Event.query.get_or_404(event_id)
    
    # 如果已经有 notion_page_id，说明已经发布过
    if event.notion_page_id:
        return jsonify({
            'success': False,
            'message': '该事件已经发布到 Notion'
        }), 400
    
    try:
        # 重新获取搜索结果
        bing_results = search_bing(event.keyword)
        msn_results = search_msn(event.keyword)
        
        # 创建 Notion 页面
        content = format_content_for_notion(event.keyword, bing_results, msn_results, [])
        
        # 确保 URL 是完整的
        full_url = request.host_url.rstrip('/') + event.url
        
        # 添加错误处理和日志
        print(f"Creating Notion page for event {event_id}")
        print(f"Content length: {len(content)}")
        print(f"URL: {full_url}")
        
        notion_page_id = notion_manager.create_page(
            title=event.keyword,
            content=content,
            url=full_url
        )
        
        if notion_page_id:
            # 更新事件记录
            event.notion_page_id = notion_page_id
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': '成功添加到 Notion'
            })
        else:
            return jsonify({
                'success': False,
                'message': '添加到 Notion 失败：无法创建页面'
            }), 500
            
    except Exception as e:
        print(f"Error adding to Notion: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'添加到 Notion 失败: {str(e)}'
        }), 500

def delete_preview_files():
    """删除所有预览文件"""
    for filename in os.listdir(EVENTS_DIR):
        if filename.startswith('preview_'):
            file_path = os.path.join(EVENTS_DIR, filename)
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"删除预览文件失败: {file_path}, 错误: {str(e)}")

def delete_preview_file(keyword):
    """删除特定关键词的预览文件"""
    for filename in os.listdir(EVENTS_DIR):
        if filename.startswith('preview_') and keyword in filename:
            file_path = os.path.join(EVENTS_DIR, filename)
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"删除预览文件失败: {file_path}, 错误: {str(e)}")

@app.route('/api/preview/cancel', methods=['POST'])
def cancel_preview():
    keyword = request.args.get('keyword')
    if keyword:
        delete_preview_file(keyword)
    return jsonify({'success': True})

def search_baidu(keyword):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
    }
    url = f"https://www.baidu.com/s?wd={keyword}"
    try:
        response = requests.get(url, headers=headers)
        return parse_baidu_results(response.text)
    except:
        return []

def parse_baidu_results(html):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    for item in soup.select('.result.c-container')[:10]:
        title_elem = item.select_one('.t') or item.select_one('h3')
        link_elem = item.select_one('a')
        abstract_elem = item.select_one('.c-abstract') or item.select_one('.content')
        
        if title_elem and link_elem:
            title = title_elem.get_text(strip=True)
            link = link_elem.get('href', '')
            snippet = abstract_elem.get_text(strip=True) if abstract_elem else ''
            
            # 尝试获取图片
            image_url = ''
            img = item.find('img')
            if img and img.get('src'):
                image_url = img.get('src')
            
            # 尝试获取时间
            time = ''
            time_elem = item.find(class_='c-abstract-time')
            if time_elem:
                time = time_elem.get_text()
            
            results.append({
                'title': title,
                'link': link,
                'snippet': snippet,
                'image_url': image_url,
                'time': time
            })
    return results

def extract_timeline_events(bing_results, msn_results, baidu_results):
    all_events = []
    
    # 从所有结果中提取带时间的事件
    for result in bing_results + msn_results + baidu_results:
        # 尝试从标题中提取时间信息
        title = result.get('title', '')
        snippet = result.get('snippet', '')
        
        # 首先使用已有的时间
        time = result.get('time', '')
        
        # 如果没有时间，尝试从标题和摘要中提取时间信息
        if not time:
            # 常见的时间格式
            time_patterns = [
                r'(\d{4})年(\d{1,2})月(\d{1,2})日',
                r'(\d{4})\.(\d{1,2})\.(\d{1,2})',
                r'(\d{4})-(\d{1,2})-(\d{1,2})',
                r'(\d{1,2})月(\d{1,2})日',
                r'昨天',
                r'今天',
                r'(\d+)小时前',
                r'(\d+)分钟前'
            ]
            
            for pattern in time_patterns:
                # 先从标题中查找
                match = re.search(pattern, title)
                if not match:
                    # 如果标题中没有，从摘要中查找
                    match = re.search(pattern, snippet)
                
                if match:
                    time = match.group(0)
                    break
        
        if time:
            # 处理相对时间
            if '小时前' in time:
                hours = int(re.search(r'(\d+)', time).group(1))
                event_time = datetime.now() - timedelta(hours=hours)
                time = event_time.strftime('%Y年%m月%d日')
            elif '分钟前' in time:
                minutes = int(re.search(r'(\d+)', time).group(1))
                event_time = datetime.now() - timedelta(minutes=minutes)
                time = event_time.strftime('%Y年%m月%d日')
            elif '昨天' in time:
                event_time = datetime.now() - timedelta(days=1)
                time = event_time.strftime('%Y年%m月%d日')
            elif '今天' in time:
                time = datetime.now().strftime('%Y年%m月%d日')
            
            # 如果时间只有月日，添加当前年份
            if re.match(r'^\d{1,2}月\d{1,2}日', time):
                time = f"{datetime.now().year}年{time}"
            
            all_events.append({
                'time': time,
                'title': title
            })
    
    # 按时间排序（将时间字符串转换为datetime对象进行比较）
    def parse_time(time_str):
        try:
            # 尝试解析完整的年月日时间
            match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', time_str)
            if match:
                year, month, day = map(int, match.groups())
                return datetime(year, month, day)
            return datetime.now()  # 如果无法解析，返回当前时间
        except:
            return datetime.now()
    
    # 按时间排序，最新的在前面
    all_events.sort(key=lambda x: parse_time(x['time']), reverse=True)
    
    # 返回前10个事件
    return all_events[:10]

def generate_index_page():
    """生成 GitHub Pages 的索引页面"""
    events = Event.query.order_by(Event.timestamp.desc()).all()
    
    index_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI 热点事件</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 800px;
                margin: 0 auto;
                padding: 20px;
            }
            .event-list {
                list-style: none;
                padding: 0;
            }
            .event-item {
                margin-bottom: 20px;
                padding: 15px;
                border: 1px solid #eee;
                border-radius: 5px;
            }
            .event-time {
                color: #666;
                font-size: 14px;
            }
            .event-title {
                margin: 5px 0;
                font-size: 18px;
            }
            a {
                color: #4e6ef2;
                text-decoration: none;
            }
            a:hover {
                text-decoration: underline;
            }
        </style>
    </head>
    <body>
        <h1>AI 热点事件</h1>
        <div class="event-list">
    """
    
    for event in events:
        filename = os.path.basename(event.url)
        index_html += f"""
            <div class="event-item">
                <div class="event-time">{event.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</div>
                <div class="event-title">
                    <a href="{filename}">{event.keyword}</a>
                </div>
            </div>
        """
    
    index_html += """
        </div>
    </body>
    </html>
    """
    
    # 保存索引页面
    with open(os.path.join(GITHUB_PAGES_DIR, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index_html)

if __name__ == '__main__':
    init_db()  # 初始化数据库
    delete_preview_files()  # 删除所有预览文件
   
    # 如果是在 GitHub Actions 中运行
    if os.getenv('GITHUB_ACTIONS'):
        # 生成所有页面
        events = Event.query.all()
        for event in events:
            # 直接从数据库生成静态页面
            with open(os.path.join(EVENTS_DIR, os.path.basename(event.url)), 'r', encoding='utf-8') as f:
                content = f.read()
            # 保存到 GitHub Pages 目录
            with open(os.path.join(GITHUB_PAGES_DIR, os.path.basename(event.url)), 'w', encoding='utf-8') as f:
                f.write(content)
        # 生成索引页面
        generate_index_page()
        print("静态页面生成完成")
        sys.exit(0)
    else:
        # 正常运行应用
        app.run(debug=True) 
