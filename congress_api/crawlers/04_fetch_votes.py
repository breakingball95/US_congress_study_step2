#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第4步：抓取众议院投票记录
"""

import asyncio
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.api_client import CongressAPIClient
from database.models import Vote, MemberVote, Bill, get_session, init_database
from settings import TARGET_CONGRESS


async def fetch_votes():
    """抓取投票记录"""
    
    engine = init_database()
    session = get_session(engine)
    
    async with CongressAPIClient() as client:
        # 第119届国会有两个会期（2025-2027）
        for session_number in [1, 2]:
            print(f"\n{'='*60}")
            print(f"获取第{TARGET_CONGRESS}届国会第{session_number}会期的投票记录...")
            print(f"{'='*60}")
            
            try:
                votes_list = await client.get_house_votes(TARGET_CONGRESS, session_number)
                print(f"共 {len(votes_list)} 次投票")
                
                for i, vote_summary in enumerate(votes_list, 1):
                    roll_call = vote_summary.get('rollCallNumber')
                    vote_id = f"{TARGET_CONGRESS}-{session_number}-{roll_call}"
                    
                    # 检查是否已存在
                    existing = session.query(Vote).filter_by(vote_id=vote_id).first()
                    if existing:
                        print(f"[{i}/{len(votes_list)}] 投票 {vote_id} 已存在，跳过")
                        continue
                    
                    print(f"[{i}/{len(votes_list)}] 处理投票: {vote_id}")
                    
                    # 获取详细投票数据
                    try:
                        vote_detail = await client.get_vote_detail(TARGET_CONGRESS, session_number, roll_call)
                    except Exception as e:
                        print(f"  获取投票详情失败 {vote_id}: {str(e)}")
                        continue
                    
                    # 关联法案
                    bill_data = vote_detail.get('bill', {})
                    bill_id = None
                    if bill_data:
                        bill_congress = bill_data.get('congress', TARGET_CONGRESS)
                        bill_type = bill_data.get('type')
                        bill_number = bill_data.get('number')
                        if bill_type and bill_number:
                            bill_id = f"{bill_congress}-{bill_type}-{bill_number}"
                    
                    # 创建投票记录
                    totals = vote_detail.get('voteTotals', {})
                    vote = Vote(
                        vote_id=vote_id,
                        congress=TARGET_CONGRESS,
                        session_number=session_number,
                        roll_call_number=roll_call,
                        date=vote_detail.get('date'),
                        question=vote_detail.get('question'),
                        result=vote_detail.get('result'),
                        yea_count=totals.get('yea'),
                        nay_count=totals.get('nay'),
                        present_count=totals.get('present'),
                        not_voting_count=totals.get('notVoting'),
                        bill_id=bill_id
                    )
                    session.add(vote)
                    
                    # 记录每个议员的投票
                    votes_by_member = vote_detail.get('votes', [])
                    vote_count = 0
                    for member_vote in votes_by_member:
                        bioguide_id = member_vote.get('bioguideId')
                        position = member_vote.get('votePosition')  # Yea, Nay, Present, Not Voting
                        
                        if bioguide_id and position:
                            mv = MemberVote(
                                vote_id=vote_id,
                                bioguide_id=bioguide_id,
                                vote_position=position
                            )
                            session.add(mv)
                            vote_count += 1
                    
                    print(f"  添加投票记录: {vote_count} 名议员投票")
                    
                    # 每10条提交一次
                    if i % 10 == 0:
                        session.commit()
                        print(f"  已提交 {i} 条投票记录")
                
                # 最终提交
                session.commit()
                
            except Exception as e:
                print(f"获取第{session_number}会期投票记录失败: {str(e)}")
                session.rollback()
                continue
    
    print("\n" + "="*60)
    print("投票记录抓取完成")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(fetch_votes())
