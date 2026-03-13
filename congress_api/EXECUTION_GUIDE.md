# Congress.gov API 数据抓取执行指南

本文档说明如何使用 Congress.gov API 抓取美国国会议员数据。

## 项目结构

```
congress_api/
├── settings.py                      # 配置文件（API Key、常量等）
├── database/
│   └── models.py                    # 数据库模型定义
├── utils/
│   └── api_client.py                # API 客户端封装
├── crawlers/
│   ├── 01_fetch_members.py          # 第1步：抓取议员数据
│   ├── 02_fetch_bills.py            # 第2步：抓取法案数据
│   ├── 03_fetch_summaries.py        # 第3步：抓取法案摘要
│   ├── 04_fetch_votes.py            # 第4步：抓取投票记录
│   └── 05_data_integration.py       # 第5步：数据整合导出
├── data/
│   ├── raw/                         # 原始抓取数据（JSON备份）
│   └── processed/                   # 处理后数据（SQLite数据库、CSV导出）
├── logs/                            # 日志目录
└── EXECUTION_GUIDE.md               # 本文档
```

## 执行流程

### 前置准备

1. **安装依赖**
   ```bash
   pip install aiohttp sqlalchemy pandas tenacity
   ```

2. **获取 API Key**
   - 访问 https://api.data.gov/signup/ 申请 API Key
   - 首次运行脚本时会提示输入

### 执行步骤

#### 第1步：抓取议员数据

```bash
cd congress_api
python crawlers/01_fetch_members.py
```

**功能**：获取第119届国会所有议员的基础信息

**数据包括**：
- 议员基本信息（姓名、党派、州、选区）
- BioGuide ID（唯一标识）
- 联系方式、社交媒体账号
- 任期信息

**输出**：
- 数据库：`data/processed/congress_data.db` 的 `members` 表
- 备份：`data/raw/members_congress_119.json`

---

#### 第2步：抓取法案数据

```bash
python crawlers/02_fetch_bills.py
```

**功能**：抓取所有议员提出和联署的法案

**核心逻辑**：
- 对每个议员调用 API 获取 `sponsored-legislation`（提出的法案）
- 对每个议员调用 API 获取 `cosponsored-legislation`（联署的法案）
- 区分存储 **Sponsor（提出者）** 和 **Cosponsor（联署人）**

**数据包括**：
- 法案基本信息（编号、类型、标题）
- 提出日期、最新进展
- 政策领域、主题标签
- Sponsor 和 Cosponsor 关联关系

**输出**：
- 数据库：`bills` 表、`bill_cosponsors` 关联表

---

#### 第3步：抓取法案摘要

```bash
python crawlers/03_fetch_summaries.py
```

**功能**：为每个法案获取内容简介

**数据包括**：
- 法案摘要文本
- 摘要版本号
- 更新日期

**输出**：
- 数据库：`bill_summaries` 表

---

#### 第4步：抓取投票记录

```bash
python crawlers/04_fetch_votes.py
```

**功能**：抓取众议院投票记录

**数据包括**：
- 投票基本信息（日期、议题、结果）
- 投票统计（赞成、反对、弃权、缺席）
- 每个议员的投票立场（Yea/Nay/Present/Not Voting）
- 关联的法案信息

**输出**：
- 数据库：`votes` 表、`member_votes` 表

---

#### 第5步：数据整合与导出

```bash
python crawlers/05_data_integration.py
```

**功能**：整合数据并导出为 CSV 格式

**导出文件**：
1. `member_bill_stats.csv` - 议员法案统计
2. `vote_records.csv` - 投票记录详情
3. `bill_details.csv` - 法案详细信息
4. `bill_summaries.csv` - 法案摘要

**统计报告**：
- 议员统计（按议院、党派分组）
- 法案类型统计
- 投票统计（按会期分组）
- 摘要覆盖率统计

---

## 完整执行命令

```bash
cd congress_api

# 依次执行所有步骤
python crawlers/01_fetch_members.py
python crawlers/02_fetch_bills.py
python crawlers/03_fetch_summaries.py
python crawlers/04_fetch_votes.py
python crawlers/05_data_integration.py
```

---

## 数据库模型

### 核心表结构

```
members (议员表)
├── bioguide_id (主键)
├── full_name, state, district
├── party, chamber
└── ...

bills (法案表)
├── bill_id (主键: congress-type-number)
├── congress, bill_type, bill_number
├── title, introduced_date
├── sponsor_id (外键 -> members)
└── ...

bill_cosponsors (法案联署关联表)
├── bill_id (外键)
├── bioguide_id (外键)
└── cosponsor_date

bill_summaries (法案摘要表)
├── summary_id (主键)
├── bill_id (外键)
└── text, action_date

votes (投票记录表)
├── vote_id (主键: congress-session-roll_call)
├── congress, session_number, roll_call_number
├── date, question, result
└── bill_id (外键, 可能为空)

member_votes (议员投票详情表)
├── vote_id (外键)
├── bioguide_id (外键)
└── vote_position (Yea/Nay/Present/Not Voting)
```

---

## 注意事项

### API 限制
- **速率限制**：5,000 请求/小时
- **本工具设置**：4,500 请求/小时（保守策略）
- **请求间隔**：约 0.8 秒/请求

### 数据量预估
- 议员：约 535 人（100 参议员 + 435 众议员）
- 法案：每个议员可能提出/联署数十到数百条
- 投票：每届国会数千次投票

### 执行时间预估
- 第1步（议员）：约 5-10 分钟
- 第2步（法案）：数小时（取决于法案数量）
- 第3步（摘要）：1-2 小时
- 第4步（投票）：1-2 小时
- 第5步（导出）：几分钟

### 断点续传
- 每个脚本独立运行，可随时中断
- 数据库会自动检查重复数据，不会重复抓取
- 中断后可从当前步骤重新运行

---

## 数据用途

抓取的数据可用于以下分析：

1. **党派一致性分析**
   - 计算议员投票与党派多数的一致性比例

2. **议题立场分析**
   - 按 policyArea 分组统计投票倾向

3. **提案活跃度分析**
   - 统计议员提出/联署法案数量

4. **跨党派合作分析**
   - 分析议员与对立党派联署法案的频率

5. **投票历史轨迹**
   - 追踪议员立场随时间的变化

---

## 故障排除

### API Key 无效
```
错误：API Key 无效或已过期
解决：检查 API Key 是否正确，或重新申请
```

### 速率限制
```
提示：达到速率限制，等待 X 秒...
处理：程序会自动等待，无需操作
```

### 数据库锁定
```
错误：database is locked
解决：关闭其他访问数据库的程序，重新运行
```

---

## 配置文件

`settings.py` 中的关键配置：

```python
TARGET_CONGRESS = 119          # 目标国会届数
RATE_LIMIT_PER_HOUR = 5000     # API 速率限制
SAFE_REQUESTS_PER_HOUR = 4500  # 保守策略
REQUEST_DELAY = 0.8            # 请求间隔（秒）
MAX_RETRIES = 3                # 最大重试次数
```

---

## 技术支持

- Congress.gov API 文档：https://api.congress.gov/
- GitHub 仓库：https://github.com/LibraryOfCongress/api.congress.gov/
- API Key 申请：https://api.data.gov/signup/
