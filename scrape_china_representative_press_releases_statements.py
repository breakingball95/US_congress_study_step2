#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
众议员涉华表态爬虫 - Press Releases 专版
收集美国众议员官方网站 Press Releases 栏目下的涉华通讯稿
"""

import sys
import subprocess
import importlib.util
import os
import csv
import re
import time
import random
import logging
from datetime import datetime, date
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# 配置参数
MAX_WORKERS = 5  # 并发线程数
MIN_DELAY = 1.0   # 减少延迟提高效率
MAX_DELAY = 2.0   # 减少延迟提高效率
REQUEST_TIMEOUT = 25  # 增加请求超时（秒）
MAX_RETRIES = 3   # 最大重试次数
START_DATE = date(2024, 10, 31)  # 只收集2024年10月31日之后的新闻
BATCH_SIZE = 10   # 每处理10个网站保存一次中间结果

# 全局变量
progress_lock = threading.Lock()
completed_count = 0
total_count = 0
all_articles = []
failed_sites = []
processed_urls_global = set()  # 全局URL去重集合
test_mode_global = False  # 测试模式标志
total_articles_saved = 0  # 总共保存的文章数

# 中国相关关键词（不区分大小写）
CHINA_KEYWORDS = [
    'china', 'chinese', 'ccp', 'chinese communist party',
    'taiwan', 'taiwanese', 'beijing', 'tiktok', 'trade war', 
    'human rights', 'g2', 'tech war', 'technology war',
    'hong kong', 'xinjiang', 'uighur', 'uyghur', 'tibet',
    'south china sea', 'indo-pacific', 'made in china',
    'belt and road', 'one china', 'cross-strait',
    'semiconductor', 'chip war', 'supply chain',
    'intellectual property', 'ip theft', 'cyber attack',
    'huawei', 'zte', 'byd', 'shein', 'temu',
    'fentanyl', 'synthetic opioid', 'currency manipulation',
    'wto', 'tariff', 'trade deficit', 'export control',
    'confucius institute', 'chinese spy', 'espionage',
    'chinese military', 'pla', 'df-', 'dongfeng',
    'balloon', 'spy balloon', 'ufo', 'unidentified object'
]

# 搜索关键词列表（用于搜索功能）
SEARCH_KEYWORDS = ['china', 'chinese', 'ccp', 'communist']

# 一级菜单关键词（media, press, news等）
PRIMARY_MENU_KEYWORDS = [
    'media', 'press', 'news', 'statements'
]

# Press Releases 二级菜单关键词
PRESS_RELEASES_KEYWORDS = [
    'press releases', 'press-releases', 'pressrelease', 'press release',
    'news releases', 'news-releases', 'newsrelease', 'news release',
    'media releases', 'media-releases', 'mediarelease', 'media release',
    'official statements', 'official-statements',
    'press statements', 'press-statements',
    'congressional statements', 'congressional-statements',
    'floor statements', 'floor-statements'
]

# User-Agent列表
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Edg/120.0.0.0'
]


def check_and_install_dependencies():
    """检查并安装必要的依赖包"""
    dependencies = [
        ('requests', 'requests>=2.28.0'),
        ('bs4', 'beautifulsoup4>=4.11.0'),
        ('lxml', 'lxml>=4.9.0'),
        ('dateutil', 'python-dateutil>=2.8.0')
    ]
    
    missing_packages = []
    for module_name, package_spec in dependencies:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            missing_packages.append(package_spec)
            print(f"  缺少依赖: {package_spec}")
    
    if missing_packages:
        print(f"\n正在安装 {len(missing_packages)} 个缺失的依赖包...")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", "--quiet"
            ] + missing_packages)
            print("依赖包安装完成！\n")
        except subprocess.CalledProcessError as e:
            print(f"安装依赖包时出错: {e}")
            print("请手动运行: pip install " + " ".join(missing_packages))
            sys.exit(1)
    else:
        print("所有依赖包已安装\n")


def setup_logging():
    """设置日志记录"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('crawl_log_press_releases.txt', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


logger = None


def get_random_headers():
    """获取随机请求头，模拟真实浏览器"""
    referers = [
        'https://www.google.com/',
        'https://www.bing.com/',
        'https://www.google.com/search?q=',
        'https://www.bing.com/search?q=',
    ]
    
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'cross-site',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'Referer': random.choice(referers)
    }


def create_session():
    """创建配置好的requests会话"""
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    
    session = requests.Session()
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=MAX_WORKERS,
        pool_maxsize=MAX_WORKERS * 2
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def smart_delay():
    """智能延迟，随机等待一段时间"""
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    time.sleep(delay)


def normalize_url(url):
    """标准化URL用于去重，保留查询参数"""
    url = url.rstrip('/')
    parsed = urlparse(url)
    # 保留查询参数，因为 ?page=1 和 ?page=2 是不同的页面
    if parsed.query:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{parsed.query}"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def is_url_processed(url):
    """检查URL是否已处理过"""
    normalized = normalize_url(url)
    return normalized in processed_urls_global


def mark_url_processed(url):
    """标记URL为已处理"""
    normalized = normalize_url(url)
    processed_urls_global.add(normalized)


def contains_china_keywords(text):
    """检查文本是否包含中国相关关键词"""
    if not text:
        return False
    
    text_lower = text.lower()
    matched_keywords = []
    
    for keyword in CHINA_KEYWORDS:
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, text_lower):
            matched_keywords.append(keyword)
    
    return matched_keywords if matched_keywords else False


def parse_date(date_text):
    """尝试从文本中解析日期"""
    from dateutil import parser as date_parser
    
    if not date_text:
        return None
    
    date_text = date_text.strip()
    current_year = datetime.now().year
    
    date_patterns = [
        r'(\w+\s+\d{1,2},?\s+\d{4})',
        r'(\d{1,2}/\d{1,2}/\d{2,4})',
        r'(\d{1,2}-\d{1,2}-\d{2,4})',
        r'(\d{4}-\d{2}-\d{2})',
        r'(\d{4}/\d{2}/\d{2})',
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, date_text)
        if match:
            try:
                parsed = date_parser.parse(match.group(1))
                # 过滤不合理的年份（未来年份或太早的年份）
                if parsed.year > current_year + 1 or parsed.year < 1990:
                    continue
                return parsed
            except:
                continue
    
    try:
        parsed = date_parser.parse(date_text)
        # 过滤不合理的年份
        if parsed.year > current_year + 1 or parsed.year < 1990:
            return None
        return parsed
    except:
        pass
    
    return None


def is_after_start_date(date_obj):
    """检查日期是否在2024年10月31日之后"""
    if not date_obj:
        return True
    
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()
    
    return date_obj >= START_DATE


def find_primary_menu_links(soup, base_url):
    """
    在页面中寻找一级菜单链接（media, press, news, statements）
    返回找到的链接列表
    """
    menu_links = []
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '').lower()
        text = link.get_text(strip=True).lower()
        
        for keyword in PRIMARY_MENU_KEYWORDS:
            if keyword in href or keyword in text:
                full_url = urljoin(base_url, link['href'])
                if full_url.startswith(base_url):
                    normalized = normalize_url(full_url)
                    if normalized not in [normalize_url(l[0]) for l in menu_links]:
                        menu_links.append((full_url, text or keyword))
                    break
    
    return menu_links


def find_press_releases_links(soup, base_url):
    """
    在页面中寻找 Press Releases 二级菜单链接
    优先返回可能是列表页的链接
    返回找到的链接列表
    """
    pr_links = []
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '').lower()
        text = link.get_text(strip=True).lower()
        
        for keyword in PRESS_RELEASES_KEYWORDS:
            if keyword in href or keyword in text:
                full_url = urljoin(base_url, link['href'])
                if full_url.startswith(base_url):
                    normalized = normalize_url(full_url)
                    if normalized not in [normalize_url(l[0]) for l in pr_links]:
                        pr_links.append((full_url, text or keyword))
                    break
    
    return pr_links


def find_search_form(soup, base_url):
    """
    在页面中查找搜索表单
    返回搜索表单的信息和提交方式
    """
    search_info = {'found': False, 'form': None, 'input_name': None, 'form_action': None}
    
    # 方法1：查找带有search或query的input
    for input_tag in soup.find_all('input', {'type': ['text', 'search']}):
        name = input_tag.get('name', '').lower()
        if any(keyword in name for keyword in ['search', 'query', 'q', 'keyword', 's']):
            search_info['found'] = True
            search_info['input_name'] = input_tag.get('name')
            
            # 查找form
            form = input_tag.find_parent('form')
            if form:
                search_info['form'] = form
                action = form.get('action', '')
                if action:
                    search_info['form_action'] = urljoin(base_url, action)
            break
    
    # 方法2：查找form中的input
    if not search_info['found']:
        for form in soup.find_all('form'):
            for input_tag in form.find_all('input', {'type': ['text', 'search']}):
                name = input_tag.get('name', '').lower()
                if any(keyword in name for keyword in ['search', 'query', 'q', 'keyword', 's']):
                    search_info['found'] = True
                    search_info['input_name'] = input_tag.get('name')
                    search_info['form'] = form
                    action = form.get('action', '')
                    if action:
                        search_info['form_action'] = urljoin(base_url, action)
                    break
            if search_info['found']:
                break
    
    # 方法3：查找WordPress搜索框
    if not search_info['found']:
        search_form = soup.find('form', {'role': 'search'})
        if search_form:
            input_tag = search_form.find('input', {'type': 'search'})
            if not input_tag:
                input_tag = search_form.find('input', {'type': 'text'})
            if input_tag:
                search_info['found'] = True
                search_info['input_name'] = input_tag.get('name', 's')
                search_info['form'] = search_form
                action = search_form.get('action', '')
                if action:
                    search_info['form_action'] = urljoin(base_url, action)
    
    return search_info


def search_with_category_filter(session, website, keyword, search_info):
    """
    在主页搜索关键词，并尝试限定结果在Press Releases分类
    返回搜索结果URL
    """
    from urllib.parse import urlencode, urlparse
    
    search_url = None
    
    # 方法1：直接构造搜索URL，尝试添加category参数
    parsed = urlparse(website)
    base_domain = f"{parsed.scheme}://{parsed.netloc}"
    
    # 常见搜索URL模式
    search_patterns = [
        # WordPress搜索
        f"{base_domain}/?s={keyword}&post_type=press-release",
        f"{base_domain}/?s={keyword}&cat=press",
        f"{base_domain}/?s={keyword}",
        # 带分类的搜索
        f"{base_domain}/search?q={keyword}&category=press",
        f"{base_domain}/search?q={keyword}",
        # 站点搜索
        f"{base_domain}/?s={keyword}",
    ]
    
    for pattern in search_patterns:
        try:
            # 先检查URL是否有效
            test_response = session.head(pattern, timeout=10, allow_redirects=True)
            if test_response.status_code == 200:
                search_url = pattern
                break
        except:
            continue
    
    # 方法2：如果找不到，使用表单构建
    if not search_url and search_info['found']:
        if search_info['form_action']:
            params = {search_info['input_name']: keyword}
            search_url = f"{search_info['form_action']}?{urlencode(params)}"
        else:
            params = {search_info['input_name']: keyword}
            search_url = f"{website.rstrip('/')}/?{urlencode(params)}"
    
    return search_url


def search_keyword_on_page(session, base_url, keyword, search_info):
    """
    在页面上搜索关键词
    返回搜索结果页面的URL
    """
    from urllib.parse import urlencode
    
    search_url = None
    
    # 方法1：使用表单提交
    if search_info['found'] and search_info['form']:
        form = search_info['form']
        
        # 尝试从表单构建URL
        if search_info['form_action']:
            params = {search_info['input_name']: keyword}
            search_url = f"{search_info['form_action']}?{urlencode(params)}"
        else:
            # 尝试从当前URL构建搜索
            parsed = urlparse(base_url)
            params = {search_info['input_name']: keyword}
            search_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{urlencode(params)}"
    
    # 方法2：直接构造常见搜索URL模式
    if not search_url:
        parsed = urlparse(base_url)
        search_patterns = [
            f"{parsed.scheme}://{parsed.netloc}/?s={keyword}",
            f"{parsed.scheme}://{parsed.netloc}/search?q={keyword}",
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}/?s={keyword}",
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}/search?q={keyword}",
        ]
        for pattern in search_patterns:
            try:
                response = session.head(pattern, timeout=5, allow_redirects=True)
                if response.status_code == 200:
                    search_url = pattern
                    break
            except:
                continue
    
    return search_url


def get_next_page_url(original_list_url, current_page_num):
    """
    基于原始列表页URL构造下一页URL
    支持多种常见的分页模式
    """
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    
    parsed = urlparse(original_list_url)
    query_params = parse_qs(parsed.query)
    next_page = current_page_num + 1
    
    # 模式1：URL路径末尾包含 /page/N/ 或 /pages/N/ (WordPress等常用)
    path_match = re.search(r'/(page|pages|p)/(\d+)/?$', parsed.path, re.IGNORECASE)
    if path_match:
        prefix = path_match.group(1)
        new_path = re.sub(r'/(page|pages|p)/(\d+)/?$', f'/{prefix}/{next_page}/', parsed.path, flags=re.IGNORECASE)
        return urlunparse((
            parsed.scheme, parsed.netloc, new_path,
            parsed.params, parsed.query, parsed.fragment
        ))
    
    # 模式2：查询参数中包含 page=N
    if 'page' in query_params:
        query_params['page'] = [str(next_page)]
        new_query = urlencode(query_params, doseq=True)
        return urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment
        ))
    
    # 模式3：第一页没有page参数，添加 ?page=N
    # 适用于像 /news/ 或 /news/documentquery.aspx?DocumentTypeID=27 这样的URL
    query_params['page'] = [str(next_page)]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, new_query, parsed.fragment
    ))


def find_page_number_links(soup, base_url, target_page, current_url=None):
    """
    寻找特定页码的链接
    返回该页码的URL或None
    """
    domain_base = base_url.split('/')[0] + '//' + base_url.split('/')[2]
    current_normalized = normalize_url(current_url) if current_url else None
    
    # 首先在pagination容器中查找
    pagination_containers = soup.find_all(['nav', 'div', 'ul', 'ol'], 
                                          class_=re.compile(r'pagination|pager|page-nav|wp-pagenavi|pages', re.I))
    
    for container in pagination_containers:
        for link in container.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()
            
            # 检查文本是否是目标页码（精确匹配）
            if text == str(target_page):
                full_url = urljoin(base_url, href)
                if full_url.startswith(domain_base):
                    if current_normalized is None or normalize_url(full_url) != current_normalized:
                        if not is_likely_single_document_page(full_url):
                            return full_url
    
    # 多种页码匹配模式
    pagination_patterns = [
        (r'[?&]page[=\/]?' + str(target_page) + r'\b', target_page),
        (r'[?&]p[=\/]?' + str(target_page) + r'\b', target_page),
        (r'[?&]pg[=\/]?' + str(target_page) + r'\b', target_page),
        (r'/page/' + str(target_page) + r'\b', target_page),
        (r'/pages/' + str(target_page) + r'\b', target_page),
        (r'/p/' + str(target_page) + r'\b', target_page),
    ]
    
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        text = link.get_text(strip=True).lower()
        
        # 检查文本是否是目标页码（精确匹配）
        if text == str(target_page):
            full_url = urljoin(base_url, href)
            if full_url.startswith(domain_base):
                if current_normalized is None or normalize_url(full_url) != current_normalized:
                    if not is_likely_single_document_page(full_url):
                        return full_url
        
        # 检查href是否匹配页码模式
        for pattern, page_num in pagination_patterns:
            if re.search(pattern, href, re.IGNORECASE):
                full_url = urljoin(base_url, href)
                if full_url.startswith(domain_base):
                    if current_normalized is None or normalize_url(full_url) != current_normalized:
                        return full_url
    
    return None


def extract_article_content(soup, url):
    """
    从文章详情页提取内容
    返回字典包含：title, date, content
    """
    article_data = {
        'title': '',
        'date': None,
        'content': ''
    }
    
    # 提取标题
    title_selectors = [
        'h1', 'h1.entry-title', 'h1.post-title', 'h1.article-title',
        '.page-title', '.entry-title', '.post-title', '.article-title',
        'meta[property="og:title"]'
    ]
    
    for selector in title_selectors:
        if selector.startswith('meta'):
            meta = soup.select_one(selector)
            if meta and meta.get('content'):
                article_data['title'] = meta['content'].strip()
                break
        else:
            elem = soup.select_one(selector)
            if elem:
                article_data['title'] = elem.get_text(strip=True)
                break
    
    # 提取日期
    date_selectors = [
        'time', '.date', '.entry-date', '.post-date', '.published',
        'meta[property="article:published_time"]',
        '.posted-on', '.timestamp', '[datetime]'
    ]
    
    for selector in date_selectors:
        if selector.startswith('meta'):
            meta = soup.select_one(selector)
            if meta and meta.get('content'):
                article_data['date'] = parse_date(meta['content'])
                break
        elif selector == '[datetime]':
            elem = soup.select_one(selector)
            if elem and elem.get('datetime'):
                article_data['date'] = parse_date(elem['datetime'])
                break
        else:
            elem = soup.select_one(selector)
            if elem:
                article_data['date'] = parse_date(elem.get_text())
                if article_data['date']:
                    break
    
    # 提取正文内容
    content_selectors = [
        'article', '.entry-content', '.post-content', '.article-content',
        '.content', '.main-content', '[role="main"]',
        '.post', '.entry', '.page-content', '.press-release-content',
        '.release-content', '.statement-content'
    ]
    
    for selector in content_selectors:
        elem = soup.select_one(selector)
        if elem:
            paragraphs = elem.find_all(['p', 'div'])
            content_parts = []
            for p in paragraphs:
                text = p.get_text(strip=True)
                if len(text) > 20:
                    content_parts.append(text)
            article_data['content'] = '\n\n'.join(content_parts)
            break
    
    # 如果没有提取到内容，尝试提取所有段落
    if not article_data['content']:
        all_paragraphs = soup.find_all('p')
        content_parts = []
        for p in all_paragraphs:
            text = p.get_text(strip=True)
            if len(text) > 50:
                content_parts.append(text)
        article_data['content'] = '\n\n'.join(content_parts[:20])
    
    return article_data


def scrape_representative_website(session, rep_data, index):
    """
    爬取单个众议员的网站，寻找 Press Releases 栏目下的涉华通讯稿
    """
    import requests
    from bs4 import BeautifulSoup
    
    name = rep_data['name']
    website = rep_data['website']
    district = rep_data.get('district', '')
    state = rep_data.get('state', '')
    party = rep_data.get('party', '')
    
    articles_found = []
    local_processed_urls = set()
    
    try:
        logger.info(f"[{index}] 正在处理: {name} - {website}")
        
        if is_url_processed(website):
            logger.info(f"[{index}] {name}: 网站已处理过，跳过")
            return articles_found
        
        # 访问主页
        smart_delay()
        response = session.get(
            website, 
            headers=get_random_headers(), 
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True
        )
        response.raise_for_status()
        
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' not in content_type:
            logger.warning(f"[{index}] {name}: 非HTML内容，跳过")
            return articles_found
        
        soup = BeautifulSoup(response.content, 'lxml')
        mark_url_processed(website)
        
        # 首先直接寻找 Press Releases 链接（可能直接显示在主页）
        pr_links = find_press_releases_links(soup, website)
        
        # 如果没有直接找到，先找一级菜单，再在一级菜单页面找 Press Releases
        if not pr_links:
            logger.info(f"[{index}] {name}: 未直接找到 Press Releases，尝试查找一级菜单...")
            primary_menu_links = find_primary_menu_links(soup, website)
            
            for menu_url, menu_name in primary_menu_links[:3]:
                try:
                    if is_url_processed(menu_url):
                        continue
                    
                    smart_delay()
                    menu_response = session.get(
                        menu_url,
                        headers=get_random_headers(),
                        timeout=REQUEST_TIMEOUT
                    )
                    menu_response.raise_for_status()
                    menu_soup = BeautifulSoup(menu_response.content, 'lxml')
                    mark_url_processed(menu_url)
                    
                    # 在一级菜单页面寻找 Press Releases 链接
                    sub_pr_links = find_press_releases_links(menu_soup, website)
                    if sub_pr_links:
                        logger.info(f"[{index}] {name}: 在 {menu_name} 页面找到 {len(sub_pr_links)} 个 Press Releases 链接")
                        pr_links.extend(sub_pr_links)
                        
                except Exception as e:
                    logger.warning(f"[{index}] {name}: 访问一级菜单失败 {menu_url}: {str(e)}")
                    continue
        
        if not pr_links:
            logger.info(f"[{index}] {name}: 未找到 Press Releases 栏目，跳过")
            return articles_found
        
        logger.info(f"[{index}] {name}: 共找到 {len(pr_links)} 个 Press Releases 页面")
        
        # 初始化文章链接列表
        page_article_links = []
        all_article_links = []
        
        logger.info(f"[{index}] {name}: 开始搜索，初始all_article_links长度: {len(all_article_links)}")
        
        # 尝试使用搜索功能：在主页搜索关键词，限定在Press Releases
        logger.info(f"[{index}] {name}: 尝试在主页搜索关键词...")
        
        try:
            # 访问主页，查找搜索表单
            smart_delay()
            home_response = session.get(
                website,
                headers=get_random_headers(),
                timeout=REQUEST_TIMEOUT
            )
            home_response.raise_for_status()
            home_soup = BeautifulSoup(home_response.content, 'lxml')
            mark_url_processed(website)
            
            # 查找搜索表单
            search_info = find_search_form(home_soup, website)
            
            if search_info['found']:
                logger.info(f"[{index}] {name}: 找到搜索表单，尝试搜索关键词...")
                
                # 依次搜索4个关键词
                for keyword in SEARCH_KEYWORDS:
                    search_url = search_with_category_filter(session, website, keyword, search_info)
                    
                    if search_url:
                        logger.info(f"[{index}] {name}: 搜索关键词 '{keyword}': {search_url}")
                        
                        # 遍历搜索结果的所有页面
                        search_page_url = search_url
                        search_page_count = 0
                        max_search_pages = 20
                        
                        while search_page_url and search_page_count < max_search_pages:
                            try:
                                smart_delay()
                                search_response = session.get(
                                    search_page_url,
                                    headers=get_random_headers(),
                                    timeout=REQUEST_TIMEOUT
                                )
                                search_response.raise_for_status()
                                search_soup = BeautifulSoup(search_response.content, 'lxml')
                                mark_url_processed(search_page_url)
                                search_page_count += 1
                                
                                logger.info(f"[{index}] {name}: 处理搜索 '{keyword}' 第 {search_page_count} 页")
                                
                                # 提取搜索结果中的文章链接
                                for link in search_soup.find_all('a', href=True):
                                    href = link.get('href', '')
                                    text = link.get_text(strip=True)
                                    
                                    if len(text) < 10 or len(text) > 200:
                                        continue
                                    
                                    full_url = urljoin(website, href)
                                    if not full_url.startswith(website):
                                        continue
                                    
                                    normalized = normalize_url(full_url)
                                    if normalized in local_processed_urls or is_url_processed(full_url):
                                        continue
                                    
                                    # 收集文章链接
                                    page_article_links.append((full_url, text, [keyword]))
                                    local_processed_urls.add(normalized)
                                
                                logger.info(f"[{index}] {name}: 搜索 '{keyword}' 第 {search_page_count} 页找到 {len(page_article_links)} 个结果")
                                
                                # 将搜索结果添加到总列表
                                all_article_links.extend(page_article_links)
                                logger.info(f"[{index}] {name}: 添加搜索结果后all_article_links长度: {len(all_article_links)}")
                                
                                # 尝试获取下一页搜索结果
                                next_search_url = get_next_page_url(search_url, search_page_count)
                                if next_search_url and not is_url_processed(next_search_url):
                                    search_page_url = next_search_url
                                else:
                                    search_page_url = None
                                    
                            except Exception as e:
                                logger.warning(f"[{index}] {name}: 搜索结果页面访问失败: {str(e)}")
                                break
                    else:
                        logger.info(f"[{index}] {name}: 无法构造关键词 '{keyword}' 的搜索URL")
            
            else:
                logger.info(f"[{index}] {name}: 未找到搜索表单，使用Press Releases页面")
        
        except Exception as e:
            logger.warning(f"[{index}] {name}: 搜索功能失败: {str(e)}")
        
        # 如果搜索没找到文章（少于5个），使用传统翻页方式
        if len(all_article_links) < 5 and pr_links:
            # 访问 Press Releases 页面
            for pr_url, pr_name in pr_links[:2]:
                if is_url_processed(pr_url):
                    continue
                
                original_list_url = pr_url
                page_count = 0
                max_pages = 30
                stop_pagination = False
                
                while original_list_url and page_count < max_pages and not stop_pagination:
                    if is_url_processed(original_list_url):
                        break
                    
                    smart_delay()
                    pr_response = session.get(original_list_url, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
                    pr_response.raise_for_status()
                    pr_soup = BeautifulSoup(pr_response.content, 'lxml')
                    mark_url_processed(original_list_url)
                    page_count += 1
                    
                    logger.info(f"[{index}] {name}: 正在处理 {pr_name} 第 {page_count} 页")
                    
                    page_article_links = []
                    for link in pr_soup.find_all('a', href=True):
                        href = link.get('href', '')
                        text = link.get_text(strip=True)
                        
                        if len(text) < 10 or len(text) > 200:
                            continue
                        
                        full_url = urljoin(website, href)
                        if not full_url.startswith(website):
                            continue
                        
                        normalized = normalize_url(full_url)
                        if normalized in local_processed_urls or is_url_processed(full_url):
                            continue
                        
                        page_article_links.append((full_url, text, []))
                        local_processed_urls.add(normalized)
                    
                    logger.info(f"[{index}] {name}: 在 {pr_name} 第 {page_count} 页找到 {len(page_article_links)} 篇文章链接")
                    
                    if page_count == 2 and page_article_links:
                        try:
                            test_url, test_title, _ = page_article_links[0]
                            smart_delay()
                            test_response = session.get(test_url, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
                            test_soup = BeautifulSoup(test_response.content, 'lxml')
                            test_data = extract_article_content(test_soup, test_url)
                            
                            if test_data['date'] and not is_after_start_date(test_data['date']):
                                logger.info(f"[{index}] {name}: {pr_name} 第2页文章早于2024年10月31日，停止翻页")
                                stop_pagination = True
                        except:
                            pass
                    
                    all_article_links.extend(page_article_links)
                    
                    if not stop_pagination:
                        next_page_url = get_next_page_url(original_list_url, page_count)
                        
                        if next_page_url and not is_url_processed(next_page_url):
                            original_list_url = next_page_url
                            logger.info(f"[{index}] {name}: 准备访问第 {page_count + 1} 页: {original_list_url}")
                        elif page_count >= max_pages:
                            logger.info(f"[{index}] {name}: 已达到最大页数限制 ({max_pages}页)")
                            original_list_url = None
                        else:
                            logger.info(f"[{index}] {name}: 无法构造第 {page_count + 1} 页URL，结束翻页")
                            original_list_url = None
                    else:
                        original_list_url = None
                
                logger.info(f"[{index}] {name}: 完成 {pr_name}，共找到 {len(all_article_links)} 篇文章链接")
                
                # 访问每篇涉华文章详情页
                for article_url, article_title, keywords in all_article_links:  # 处理所有文章
                    try:
                        normalized = normalize_url(article_url)
                        if is_url_processed(article_url):
                            continue
                        
                        smart_delay()
                        article_response = session.get(
                            article_url,
                            headers=get_random_headers(),
                            timeout=REQUEST_TIMEOUT
                        )
                        article_response.raise_for_status()
                        article_soup = BeautifulSoup(article_response.content, 'lxml')
                        mark_url_processed(article_url)
                        
                        # 提取文章内容
                        article_data = extract_article_content(article_soup, article_url)
                        
                        # 检查日期
                        if not is_after_start_date(article_data['date']):
                            logger.info(f"[{index}] {name}: 文章日期早于2024年10月31日，跳过")
                            continue
                        
                        # 检查文章内容（标题+正文）是否包含中国关键词
                        full_text = f"{article_data['title']} {article_data['content']}"
                        matched_keywords = contains_china_keywords(full_text)
                        
                        if not matched_keywords:
                            continue
                        
                        # 保存文章信息
                        article_record = {
                            'representative_name': name,
                            'district': district,
                            'state': state,
                            'party': party,
                            'article_title': article_data['title'] or article_title,
                            'article_url': article_url,
                            'publish_date': article_data['date'].strftime('%Y-%m-%d') if article_data['date'] else '',
                            'matched_keywords': ', '.join(matched_keywords),
                            'content': article_data['content'][:5000],  # 增加内容长度限制
                            'press_releases_source': pr_name
                        }
                        
                        articles_found.append(article_record)
                        logger.info(f"[{index}] {name}: 成功提取涉华文章 - {article_record['article_title'][:50]}... (关键词: {', '.join(matched_keywords)})")
                        
                    except Exception as e:
                        logger.error(f"[{index}] {name}: 提取文章失败 {article_url}: {str(e)}")
                        continue
        
        return articles_found
        
    except requests.exceptions.RequestException as e:
        error_msg = f"网络请求错误: {str(e)}"
        logger.error(f"[{index}] {name}: {error_msg}")
        failed_sites.append({'name': name, 'website': website, 'error': error_msg})
        return articles_found
    except Exception as e:
        error_msg = f"未知错误: {str(e)}"
        logger.error(f"[{index}] {name}: {error_msg}")
        failed_sites.append({'name': name, 'website': website, 'error': error_msg})
        return articles_found


def save_results_to_csv(articles, filename='scrape_china_representative_press_releases_statements.csv'):
    """保存结果到CSV文件"""
    global total_articles_saved
    
    if not articles:
        logger.info("没有文章需要保存")
        return
    
    fieldnames = [
        'representative_name', 'district', 'state', 'party',
        'article_title', 'article_url', 'publish_date',
        'matched_keywords', 'content', 'press_releases_source'
    ]
    
    file_exists = os.path.exists(filename)
    
    with open(filename, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(articles)
    
    total_articles_saved += len(articles)
    logger.info(f"已保存 {len(articles)} 篇文章到 {filename}（累计: {total_articles_saved} 篇）")


def load_representatives_from_csv(filename='house_representatives_websites.csv', limit=None):
    """从CSV文件加载众议员信息"""
    representatives = []
    
    if not os.path.exists(filename):
        logger.error(f"文件不存在: {filename}")
        return representatives
    
    with open(filename, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            representatives.append(row)
    
    return representatives


def main():
    """主函数"""
    global logger, completed_count, total_count, all_articles, test_mode_global
    
    print("=" * 60)
    print("众议员涉华表态爬虫 - Press Releases 专版")
    print("=" * 60)
    
    # 检查依赖
    print("\n检查依赖包...")
    check_and_install_dependencies()
    
    # 设置日志
    logger = setup_logging()
    logger.info("爬虫启动")
    
    # 导入需要的库
    import requests
    from bs4 import BeautifulSoup
    
    # 加载众议员数据
    print("\n加载众议员数据...")
    test_mode = input("是否测试模式（只处理前5个）? (y/n): ").lower().strip() == 'y'
    test_mode_global = test_mode
    limit = 5 if test_mode else None
    
    representatives = load_representatives_from_csv(limit=limit)
    total_count = len(representatives)
    
    if not representatives:
        logger.error("没有加载到众议员数据")
        return
    
    print(f"\n共加载 {total_count} 名众议员")
    if test_mode:
        print("测试模式：只处理前5名众议员\n")
    else:
        print("完整模式：处理所有众议员\n")
    
    # 根据模式设置输出文件名
    output_filename = 'scrape_china_representative_press_releases_statements_test.csv' if test_mode else 'scrape_china_representative_press_releases_statements.csv'
    
    # 如果测试模式，删除旧的测试文件
    if test_mode and os.path.exists(output_filename):
        os.remove(output_filename)
        logger.info(f"已删除旧的测试文件: {output_filename}")
    
    # 创建会话
    session = create_session()
    
    # 多线程处理
    print(f"开始爬取（使用 {MAX_WORKERS} 个线程）...\n")
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_rep = {
            executor.submit(scrape_representative_website, session, rep, i+1): rep 
            for i, rep in enumerate(representatives)
        }
        
        for future in as_completed(future_to_rep):
            rep = future_to_rep[future]
            try:
                articles = future.result()
                if articles:
                    with progress_lock:
                        all_articles.extend(articles)
                        # 批量保存
                        if len(all_articles) >= BATCH_SIZE:
                            save_results_to_csv(all_articles, output_filename)
                            all_articles = []
                
                with progress_lock:
                    completed_count += 1
                    print(f"进度: {completed_count}/{total_count} - {rep['name']} 完成")
                    
            except Exception as e:
                logger.error(f"处理 {rep['name']} 时出错: {str(e)}")
                with progress_lock:
                    completed_count += 1
    
    # 保存剩余的文章
    if all_articles:
        save_results_to_csv(all_articles, output_filename)
    
    # 保存失败的网站记录
    if failed_sites:
        failed_filename = 'failed_sites_press_releases_test.txt' if test_mode else 'failed_sites_press_releases.txt'
        with open(failed_filename, 'w', encoding='utf-8') as f:
            for site in failed_sites:
                f.write(f"{site['name']}: {site['website']} - {site['error']}\n")
        logger.info(f"已保存 {len(failed_sites)} 个失败网站记录到 {failed_filename}")
    
    # 输出统计
    print("\n" + "=" * 60)
    print("爬取完成！")
    print("=" * 60)
    print(f"处理网站数: {total_count}")
    print(f"成功提取文章数: {total_articles_saved}")
    print(f"失败网站数: {len(failed_sites)}")
    print(f"结果已保存到: {output_filename}")
    print(f"日志文件: crawl_log_press_releases.txt")
    
    logger.info(f"爬虫结束 - 共保存 {total_articles_saved} 篇涉华文章")


if __name__ == "__main__":
    main()
