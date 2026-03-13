#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第2步：抓取法案数据
重点：区分 Sponsor（提出者）和 Cosponsor（联署人）
"""

import asyncio
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.api_client import CongressAPIClient
from database.models import Bill, Member, bill_cosponsors, get_session, init_database
from settings import TARGET_CONGRESS


async def fetch_bills_for_member(session, client, member):
    """抓取单个议员的法案数据"""
    
    print(f"\n处理议员: {member.full_name} ({member.bioguide_id})")
    
    # 1. 获取提出的法案 (Sponsored Bills)
    print("  获取提出的法案...")
    sponsored_bills = await client.get_member_sponsored_bills(member.bioguide_id)
    print(f"  提出法案数量: {len(sponsored_bills)}")
    
    for bill_data in sponsored_bills:
        await process_bill(session, client, bill_data, sponsor=member)
    
    # 2. 获取联署的法案 (Cosponsored Bills)
    print("  获取联署的法案...")
    cosponsored_bills = await client.get_member_cosponsored_bills(member.bioguide_id)
    print(f"  联署法案数量: {len(cosponsored_bills)}")
    
    for bill_data in cosponsored_bills:
        await process_bill(session, client, bill_data, cosponsor=member)


async def process_bill(session, client, bill_data, sponsor=None, cosponsor=None):
    """处理单个法案数据"""
    
    # 构建唯一 ID
    congress = bill_data.get('congress', TARGET_CONGRESS)
    bill_type = bill_data.get('type')
    number = bill_data.get('number')
    
    if not bill_type or not number:
        print(f"    跳过无效法案数据")
        return
    
    bill_id = f"{congress}-{bill_type}-{number}"
    
    # 检查是否已存在
    bill = session.query(Bill).filter_by(bill_id=bill_id).first()
    
    if not bill:
        # 获取法案详情（更完整的信息）
        try:
            detail = await client.get_bill_detail(congress, bill_type, number)
        except Exception as e:
            print(f"    获取法案详情失败 {bill_id}: {str(e)}")
            detail = {}
        
        # 提取政策领域
        policy_area = None
        if detail.get('policyArea'):
            policy_area = detail['policyArea'].get('name')
        
        # 提取主题标签
        subjects = None
        if detail.get('subjects'):
            subjects_list = detail['subjects'].get('legislativeSubjects', [])
            subjects = ', '.join([s.get('name', '') for s in subjects_list[:5]])
        
        # 创建新法案记录
        bill = Bill(
            bill_id=bill_id,
            congress=congress,
            bill_type=bill_type,
            bill_number=number,
            title=bill_data.get('title') or detail.get('title'),
            short_title=detail.get('shortTitle'),
            introduced_date=bill_data.get('introducedDate'),
            latest_action_date=detail.get('latestAction', {}).get('actionDate'),
            latest_action_text=detail.get('latestAction', {}).get('text'),
            policy_area=policy_area,
            subjects=subjects,
            status=detail.get('latestAction', {}).get('text'),
        )
        session.add(bill)
        print(f"    新增法案: {bill_id}")
    
    # 设置 Sponsor（提出者）
    if sponsor and not bill.sponsor_id:
        bill.sponsor_id = sponsor.bioguide_id
        print(f"    设置提出者: {sponsor.full_name}")
    
    # 添加 Cosponsor（联署人）
    if cosponsor:
        # 检查是否已经是联署人
        existing = session.query(bill_cosponsors).filter_by(
            bill_id=bill_id,
            bioguide_id=cosponsor.bioguide_id
        ).first()
        
        if not existing:
            # 获取联署日期（从原始数据中）
            cosponsor_date = None
            is_original = False
            
            # 从 bill_data 的 cosponsors 列表中查找
            for cs in bill_data.get('cosponsors', []):
                if cs.get('bioguideId') == cosponsor.bioguide_id:
                    cosponsor_date = cs.get('sponsorshipDate')
                    is_original = cs.get('isOriginalCosponsor', False)
                    break
            
            # 插入关联记录
            stmt = bill_cosponsors.insert().values(
                bill_id=bill_id,
                bioguide_id=cosponsor.bioguide_id,
                cosponsor_date=cosponsor_date,
                is_original_cosponsor=is_original
            )
            session.execute(stmt)
            print(f"    添加联署人: {cosponsor.full_name}")


async def fetch_all_bills():
    """抓取所有议员的法案"""
    
    engine = init_database()
    session = get_session(engine)
    
    # 获取所有议员
    members = session.query(Member).all()
    print(f"共 {len(members)} 名议员需要处理")
    
    async with CongressAPIClient() as client:
        for i, member in enumerate(members, 1):
            print(f"\n[{i}/{len(members)}] ", end="")
            try:
                await fetch_bills_for_member(session, client, member)
                session.commit()  # 每个议员处理完提交一次
            except Exception as e:
                print(f"处理议员 {member.full_name} 时出错: {str(e)}")
                session.rollback()
                continue
    
    print("\n法案数据抓取完成")


if __name__ == "__main__":
    asyncio.run(fetch_all_bills())
