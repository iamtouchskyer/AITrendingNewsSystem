from flask import Flask, request, jsonify, render_template_string, send_from_directory
import requests
from bs4 import BeautifulSoup
import os
from datetime import datetime
from models import db, Event, User

app = Flask(__name__, static_folder='static')

# 数据库配置
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///trending.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# 确保events目录存在
EVENTS_DIR = 'static/events'
os.makedirs(EVENTS_DIR, exist_ok=True)

# 创建所有数据库表
def init_db():
    with app.app_context():
        db.create_all()
        # 创建默认管理员用户
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', password='password')
            db.session.add(admin)
            db.session.commit()

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
    
    # 搜索Bing和MSN
    bing_results = search_bing(keyword)
    msn_results = search_msn(keyword)
    
    # 生成结果页面
    page_url = generate_results_page(keyword, bing_results, msn_results)
    
    # 保存到数据库
    event = Event(
        keyword=keyword,
        url=page_url
    )
    db.session.add(event)
    db.session.commit()
    
    return jsonify({
        'url': page_url,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

@app.route('/api/events')
def get_events():
    events = Event.query.order_by(Event.timestamp.desc()).all()
    return jsonify([event.to_dict() for event in events])

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
    keyword = request.args.get('keyword')
    
    # 搜索Bing和MSN
    bing_results = search_bing(keyword)
    msn_results = search_msn(keyword)
    
    # 生成预览页面
    page_url = generate_preview_page(keyword, bing_results, msn_results)
    
    return jsonify({
        'url': page_url
    })

def parse_bing_results(html):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    for item in soup.select('.b_algo')[:5]:  # 获取前5个结果
        title = item.find('h2').get_text() if item.find('h2') else ''
        link = item.find('a')['href'] if item.find('a') else ''
        snippet = item.find('p').get_text() if item.find('p') else ''
        results.append({
            'title': title,
            'link': link,
            'snippet': snippet
        })
    return results

def parse_msn_results(html):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    
    # 尝试多个可能的选择器
    news_items = (
        soup.select('.contentCard') or  # 新版卡片
        soup.select('.article-card') or  # 文章卡片
        soup.select('.news-card') or     # 新闻卡片
        soup.select('.cardContent')      # 内容卡片
    )
    
    for item in news_items[:5]:
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
                link = 'https://www.msn.com' + link
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''
            
            results.append({
                'title': title,
                'link': link,
                'snippet': snippet
            })
    
    return results

def search_bing(keyword):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    url = f"https://www.bing.com/search?q={keyword}"
    try:
        response = requests.get(url, headers=headers)
        return parse_bing_results(response.text)
    except:
        return []

def search_msn(keyword):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Cache-Control': 'no-cache',
        'Pragma': 'no-cache'
    }
    
    # 尝试多个可能的 URL 模式
    urls = [
        f"https://www.msn.com/zh-cn/news/search?q={keyword}",
        f"https://www.msn.com/zh-cn/search?q={keyword}&category=news",
        f"https://www.msn.com/zh-cn/news/searchresults?q={keyword}"
    ]
    
    all_results = []
    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                results = parse_msn_results(response.text)
                if results:
                    all_results.extend(results)
                    break  # 如果找到结果就停止尝试其他URL
        except Exception as e:
            print(f"MSN搜索错误 ({url}): {str(e)}")
            continue
    
    # 去重
    seen = set()
    unique_results = []
    for result in all_results:
        if result['link'] not in seen:
            seen.add(result['link'])
            unique_results.append(result)
    
    return unique_results[:5]  # 返回前5个唯一结果

def generate_results_page(keyword, bing_results, msn_results):
    template = """
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
            .content {
                max-width: 800px;
                margin: 20px auto;
                background: white;
                border-radius: 8px;
                padding: 20px;
            }
            .news-item {
                padding: 15px 0;
                border-bottom: 1px solid #f0f0f0;
            }
            .news-item:last-child {
                border-bottom: none;
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
            <div class="tab active">全部 <span class="count">{{ bing_results|length + msn_results|length }}</span></div>
            <div class="tab">Bing <span class="count">{{ bing_results|length }}</span></div>
            <div class="tab">MSN <span class="count">{{ msn_results|length }}</span></div>
        </div>
        <div class="content">
            {% if bing_results %}
            <div class="source-tag">Bing搜索结果</div>
            {% for result in bing_results %}
            <div class="news-item">
                <a href="{{ result.link }}" class="news-title" target="_blank">{{ result.title }}</a>
                <div class="news-snippet">{{ result.snippet }}</div>
            </div>
            {% endfor %}
            {% endif %}

            {% if msn_results %}
            <div class="source-tag">MSN搜索结果</div>
            {% for result in msn_results %}
            <div class="news-item">
                <a href="{{ result.link }}" class="news-title" target="_blank">{{ result.title }}</a>
                <div class="news-snippet">{{ result.snippet }}</div>
            </div>
            {% endfor %}
            {% endif %}
        </div>
    </body>
    </html>
    """
    
    # 渲染模板
    html_content = render_template_string(
        template,
        keyword=keyword,
        bing_results=bing_results,
        msn_results=msn_results,
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    # 生成唯一文件名
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{keyword}.html"
    filepath = os.path.join(EVENTS_DIR, filename)
    
    # 保存文件
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return f"/static/events/{filename}"

def generate_preview_page(keyword, bing_results, msn_results):
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
            .content {
                max-width: 800px;
                margin: 20px auto;
                background: white;
                border-radius: 8px;
                padding: 20px;
            }
            .news-item {
                padding: 15px 0;
                border-bottom: 1px solid #f0f0f0;
            }
            .news-item:last-child {
                border-bottom: none;
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
        <div class="content">
            {% if bing_results %}
            <div class="source-tag">Bing搜索结果</div>
            {% for result in bing_results %}
            <div class="news-item">
                <a href="{{ result.link }}" class="news-title" target="_blank">{{ result.title }}</a>
                <div class="news-snippet">{{ result.snippet }}</div>
            </div>
            {% endfor %}
            {% endif %}

            {% if msn_results %}
            <div class="source-tag">MSN搜索结果</div>
            {% for result in msn_results %}
            <div class="news-item">
                <a href="{{ result.link }}" class="news-title" target="_blank">{{ result.title }}</a>
                <div class="news-snippet">{{ result.snippet }}</div>
            </div>
            {% endfor %}
            {% endif %}
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
            
            function cancelPreview() {
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
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    
    # 生成预览文件
    filename = f"preview_{datetime.now().strftime('%Y%m%d%H%M%S')}_{keyword}.html"
    filepath = os.path.join(EVENTS_DIR, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    return f"/static/events/{filename}"

if __name__ == '__main__':
    init_db()  # 初始化数据库
    app.run(debug=True) 