#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第3步：抓取法案摘要
"""

import asyncio
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.api_client import CongressAPIClient
from database.models import Bill, BillSummary, get_session, init_database
from settings import TARGET_CONGRESS


async def fetch_summaries():
    """抓取所有法案的摘要"""
    
    engine = init_database()
    session = get_session(engine)
    
    # 获取需要抓取摘要的法案
    bills = session.query(Bill).filter(
        Bill.congress == TARGET_CONGRESS
    ).all()
    
    print(f"共 {len(bills)} 个法案需要获取摘要")
    
    async with CongressAPIClient() as client:
        for i, bill in enumerate(bills, 1):
            print(f"[{i}/{len(bills)}] 处理法案: {bill.bill_id}")
            
            # 检查是否已有摘要
            existing = session.query(BillSummary).filter_by(bill_id=bill.bill_id).first()
            if existing:
                print("  摘要已存在，跳过")
                continue
            
            try:
                summaries = await client.get_bill_summaries(
                    bill.congress, 
                    bill.bill_type, 
                    bill.bill_number
                )
                
                if not summaries:
                    print("  该法案暂无摘要")
                    continue
                
                for summary_data in summaries:
                    summary = BillSummary(
                        bill_id=bill.bill_id,
                        text=summary_data.get('text'),
                        text_version=summary_data.get('versionCode'),
                        action_date=summary_data.get('actionDate'),
                        update_date=summary_data.get('updateDate')
                    )
                    session.add(summary)
                    print(f"  添加摘要: {summary.text_version or '默认版本'}")
                
                session.commit()
                
            except Exception as e:
                print(f"  获取摘要失败: {str(e)}")
                session.rollback()
                continue
    
    print("\n摘要抓取完成")


if __name__ == "__main__":
    asyncio.run(fetch_summaries())
