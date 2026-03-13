#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库模型定义
使用 SQLAlchemy 作为 ORM
"""

from sqlalchemy import create_engine, Column, String, Integer, Date, Text, ForeignKey, Table, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from datetime import datetime
import sys
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))
from settings import PROCESSED_DATA_DIR

Base = declarative_base()

# 多对多关系表：法案联署人
bill_cosponsors = Table(
    'bill_cosponsors',
    Base.metadata,
    Column('bill_id', String(20), ForeignKey('bills.bill_id'), primary_key=True),
    Column('bioguide_id', String(10), ForeignKey('members.bioguide_id'), primary_key=True),
    Column('cosponsor_date', Date),
    Column('is_original_cosponsor', Boolean, default=False),
)


class Member(Base):
    """议员表"""
    __tablename__ = 'members'
    
    bioguide_id = Column(String(10), primary_key=True)  # 唯一标识
    first_name = Column(String(100))
    last_name = Column(String(100))
    full_name = Column(String(200))
    state = Column(String(2))  # 州代码，如 CA, NY
    district = Column(Integer)  # 选区号，参议员为 null
    party = Column(String(50))  # 党派：Democratic, Republican, Independent
    chamber = Column(String(10))  # 议院：House 或 Senate
    
    # 联系信息
    website = Column(String(500))
    office_address = Column(Text)
    phone = Column(String(50))
    
    # 社交媒体
    twitter = Column(String(100))
    facebook = Column(String(100))
    youtube = Column(String(100))
    
    # 任期信息
    start_date = Column(Date)
    end_date = Column(Date)
    
    # 元数据
    created_at = Column(Date, default=datetime.now)
    updated_at = Column(Date, default=datetime.now, onupdate=datetime.now)
    
    # 关系
    sponsored_bills = relationship("Bill", back_populates="sponsor")
    cosponsored_bills = relationship("Bill", secondary=bill_cosponsors, back_populates="cosponsors")
    votes = relationship("MemberVote", back_populates="member")


class Bill(Base):
    """法案表"""
    __tablename__ = 'bills'
    
    bill_id = Column(String(20), primary_key=True)  # 格式: {congress}-{type}-{number}
    congress = Column(Integer, index=True)  # 国会届数，如 119
    bill_type = Column(String(10), index=True)  # HR, S, HRES, SRES, HJRES, SJRES, HC, SC
    bill_number = Column(Integer, index=True)  # 法案编号
    
    # 标题
    title = Column(Text)
    short_title = Column(Text)
    
    # 提出信息
    introduced_date = Column(Date)
    sponsor_id = Column(String(10), ForeignKey('members.bioguide_id'))
    
    # 法案状态
    status = Column(String(50))  # 当前状态
    latest_action_date = Column(Date)
    latest_action_text = Column(Text)
    
    # 分类信息
    policy_area = Column(String(200))  # 政策领域
    subjects = Column(Text)  # 主题标签（JSON 格式存储）
    
    # 元数据
    created_at = Column(Date, default=datetime.now)
    updated_at = Column(Date, default=datetime.now, onupdate=datetime.now)
    
    # 关系
    sponsor = relationship("Member", back_populates="sponsored_bills")
    cosponsors = relationship("Member", secondary=bill_cosponsors, back_populates="cosponsored_bills")
    summaries = relationship("BillSummary", back_populates="bill")
    votes = relationship("Vote", back_populates="bill")


class BillSummary(Base):
    """法案摘要表"""
    __tablename__ = 'bill_summaries'
    
    summary_id = Column(Integer, primary_key=True, autoincrement=True)
    bill_id = Column(String(20), ForeignKey('bills.bill_id'))
    
    # 摘要内容
    text = Column(Text)  # 摘要文本
    text_version = Column(String(20))  # 版本号
    
    # 时间信息
    action_date = Column(Date)
    update_date = Column(Date)
    
    # 元数据
    created_at = Column(Date, default=datetime.now)
    
    # 关系
    bill = relationship("Bill", back_populates="summaries")


class Vote(Base):
    """投票记录表"""
    __tablename__ = 'votes'
    
    vote_id = Column(String(30), primary_key=True)  # 格式: {congress}-{session}-{roll_call}
    congress = Column(Integer, index=True)
    session_number = Column(Integer)  # 会期（1 或 2）
    roll_call_number = Column(Integer)
    
    # 投票信息
    date = Column(Date)
    question = Column(Text)  # 投票议题
    result = Column(String(50))  # 投票结果：Passed, Failed, Agreed to 等
    
    # 统计
    yea_count = Column(Integer)
    nay_count = Column(Integer)
    present_count = Column(Integer)
    not_voting_count = Column(Integer)
    
    # 关联法案（可能为空）
    bill_id = Column(String(20), ForeignKey('bills.bill_id'), nullable=True)
    
    # 元数据
    created_at = Column(Date, default=datetime.now)
    
    # 关系
    bill = relationship("Bill", back_populates="votes")
    member_votes = relationship("MemberVote", back_populates="vote")


class MemberVote(Base):
    """议员投票详情表"""
    __tablename__ = 'member_votes'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    vote_id = Column(String(30), ForeignKey('votes.vote_id'))
    bioguide_id = Column(String(10), ForeignKey('members.bioguide_id'))
    
    # 投票立场
    vote_position = Column(String(20))  # Yea, Nay, Present, Not Voting
    
    # 元数据
    created_at = Column(Date, default=datetime.now)
    
    # 关系
    vote = relationship("Vote", back_populates="member_votes")
    member = relationship("Member", back_populates="votes")


# 数据库连接函数
def get_engine(db_path=None):
    """创建数据库引擎"""
    if db_path is None:
        db_path = PROCESSED_DATA_DIR / "congress_data.db"
    
    return create_engine(f"sqlite:///{db_path}", echo=False)


def init_database(engine=None):
    """初始化数据库表"""
    if engine is None:
        engine = get_engine()
    
    Base.metadata.create_all(engine)
    return engine


def get_session(engine=None):
    """获取数据库会话"""
    if engine is None:
        engine = get_engine()
    
    Session = sessionmaker(bind=engine)
    return Session()


if __name__ == "__main__":
    # 测试数据库初始化
    print("初始化数据库...")
    engine = init_database()
    print(f"数据库已创建: {PROCESSED_DATA_DIR / 'congress_data.db'}")
    print("表结构:")
    for table in Base.metadata.tables:
        print(f"  - {table}")
