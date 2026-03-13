#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本：检查众议员网站是否有涉华内容
"""

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

# 中国相关关键词
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
    'balloon', 'spy balloon'
]

def contains_china_keywords(text):
    """检查文本是否包含中国相关关键词"""
    if not text:
        return False
    
    text_lower = text.lower()
    matched = []
    
    for keyword in CHINA_KEYWORDS:
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, text_lower):
            matched.append(keyword)
    
    return matched

# 测试几个网站
test_sites = [
    ("Aderholt, Robert", "https://aderholt.house.gov/"),
    ("McCaul, Michael", "https://mccaul.house.gov/"),  # 知名对华强硬派
    ("Gallagher, Mike", "https://gallagher.house.gov/"),  # 中国特别委员会主席
]

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

for name, url in test_sites:
    print(f"\n{'='*60}")
    print(f"测试: {name}")
    print(f"网址: {url}")
    print('='*60)
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(response.content, 'lxml')
        
        # 寻找新闻链接
        news_links = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            text = link.get_text(strip=True)
            if any(k in href for k in ['press', 'news', 'media']) and len(text) > 5:
                full_url = urljoin(url, link['href'])
                news_links.append((full_url, text))
        
        print(f"找到 {len(news_links)} 个新闻相关链接")
        
        # 检查前3个新闻链接
        for news_url, link_text in news_links[:3]:
            try:
                print(f"\n访问: {link_text[:50]}...")
                news_resp = requests.get(news_url, headers=headers, timeout=15)
                news_soup = BeautifulSoup(news_resp.content, 'lxml')
                
                # 获取所有文本
                all_text = news_soup.get_text()
                
                # 检查涉华关键词
                matched = contains_china_keywords(all_text[:50000])  # 检查前50000字符
                
                if matched:
                    print(f"  ✓ 找到涉华关键词: {matched}")
                    
                    # 找到具体文章
                    for link in news_soup.find_all('a', href=True):
                        article_text = link.get_text(strip=True)
                        if len(article_text) > 20:
                            article_matched = contains_china_keywords(article_text)
                            if article_matched:
                                print(f"    - 文章: {article_text[:80]}...")
                                print(f"      链接: {urljoin(url, link['href'])}")
                                print(f"      关键词: {article_matched}")
                else:
                    print(f"  ✗ 未找到涉华关键词")
                    
            except Exception as e:
                print(f"  错误: {e}")
                
    except Exception as e:
        print(f"错误: {e}")

print("\n测试完成")
