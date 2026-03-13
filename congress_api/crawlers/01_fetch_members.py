#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第1步：抓取第119届国会所有议员基础数据
"""

import asyncio
import json
import csv
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.api_client import CongressAPIClient
from database.models import Member, get_session, init_database
from settings import TARGET_CONGRESS, RAW_DATA_DIR, PROCESSED_DATA_DIR


async def fetch_members():
    """抓取议员数据主函数"""
    
    # 初始化数据库
    engine = init_database()
    session = get_session(engine)
    
    async with CongressAPIClient() as client:
        print(f"开始抓取第 {TARGET_CONGRESS} 届国会议员数据...")
        print("-" * 60)
        
        # 获取所有议员
        members_data = await client.get_members(congress=TARGET_CONGRESS)
        
        print(f"\n共获取 {len(members_data)} 名议员")
        print("-" * 60)
        
        # 统计计数器
        added_count = 0
        skipped_count = 0
        error_count = 0
        
        # 处理每个议员
        for i, member_data in enumerate(members_data, 1):
            # 提取关键字段
            bioguide_id = member_data.get('bioguideId')
            
            if not bioguide_id:
                print(f"[{i}/{len(members_data)}] 跳过：缺少 bioguide_id")
                error_count += 1
                continue
            
            # 检查是否已存在
            existing = session.query(Member).filter_by(bioguide_id=bioguide_id).first()
            if existing:
                print(f"[{i}/{len(members_data)}] 跳过已存在: {member_data.get('name', 'Unknown')}")
                skipped_count += 1
                continue
            
            # 获取议员详细信息（更完整的数据）
            try:
                detail = await client.get_member_detail(bioguide_id)
                # 将详情保存到 member_data 中，供后续 CSV 导出使用
                member_data['detail'] = detail
            except Exception as e:
                print(f"[{i}/{len(members_data)}] 获取详情失败 {bioguide_id}: {str(e)}")
                detail = {}
                member_data['detail'] = {}
            
            # 提取任期信息
            terms = detail.get('terms', {}).get('item', [])
            current_term = terms[-1] if terms else {}
            
            # 创建新记录
            member = Member(
                bioguide_id=bioguide_id,
                first_name=member_data.get('firstName'),
                last_name=member_data.get('lastName'),
                full_name=member_data.get('name'),
                state=member_data.get('state'),
                district=member_data.get('district'),  # 参议员为 None
                party=member_data.get('partyName'),
                chamber=member_data.get('chamber'),  # House 或 Senate
                
                # 联系信息
                website=detail.get('officialWebsiteUrl') or member_data.get('url'),
                office_address=current_term.get('address'),
                phone=current_term.get('phone'),
                
                # 社交媒体
                twitter=detail.get('twitter'),
                facebook=detail.get('facebook'),
                youtube=detail.get('youtube'),
                
                # 任期信息
                start_date=current_term.get('startYear'),
                end_date=current_term.get('endYear')
            )
            
            session.add(member)
            added_count += 1
            print(f"[{i}/{len(members_data)}] 添加议员: {member.full_name} ({member.state}-{member.district or 'Senate'})")
            
            # 每50条提交一次，避免事务过大
            if i % 50 == 0:
                session.commit()
                print(f"  -> 已提交 {i} 条记录")
        
        # 最终提交
        session.commit()
        
        print("\n" + "=" * 60)
        print("议员数据保存完成")
        print(f"  新增: {added_count}")
        print(f"  跳过: {skipped_count}")
        print(f"  错误: {error_count}")
        print("=" * 60)
        
        # 同时保存原始 JSON 到文件（备份）
        raw_file = RAW_DATA_DIR / f"members_congress_{TARGET_CONGRESS}.json"
        with open(raw_file, 'w', encoding='utf-8') as f:
            json.dump(members_data, f, ensure_ascii=False, indent=2)
        print(f"\n原始数据已保存到: {raw_file}")
        
        # 保存为 CSV 文件
        csv_file = PROCESSED_DATA_DIR / f"members_congress_{TARGET_CONGRESS}.csv"
        with open(csv_file, 'w', encoding='utf-8-sig', newline='') as f:
            if members_data:
                # 确定 CSV 列（从数据中收集所有可能的字段）
                fieldnames = [
                    'bioguideId', 'name', 'firstName', 'lastName',
                    'partyName', 'state', 'district', 'chamber',
                    'url', 'officialWebsiteUrl',
                    'twitter', 'facebook', 'youtube',
                    'officeAddress', 'phone',
                    'startYear', 'endYear'
                ]
                
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
                writer.writeheader()
                
                for member in members_data:
                    row = {
                        'bioguideId': member.get('bioguideId'),
                        'name': member.get('name'),
                        'firstName': member.get('firstName'),
                        'lastName': member.get('lastName'),
                        'partyName': member.get('partyName'),
                        'state': member.get('state'),
                        'district': member.get('district'),
                        'chamber': member.get('chamber'),
                        'url': member.get('url'),
                        'officialWebsiteUrl': member.get('officialWebsiteUrl')
                    }
                    
                    # 从详情中获取额外信息
                    if 'detail' in member:
                        detail = member['detail']
                        row['twitter'] = detail.get('twitter')
                        row['facebook'] = detail.get('facebook')
                        row['youtube'] = detail.get('youtube')
                        
                        terms = detail.get('terms', {}).get('item', [])
                        if terms:
                            current_term = terms[-1]
                            row['officeAddress'] = current_term.get('address')
                            row['phone'] = current_term.get('phone')
                            row['startYear'] = current_term.get('startYear')
                            row['endYear'] = current_term.get('endYear')
                    
                    writer.writerow(row)
        
        print(f"CSV 数据已保存到: {csv_file}")
        
        # 生成统计信息
        print("\n党派分布:")
        party_stats = {}
        for m in members_data:
            party = m.get('partyName', 'Unknown')
            party_stats[party] = party_stats.get(party, 0) + 1
        for party, count in sorted(party_stats.items(), key=lambda x: x[1], reverse=True):
            print(f"  {party}: {count}")
        
        print("\n议院分布:")
        chamber_stats = {}
        for m in members_data:
            chamber = m.get('chamber', 'Unknown')
            chamber_stats[chamber] = chamber_stats.get(chamber, 0) + 1
        for chamber, count in chamber_stats.items():
            print(f"  {chamber}: {count}")


if __name__ == "__main__":
    asyncio.run(fetch_members())
