#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
众议员Press Release页面URL查找工具 - 使用Selenium/ChromeDriver
根据house_representatives_websites.csv中441名代表的个人网站，
找到每个个人网站中press release这一级的页面的网址
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
from datetime import datetime
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# 配置参数
MAX_WORKERS = 5  # 并发浏览器数，兼顾效率和稳定性
PAGE_LOAD_TIMEOUT = 25  # 页面加载超时时间
SCRIPT_TIMEOUT = 20  # 脚本执行超时时间
IMPLICIT_WAIT = 8  # 隐式等待时间
MAX_RETRIES = 3  # 最大重试次数（不超过3次）
MIN_DELAY_BETWEEN_REQUESTS = 2  # 请求间最小延迟（秒）
MAX_DELAY_BETWEEN_REQUESTS = 4  # 请求间最大延迟（秒）
SAVE_INTERVAL = 50  # 每50人保存一次CSV

# 全局变量
progress_lock = threading.Lock()
save_lock = threading.Lock()
completed_count = 0
total_count = 0
results = []
failed_sites = []

# 一级菜单关键词（Media/Press/News相关）
PRIMARY_MENU_KEYWORDS = [
    'media', 'press', 'news', 'statements', 'media center', 'newsroom'
]

# Press Releases 二级菜单关键词
PRESS_RELEASES_KEYWORDS = [
    'press releases', 'press-releases', 'pressrelease', 'press release',
    'news releases', 'news-releases', 'newsrelease', 'news release',
    'media releases', 'media-releases', 'mediarelease', 'media release',
    'official statements', 'official-statements',
    'press statements', 'press-statements',
    'press room', 'pressroom', 'news room', 'newsroom',
    'media room', 'mediaroom',
]

# 排除单篇文章URL的模式（避免抓到具体文章而不是列表页）
ARTICLE_URL_PATTERNS = [
    r'/\d{4}/\d{2}/\d{2}/',  # 日期格式 /2024/03/15/
    r'/article/',  # /article/
    r'/post/',  # /post/
    r'/blog/',  # /blog/
    r'/news/\d+',  # /news/12345
    r'/press-release/\d+',  # /press-release/12345
]


def check_and_install_dependencies():
    """检查并安装必要的依赖包"""
    dependencies = [
        ('selenium', 'selenium>=4.15.0'),
        ('webdriver_manager', 'webdriver-manager>=4.0.0'),
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
    logger = logging.getLogger('PressReleaseUrlFinder')
    logger.setLevel(logging.INFO)

    if logger.handlers:
        return logger

    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

    file_handler = logging.FileHandler('house_representatives_websites_PRESS.log', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


logger = None
_chromedriver_path = None  # 全局缓存ChromeDriver路径
_driver_lock = threading.Lock()  # 用于同步ChromeDriver安装


def get_chromedriver_path():
    """获取ChromeDriver路径，使用全局缓存避免并发冲突"""
    global _chromedriver_path
    
    with _driver_lock:
        if _chromedriver_path is None:
            from webdriver_manager.chrome import ChromeDriverManager
            try:
                _chromedriver_path = ChromeDriverManager().install()
                logger.info(f"ChromeDriver已安装: {_chromedriver_path}")
            except Exception as e:
                logger.error(f"ChromeDriver安装失败: {str(e)}")
                raise
    
    return _chromedriver_path


def create_driver():
    """创建Chrome WebDriver"""
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)
    
    # 优化性能
    options.add_argument('--disable-extensions')
    options.add_argument('--disable-images')
    
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]
    options.add_argument(f'user-agent={random.choice(user_agents)}')

    # 使用缓存的ChromeDriver路径
    chromedriver_path = get_chromedriver_path()
    service = Service(chromedriver_path)
    
    try:
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        driver.set_script_timeout(SCRIPT_TIMEOUT)
        driver.implicitly_wait(IMPLICIT_WAIT)
        return driver
    except Exception as e:
        logger.error(f"创建WebDriver失败: {str(e)}")
        raise


def smart_delay(min_delay=None, max_delay=None):
    """智能延迟 - 使用配置参数控制延迟，避免IP被封"""
    if min_delay is None:
        min_delay = MIN_DELAY_BETWEEN_REQUESTS
    if max_delay is None:
        max_delay = MAX_DELAY_BETWEEN_REQUESTS
    delay = random.uniform(min_delay, max_delay)
    time.sleep(delay)


def normalize_url(url):
    """标准化URL"""
    url = url.rstrip('/')
    parsed = urlparse(url)
    if parsed.query:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{parsed.query}"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def is_article_url(url):
    """检查URL是否是单篇文章（而不是列表页）"""
    url_lower = url.lower()
    for pattern in ARTICLE_URL_PATTERNS:
        if re.search(pattern, url_lower):
            return True
    return False


def load_page_with_retry(driver, url, max_retries=MAX_RETRIES):
    """带重试机制的页面加载 - 最多重试3次，避免IP被封"""
    from selenium.common.exceptions import TimeoutException, WebDriverException
    
    for attempt in range(max_retries):
        try:
            driver.get(url)
            return True
        except TimeoutException:
            logger.warning(f"页面加载超时 (尝试 {attempt + 1}/{max_retries}): {url}")
            if attempt < max_retries - 1:
                # 使用更长的延迟，避免IP被封
                wait_time = 3 + attempt * 2  # 第1次等待3秒，第2次等待5秒
                logger.info(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
            else:
                logger.error(f"页面加载失败，已达最大重试次数 ({max_retries}): {url}")
                return False
        except WebDriverException as e:
            logger.warning(f"页面加载失败 (尝试 {attempt + 1}/{max_retries}): {url}, 错误: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = 3 + attempt * 2
                logger.info(f"等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)
            else:
                logger.error(f"页面加载失败，已达最大重试次数 ({max_retries}): {url}")
                return False
    return False


def find_press_releases_link(driver, base_url, exclude_media_center=False):
    """在页面中查找Press Releases链接
    
    Args:
        driver: WebDriver实例
        base_url: 基础URL
        exclude_media_center: 如果为True，排除Media Center等一级菜单链接
    """
    from selenium.webdriver.common.by import By

    pr_links = []

    try:
        links = driver.find_elements(By.TAG_NAME, 'a')
        for link in links:
            try:
                href = link.get_attribute('href')
                text = link.text.strip()
                title = link.get_attribute('title') or ''
                text_lower = text.lower()
                href_lower = href.lower() if href else ''

                if not href:
                    continue

                # 跳过锚点链接和javascript链接
                if href.startswith('#') or href.startswith('javascript:'):
                    continue

                # 如果exclude_media_center为True，跳过Media Center等一级菜单链接
                # 但保留包含 "press releases" 的链接
                if exclude_media_center:
                    # 检查是否是一级菜单链接（media center, media-center等）
                    # 但链接文本包含 "press releases" 的不跳过
                    has_press_release = 'press release' in text_lower or 'press-release' in href_lower
                    
                    if not has_press_release:
                        # 检查是否是一级菜单链接
                        is_media_center = False
                        for mc_keyword in ['media center', 'media-center', 'newsroom', 'news room']:
                            if mc_keyword in text_lower or mc_keyword in href_lower:
                                is_media_center = True
                                break
                        # 如果是一级菜单链接且不是press releases，跳过
                        if is_media_center:
                            continue
                        # 如果链接文本只包含"media"/"press"/"news"但不包含"releases"，也跳过
                        if (text_lower in ['media', 'press', 'news']) and \
                           ('release' not in text_lower):
                            continue

                for keyword in PRESS_RELEASES_KEYWORDS:
                    if keyword in href_lower or keyword in text_lower or keyword in title.lower():
                        full_url = urljoin(base_url, href)
                        # 确保链接是同一域名下的
                        if urlparse(full_url).netloc == urlparse(base_url).netloc:
                            # 检查是否是单篇文章URL
                            if is_article_url(full_url):
                                logger.debug(f"跳过单篇文章URL: {full_url}")
                                continue
                            pr_links.append({
                                'url': full_url,
                                'text': text if text else keyword
                            })
                            break
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"查找Press Releases链接失败: {str(e)}")

    return pr_links


def find_primary_menu_links(driver, base_url):
    """查找一级菜单链接（Media/Press/News相关）"""
    from selenium.webdriver.common.by import By

    menu_links = []

    try:
        links = driver.find_elements(By.TAG_NAME, 'a')
        for link in links:
            try:
                href = link.get_attribute('href')
                text = link.text.strip()

                if not href:
                    continue

                # 跳过锚点链接和javascript链接
                if href.startswith('#') or href.startswith('javascript:'):
                    continue

                if any(keyword in text.lower() for keyword in PRIMARY_MENU_KEYWORDS):
                    full_url = urljoin(base_url, href)
                    # 确保链接是同一域名下的
                    if urlparse(full_url).netloc == urlparse(base_url).netloc:
                        menu_links.append({
                            'url': full_url,
                            'text': text if text else 'Media/Press/News'
                        })
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"查找一级菜单失败: {str(e)}")

    return menu_links


def get_unique_links(links):
    """去重链接列表"""
    seen_urls = set()
    unique_links = []
    for link in links:
        norm_url = normalize_url(link['url'])
        if norm_url not in seen_urls:
            seen_urls.add(norm_url)
            unique_links.append(link)
    return unique_links


def save_results_to_csv(results, filename='house_representatives_websites_PRESS.csv'):
    """保存结果到CSV文件（线程安全）"""
    if not results:
        logger.info("没有结果需要保存")
        return

    fieldnames = [
        'name', 'website', 'district', 'state', 'party', 'committee',
        'press_release_url', 'press_release_text', 'found_method', 'status'
    ]

    with save_lock:
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)

    logger.info(f"已保存 {len(results)} 条结果到 {filename}")


def find_press_release_url(index, name, website, district, state, party, committee, output_filename):
    """查找单个议员的Press Release页面URL"""
    global completed_count, total_count, results

    from selenium.common.exceptions import TimeoutException, WebDriverException

    driver = None
    result = {
        'name': name,
        'website': website,
        'district': district,
        'state': state,
        'party': party,
        'committee': committee,
        'press_release_url': '',
        'press_release_text': '',
        'found_method': '',
        'status': 'pending'
    }

    try:
        driver = create_driver()
        logger.info(f"[{index}] {name}: 开始查找 {website}")

        smart_delay()  # 使用默认延迟（2-4秒）
        
        # 使用带重试的页面加载
        if not load_page_with_retry(driver, website):
            result['status'] = 'timeout'
            logger.error(f"[{index}] {name}: 页面加载超时")
            failed_sites.append({'name': name, 'website': website, 'error': '页面加载超时'})
            return result

        # 第一步：直接在主页查找Press Releases链接（排除Media Center等一级菜单，但保留Press Releases）
        pr_links = find_press_releases_link(driver, website, exclude_media_center=True)

        if pr_links:
            unique_links = get_unique_links(pr_links)
            
            if unique_links:
                result['press_release_url'] = unique_links[0]['url']
                result['press_release_text'] = unique_links[0]['text']
                result['found_method'] = 'direct'
                result['status'] = 'success'
                logger.info(f"[{index}] {name}: 直接在主页找到Press Release链接 - {unique_links[0]['url']}")
        
        # 第二步：如果没有直接找到，查找一级菜单（Media/Press/News）
        if not result['press_release_url']:
            menu_links = find_primary_menu_links(driver, website)
            
            if menu_links:
                logger.info(f"[{index}] {name}: 找到 {len(menu_links)} 个一级菜单链接，开始检查...")
                
                for menu_link in menu_links[:3]:
                    try:
                        smart_delay()  # 使用默认延迟（2-4秒）
                        
                        # 使用带重试的页面加载
                        if not load_page_with_retry(driver, menu_link['url']):
                            logger.warning(f"[{index}] {name}: 菜单页面加载超时 - {menu_link['url']}")
                            continue

                        # 在一级菜单页面查找Press Releases链接（不排除Media Center）
                        sub_pr_links = find_press_releases_link(driver, website, exclude_media_center=False)
                        
                        if sub_pr_links:
                            unique_links = get_unique_links(sub_pr_links)
                            
                            if unique_links:
                                result['press_release_url'] = unique_links[0]['url']
                                result['press_release_text'] = unique_links[0]['text']
                                result['found_method'] = f"via_menu:{menu_link['text']}"
                                result['status'] = 'success'
                                logger.info(f"[{index}] {name}: 在菜单 {menu_link['text']} 中找到Press Release链接 - {unique_links[0]['url']}")
                                break
                    except Exception as e:
                        logger.warning(f"[{index}] {name}: 访问菜单 {menu_link['url']} 失败: {str(e)}")
                        continue

        if not result['press_release_url']:
            result['status'] = 'not_found'
            logger.info(f"[{index}] {name}: 未找到Press Release页面")

    except TimeoutException:
        result['status'] = 'timeout'
        error_msg = f"页面加载超时"
        logger.error(f"[{index}] {name}: {error_msg}")
        failed_sites.append({'name': name, 'website': website, 'error': error_msg})
    except WebDriverException as e:
        result['status'] = 'error'
        error_msg = f"WebDriver错误: {str(e)}"
        logger.error(f"[{index}] {name}: {error_msg}")
        failed_sites.append({'name': name, 'website': website, 'error': error_msg})
    except Exception as e:
        result['status'] = 'error'
        error_msg = f"未知错误: {str(e)}"
        logger.error(f"[{index}] {name}: {error_msg}")
        failed_sites.append({'name': name, 'website': website, 'error': error_msg})
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    with progress_lock:
        completed_count += 1
        progress = (completed_count / total_count) * 100
        print(f"\r进度: {completed_count}/{total_count} ({progress:.1f}%)", end='', flush=True)

    return result


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
    global logger, completed_count, total_count, results

    print("=" * 60)
    print("众议员Press Release页面URL查找工具 - Selenium/ChromeDriver版")
    print("=" * 60)

    print("\n检查依赖包...")
    check_and_install_dependencies()

    logger = setup_logging()
    logger.info("Press Release URL查找工具启动")

    print("\n加载众议员数据...")
    test_mode = input("是否测试模式（只处理前5人）? (y/n): ").lower().strip() == 'y'
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
        print(f"完整模式：处理所有众议员，每{SAVE_INTERVAL}人自动保存\n")

    output_filename = 'house_representatives_websites_PRESS_test.csv' if test_mode else 'house_representatives_websites_PRESS.csv'

    print(f"开始查找Press Release页面URL（使用 {MAX_WORKERS} 个浏览器实例）...\n")

    # 检查是否存在之前的临时结果
    temp_filename = output_filename + '.tmp'
    if os.path.exists(temp_filename):
        print(f"发现之前的临时文件: {temp_filename}")
        response = input("是否恢复之前的进度? (y/n): ").lower().strip()
        if response == 'y':
            with open(temp_filename, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                results = list(reader)
                completed_count = len(results)
                print(f"已恢复 {completed_count} 条记录，从第 {completed_count + 1} 人继续...\n")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}

        for i, rep in enumerate(representatives, 1):
            # 如果已经处理过，跳过
            if i <= completed_count:
                continue
                
            name = rep.get('name', '')
            website = rep.get('website', '')
            district = rep.get('district', '')
            state = rep.get('state', '')
            party = rep.get('party', '')
            committee = rep.get('committee', '')

            if not website:
                logger.warning(f"[{i}] {name}: 没有网站信息，跳过")
                continue

            future = executor.submit(
                find_press_release_url, 
                i, name, website, district, state, party, committee, output_filename
            )
            futures[future] = (i, name)

        # 收集结果并定期保存
        for future in as_completed(futures):
            i, name = futures[future]
            try:
                result = future.result()
                results.append(result)
                
                # 每SAVE_INTERVAL人保存一次
                if len(results) % SAVE_INTERVAL == 0:
                    save_results_to_csv(results, temp_filename)
                    logger.info(f"已自动保存临时结果: {len(results)} 条记录")
                    
            except Exception as e:
                logger.error(f"处理 {name} 时出错: {str(e)}")

    # 最终保存
    save_results_to_csv(results, output_filename)
    
    # 删除临时文件
    if os.path.exists(temp_filename):
        try:
            os.remove(temp_filename)
            logger.info(f"已删除临时文件: {temp_filename}")
        except Exception as e:
            logger.warning(f"删除临时文件失败: {str(e)}")

    # 统计
    success_count = sum(1 for r in results if r['status'] == 'success')
    not_found_count = sum(1 for r in results if r['status'] == 'not_found')
    error_count = sum(1 for r in results if r['status'] in ['error', 'timeout'])

    print("\n" + "=" * 60)
    print("查找完成！")
    print("=" * 60)
    print(f"处理网站数: {total_count}")
    print(f"成功找到Press Release URL: {success_count}")
    print(f"未找到Press Release页面: {not_found_count}")
    print(f"处理失败: {error_count}")
    print(f"结果已保存到: {output_filename}")
    print(f"日志文件: house_representatives_websites_PRESS.log")

    logger.info(f"查找结束 - 成功: {success_count}, 未找到: {not_found_count}, 失败: {error_count}")


if __name__ == '__main__':
    main()
