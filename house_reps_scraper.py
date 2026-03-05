#!/usr/bin/env python3
"""
美国众议院议员网站爬虫

功能：爬取美国众议院网站上所有议员的个人官网链接，并保存为CSV文件

使用方法：
1. 确保已安装Python 3
2. 运行脚本：python house_reps_scraper.py
   （脚本会自动检测并安装所需依赖）

输出：生成 house_representatives_websites.csv 文件，包含议员姓名、个人网站链接、选区、所属地区分类、政党和委员会信息
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

# 首先创建一个日志文件，确认脚本开始执行
with open('scraper_log.txt', 'w', encoding='utf-8') as log_file:
    log_file.write('脚本开始执行...\n')

import requests
from bs4 import BeautifulSoup
import csv
import os
import re

# 写入日志
with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
    log_file.write('模块导入成功\n')

# 定义地区分类
US_STATES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut",
    "Delaware", "Florida", "Georgia", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa",
    "Kansas", "Kentucky", "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan",
    "Minnesota", "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota", "Ohio", "Oklahoma",
    "Oregon", "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota", "Tennessee",
    "Texas", "Utah", "Vermont", "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming"
]

US_TERRITORIES = [
    "American Samoa", "Guam", "Northern Mariana Islands", "Puerto Rico", "Virgin Islands"
]

FEDERAL_DISTRICT = ["District of Columbia"]

# 所有有效地区名称（用于匹配）
ALL_REGIONS = US_STATES + US_TERRITORIES + FEDERAL_DISTRICT

def get_region_category(state_name):
    """
    根据州名返回地区分类
    - 领地: us_territories
    - 联邦特区: federal_district
    - 州: state
    """
    if state_name in US_TERRITORIES:
        return "us_territories"
    elif state_name in FEDERAL_DISTRICT:
        return "federal_district"
    elif state_name in US_STATES:
        return "state"
    else:
        return "unknown"

def extract_state_from_district(district_text):
    """
    从district文本中提取州名
    
    例如：
    - "North Carolina 12th" -> "North Carolina"
    - "Alabama 4th" -> "Alabama"
    - "Alaska at large" -> "Alaska"
    - "Puerto Rico" -> "Puerto Rico"
    - "District of Columbia" -> "District of Columbia"
    """
    if not district_text:
        return ""
    
    district_text = district_text.strip()
    
    # 首先尝试匹配完整的州名（包括多词州名）
    # 按照州名长度降序排序，确保先匹配长的（如"North Carolina"先于"North"）
    for state in sorted(ALL_REGIONS, key=len, reverse=True):
        if district_text.startswith(state):
            return state
    
    # 如果没有匹配到，返回原文本（可能是异常情况）
    return district_text

def get_representatives():
    """获取众议院议员信息"""
    # 写入日志
    with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
        log_file.write('开始获取众议员信息...\n')
    
    # 众议院网站URL
    url = "https://www.house.gov/representatives"
    
    # 发送请求
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write(f'正在请求URL: {url}\n')
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()  # 检查请求是否成功
        
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write(f'请求成功，状态码: {response.status_code}\n')
    except Exception as e:
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write(f'请求失败: {e}\n')
        return []
    
    # 解析HTML
    try:
        soup = BeautifulSoup(response.content, "html.parser")
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write('HTML解析成功\n')
    except Exception as e:
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write(f'HTML解析失败: {e}\n')
        return []
    
    # 查找众议员信息
    representatives = []
    
    # 首先尝试从 "By Last Name" 视图提取数据
    try:
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write('尝试从 By Last Name 视图提取数据...\n')
        
        # 查找所有表格
        tables = soup.find_all('table')
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write(f'找到 {len(tables)} 个表格\n')
        
        for table in tables:
            # 查找表头，确认是否是议员表格
            header = table.find('thead')
            if header:
                header_text = header.get_text(strip=True)
                # 检查是否包含关键列名
                if 'Name' in header_text and 'District' in header_text:
                    with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
                        log_file.write('找到议员信息表格\n')
                    
                    # 提取数据行
                    rows = table.find_all('tr')
                    with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
                        log_file.write(f'表格中有 {len(rows)} 行数据\n')
                    
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) >= 6:  # 确保有足够的单元格
                            # 提取数据
                            name_cell = cells[0]
                            district_cell = cells[1]
                            party = cells[2].get_text(strip=True)
                            office = cells[3].get_text(strip=True)
                            phone = cells[4].get_text(strip=True)
                            committee = cells[5].get_text(strip=True)
                            
                            # 提取姓名和网站链接
                            name_link = name_cell.find('a', href=True)
                            if name_link:
                                name = name_link.get_text(strip=True).replace('(link is external)', '').strip()
                                website = name_link.get('href')
                                
                                # 获取完整的district文本（如"North Carolina 12th"）
                                district_full = district_cell.get_text(strip=True)
                                
                                # 提取州名
                                state = extract_state_from_district(district_full)
                                
                                # 确定地区分类
                                region_category = get_region_category(state)
                                
                                if name and website:
                                    representatives.append({
                                        "name": name,
                                        "website": website,
                                        "district": district_full,  # 保存完整的district文本
                                        "state": state,
                                        "region_category": region_category,
                                        "party": party,
                                        "committee": committee
                                    })
                                    # 写入日志
                                    with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
                                        log_file.write(f'添加众议员: {name} ({state}, {district_full}, {region_category})\n')
        
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write(f'从 By Last Name 视图找到 {len(representatives)} 位众议员\n')
    except Exception as e:
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write(f'从 By Last Name 视图提取数据失败: {e}\n')
            import traceback
            log_file.write(traceback.format_exc())
    
    # 如果从 By Last Name 视图没有找到数据，尝试从 "By State and District" 视图提取
    if not representatives:
        try:
            with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
                log_file.write('尝试从 By State and District 视图提取数据...\n')
            
            current_state = ""
            
            # 遍历所有元素，寻找州名和众议员数据
            for element in soup.find_all(['h2', 'h3', 'tr']):
                # 检查是否是州名
                if element.name in ['h2', 'h3']:
                    text = element.get_text(strip=True)
                    # 检查是否是有效的地区名称
                    if text in ALL_REGIONS:
                        current_state = text
                        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
                            log_file.write(f'识别到地区: {current_state}\n')
                
                # 检查是否是众议员行
                elif element.name == 'tr' and current_state:
                    # 查找所有单元格
                    cells = element.find_all('td')
                    if len(cells) >= 6:  # 确保有足够的单元格
                        # 提取数据
                        district_full = cells[0].get_text(strip=True)
                        name_cell = cells[1]
                        party = cells[2].get_text(strip=True)
                        office = cells[3].get_text(strip=True)
                        phone = cells[4].get_text(strip=True)
                        committee = cells[5].get_text(strip=True)
                        
                        # 提取姓名和网站链接
                        name_link = name_cell.find('a', href=True)
                        if name_link:
                            name = name_link.get_text(strip=True).replace('(link is external)', '').strip()
                            website = name_link.get('href')
                            
                            if name and website:
                                # 确定地区分类
                                region_category = get_region_category(current_state)
                                
                                representatives.append({
                                    "name": name,
                                    "website": website,
                                    "district": district_full,  # 保存完整的district文本
                                    "state": current_state,
                                    "region_category": region_category,
                                    "party": party,
                                    "committee": committee
                                })
                                # 写入日志
                                with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
                                    log_file.write(f'添加众议员: {name} ({current_state}, {district_full}, {region_category})\n')
            
            # 写入日志
            with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
                log_file.write(f'从 By State and District 视图找到 {len(representatives)} 位众议员\n')
        except Exception as e:
            # 写入日志
            with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
                log_file.write(f'从 By State and District 视图提取数据失败: {e}\n')
                import traceback
                log_file.write(traceback.format_exc())
    
    # 去重，避免重复条目
    seen = set()
    unique_representatives = []
    for rep in representatives:
        if rep["website"] not in seen:
            seen.add(rep["website"])
            unique_representatives.append(rep)
    
    # 写入日志
    with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
        log_file.write(f'去重后找到 {len(unique_representatives)} 个唯一链接\n')
    
    return unique_representatives

def save_to_csv(representatives):
    """保存议员信息到CSV文件"""
    # 写入日志
    with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
        log_file.write('开始保存到CSV...\n')
    
    if not representatives:
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write('未找到众议员网站链接\n')
        return False
    
    # 写入日志
    with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
        log_file.write(f'找到 {len(representatives)} 位众议员的网站链接\n')
    
    # 保存为CSV格式
    csv_file = os.path.join(os.getcwd(), "house_representatives_websites.csv")
    try:
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["name", "website", "district", "state", "region_category", "party", "committee"])
            for rep in representatives:
                writer.writerow([
                    rep["name"], 
                    rep["website"], 
                    rep.get("district", ""),
                    rep.get("state", ""), 
                    rep.get("region_category", ""),
                    rep.get("party", ""), 
                    rep.get("committee", "")
                ])
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write(f'已保存为CSV格式: {csv_file}\n')
        # 打印到控制台
        print(f'已保存为CSV格式: {csv_file}')
        return True
    except Exception as e:
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write(f'保存CSV失败: {e}\n')
        # 打印到控制台
        print(f'保存CSV失败: {e}')
        return False

def main():
    """主函数"""
    # 写入日志
    with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
        log_file.write('开始执行主函数\n')
    
    try:
        # 获取议员信息
        representatives = get_representatives()
        
        # 保存到CSV
        success = save_to_csv(representatives)
        
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            if success:
                log_file.write('爬取完成！\n')
            else:
                log_file.write('爬取失败！\n')
    except Exception as e:
        # 写入日志
        with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
            log_file.write(f'发生错误: {e}\n')
            import traceback
            log_file.write(traceback.format_exc())

if __name__ == "__main__":
    main()
    # 写入日志
    with open('scraper_log.txt', 'a', encoding='utf-8') as log_file:
        log_file.write('脚本执行完毕\n')
