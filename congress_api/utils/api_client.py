#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 请求客户端封装
处理认证、速率限制、重试、分页等
"""

import asyncio
import aiohttp
import time
from typing import Optional, Dict, Any, List
from tenacity import retry, stop_after_attempt, wait_exponential
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from settings import (
    API_BASE_URL, get_api_key, REQUEST_DELAY, 
    MAX_RETRIES, DEFAULT_LIMIT
)


class CongressAPIClient:
    """Congress.gov API 客户端"""
    
    def __init__(self):
        self.api_key = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_request_time = 0
        self.request_count = 0
        self.base_delay = REQUEST_DELAY
        
    async def __aenter__(self):
        """异步上下文管理器入口"""
        self.api_key = get_api_key()
        self.session = aiohttp.ClientSession(
            headers={
                "X-API-Key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "CongressDataResearch/1.0"
            }
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        if self.session:
            await self.session.close()
    
    async def _rate_limit(self):
        """速率限制控制"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.base_delay:
            wait_time = self.base_delay - time_since_last
            await asyncio.sleep(wait_time)
        
        self.last_request_time = time.time()
        self.request_count += 1
    
    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def request(
        self, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        发送 API 请求
        
        Args:
            endpoint: API 端点路径（不含基础 URL）
            params: 查询参数
        
        Returns:
            API 响应的 JSON 数据
        """
        await self._rate_limit()
        
        url = f"{API_BASE_URL}/{endpoint}"
        
        async with self.session.get(url, params=params) as response:
            # 处理速率限制
            if response.status == 429:
                retry_after = int(response.headers.get('Retry-After', 60))
                print(f"达到速率限制，等待 {retry_after} 秒...")
                await asyncio.sleep(retry_after)
                raise Exception("Rate limited")
            
            # 处理其他错误
            if response.status == 403:
                raise Exception("API Key 无效或已过期")
            
            response.raise_for_status()
            
            data = await response.json()
            
            # 打印请求信息（调试用）
            request_info = data.get('request', {})
            print(f"请求: {request_info.get('contentType', 'unknown')}")
            
            return data
    
    async def fetch_all_pages(
        self, 
        endpoint: str, 
        params: Optional[Dict[str, Any]] = None,
        limit: int = DEFAULT_LIMIT
    ) -> List[Dict[str, Any]]:
        """
        获取所有分页数据
        
        Args:
            endpoint: API 端点
            params: 基础查询参数
            limit: 每页数量
        
        Returns:
            所有页面的数据列表
        """
        all_data = []
        offset = 0
        
        while True:
            page_params = (params or {}).copy()
            page_params.update({
                "limit": limit,
                "offset": offset,
                "format": "json"
            })
            
            try:
                response = await self.request(endpoint, page_params)
                
                # 根据端点类型提取数据
                data_key = None
                for key in ['bills', 'members', 'votes', 'summaries', 'amendments']:
                    if key in response:
                        data_key = key
                        break
                
                data = response.get(data_key, []) if data_key else []
                
                if not data:
                    break
                
                all_data.extend(data)
                
                # 检查是否还有下一页
                pagination = response.get('pagination', {})
                next_url = pagination.get('next')
                
                if not next_url:
                    break
                
                offset += limit
                print(f"已获取 {len(all_data)} 条数据，继续下一页...")
                
            except Exception as e:
                print(f"获取数据失败: {str(e)}")
                raise
        
        return all_data
    
    # ============ 便捷方法 ============
    
    async def get_members(self, congress: int = None, current: bool = False) -> List[Dict]:
        """获取议员列表"""
        params = {}
        if congress:
            params["congress"] = congress
        if current:
            params["currentMember"] = "true"
        
        return await self.fetch_all_pages("member", params)
    
    async def get_member_detail(self, bioguide_id: str) -> Dict:
        """获取议员详情"""
        return await self.request(f"member/{bioguide_id}")
    
    async def get_member_sponsored_bills(self, bioguide_id: str) -> List[Dict]:
        """获取议员提出的法案"""
        return await self.fetch_all_pages(f"member/{bioguide_id}/sponsored-legislation")
    
    async def get_member_cosponsored_bills(self, bioguide_id: str) -> List[Dict]:
        """获取议员联署的法案"""
        return await self.fetch_all_pages(f"member/{bioguide_id}/cosponsored-legislation")
    
    async def get_bill_detail(self, congress: int, bill_type: str, number: int) -> Dict:
        """获取法案详情"""
        return await self.request(f"bill/{congress}/{bill_type}/{number}")
    
    async def get_bill_summaries(self, congress: int, bill_type: str, number: int) -> List[Dict]:
        """获取法案摘要"""
        return await self.fetch_all_pages(f"summaries/{congress}/{bill_type}/{number}")
    
    async def get_house_votes(self, congress: int, session: int = None) -> List[Dict]:
        """获取众议院投票记录"""
        params = {}
        if session:
            params["sessionNumber"] = session
        return await self.fetch_all_pages(f"house-vote/{congress}", params)
    
    async def get_vote_detail(self, congress: int, session: int, roll_call: int) -> Dict:
        """获取投票详情"""
        return await self.request(f"house-vote/{congress}/{session}/{roll_call}")


# 同步包装函数（方便非异步代码调用）
def run_async(coro):
    """运行异步协程"""
    return asyncio.run(coro)


if __name__ == "__main__":
    # 测试 API 客户端
    async def test_client():
        async with CongressAPIClient() as client:
            # 测试获取议员列表
            print("测试获取议员列表...")
            members = await client.get_members(congress=119)
            print(f"获取到 {len(members)} 名议员")
            if members:
                print(f"第一名议员: {members[0].get('name')}")
    
    run_async(test_client())
