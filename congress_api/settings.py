#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置文件 - Congress.gov API 数据抓取工具
运行时会提示输入 API Key
"""

import os
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).parent

# 数据存储路径
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
LOGS_DIR = BASE_DIR / "logs"

# 确保目录存在
for dir_path in [RAW_DATA_DIR, PROCESSED_DATA_DIR, LOGS_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)

# API 配置
API_BASE_URL = "https://api.congress.gov/v3"
API_KEY = None  # 运行时通过交互式输入获取

# 抓取范围配置
TARGET_CONGRESS = 119  # 目标国会届数

# 速率限制配置
RATE_LIMIT_PER_HOUR = 5000
SAFE_REQUESTS_PER_HOUR = 4500  # 保守策略
REQUEST_DELAY = 3600 / SAFE_REQUESTS_PER_HOUR  # 约 0.8 秒/请求
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2  # 基础重试延迟（秒）

# 分页配置
DEFAULT_LIMIT = 250  # 最大分页数
MAX_LIMIT = 250

# 日志配置
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_LEVEL = "INFO"


def get_api_key():
    """
    交互式获取 API Key
    每次运行时都提示用户输入，不保存到文件
    
    Returns:
        str: API Key
    
    Raises:
        ValueError: 如果 API Key 为空
    """
    global API_KEY
    
    # 如果已经设置，直接返回
    if API_KEY:
        return API_KEY
    
    # 交互式提示输入
    print("=" * 60, flush=True)
    print("Congress.gov API 数据抓取工具", flush=True)
    print("=" * 60, flush=True)
    print("\n请输入您的 Congress.gov API Key", flush=True)
    print("（如果您还没有 API Key，请访问 https://api.data.gov/signup/ 申请）", flush=True)
    print("-" * 60, flush=True)
    
    api_key = input("API Key: ").strip()
    
    if not api_key:
        raise ValueError("API Key 不能为空，请重新运行程序并输入有效的 API Key")
    
    API_KEY = api_key
    return api_key


def get_api_headers():
    """
    获取 API 请求头
    
    Returns:
        dict: 包含 API Key 的请求头字典
    """
    return {
        "X-API-Key": get_api_key(),
        "Accept": "application/json",
        "User-Agent": "CongressDataResearch/1.0"
    }


# 法案类型映射
BILL_TYPES = {
    "HR": "House Bill (众议院法案)",
    "S": "Senate Bill (参议院法案)",
    "HRES": "House Simple Resolution (众议院简单决议)",
    "SRES": "Senate Simple Resolution (参议院简单决议)",
    "HJRES": "House Joint Resolution (众议院联合决议)",
    "SJRES": "Senate Joint Resolution (参议院联合决议)",
    "HCONRES": "House Concurrent Resolution (众议院共同决议)",
    "SCONRES": "Senate Concurrent Resolution (参议院共同决议)",
}

# 议院映射
CHAMBERS = {
    "House": "众议院",
    "Senate": "参议院"
}

# 党派映射
PARTIES = {
    "Democratic": "民主党",
    "Republican": "共和党",
    "Independent": "独立人士"
}
