#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
众议员Press Releases爬虫 - 第一步
收集美国众议员官方网站 Press Releases 栏目下的所有通讯稿
时间范围：2024年10月31日至今
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
MIN_DELAY = 1.0
MAX_DELAY = 2.0
REQUEST_TIMEOUT = 25
MAX_RETRIES = 3
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

    if missing_packages:
        print(f"正在安装缺失的依赖包: {missing_packages}")
        for package in missing_packages:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', package])


def setup_logging():
    """配置日志"""
    logger = logging.getLogger('PressReleaseScraper')
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    file_handler = logging.FileHandler('scrape_press_releases.log', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


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
    if parsed.query:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{parsed.query}"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def is_url_processed(url):
    """检查URL是否已处理"""
    normalized = normalize_url(url)
    return normalized in processed_urls_global


def mark_url_processed(url):
    """标记URL已处理"""
    normalized = normalize_url(url)
    processed_urls_global.add(normalized)


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
                if parsed.year > current_year + 1 or parsed.year < 1990:
                    continue
                return parsed
            except:
                continue

    try:
        parsed = date_parser.parse(date_text)
        if parsed.year > current_year + 1 or parsed.year < 1990:
            return None
        return parsed
    except:
        pass

    return None


def is_after_start_date(date_obj):
    """检查日期是否在2024年10月31日之后"""
    if not date_obj:
        return False  # 无法解析日期的文章不保存

    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()

    return date_obj >= START_DATE


def find_primary_menu_links(soup, base_url):
    """在页面中寻找一级菜单链接（media, press, news, statements）"""
    menu_links = []

    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
        text = link.get_text(strip=True).lower()

        if any(keyword in text for keyword in PRIMARY_MENU_KEYWORDS):
            full_url = urljoin(base_url, href)
            if full_url.startswith(base_url):
                normalized = normalize_url(full_url)
                if normalized not in [normalize_url(l[0]) for l in menu_links]:
                    menu_links.append((full_url, text))

    return menu_links


def find_press_releases_links(soup, base_url):
    """在页面中寻找 Press Releases 链接"""
    pr_links = []

    for link in soup.find_all('a', href=True):
        href = link.get('href', '')
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


def get_next_page_url(original_list_url, current_page_num):
    """基于原始列表页URL构造下一页URL"""
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

    parsed = urlparse(original_list_url)
    query_params = parse_qs(parsed.query)
    next_page = current_page_num + 1

    path_match = re.search(r'/(page|pages|p)/(\d+)/?$', parsed.path, re.IGNORECASE)
    if path_match:
        prefix = path_match.group(1)
        new_path = re.sub(r'/(page|pages|p)/(\d+)/?$', f'/{prefix}/{next_page}/', parsed.path, flags=re.IGNORECASE)
        return urlunparse((
            parsed.scheme, parsed.netloc, new_path,
            parsed.params, parsed.query, parsed.fragment
        ))

    if 'page' in query_params:
        query_params['page'] = [str(next_page)]
        new_query = urlencode(query_params, doseq=True)
        return urlunparse((
            parsed.scheme, parsed.netloc, parsed.path,
            parsed.params, new_query, parsed.fragment
        ))

    query_params['page'] = [str(next_page)]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, new_query, parsed.fragment
    ))


def extract_article_content(soup, url):
    """从文章页面提取内容"""
    from bs4 import BeautifulSoup

    title = None
    content = None
    date_obj = None

    title_tag = soup.find('h1')
    if not title_tag:
        title_tag = soup.find('h2')
    if title_tag:
        title = title_tag.get_text(strip=True)

    content_selectors = [
        'article',
        '[role="main"]',
        '.article-content',
        '.post-content',
        '.entry-content',
        '.content',
        'main',
        '.story-body'
    ]

    for selector in content_selectors:
        content_elem = soup.select_one(selector)
        if content_elem:
            paragraphs = content_elem.find_all('p')
            if paragraphs:
                content = '\n\n'.join([p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True)])
                break

    if not content:
        all_p = soup.find_all('p')
        if all_p:
            content = '\n\n'.join([p.get_text(strip=True) for p in all_p[:20] if p.get_text(strip=True)])

    date_selectors = [
        'time[datetime]',
        '.publish-date',
        '.post-date',
        '.article-date',
        '.date',
        'meta[property="article:published_time"]'
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
    """爬取单个议员的Press Releases"""
    global completed_count, total_count, all_articles, all_article_links

    from bs4 import BeautifulSoup

    articles_found = []
    local_processed_urls = set()
    all_article_links = []

    try:
        session = create_session()
        logger.info(f"[{index}] {name}: 开始爬取 {website}")

        smart_delay()
        response = session.get(website, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'lxml')
        mark_url_processed(website)

        pr_links = find_press_releases_links(soup, website)

        if not pr_links:
            primary_menu_links = find_primary_menu_links(soup, website)

            for menu_url, menu_name in primary_menu_links[:3]:
                if is_url_processed(menu_url):
                    continue

                try:
                    smart_delay()
                    menu_response = session.get(menu_url, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
                    menu_response.raise_for_status()
                    menu_soup = BeautifulSoup(menu_response.content, 'lxml')
                    mark_url_processed(menu_url)

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

                    page_article_links.append((full_url, text))
                    local_processed_urls.add(normalized)

                logger.info(f"[{index}] {name}: 在 {pr_name} 第 {page_count} 页找到 {len(page_article_links)} 篇文章链接")

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

                all_article_links.extend(page_article_links)

                if not stop_pagination:
                    next_page_url = get_next_page_url(original_list_url, page_count)

                    if next_page_url and not is_url_processed(next_page_url):
                        original_list_url = next_page_url
                    elif page_count >= max_pages:
                        original_list_url = None
                    else:
                        original_list_url = None
                else:
                    original_list_url = None

            logger.info(f"[{index}] {name}: 完成 {pr_name}，共找到 {len(all_article_links)} 篇文章链接")

        # 遍历文章链接，提取符合日期要求的文章
        consecutive_old_articles = 0  # 连续不符合日期要求的文章数量
        
        for article_url, article_title in all_article_links:
            try:
                if is_url_processed(article_url):
                    continue

                smart_delay()
                article_response = session.get(article_url, headers=get_random_headers(), timeout=REQUEST_TIMEOUT)
                article_response.raise_for_status()
                article_soup = BeautifulSoup(article_response.content, 'lxml')
                mark_url_processed(article_url)

                article_data = extract_article_content(article_soup, article_url)

                if not is_after_start_date(article_data['date']):
                    consecutive_old_articles += 1
                    date_str = article_data['date'].strftime('%Y-%m-%d') if article_data['date'] else '无法解析'
                    logger.info(f"[{index}] {name}: 文章日期 {date_str} 早于2024年10月31日，跳过: {article_url[:60]}...")
                    
                    # 连续10条以上不符合要求，停止搜索
                    if consecutive_old_articles >= 10:
                        logger.info(f"[{index}] {name}: 连续{consecutive_old_articles}篇文章早于2024年10月31日，停止搜索")
                        break
                    continue
                
                # 如果找到符合要求的文章，重置计数器
                consecutive_old_articles = 0
                
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
    """保存结果到CSV文件"""
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
    print("众议员Press Releases爬虫 - 第一步")
    print("收集2024年10月31日至今的所有Press Releases")
    print("=" * 60)

    print("\n检查依赖包...")
    check_and_install_dependencies()

    logger = setup_logging()
    logger.info("爬虫启动")

    import requests
    from bs4 import BeautifulSoup

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

    if test_mode and os.path.exists(output_filename):
        os.remove(output_filename)
        logger.info(f"已删除旧的测试文件: {output_filename}")

    session = create_session()

    print(f"开始爬取（使用 {MAX_WORKERS} 个线程）...\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}

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

        for future in as_completed(futures):
            i, name = futures[future]
            try:
                articles = future.result()
                all_articles.extend(articles)

                if len(all_articles) >= BATCH_SIZE:
                    save_results_to_csv(all_articles, output_filename)
                    all_articles = []

            except Exception as e:
                logger.error(f"处理 {name} 时出错: {str(e)}")

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


if __name__ == '__main__':
    main()
