#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
众议员涉华表态爬虫
收集美国众议员对中国有关问题的表态和新闻
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
from urllib.parse import urljoin, urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# 配置参数
MAX_WORKERS = 5  # 并发线程数（保守设置，避免被封）
MIN_DELAY = 2.0   # 最小延迟（秒）
MAX_DELAY = 5.0   # 最大延迟（秒）
REQUEST_TIMEOUT = 20  # 请求超时（秒）
MAX_RETRIES = 3   # 最大重试次数
START_DATE = date(2021, 1, 1)  # 只收集2021年1月1日之后的新闻
BATCH_SIZE = 10   # 每处理10个网站保存一次中间结果

# 全局变量
progress_lock = threading.Lock()
completed_count = 0
total_count = 0
all_articles = []
failed_sites = []
processed_urls_global = set()  # 全局URL去重集合
test_mode_global = False  # 测试模式标志

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

# 新闻栏目关键词
NEWS_SECTION_KEYWORDS = [
    'press', 'news', 'media', 'statements',
    'press-releases', 'press releases', 'media-center', 'media center',
    'newsroom', 'in the news', 'latest news', 'news releases',
    'press room', 'pressroom', 'for the media'
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
        ('dateutil', 'python-dateutil>=2.8.0'),
        ('youtube_transcript_api', 'youtube-transcript-api>=0.6.0')
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
            logging.FileHandler('crawl_log.txt', encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


logger = None


def get_random_headers():
    """获取随机请求头"""
    return {
        'User-Agent': random.choice(USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Cache-Control': 'max-age=0'
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
    """标准化URL用于去重"""
    # 移除末尾的斜杠
    url = url.rstrip('/')
    # 移除常见的跟踪参数
    parsed = urlparse(url)
    # 只保留路径，忽略查询参数中的跟踪代码
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def is_url_processed(url):
    """检查URL是否已处理过"""
    normalized = normalize_url(url)
    return normalized in processed_urls_global


def mark_url_processed(url):
    """标记URL为已处理"""
    normalized = normalize_url(url)
    processed_urls_global.add(normalized)


def extract_youtube_video_id(url):
    """从YouTube URL中提取视频ID"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def is_youtube_url(url):
    """检查是否是YouTube链接"""
    return 'youtube.com' in url or 'youtu.be' in url


def get_youtube_transcript(video_id, max_retries=2):
    """
    获取YouTube视频的transcript
    返回transcript文本或None
    """
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        
        for attempt in range(max_retries):
            try:
                # 添加延迟避免被封
                time.sleep(random.uniform(3, 6))
                
                # 尝试获取transcript
                transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
                
                # 合并所有文本
                full_text = ' '.join([item['text'] for item in transcript_list])
                return full_text
                
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(random.uniform(5, 10))
                    continue
                else:
                    logger.warning(f"获取YouTube transcript失败 {video_id}: {str(e)}")
                    return None
                    
    except ImportError:
        logger.warning("youtube_transcript_api未安装，无法获取YouTube字幕")
        return None


def find_news_section_links(soup, base_url):
    """
    在页面中寻找新闻/媒体相关的链接
    返回找到的链接列表
    """
    news_links = []
    
    # 查找所有链接
    for link in soup.find_all('a', href=True):
        href = link.get('href', '').lower()
        text = link.get_text(strip=True).lower()
        
        # 检查href或文本是否包含新闻相关关键词
        for keyword in NEWS_SECTION_KEYWORDS:
            if keyword in href or keyword in text:
                full_url = urljoin(base_url, link['href'])
                # 避免重复和外部链接
                if full_url.startswith(base_url):
                    normalized = normalize_url(full_url)
                    if normalized not in [normalize_url(l[0]) for l in news_links]:
                        news_links.append((full_url, text or keyword))
                    break
    
    return news_links


def find_pagination_links(soup, base_url, current_url):
    """
    在页面中寻找翻页链接（Page 2, 3, 4...）
    返回找到的翻页链接列表
    """
    pagination_links = []
    
    # 常见的翻页链接模式
    pagination_patterns = [
        r'page[=\/]?(\d+)',
        r'p[=\/]?(\d+)',
        r'/page/(\d+)',
        r'/pages/(\d+)',
        r'offset[=\/]?(\d+)',
        r'start[=\/]?(\d+)',
    ]
    
    # 查找页码链接
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        text = link.get_text(strip=True).lower()
        
        # 检查是否是页码链接（数字或包含page字样）
        is_page_link = False
        page_number = None
        
        # 检查文本是否是数字（页码）
        if text.isdigit():
            page_number = int(text)
            if page_number > 1:  # 只收集第2页及以后的链接
                is_page_link = True
        
        # 检查是否包含页码相关文字
        if not is_page_link:
            page_keywords = ['next', '下一页', 'page', 'older', 'previous posts', 'load more']
            for keyword in page_keywords:
                if keyword in text or keyword in href.lower():
                    is_page_link = True
                    break
        
        # 检查href是否匹配翻页模式
        if not is_page_link:
            for pattern in pagination_patterns:
                match = re.search(pattern, href, re.IGNORECASE)
                if match:
                    try:
                        page_number = int(match.group(1))
                        if page_number > 1:
                            is_page_link = True
                            break
                    except:
                        continue
        
        if is_page_link:
            full_url = urljoin(base_url, href)
            # 确保链接属于同一网站
            if full_url.startswith(base_url.split('/')[0] + '//' + base_url.split('/')[2]):
                normalized = normalize_url(full_url)
                # 避免重复
                if normalized not in [normalize_url(l) for l in pagination_links]:
                    pagination_links.append(full_url)
    
    return pagination_links[:5]  # 最多返回5个翻页链接（限制爬取深度）


def contains_china_keywords(text):
    """
    检查文本是否包含中国相关关键词
    """
    if not text:
        return False
    
    text_lower = text.lower()
    matched_keywords = []
    
    for keyword in CHINA_KEYWORDS:
        # 使用单词边界匹配，避免部分匹配
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, text_lower):
            matched_keywords.append(keyword)
    
    return matched_keywords if matched_keywords else False


def parse_date(date_text):
    """
    尝试从文本中解析日期
    返回datetime对象或None
    """
    from dateutil import parser as date_parser
    
    if not date_text:
        return None
    
    # 清理文本
    date_text = date_text.strip()
    
    # 常见日期格式
    date_patterns = [
        r'(\w+\s+\d{1,2},?\s+\d{4})',  # January 1, 2024 or January 1 2024
        r'(\d{1,2}/\d{1,2}/\d{2,4})',   # 1/1/2024 or 01/01/24
        r'(\d{1,2}-\d{1,2}-\d{2,4})',   # 1-1-2024 or 01-01-24
        r'(\d{4}-\d{2}-\d{2})',          # 2024-01-01
        r'(\d{4}/\d{2}/\d{2})',          # 2024/01/01
    ]
    
    for pattern in date_patterns:
        match = re.search(pattern, date_text)
        if match:
            try:
                parsed = date_parser.parse(match.group(1))
                return parsed
            except:
                continue
    
    # 直接尝试解析
    try:
        return date_parser.parse(date_text)
    except:
        pass
    
    return None


def is_after_start_date(date_obj):
    """检查日期是否在2021年1月1日之后"""
    if not date_obj:
        return True  # 如果无法解析日期，默认保留
    
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()
    
    return date_obj >= START_DATE


def extract_article_content(soup, url):
    """
    从文章详情页提取内容
    返回字典包含：title, date, content, redirect_url, redirect_title, redirect_content
    """
    from bs4 import BeautifulSoup
    import requests
    
    article_data = {
        'title': '',
        'date': None,
        'content': '',
        'redirect_url': '',
        'redirect_title': '',
        'redirect_date': '',
        'redirect_content': '',
        'is_youtube': False,
        'youtube_transcript': ''
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
        '.post', '.entry', '.page-content'
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
    
    # 检查页面中的跳转链接
    redirect_links = []
    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        text = link.get_text(strip=True)
        
        # 跳过导航和短链接
        if len(text) < 5 or len(text) > 200:
            continue
        
        full_url = urljoin(url, href)
        
        # 检查是否是YouTube链接
        if is_youtube_url(full_url):
            video_id = extract_youtube_video_id(full_url)
            if video_id and not is_url_processed(full_url):
                redirect_links.append(('youtube', full_url, text, video_id))
        # 检查是否是其他外部链接（可能包含更多内容）
        elif not full_url.startswith(url.split('/')[2]) and ('podcast' in text.lower() or 'episode' in text.lower() or 'listen' in text.lower()):
            if not is_url_processed(full_url):
                redirect_links.append(('external', full_url, text, None))
    
    # 处理跳转链接（限制数量）
    for link_type, link_url, link_text, video_id in redirect_links[:3]:  # 最多处理3个跳转链接
        try:
            smart_delay()
            
            if link_type == 'youtube' and video_id:
                # 获取YouTube transcript
                logger.info(f"  发现YouTube链接，尝试获取transcript: {link_url}")
                transcript = get_youtube_transcript(video_id)
                
                if transcript:
                    article_data['redirect_url'] = link_url
                    article_data['redirect_title'] = link_text
                    article_data['is_youtube'] = True
                    article_data['youtube_transcript'] = transcript[:3000]  # 限制长度
                    article_data['redirect_content'] = f"[YouTube Video Transcript]\n{transcript[:2000]}..."
                    mark_url_processed(link_url)
                    break
                    
            elif link_type == 'external':
                # 尝试访问外部链接
                session_temp = create_session()
                response = session_temp.get(
                    link_url,
                    headers=get_random_headers(),
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True
                )
                
                if response.status_code == 200 and 'text/html' in response.headers.get('content-type', ''):
                    redirect_soup = BeautifulSoup(response.content, 'lxml')
                    redirect_data = extract_article_content(redirect_soup, link_url)
                    
                    article_data['redirect_url'] = link_url
                    article_data['redirect_title'] = redirect_data['title'] or link_text
                    article_data['redirect_date'] = redirect_data['date'].strftime('%Y-%m-%d') if redirect_data['date'] else ''
                    article_data['redirect_content'] = redirect_data['content'][:3000]
                    mark_url_processed(link_url)
                    break
                    
        except Exception as e:
            logger.warning(f"  处理跳转链接失败 {link_url}: {str(e)}")
            continue
    
    return article_data


def scrape_representative_website(session, rep_data, index):
    """
    爬取单个众议员的网站，寻找涉华新闻
    """
    import requests
    from bs4 import BeautifulSoup
    
    name = rep_data['name']
    website = rep_data['website']
    district = rep_data.get('district', '')
    state = rep_data.get('state', '')
    party = rep_data.get('party', '')
    
    articles_found = []
    local_processed_urls = set()  # 本地URL去重
    
    try:
        logger.info(f"[{index}] 正在处理: {name} - {website}")
        
        # 检查是否已处理过
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
        
        # 检查内容类型
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' not in content_type:
            logger.warning(f"[{index}] {name}: 非HTML内容，跳过")
            return articles_found
        
        soup = BeautifulSoup(response.content, 'lxml')
        mark_url_processed(website)
        
        # 寻找新闻栏目链接
        news_links = find_news_section_links(soup, website)
        
        if not news_links:
            logger.info(f"[{index}] {name}: 未找到新闻栏目，尝试从主页提取")
            news_links = [(website, 'homepage')]
        else:
            logger.info(f"[{index}] {name}: 找到 {len(news_links)} 个新闻相关链接")
        
        # 访问新闻页面并提取文章（支持翻页，直到找到2021年之后的新闻）
        for news_url, section_name in news_links[:3]:  # 最多处理前3个新闻链接
            try:
                if is_url_processed(news_url):
                    continue
                
                # 处理当前页和翻页
                pages_to_process = [news_url]
                processed_pages = set()
                page_count = 0
                max_pages = 10  # 最多处理10页（安全限制）
                stop_pagination = False  # 是否停止翻页的标志
                all_article_links = []  # 收集所有页面的涉华文章
                
                while pages_to_process and page_count < max_pages and not stop_pagination:
                    current_page_url = pages_to_process.pop(0)
                    
                    if is_url_processed(current_page_url):
                        continue
                    
                    try:
                        smart_delay()
                        news_response = session.get(
                            current_page_url,
                            headers=get_random_headers(),
                            timeout=REQUEST_TIMEOUT
                        )
                        news_response.raise_for_status()
                        news_soup = BeautifulSoup(news_response.content, 'lxml')
                        mark_url_processed(current_page_url)
                        processed_pages.add(current_page_url)
                        page_count += 1
                        
                        logger.info(f"[{index}] {name}: 正在处理 {section_name} 第 {page_count} 页")
                        
                        # 寻找翻页链接（只在第一页时查找）
                        if page_count == 1:
                            pagination_links = find_pagination_links(news_soup, website, current_page_url)
                            for page_link in pagination_links:
                                if not is_url_processed(page_link) and page_link not in processed_pages:
                                    pages_to_process.append(page_link)
                                    logger.info(f"[{index}] {name}: 发现翻页链接: {page_link}")
                        
                        # 寻找文章链接并检查日期
                        page_article_links = []
                        potential_articles = []
                        page_has_recent_articles = False  # 本页是否有2021年后的文章
                        
                        for link in news_soup.find_all('a', href=True):
                            href = link.get('href', '')
                            text = link.get_text(strip=True)
                            
                            if len(text) < 10 or len(text) > 200:
                                continue
                            
                            full_url = urljoin(website, href)
                            if not full_url.startswith(website):
                                continue
                            
                            # 检查URL是否已处理
                            normalized = normalize_url(full_url)
                            if normalized in local_processed_urls or is_url_processed(full_url):
                                continue
                            
                            # 检查标题是否包含中国关键词
                            matched_keywords = contains_china_keywords(text)
                            if matched_keywords:
                                page_article_links.append((full_url, text, matched_keywords))
                                local_processed_urls.add(normalized)
                            else:
                                potential_articles.append((full_url, text))
                        
                        logger.info(f"[{index}] {name}: 在 {section_name} 第 {page_count} 页找到 {len(page_article_links)} 篇标题含涉华关键词的文章")
                        
                        # 检查潜在文章（限制数量）
                        checked_count = 0
                        for article_url, article_title in potential_articles[:20]:
                            if checked_count >= 5:
                                break
                            
                            normalized = normalize_url(article_url)
                            if normalized in local_processed_urls:
                                continue
                            
                            try:
                                smart_delay()
                                article_response = session.get(
                                    article_url,
                                    headers=get_random_headers(),
                                    timeout=REQUEST_TIMEOUT
                                )
                                article_response.raise_for_status()
                                article_soup = BeautifulSoup(article_response.content, 'lxml')
                                
                                article_data = extract_article_content(article_soup, article_url)
                                full_text = f"{article_data['title']} {article_data['content']}"
                                
                                # 检查日期
                                if article_data['date']:
                                    if is_after_start_date(article_data['date']):
                                        page_has_recent_articles = True
                                
                                matched_keywords = contains_china_keywords(full_text)
                                if matched_keywords:
                                    page_article_links.append((article_url, article_title, matched_keywords))
                                    logger.info(f"[{index}] {name}: 潜在文章中发现涉华内容 - {article_title[:50]}...")
                                
                                local_processed_urls.add(normalized)
                                checked_count += 1
                                
                            except Exception as e:
                                continue
                        
                        # 检查本页文章日期，判断是否需要继续翻页
                        if page_count >= 2:  # 从第2页开始检查日期
                            recent_articles_count = 0
                            oldest_article_date = None
                            
                            for article_url, article_title, keywords in page_article_links[:5]:  # 检查前5篇文章
                                try:
                                    smart_delay()
                                    article_response = session.get(
                                        article_url,
                                        headers=get_random_headers(),
                                        timeout=REQUEST_TIMEOUT
                                    )
                                    article_response.raise_for_status()
                                    article_soup = BeautifulSoup(article_response.content, 'lxml')
                                    article_data = extract_article_content(article_soup, article_url)
                                    
                                    if article_data['date']:
                                        if is_after_start_date(article_data['date']):
                                            recent_articles_count += 1
                                            page_has_recent_articles = True
                                        if oldest_article_date is None or article_data['date'] < oldest_article_date:
                                            oldest_article_date = article_data['date']
                                    
                                except Exception as e:
                                    continue
                            
                            # 如果本页所有文章都早于2021年，停止翻页
                            if not page_has_recent_articles and oldest_article_date:
                                logger.info(f"[{index}] {name}: {section_name} 第 {page_count} 页文章均早于2021年（最早: {oldest_article_date.strftime('%Y-%m-%d')}），停止翻页")
                                stop_pagination = True
                        
                        all_article_links.extend(page_article_links)
                        logger.info(f"[{index}] {name}: 在 {section_name} 第 {page_count} 页最终找到 {len(page_article_links)} 篇涉华文章")
                        
                    except Exception as e:
                        logger.error(f"[{index}] {name}: 访问新闻页面失败 {current_page_url}: {str(e)}")
                        continue
                
                logger.info(f"[{index}] {name}: 完成 {section_name} 的所有翻页，共处理 {page_count} 页，累计找到 {len(all_article_links)} 篇涉华文章")
                
                # 使用收集到的所有文章链接
                article_links = all_article_links
                
                # 访问每篇涉华文章详情页
                for article_url, article_title, keywords in article_links[:10]:
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
                        
                        # 提取文章内容（包含跳转链接处理）
                        article_data = extract_article_content(article_soup, article_url)
                        
                        # 检查日期
                        if not is_after_start_date(article_data['date']):
                            logger.info(f"[{index}] {name}: 文章日期早于2021年，跳过")
                            continue
                        
                        # 再次确认内容包含中国关键词
                        full_text = f"{article_data['title']} {article_data['content']}"
                        if article_data['redirect_content']:
                            full_text += f" {article_data['redirect_content']}"
                        if article_data['youtube_transcript']:
                            full_text += f" {article_data['youtube_transcript']}"
                        
                        if not contains_china_keywords(full_text):
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
                            'matched_keywords': ', '.join(keywords),
                            'content': article_data['content'][:3000],
                            'redirect_url': article_data['redirect_url'],
                            'redirect_title': article_data['redirect_title'],
                            'redirect_date': article_data['redirect_date'],
                            'redirect_content': article_data['redirect_content'][:2000] if article_data['redirect_content'] else '',
                            'is_youtube': 'Yes' if article_data['is_youtube'] else 'No',
                            'youtube_transcript': article_data['youtube_transcript'][:2000] if article_data['youtube_transcript'] else ''
                        }
                        
                        articles_found.append(article_record)
                        logger.info(f"[{index}] {name}: 成功提取文章 - {article_record['article_title'][:50]}...")
                        
                    except Exception as e:
                        logger.error(f"[{index}] {name}: 提取文章失败 {article_url}: {str(e)}")
                        continue
                
            except Exception as e:
                logger.error(f"[{index}] {name}: 访问新闻页面失败 {news_url}: {str(e)}")
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


def save_results_to_csv(articles, filename='representatives_website_china_related_articles.csv'):
    """保存结果到CSV文件"""
    if not articles:
        logger.info("没有文章需要保存")
        return
    
    fieldnames = [
        'representative_name', 'district', 'state', 'party',
        'article_title', 'article_url', 'publish_date',
        'matched_keywords', 'content',
        'redirect_url', 'redirect_title', 'redirect_date', 'redirect_content',
        'is_youtube', 'youtube_transcript'
    ]
    
    file_exists = os.path.exists(filename)
    
    with open(filename, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(articles)
    
    logger.info(f"已保存 {len(articles)} 篇文章到 {filename}")


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
    print("众议员涉华表态爬虫")
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
    output_filename = 'representatives_website_china_related_articles_test.csv' if test_mode else 'representatives_website_china_related_articles.csv'
    
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
        failed_filename = 'failed_sites_test.txt' if test_mode else 'failed_sites.txt'
        with open(failed_filename, 'w', encoding='utf-8') as f:
            for site in failed_sites:
                f.write(f"{site['name']}: {site['website']} - {site['error']}\n")
        logger.info(f"已保存 {len(failed_sites)} 个失败网站记录到 {failed_filename}")
    
    # 输出统计
    print("\n" + "=" * 60)
    print("爬取完成！")
    print("=" * 60)
    print(f"处理网站数: {total_count}")
    print(f"成功提取文章数: {len(all_articles)}")
    print(f"失败网站数: {len(failed_sites)}")
    print(f"结果已保存到: {output_filename}")
    print(f"日志文件: crawl_log.txt")
    
    logger.info("爬虫结束")


if __name__ == "__main__":
    main()
