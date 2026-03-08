#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
众议员Press Releases爬虫 - 第一步
收集美国众议员官方网站 Press Releases 栏目下的所有通讯稿
时间范围：2024年10月31日至今

使用说明：
1. 确保有 house_representatives_websites.csv 文件（包含议员信息）
2. 运行脚本，选择测试模式或完整模式
3. 结果会保存到 CSV 文件中
"""

# 导入必要的库
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
from urllib.parse import urljoin, urlparse, urlencode, urlunparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# 延迟导入第三方库（在check_and_install_dependencies之后）
requests = None
BeautifulSoup = None
date_parser = None

# ==================== 配置参数区域 ====================
# 这些参数控制爬虫的行为

MAX_WORKERS = 10  # 并发线程数：同时处理10个议员的网站（提高并发）
MIN_DELAY = 0.5  # 最小延迟：每次请求后至少等待0.5秒（减少延迟）
MAX_DELAY = 1.0  # 最大延迟：每次请求后最多等待1秒（减少延迟）
REQUEST_TIMEOUT = 15  # 请求超时时间：15秒（减少超时时间）
MAX_RETRIES = 2  # 请求失败时的最大重试次数（减少重试次数）
START_DATE = date(2024, 10, 31)  # 只收集2024年10月31日之后的新闻
BATCH_SIZE = 10   # 每处理10个网站保存一次中间结果

# ==================== 全局变量区域 ====================
# 这些变量在整个程序中共享

progress_lock = threading.Lock()  # 线程锁：保护共享变量的安全访问
completed_count = 0  # 已完成处理的议员数量
total_count = 0  # 总共需要处理的议员数量
all_articles = []  # 临时存储抓取的文章
failed_sites = []  # 记录抓取失败的网站
processed_urls_global = set()  # 全局URL去重集合：避免重复访问相同页面
test_mode_global = False  # 测试模式标志：True表示只处理前5个议员
total_articles_saved = 0  # 总共保存的文章数

# ==================== 关键词配置区域 ====================
# 这些关键词用于识别网页中的特定内容

# 一级菜单关键词：只从 media、media center 或 newsroom 进入
# 说明：爬虫会先找这些关键词对应的菜单，再在里面找Press Releases
PRIMARY_MENU_KEYWORDS = [
    'media',        # 媒体
    'media center', # 媒体中心
    'newsroom'      # 新闻室
]

# Press Releases 二级菜单关键词（精确匹配）
# 说明：在一级菜单页面中，只寻找精确的 'press releases' 链接
PRESS_RELEASES_KEYWORDS = [
    'press releases',      # 最标准的格式
    'press-releases',      # 带横线的格式
    'pressrelease',        # 不带空格的格式
]

# 二级菜单排除关键词：这些不是真正的 Press Releases
PRESS_RELEASES_EXCLUDE_KEYWORDS = [
    'contact', 'email', 'subscribe', 'unsubscribe', 'newsletter',
    'staff', 'appointment', 'request', 'tour', 'flag', 'ticket',
    'media inquiry', 'media contact', 'press contact', 'press inquiry',
    'contact us', 'contact me', 'email us', 'email me'
]

# User-Agent列表：模拟不同的浏览器访问
# 说明：轮换使用不同的User-Agent，避免被网站识别为爬虫
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Edg/120.0.0.0'
]

# ==================== 函数定义区域 ====================

def check_and_install_dependencies():
    """
    检查并安装必要的依赖包
    
    说明：
    - 检查是否安装了requests、beautifulsoup4、lxml、python-dateutil
    - 如果缺少某个包，自动使用pip安装
    - 安装完成后初始化全局库变量
    """
    global requests, BeautifulSoup, date_parser
    
    dependencies = [
        ('requests', 'requests>=2.28.0'),      # 用于发送HTTP请求
        ('bs4', 'beautifulsoup4>=4.11.0'),     # 用于解析HTML
        ('lxml', 'lxml>=4.9.0'),               # HTML解析器
        ('dateutil', 'python-dateutil>=2.8.0') # 用于解析日期
    ]

    missing_packages = []
    for module_name, package_spec in dependencies:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            missing_packages.append(package_spec)

    if missing_packages:
        print(f"正在安装缺失的依赖包: {missing_packages}")
        for package in missing_packages:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])
    
    # 初始化全局库变量
    import requests
    from bs4 import BeautifulSoup
    from dateutil import parser as date_parser
    
    # 将导入的库赋值给全局变量
    sys.modules[__name__].requests = requests
    sys.modules[__name__].BeautifulSoup = BeautifulSoup
    sys.modules[__name__].date_parser = date_parser


def setup_logging():
    """
    配置日志系统
    
    说明：
    - 日志会同时输出到文件(scrape_press_releases.log)和屏幕
    - 日志格式：时间 - 日志级别 - 消息
    """
    logger = logging.getLogger('PressReleaseScraper')
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    # 文件处理器：将日志写入文件
    file_handler = logging.FileHandler('scrape_press_releases.log', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 控制台处理器：将日志输出到屏幕
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


# 全局logger变量，在main函数中初始化
logger = None


def get_random_headers():
    """
    获取随机请求头，模拟真实浏览器
    
    说明：
    - 随机选择一个User-Agent
    - 添加其他HTTP头信息，使请求看起来像真实浏览器访问
    """
    referers = [
        'https://www.google.com/',
        'https://www.bing.com/',
        'https://www.google.com/search?q=',
        'https://www.bing.com/search?q=',
    ]

    return {
        'User-Agent': random.choice(USER_AGENTS),  # 随机User-Agent
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
        'Referer': random.choice(referers)  # 随机来源页面
    }


def create_session():
    """
    创建配置好的requests会话
    
    说明：
    - 创建一个HTTP会话对象
    - 配置自动重试机制：遇到特定错误码时自动重试
    - 配置连接池，提高性能
    """
    global requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    session = requests.Session()
    
    # 配置重试策略
    retry_strategy = Retry(
        total=MAX_RETRIES,  # 最多重试3次
        backoff_factor=2,   # 重试间隔时间递增
        status_forcelist=[429, 500, 502, 503, 504],  # 遇到这些状态码时重试
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    
    # 创建适配器
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=MAX_WORKERS,
        pool_maxsize=MAX_WORKERS * 2
    )
    
    # 为HTTP和HTTPS请求都配置适配器
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session


def smart_delay():
    """
    智能延迟，随机等待一段时间
    
    说明：
    - 随机等待1-2秒
    - 目的是模拟人类操作，避免请求过快被网站封禁
    """
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    time.sleep(delay)


def normalize_url(url):
    """
    标准化URL用于去重，保留查询参数
    
    参数：
        url: 原始URL字符串
    
    返回：
        标准化后的URL字符串
    
    说明：
    - 移除URL末尾的斜杠
    - 保留查询参数（如?page=2）
    - 用于URL去重比较
    """
    url = url.rstrip('/')
    parsed = urlparse(url)
    if parsed.query:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{parsed.query}"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def is_url_processed(url):
    """
    检查URL是否已处理
    
    参数：
        url: 要检查的URL
    
    返回：
        True如果URL已处理，False否则
    
    说明：
    - 使用全局集合processed_urls_global进行去重
    - 防止重复访问相同页面
    """
    normalized = normalize_url(url)
    return normalized in processed_urls_global


def mark_url_processed(url):
    """
    标记URL已处理
    
    参数：
        url: 要标记的URL
    
    说明：
    - 将URL添加到全局已处理集合
    """
    normalized = normalize_url(url)
    processed_urls_global.add(normalized)


def parse_date(date_text):
    """
    尝试从文本中解析日期
    
    参数：
        date_text: 包含日期的文本字符串
    
    返回：
        解析后的datetime对象，或None如果解析失败
    
    说明：
    - 支持多种日期格式（如：January 15, 2024、2024-01-15、01/15/2024等）
    - 检查日期合理性：不能是未来日期，不能早于1990年
    """
    global date_parser

    if not date_text:
        return None

    date_text = date_text.strip()
    today = datetime.now().date()  # 获取当前日期

    # 定义常见的日期模式（正则表达式）
    date_patterns = [
        r'(\w+\s+\d{1,2},?\s+\d{4})',  # January 15, 2024
        r'(\d{1,2}/\d{1,2}/\d{2,4})',   # 01/15/2024
        r'(\d{1,2}-\d{1,2}-\d{2,4})',   # 01-15-2024
        r'(\d{4}-\d{2}-\d{2})',          # 2024-01-15
        r'(\d{4}/\d{2}/\d{2})',          # 2024/01/15
    ]

    # 尝试用正则表达式匹配日期
    for pattern in date_patterns:
        match = re.search(pattern, date_text)
        if match:
            try:
                parsed = date_parser.parse(match.group(1))
                # 检查日期是否合理：不能是未来日期，也不能早于1990年
                parsed_date = parsed.date() if isinstance(parsed, datetime) else parsed
                if parsed_date > today or parsed_date.year < 1990:
                    continue
                return parsed
            except:
                continue

    # 如果正则匹配失败，尝试直接解析整个文本
    try:
        parsed = date_parser.parse(date_text)
        # 检查日期是否合理：不能是未来日期，也不能早于1990年
        parsed_date = parsed.date() if isinstance(parsed, datetime) else parsed
        if parsed_date > today or parsed_date.year < 1990:
            return None
        return parsed
    except:
        pass

    return None


def is_after_start_date(date_obj):
    """
    检查日期是否在2024年10月31日之后
    
    参数：
        date_obj: datetime对象或date对象
    
    返回：
        True如果日期在2024年10月31日之后，False否则
    
    说明：
    - 如果日期为None，返回False（不保存无法解析日期的文章）
    """
    if not date_obj:
        return False  # 无法解析日期的文章不保存

    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()

    return date_obj >= START_DATE


def find_primary_menu_links(soup, base_url, session=None):
    """
    在页面中寻找一级菜单链接（media, media center, newsroom）
    
    参数：
        soup: BeautifulSoup解析后的HTML对象
        base_url: 网站的基础URL
        session: HTTP会话对象（可选，用于访问menu页面）
    
    返回：
        列表，包含(链接URL, 链接文本)元组
    
    说明：
    - 先在首页查找一级菜单链接
    - 如果首页没有找到，则在 'menu' 页面中查找
    - 只返回与base_url同域名的链接
    """
    global BeautifulSoup
    
    menu_links = []
    base_domain = urlparse(base_url).netloc.lower()  # 提取基础域名
    
    def extract_menu_links(page_soup):
        """从页面中提取一级菜单链接"""
        links = []
        for link in page_soup.find_all('a', href=True):
            href = link.get('href', '')
            text = link.get_text(strip=True).lower()
            
            # 检查链接文本是否包含一级菜单关键词
            if any(keyword in text for keyword in PRIMARY_MENU_KEYWORDS):
                full_url = urljoin(base_url, href)
                # 严格检查域名是否匹配（防止跨站链接）
                full_domain = urlparse(full_url).netloc.lower()
                if full_domain == base_domain:
                    normalized = normalize_url(full_url)
                    # 去重：避免添加重复链接
                    if normalized not in [normalize_url(l[0]) for l in links]:
                        links.append((full_url, text))
        return links
    
    # 第1步：在首页查找
    menu_links = extract_menu_links(soup)
    
    # 第2步：如果首页没有找到，且提供了session，则在 'menu' 页面中查找
    if not menu_links and session:
        # 查找 'menu' 链接
        menu_page_url = None
        for link in soup.find_all('a', href=True):
            text = link.get_text(strip=True).lower()
            if text in ['menu', 'navigation', 'nav']:
                href = link.get('href', '')
                full_url = urljoin(base_url, href)
                full_domain = urlparse(full_url).netloc.lower()
                if full_domain == base_domain:
                    menu_page_url = full_url
                    break
        
        # 如果找到menu页面，访问它
        if menu_page_url:
            try:
                smart_delay()
                response = session.get(menu_page_url, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                menu_soup = BeautifulSoup(response.content, 'lxml')
                menu_links = extract_menu_links(menu_soup)
            except Exception as e:
                logger.debug(f"访问menu页面失败 {menu_page_url}: {str(e)}")
    
    return menu_links


def find_press_releases_links(soup, base_url):
    """
    在页面中寻找 Press Releases 链接（精确匹配，排除干扰项）
    
    参数：
        soup: BeautifulSoup解析后的HTML对象
        base_url: 网站的基础URL
    
    返回：
        列表，包含(链接URL, 链接文本)元组
    
    说明：
    - 查找包含PRESS_RELEASES_KEYWORDS中关键词的链接
    - 排除包含PRESS_RELEASES_EXCLUDE_KEYWORDS的链接（如contact, email等）
    - 只返回与base_url同域名的链接
    """
    pr_links = []
    base_domain = urlparse(base_url).netloc.lower()  # 提取基础域名

    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        text = link.get_text(strip=True).lower()
        
        # 第1步：检查是否包含排除关键词（如果是，直接跳过）
        is_excluded = False
        for exclude_keyword in PRESS_RELEASES_EXCLUDE_KEYWORDS:
            if exclude_keyword in text or exclude_keyword in href.lower():
                is_excluded = True
                break
        if is_excluded:
            continue
        
        # 第2步：检查是否包含Press Releases关键词
        for keyword in PRESS_RELEASES_KEYWORDS:
            if keyword in href or keyword in text:
                full_url = urljoin(base_url, link['href'])
                # 严格检查域名是否匹配（防止跨站链接）
                full_domain = urlparse(full_url).netloc.lower()
                if full_domain == base_domain:
                    normalized = normalize_url(full_url)
                    # 去重：避免添加重复链接
                    if normalized not in [normalize_url(l[0]) for l in pr_links]:
                        pr_links.append((full_url, text or keyword))
                break

    return pr_links


def get_next_page_url(original_list_url, current_page_num):
    """
    基于原始列表页URL构造下一页URL
    
    参数：
        original_list_url: 当前页面的URL
        current_page_num: 当前页码
    
    返回：
        下一页的URL字符串
    
    说明：
    - 支持多种翻页格式：/page/2/、?page=2、?paged=2等
    - 如果没有找到页码参数，默认添加?page=2
    """
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

    parsed = urlparse(original_list_url)
    query_params = parse_qs(parsed.query)
    next_page = current_page_num + 1

    # 检查路径中是否包含页码 /page/2/ 或 /pages/2/ 或 /p/2/
    path_match = re.search(r'/(page|pages|p)/(\d+)/?$', parsed.path, re.IGNORECASE)
    if path_match:
        prefix = path_match.group(1)
        new_path = re.sub(r'/(page|pages|p)/(\d+)/?$', f'/{prefix}/{next_page}/', parsed.path, flags=re.IGNORECASE)
        return urlunparse((
            parsed.scheme, parsed.netloc, new_path,
            parsed.params, parsed.query, parsed.fragment
        ))

    # 检查查询参数中是否有 page 参数（支持多种参数名）
    page_param_names = ['page', 'paged', 'pg', 'p', 'offset', 'start']
    for param_name in page_param_names:
        if param_name in query_params:
            query_params[param_name] = [str(next_page)]
            new_query = urlencode(query_params, doseq=True)
            return urlunparse((
                parsed.scheme, parsed.netloc, parsed.path,
                parsed.params, new_query, parsed.fragment
            ))

    # 默认添加 page 参数
    query_params['page'] = [str(next_page)]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, new_query, parsed.fragment
    ))


def extract_article_content(soup, url):
    """
    从文章页面提取内容
    
    参数：
        soup: BeautifulSoup解析后的HTML对象
        url: 文章页面的URL
    
    返回：
        字典，包含title（标题）、content（内容）、date（日期）
    
    说明：
    - 尝试多种CSS选择器来提取标题、内容和日期
    - 如果一种方法失败，会尝试其他备选方法
    """
    title = None
    content = None
    date_obj = None

    # 提取标题：优先找h1标签，其次是h2
    title_tag = soup.find('h1')
    if not title_tag:
        title_tag = soup.find('h2')
    if title_tag:
        title = title_tag.get_text(strip=True)

    # 提取内容：尝试多种CSS选择器
    content_selectors = [
        'article',              # HTML5 article标签
        '[role="main"]',        # ARIA role="main"
        '.article-content',     # 常见的文章容器class
        '.post-content',
        '.entry-content',
        '.content',
        'main',                 # HTML5 main标签
        '.story-body'
    ]

    for selector in content_selectors:
        content_elem = soup.select_one(selector)
        if content_elem:
            paragraphs = content_elem.find_all('p')
            if paragraphs:
                content = '\n\n'.join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])
                break

    # 如果上述方法都失败，直接取所有p标签的前20个
    if not content:
        all_p = soup.find_all('p')
        if all_p:
            content = '\n\n'.join([p.get_text(strip=True) for p in all_p[:20] if p.get_text(strip=True)])

    # 提取日期：尝试多种CSS选择器
    date_selectors = [
        'time[datetime]',                    # HTML5 time标签
        '.publish-date',
        '.post-date',
        '.article-date',
        '.date',
        'meta[property="article:published_time"]'  # Open Graph meta标签
    ]

    for selector in date_selectors:
        date_elem = soup.select_one(selector)
        if date_elem:
            if date_elem.name == 'time' and date_elem.get('datetime'):
                date_obj = parse_date(date_elem.get('datetime'))
            elif date_elem.name == 'meta' and date_elem.get('content'):
                date_obj = parse_date(date_elem.get('content'))
            else:
                date_obj = parse_date(date_elem.get_text(strip=True))
            if date_obj:
                break

    # 如果上述方法都失败，从页面文本中搜索日期模式
    if not date_obj:
        date_text = soup.get_text()
        date_match = re.search(r'(\w+\s+\d{1,2},?\s+\d{4})', date_text)
        if date_match:
            date_obj = parse_date(date_match.group(1))

    return {
        'title': title,
        'content': content,
        'date': date_obj
    }


def scrape_representative_press_releases(index, name, website, district, state, party):
    """
    爬取单个议员的Press Releases
    
    参数：
        index: 议员序号（用于日志标识）
        name: 议员姓名
        website: 议员网站URL
        district: 选区
        state: 州
        party: 党派
    
    返回：
        列表，包含抓取的文章记录字典
    
    说明：
    - 这是爬虫的核心函数
    - 只从一级菜单（media, media center, newsroom）进入Press Releases
    - 处理翻页，直到找到足够旧的文章或达到最大页数
    """
    global completed_count, total_count, all_articles, BeautifulSoup, requests

    # 初始化变量（确保在异常时也能访问）
    articles_found = []  # 存储找到的文章
    all_article_links = []  # 存储所有文章链接
    session = None

    try:
        # 创建HTTP会话
        session = create_session()
        logger.info(f"[{index}] {name}: 开始爬取 {website}")

        # 访问议员首页
        smart_delay()
        response = session.get(website, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        mark_url_processed(website)

        # 只从一级菜单（media, media center, newsroom）进入Press Releases
        pr_links = []
        # 传入session参数，以便在首页没找到时访问menu页面
        primary_menu_links = find_primary_menu_links(soup, website, session)

        if primary_menu_links:
            logger.info(f"[{index}] {name}: 找到 {len(primary_menu_links)} 个一级菜单链接")

        # 遍历一级菜单（最多前3个）
        for menu_url, menu_name in primary_menu_links[:3]:
            if is_url_processed(menu_url):
                continue

            try:
                smart_delay()
                menu_response = session.get(menu_url, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
                menu_response.raise_for_status()
                menu_soup = BeautifulSoup(menu_response.content, 'lxml')
                mark_url_processed(menu_url)

                # 在一级菜单页面中查找Press Releases链接
                sub_pr_links = find_press_releases_links(menu_soup, website)
                if sub_pr_links:
                    logger.info(f"[{index}] {name}: 在 {menu_name} 页面找到 {len(sub_pr_links)} 个 Press Releases 链接")
                    pr_links.extend(sub_pr_links)

            except Exception as e:
                logger.warning(f"[{index}] {name}: 访问一级菜单失败 {menu_url}: {str(e)}")
                continue

        if not pr_links:
            logger.info(f"[{index}] {name}: 未从一级菜单找到 Press Releases 栏目，跳过")
            return articles_found

        logger.info(f"[{index}] {name}: 共从一级菜单找到 {len(pr_links)} 个 Press Releases 页面")

        # 遍历每个Press Releases页面
        for pr_url, pr_name in pr_links:
            if is_url_processed(pr_url):
                continue

            base_list_url = pr_url  # 保存原始列表页URL，用于翻页
            current_page_url = pr_url  # 当前页面的URL
            page_count = 0
            max_pages = 30
            stop_pagination = False
            local_processed_urls = set()  # 每个PR页面独立的URL去重

            # 翻页循环
            while current_page_url and page_count < max_pages and not stop_pagination:
                if is_url_processed(current_page_url):
                    break

                smart_delay()
                pr_response = session.get(current_page_url, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
                pr_response.raise_for_status()
                pr_soup = BeautifulSoup(pr_response.content, 'lxml')
                mark_url_processed(current_page_url)
                page_count += 1

                logger.info(f"[{index}] {name}: 正在处理 {pr_name} 第 {page_count} 页")

                page_article_links = []

                # 文章链接的常见模式（正则表达式）
                article_patterns = [
                    r'/\d{4}/\d{2}/',  # /2024/01/ 日期格式
                    r'/\d{4}/\d{1,2}/', # /2024/3/ 单位数月份
                    r'/\d{4}/',        # /2024/ 年份格式
                    r'/\d{4}-\d{2}-\d{2}/', # /2024-03-15/ 横线日期格式
                    r'press-release',
                    r'pressrelease',
                    r'news-release',
                    r'newsrelease',
                    r'statement',
                    r'article',
                    r'post',
                    r'news/\d',        # news/ followed by digit
                    r'news-',
                    r'documentid',      # 某些网站使用 DocumentID
                    r'\?p=\d+',         # WordPress ?p=123 格式
                    r'/\d{4}/\d{2}/\d{2}/', # /2024/03/15/ 完整日期
                    r'/media/',          # /media/ 路径
                    r'/news/',            # /news/ 路径
                    r'/press/',           # /press/ 路径
                ]

                # 需要排除的导航/通用页面关键词（正则表达式）
                excluded_patterns = [
                    r'^home$',
                    r'about(?!\s+us)',  # about 但不匹配 about us（可能是文章）
                    r'contact',
                    r'staff',
                    r'district',
                    r'services',
                    r'flags?',
                    r'tours?',
                    r'tickets?',
                    r'help',
                    r'privacy',
                    r'accessibility',
                    r'subscribe',
                    r'unsubscribe',
                    r'newsletter',
                    r'email',
                    r'submit',
                    r'request',
                    r'appointment',
                    r'financial\s+disclosure',
                    r'disclosures?',
                    r'committees?',
                    r'caucuses?',
                    r'legislation',
                    r'votes?',
                    r'resources',
                    r'immigration(?!\s+reform)',  # immigration 但不匹配 immigration reform
                    r'constituent',
                    r'problems?',
                    r'internship',
                    r'employment',
                    r'jobs?',
                    r'volunteer',
                    r'our\s+district',
                    r'biography',
                    r'official\s+photograph',
                    r'offices?',
                    r'write\s+me',
                    r'connect\s+with\s+me',
                    r'social\s+media',
                    r'grant\s+applicants?',
                    r'recursos',  # 西班牙语资源
                    r'website\s+problem',
                    r'appearance',
                    r'casework',
                    r'federal\s+agencies',
                    r'federal\s+grants',
                    r'student\s+resources',
                    r'military\s+academies',
                    r'art\s+competition',
                    r'congressional\s+award',
                    r'page\s+program',
                    r'internships?',
                    r'job\s+opportunities',
                    r'newsletters?',
                    r'subscribe',
                    r'unsubscribe',
                    r'rss\s+feed',
                    r'podcast',
                    r'video',
                    r'photo\s+gallery',
                    r'audio',
                    r'multimedia',
                ]

                # 提取文章链接
                for link in pr_soup.find_all('a', href=True):
                    href = link.get('href', '')
                    text = link.get_text(strip=True)
                    text_lower = text.lower()

                    # 检查文本长度（太短或太长都跳过）
                    if len(text) < 10 or len(text) > 200:
                        continue

                    # 先检查URL是否符合文章链接模式（优先级最高）
                    full_url = urljoin(website, href)
                    url_lower = full_url.lower()
                    is_article = any(re.search(pattern, url_lower) for pattern in article_patterns)

                    # 如果URL符合文章模式，跳过排除关键词检查
                    if not is_article:
                        # URL不符合文章模式，检查排除关键词
                        if any(re.search(pattern, text_lower) for pattern in excluded_patterns):
                            continue
                    
                    # 严格检查URL是否属于当前议员的网站
                    website_domain = urlparse(website).netloc.lower()
                    full_url_domain = urlparse(full_url).netloc.lower()
                    if full_url_domain != website_domain:
                        continue

                    # 如果不符合任何文章模式，跳过
                    if not is_article:
                        continue

                    # 去重检查
                    normalized = normalize_url(full_url)
                    if normalized in local_processed_urls:
                        continue

                    page_article_links.append((full_url, text))
                    local_processed_urls.add(normalized)

                logger.info(f"[{index}] {name}: 在 {pr_name} 第 {page_count} 页找到 {len(page_article_links)} 篇文章链接")
                
                # 调试：如果找到0篇文章，记录页面中所有链接的前10个
                if len(page_article_links) == 0:
                    all_links_debug = []
                    for link in pr_soup.find_all('a', href=True)[:10]:
                        href = link.get('href', '')
                        text = link.get_text(strip=True)[:50]
                        all_links_debug.append(f"{text[:30]}... -> {href[:60]}")
                    logger.info(f"[{index}] {name}: 调试 - 页面中的部分链接: {all_links_debug}")

                # 第2页检查日期，如果文章早于2024年10月31日，则停止翻页
                if page_count == 2 and page_article_links:
                    try:
                        test_url, test_title = page_article_links[0]
                        smart_delay()
                        test_response = session.get(test_url, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
                        test_soup = BeautifulSoup(test_response.content, 'lxml')
                        test_data = extract_article_content(test_soup, test_url)

                        if test_data['date'] and not is_after_start_date(test_data['date']):
                            logger.info(f"[{index}] {name}: {pr_name} 第2页文章早于2024年10月31日，停止翻页")
                            stop_pagination = True
                    except:
                        pass

                # 将本页找到的文章链接添加到总列表
                all_article_links.extend(page_article_links)

                # 获取下一页URL
                if not stop_pagination:
                    # 首先尝试从页面中提取下一页链接
                    next_page_link = None
                    next_page_patterns = [
                        'a.next', 'a[rel="next"]', '.pagination a.next', '.nav-previous a',
                        'a:contains("Next")', 'a:contains("→")', 'a:contains(">")'
                    ]
                    for pattern in next_page_patterns:
                        try:
                            next_link = pr_soup.select_one(pattern)
                            if next_link and next_link.get('href'):
                                potential_next = urljoin(website, next_link['href'])
                                # 确保提取的下一页链接与当前页面不同
                                if normalize_url(potential_next) != normalize_url(current_page_url):
                                    next_page_link = potential_next
                                    break
                        except:
                            continue
                    
                    # 如果页面中没有找到下一页链接，则基于原始列表页URL生成
                    if next_page_link:
                        next_page_url = next_page_link
                        logger.info(f"[{index}] {name}: 从页面提取的下一页URL: {next_page_url}")
                    else:
                        next_page_url = get_next_page_url(base_list_url, page_count)
                        logger.info(f"[{index}] {name}: 生成的下一页URL: {next_page_url}")

                    # 确保下一页URL与当前页面不同且未访问过
                    if next_page_url and normalize_url(next_page_url) != normalize_url(current_page_url) and not is_url_processed(next_page_url):
                        current_page_url = next_page_url
                    elif page_count >= max_pages:
                        current_page_url = None
                    else:
                        current_page_url = None
                else:
                    current_page_url = None

            logger.info(f"[{index}] {name}: 完成 {pr_name}，共找到 {len(all_article_links)} 篇文章链接")

        # 遍历文章链接，提取符合日期要求的文章
        consecutive_old_articles = 0  # 连续不符合日期要求的文章数量
        processed_article_urls = set()  # 当前议员文章URL去重
        
        for article_url, article_title in all_article_links:
            try:
                # 严格检查文章URL是否属于当前议员的网站
                article_domain = urlparse(article_url).netloc.lower()
                website_domain = urlparse(website).netloc.lower()
                if article_domain != website_domain:
                    continue

                # 只检查当前议员的文章URL是否重复，不使用全局去重
                normalized_article_url = normalize_url(article_url)
                if normalized_article_url in processed_article_urls:
                    continue
                processed_article_urls.add(normalized_article_url)

                smart_delay()
                article_response = session.get(article_url, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
                article_response.raise_for_status()
                article_soup = BeautifulSoup(article_response.content, 'lxml')
                mark_url_processed(article_url)

                article_data = extract_article_content(article_soup, article_url)

                # 检查日期是否在2024年10月31日之后
                if not is_after_start_date(article_data['date']):
                    consecutive_old_articles += 1
                    date_str = article_data['date'].strftime('%Y-%m-%d') if article_data['date'] else '无法解析或无日期'
                    logger.info(f"[{index}] {name}: 文章日期 {date_str} 早于2024年10月31日，跳过: {article_url[:60]}...")
                    
                    # 连续10条以上不符合要求，停止搜索
                    if consecutive_old_articles >= 10:
                        logger.info(f"[{index}] {name}: 连续{consecutive_old_articles}篇文章早于2024年10月31日，停止搜索")
                        break
                    continue
                
                # 如果找到符合要求的文章，重置计数器
                consecutive_old_articles = 0
                
                # 创建文章记录
                article_record = {
                    'representative_name': name,
                    'district': district,
                    'state': state,
                    'party': party,
                    'article_title': article_data['title'] or article_title,
                    'article_url': article_url,
                    'publish_date': article_data['date'].strftime('%Y-%m-%d') if article_data['date'] else '',
                    'content': article_data['content'][:10000] if article_data['content'] else '',
                }

                articles_found.append(article_record)
                logger.info(f"[{index}] {name}: 成功提取文章 - {article_record['article_title'][:50]}...")

            except Exception as e:
                logger.error(f"[{index}] {name}: 提取文章失败 {article_url}: {str(e)}")
                continue

        # 更新进度
        with progress_lock:
            completed_count += 1
            progress = (completed_count / total_count) * 100
            print(f"\r进度: {completed_count}/{total_count} ({progress:.1f}%)", end='', flush=True)

        return articles_found

    except Exception as e:
        error_msg = f"未知错误: {str(e)}"
        logger.error(f"[{index}] {name}: {error_msg}")
        failed_sites.append({'name': name, 'website': website, 'error': error_msg})
        return articles_found


def save_results_to_csv(articles, filename='scrape_representative_press_releases.csv'):
    """
    保存结果到CSV文件
    
    参数：
        articles: 文章记录列表
        filename: CSV文件名
    
    说明：
    - 如果文件不存在，会写入表头
    - 使用追加模式，不会覆盖已有数据
    """
    global total_articles_saved

    if not articles:
        logger.info("没有文章需要保存")
        return

    fieldnames = [
        'representative_name', 'district', 'state', 'party',
        'article_title', 'article_url', 'publish_date', 'content'
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
    """
    从CSV文件加载众议员信息
    
    参数：
        filename: CSV文件名
        limit: 限制加载数量（用于测试模式）
    
    返回：
        议员信息列表，每个元素是一个字典
    
    说明：
    - CSV文件应包含：name, website, district, state, party等列
    """
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
    """
    主函数：程序的入口点
    
    说明：
    - 检查依赖包
    - 加载议员数据
    - 使用多线程并发抓取
    - 保存结果到CSV文件
    """
    global logger, completed_count, total_count, all_articles, test_mode_global

    print("=" * 60)
    print("众议员Press Releases爬虫 - 第一步")
    print("收集2024年10月31日至今的所有Press Releases")
    print("=" * 60)

    print("\n检查依赖包...")
    check_and_install_dependencies()

    logger = setup_logging()
    logger.info("爬虫启动")

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

    output_filename = 'scrape_representative_press_releases_test.csv' if test_mode else 'scrape_representative_press_releases.csv'

    # 测试模式下删除旧文件
    if test_mode and os.path.exists(output_filename):
        os.remove(output_filename)
        logger.info(f"已删除旧的测试文件: {output_filename}")

    session = create_session()

    print(f"开始爬取（使用 {MAX_WORKERS} 个线程）...\n")

    # 使用线程池并发处理多个议员
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}

        # 提交所有任务
        for i, rep in enumerate(representatives, 1):
            name = rep.get('name', '')
            website = rep.get('website', '')
            district = rep.get('district', '')
            state = rep.get('state', '')
            party = rep.get('party', '')

            if not website:
                continue

            future = executor.submit(scrape_representative_press_releases, i, name, website, district, state, party)
            futures[future] = (i, name)

        # 处理完成的任务
        for future in as_completed(futures):
            i, name = futures[future]
            try:
                articles = future.result()
                
                # 立即保存每个议员的文章（避免多线程竞争和数据丢失）
                if articles:
                    with progress_lock:
                        save_results_to_csv(articles, output_filename)
                        all_articles.extend(articles)

            except Exception as e:
                logger.error(f"处理 {name} 时出错: {str(e)}")

    # 保存剩余的文章
    if all_articles:
        save_results_to_csv(all_articles, output_filename)

    print("\n" + "=" * 60)
    print("爬取完成！")
    print("=" * 60)
    print(f"处理网站数: {total_count}")
    print(f"成功提取文章数: {total_articles_saved}")
    print(f"失败网站数: {len(failed_sites)}")
    print(f"结果已保存到: {output_filename}")
    print(f"日志文件: scrape_press_releases.log")

    logger.info(f"爬虫结束 - 共保存 {total_articles_saved} 篇文章")


# 程序入口
if __name__ == '__main__':
    main()
