#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import re

# 尝试访问contact页面或其他页面
urls_to_check = [
    'https://aderholt.house.gov/',
    'https://aderholt.house.gov/about-robert',
    'https://aderholt.house.gov/contact-robert',
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

for url in urls_to_check:
    print(f'\n=== 检查页面: {url} ===')
    try:
        response = requests.get(url, headers=headers, timeout=30)
        html = response.text.lower()
        
        # 查找twitter或x.com
        if 'twitter.com' in html or 'x.com' in html:
            print('找到Twitter/X链接!')
            # 提取所有可能的链接
            links = re.findall(r'href=["\']([^"\']*(?:twitter\.com|x\.com)[^"\']*)["\']', html)
            for link in set(links):
                print(f'  {link}')
        else:
            print('未找到Twitter/X链接')
            
        # 查找议员姓名附近的内容
        if 'aderholt' in html:
            # 查找包含aderholt的行
            lines = html.split('\n')
            for line in lines:
                if 'aderholt' in line and ('twitter' in line or 'x.com' in line):
                    print(f'相关行: {line[:200]}')
    except Exception as e:
        print(f'错误: {e}')

# 尝试搜索Google
print('\n=== 尝试搜索Google ===')
search_query = 'Robert Aderholt twitter X site:twitter.com OR site:x.com'
print(f'搜索查询: {search_query}')
print('注: 实际搜索需要额外的API或库')
