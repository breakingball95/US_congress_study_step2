#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第5步：数据整合与导出
"""

import pandas as pd
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.models import get_engine, init_database
from settings import PROCESSED_DATA_DIR


def export_member_bill_stats():
    """
    导出议员-法案统计
    用于分析：哪些议员提出了哪些法案，联署了哪些法案
    """
    engine = init_database()
    
    query = """
    SELECT 
        m.bioguide_id,
        m.full_name,
        m.party,
        m.state,
        m.chamber,
        COUNT(DISTINCT b.bill_id) as bills_sponsored,
        COUNT(DISTINCT bc.bill_id) as bills_cosponsored
    FROM members m
    LEFT JOIN bills b ON m.bioguide_id = b.sponsor_id
    LEFT JOIN bill_cosponsors bc ON m.bioguide_id = bc.bioguide_id
    WHERE m.chamber = 'House'
    GROUP BY m.bioguide_id
    ORDER BY bills_sponsored DESC
    """
    
    df = pd.read_sql(query, engine)
    output_file = PROCESSED_DATA_DIR / "member_bill_stats.csv"
    df.to_csv(output_file, index=False)
    print(f"议员法案统计已导出: {output_file}")
    return df


def export_vote_analysis():
    """
    导出投票分析数据
    用于分析：议员投票倾向、党派一致性等
    """
    engine = init_database()
    
    query = """
    SELECT 
        m.bioguide_id,
        m.full_name,
        m.party,
        v.vote_id,
        v.question,
        v.date,
        v.result as vote_result,
        mv.vote_position,
        b.policy_area,
        b.bill_type,
        b.bill_number,
        b.title as bill_title
    FROM member_votes mv
    JOIN members m ON mv.bioguide_id = m.bioguide_id
    JOIN votes v ON mv.vote_id = v.vote_id
    LEFT JOIN bills b ON v.bill_id = b.bill_id
    WHERE m.chamber = 'House'
    ORDER BY v.date DESC
    """
    
    df = pd.read_sql(query, engine)
    output_file = PROCESSED_DATA_DIR / "vote_records.csv"
    df.to_csv(output_file, index=False)
    print(f"投票记录已导出: {output_file}")
    return df


def export_bill_details():
    """
    导出法案详细信息
    包含法案、摘要、提出者、联署人信息
    """
    engine = init_database()
    
    query = """
    SELECT 
        b.bill_id,
        b.congress,
        b.bill_type,
        b.bill_number,
        b.title,
        b.short_title,
        b.introduced_date,
        b.policy_area,
        b.subjects,
        b.status,
        m.full_name as sponsor_name,
        m.party as sponsor_party,
        m.state as sponsor_state,
        GROUP_CONCAT(DISTINCT mc.full_name) as cosponsors
    FROM bills b
    LEFT JOIN members m ON b.sponsor_id = m.bioguide_id
    LEFT JOIN bill_cosponsors bc ON b.bill_id = bc.bill_id
    LEFT JOIN members mc ON bc.bioguide_id = mc.bioguide_id
    WHERE b.congress = 119
    GROUP BY b.bill_id
    ORDER BY b.introduced_date DESC
    """
    
    df = pd.read_sql(query, engine)
    output_file = PROCESSED_DATA_DIR / "bill_details.csv"
    df.to_csv(output_file, index=False)
    print(f"法案详情已导出: {output_file}")
    return df


def export_bill_summaries():
    """
    导出法案摘要信息
    """
    engine = init_database()
    
    query = """
    SELECT 
        b.bill_id,
        b.bill_type,
        b.bill_number,
        b.title,
        bs.text as summary_text,
        bs.text_version,
        bs.action_date as summary_date
    FROM bills b
    JOIN bill_summaries bs ON b.bill_id = bs.bill_id
    WHERE b.congress = 119
    ORDER BY b.bill_id, bs.action_date
    """
    
    df = pd.read_sql(query, engine)
    output_file = PROCESSED_DATA_DIR / "bill_summaries.csv"
    df.to_csv(output_file, index=False)
    print(f"法案摘要已导出: {output_file}")
    return df


def generate_statistics():
    """生成数据统计报告"""
    engine = init_database()
    
    print("\n" + "="*60)
    print("数据统计报告")
    print("="*60)
    
    # 议员统计
    member_stats = pd.read_sql("""
        SELECT 
            chamber,
            party,
            COUNT(*) as count
        FROM members
        GROUP BY chamber, party
    """, engine)
    print("\n议员统计:")
    print(member_stats.to_string(index=False))
    
    # 法案统计
    bill_stats = pd.read_sql("""
        SELECT 
            bill_type,
            COUNT(*) as count
        FROM bills
        WHERE congress = 119
        GROUP BY bill_type
    """, engine)
    print("\n法案类型统计:")
    print(bill_stats.to_string(index=False))
    
    # 投票统计
    vote_stats = pd.read_sql("""
        SELECT 
            session_number,
            COUNT(*) as count
        FROM votes
        WHERE congress = 119
        GROUP BY session_number
    """, engine)
    print("\n投票统计:")
    print(vote_stats.to_string(index=False))
    
    # 摘要统计
    summary_stats = pd.read_sql("""
        SELECT 
            COUNT(DISTINCT b.bill_id) as bills_with_summary
        FROM bills b
        JOIN bill_summaries bs ON b.bill_id = bs.bill_id
        WHERE b.congress = 119
    """, engine)
    print("\n摘要统计:")
    print(f"有摘要的法案数: {summary_stats.iloc[0]['bills_with_summary']}")
    
    print("\n" + "="*60)


def main():
    """主函数：执行所有数据导出"""
    print("="*60)
    print("数据整合与导出")
    print("="*60)
    
    # 导出各类数据
    print("\n1. 导出议员法案统计...")
    export_member_bill_stats()
    
    print("\n2. 导出投票记录...")
    export_vote_analysis()
    
    print("\n3. 导出法案详情...")
    export_bill_details()
    
    print("\n4. 导出法案摘要...")
    export_bill_summaries()
    
    # 生成统计报告
    print("\n5. 生成统计报告...")
    generate_statistics()
    
    print("\n" + "="*60)
    print("所有数据导出完成！")
    print(f"数据文件保存在: {PROCESSED_DATA_DIR}")
    print("="*60)


if __name__ == "__main__":
    main()
