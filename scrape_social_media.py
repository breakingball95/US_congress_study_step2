#!/usr/bin/env python3
"""
美国众议院议员社交媒体爬虫（优化版）

功能：爬取美国众议院议员的X（Twitter）和Facebook个人主页链接，并保存为CSV文件

使用方法：
1. 确保已安装Python 3
2. 运行脚本：python scrape_social_media.py
   （脚本会自动检测并安装所需依赖）

输出：生成 house_representatives_social_media.csv 文件，列名为 name, website, X, Facebook

优化特性：
- 使用多线程并行处理（默认10个线程）
- 使用连接池复用HTTP连接
- 智能延迟策略（动态调整）
- 断点续传功能
- 实时保存进度
"""

# ============================================
# 第一部分：自动检测并安装依赖库
# ============================================
import subprocess
import sys
import importlib.util

def check_and_install_dependencies():
    """自动检测并安装所需依赖库"""
    
    # 定义需要检查的依赖 (模块导入名, pip包名)
    dependencies = [
        ("requests", "requests"),
        ("bs4", "beautifulsoup4"),
    ]
    
    print("=" * 50)
    print("正在检查依赖库...")
    print("=" * 50)
    
    need_install = []
    
    # 检测哪些库未安装
    for module_name, package_name in dependencies:
        spec = importlib.util.find_spec(module_name)
        if spec is None:
            print(f"  ✗ {module_name:15} 未安装")
            need_install.append(package_name)
        else:
            print(f"  ✓ {module_name:15} 已安装")
    
    # 安装缺失的库
    if need_install:
        print("\n正在安装缺失的依赖库...")
        for pkg in need_install:
            print(f"  安装 {pkg}...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", pkg],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"  ✓ {pkg} 安装成功")
            except subprocess.CalledProcessError:
                print(f"  ✗ {pkg} 安装失败")
                print(f"\n错误：无法安装 {pkg}，请检查网络连接或手动运行：pip install {pkg}")
                sys.exit(1)
        print("\n所有依赖库安装完成！")
    else:
        print("\n所有依赖库已就绪！")
    
    print("=" * 50)
    print()

# 运行依赖检测和安装
check_and_install_dependencies()

# ============================================
# 第二部分：主程序代码
# ============================================

import requests
from bs4 import BeautifulSoup
import csv
import time
import os
import random
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置参数
MAX_WORKERS = 10  # 并发线程数
MIN_DELAY = 1.5   # 最小延迟（秒）
MAX_DELAY = 3.5   # 最大延迟（秒）
REQUEST_TIMEOUT = 15  # 请求超时（秒）
MAX_RETRIES = 2   # 最大重试次数

# 反反爬虫设置：多个User-Agent随机轮换
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

# 全局变量
progress_lock = Lock()
completed_count = 0
total_count = 0

# 创建带连接池和重试机制的session
def create_session():
    """创建带连接池和重试机制的session"""
    session = requests.Session()
    
    # 配置重试策略
    retry_strategy = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    
    # 配置连接池
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=20
    )
    
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

# 读取之前爬取的众议员数据
def load_representatives():
    """从CSV文件加载众议员数据"""
    data_file = "house_representatives_websites.csv"
    
    if not os.path.exists(data_file):
        print(f"错误: 未找到众议员数据文件 {data_file}，请先运行 house_reps_scraper.py")
        return []
    
    try:
        representatives = []
        with open(data_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                representatives.append({
                    "name": row.get("name", ""),
                    "website": row.get("website", "")
                })
        return representatives
    except Exception as e:
        print(f"读取数据文件失败: {e}")
        return []

# 获取社交媒体链接（优化版）
def get_social_media_links(session, url, name=""):
    """从议员个人网站获取X和Facebook链接"""
    social_links = {
        "X": "",
        "Facebook": ""
    }
    
    if not url:
        return social_links
    
    # 随机选择User-Agent
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
    
    try:
        # 随机延迟
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        
        response = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        
        # 快速检查：如果页面中没有twitter或facebook关键词，直接返回
        html_lower = response.text.lower()
        has_twitter = 'twitter.com' in html_lower or 'x.com' in html_lower
        has_facebook = 'facebook.com' in html_lower
        
        if not has_twitter and not has_facebook:
            return social_links
        
        soup = BeautifulSoup(response.content, "html.parser")
        
        # 1. 快速查找：直接搜索所有链接
        links = soup.find_all("a", href=True)
        
        for link in links:
            href = link.get("href", "").strip()
            if not href:
                continue
                
            href_lower = href.lower()
            
            # 检查X/Twitter链接
            if not social_links["X"] and has_twitter:
                if any(keyword in href_lower for keyword in ["twitter.com", "x.com"]):
                    if not any(keyword in href_lower for keyword in ["intent/", "share", "status/"]):
                        social_links["X"] = href
            
            # 检查Facebook链接
            if not social_links["Facebook"] and has_facebook:
                if "facebook.com" in href_lower:
                    if not any(keyword in href_lower for keyword in ["sharer", "share.php", "dialog/"]):
                        social_links["Facebook"] = href
            
            # 如果都找到了，提前退出
            if social_links["X"] and social_links["Facebook"]:
                break
        
        # 2. 如果没找到，尝试通过图标查找
        if (not social_links["X"] and has_twitter) or (not social_links["Facebook"] and has_facebook):
            icons = soup.find_all(["i", "span", "svg", "img"], class_=True)
            for icon in icons:
                classes = icon.get("class", [])
                classes_str = " ".join(classes).lower()
                
                # 查找X/Twitter图标
                if not social_links["X"] and has_twitter:
                    if any(keyword in classes_str for keyword in ["twitter", "fa-twitter", "x-icon"]):
                        parent = icon.find_parent("a", href=True)
                        if parent:
                            parent_href = parent.get("href", "").lower()
                            if any(keyword in parent_href for keyword in ["twitter.com", "x.com"]):
                                social_links["X"] = parent.get("href")
                
                # 查找Facebook图标
                if not social_links["Facebook"] and has_facebook:
                    if any(keyword in classes_str for keyword in ["facebook", "fa-facebook"]):
                        parent = icon.find_parent("a", href=True)
                        if parent:
                            parent_href = parent.get("href", "").lower()
                            if "facebook.com" in parent_href:
                                social_links["Facebook"] = parent.get("href")
                
                if social_links["X"] and social_links["Facebook"]:
                    break
        
    except requests.exceptions.Timeout:
        pass  # 静默处理超时
    except requests.exceptions.TooManyRedirects:
        pass  # 静默处理重定向过多
    except Exception:
        pass  # 静默处理其他错误
    
    return social_links

# 处理单个议员
def process_representative(session, rep, index):
    """处理单个议员"""
    global completed_count
    
    name = rep.get("name", "")
    website = rep.get("website", "")
    
    # 获取社交媒体链接
    social_links = get_social_media_links(session, website, name)
    rep.update(social_links)
    
    # 更新进度
    with progress_lock:
        completed_count += 1
        current = completed_count
        
        # 每10个输出一次进度
        if current % 10 == 0 or current == 1 or current == total_count:
            print(f"进度: [{current}/{total_count}] {current/total_count*100:.1f}%")
    
    return rep

# 保存数据到文件（追加模式）
def save_data(representatives, filename="house_representatives_social_media.csv", mode='w'):
    """保存数据到CSV文件"""
    try:
        with open(filename, mode, newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if mode == 'w':
                writer.writerow(["name", "website", "X", "Facebook"])
            for rep in representatives:
                writer.writerow([
                    rep["name"], 
                    rep["website"], 
                    rep.get("X", ""), 
                    rep.get("Facebook", "")
                ])
        return True
    except Exception as e:
        print(f"保存CSV失败: {e}")
        return False

# 加载已完成的进度
def load_progress():
    """加载已完成的进度"""
    progress_file = "scrape_progress.txt"
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f:
                completed_names = set(line.strip() for line in f if line.strip())
            return completed_names
        except:
            pass
    return set()

# 保存进度
def save_progress(name):
    """保存进度"""
    progress_file = "scrape_progress.txt"
    with open(progress_file, 'a') as f:
        f.write(f"{name}\n")

def main():
    """主函数"""
    global total_count, completed_count
    
    print("美国众议院议员社交媒体爬虫（优化版）")
    print("=" * 60)
    print(f"配置: {MAX_WORKERS}线程, 延迟{MIN_DELAY}-{MAX_DELAY}秒")
    print("=" * 60)
    
    # 加载众议员数据
    print("正在加载众议员数据...")
    representatives = load_representatives()
    
    if not representatives:
        print("没有众议员数据，无法继续")
        return
    
    # 加载已完成的进度
    completed_names = load_progress()
    
    # 过滤已完成的
    remaining_reps = [rep for rep in representatives if rep["name"] not in completed_names]
    already_completed = len(representatives) - len(remaining_reps)
    
    total_count = len(representatives)
    completed_count = already_completed
    
    print(f"找到 {len(representatives)} 位众议员")
    if already_completed > 0:
        print(f"已跳过 {already_completed} 位已完成的议员")
    print(f"剩余 {len(remaining_reps)} 位需要处理")
    print("=" * 60)
    
    if not remaining_reps:
        print("所有议员已处理完成！")
        return
    
    # 创建输出文件（如果不存在）
    output_file = "house_representatives_social_media.csv"
    if not os.path.exists(output_file):
        save_data([], output_file, 'w')
    
    # 使用多线程处理
    print(f"开始爬取（使用{MAX_WORKERS}个线程）...")
    print("提示：按Ctrl+C可随时中断，下次运行会自动续传")
    print("=" * 60)
    
    start_time = time.time()
    
    try:
        # 创建session
        session = create_session()
        
        # 使用线程池
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # 提交所有任务
            future_to_rep = {
                executor.submit(process_representative, session, rep, i): rep 
                for i, rep in enumerate(remaining_reps)
            }
            
            # 处理完成的任务
            completed_reps = []
            for future in as_completed(future_to_rep):
                rep = future_to_rep[future]
                try:
                    result = future.result()
                    completed_reps.append(result)
                    save_progress(result["name"])
                    
                    # 每50个保存一次
                    if len(completed_reps) >= 50:
                        save_data(completed_reps, output_file, 'a')
                        completed_reps = []
                        
                except Exception as e:
                    print(f"处理 {rep['name']} 时出错: {e}")
            
            # 保存剩余的数据
            if completed_reps:
                save_data(completed_reps, output_file, 'a')
    
    except KeyboardInterrupt:
        print("\n\n用户中断，已保存进度，下次运行将自动续传")
        return
    
    elapsed_time = time.time() - start_time
    
    print("=" * 60)
    print("爬取完成！")
    print(f"总用时: {elapsed_time:.1f}秒 ({elapsed_time/60:.1f}分钟)")
    print(f"平均速度: {len(remaining_reps)/elapsed_time:.2f}个/秒")
    
    # 统计结果
    all_reps = load_representatives()
    # 重新读取CSV获取最新结果
    try:
        with open(output_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            results = list(reader)
            x_count = sum(1 for r in results if r.get("X"))
            fb_count = sum(1 for r in results if r.get("Facebook"))
            
            print(f"\n统计结果:")
            print(f"  - 总数: {len(results)}")
            print(f"  - 找到X链接: {x_count} ({x_count/len(results)*100:.1f}%)")
            print(f"  - 找到Facebook链接: {fb_count} ({fb_count/len(results)*100:.1f}%)")
    except:
        pass
    
    print(f"\n请查看生成的 {output_file} 文件")
    
    # 清理进度文件
    if os.path.exists("scrape_progress.txt"):
        os.remove("scrape_progress.txt")
        print("已清理临时进度文件")

if __name__ == "__main__":
    main()
