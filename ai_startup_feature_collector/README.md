# AI Startup Feature Collector

该仓库提供一套端到端的数据采集与特征构建框架，帮助投资人、研究者、创业者评估 AI 创业公司的潜在成功概率。系统围绕论文中提及的 **Startup Success Feature Framework (SSFF)** 搭建，分为三个主模块：

1. **Prediction Block**：结构化创业公司基本面特征，用于训练 Random Forest、神经网络等模型。
2. **Founder Segmentation Block**：创始人能力分层、Founder-Idea Fit 计算。
3. **External Knowledge Block**：通过 RAG 检索外部市场情报，生成增强特征。

## 功能概览

- 🔌 插件式数据源定义（Product Hunt、YC、Crunchbase、OpenCorporates、LinkedIn、GitHub、新闻情绪等）
- 📦 多种特征层输出：`features_ssff.parquet`、`features_founder.parquet`、`features_ssff_ext.json`
- 🧠 支持大模型嵌入计算 Founder-Idea Fit（兼容 `text-embedding-3-large` 或任意 OpenAI 兼容接口）
- 🔄 RAG 检索流程：SERP → 文档解析 → 特征抽取
- 🧪 单元测试和 `examples/` 样例脚本帮助快速上手

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[serp,io,rag]
cp .env.template .env
python -m ai_startup_feature_collector.cli --config configs/demo.yml
```

### 环境变量

在根目录创建 `.env`，示例：

```
PRODUCT_HUNT_TOKEN=ph-token
CRUNCHBASE_USER_KEY=cb-key
SERPAPI_KEY=serp-key
OPENAI_API_KEY=sk-xxx
LINKEDIN_SESSION=li-session-cookie
```

## 目录结构

```
ai_startup_feature_collector/
├── ai_startup_feature_collector/
│   ├── cli.py                    # 命令行入口
│   ├── config.py                 # 配置与凭证读取
│   ├── models.py                 # 特征数据结构
│   ├── pipelines/                # 三大主流程
│   │   ├── fundamentals.py
│   │   ├── founders.py
│   │   └── external.py
│   ├── sources/                  # 数据源适配层
│   │   ├── base.py
│   │   ├── crunchbase.py
│   │   ├── github.py
│   │   ├── linkedin.py
│   │   ├── open_corporates.py
│   │   ├── product_hunt.py
│   │   ├── serp.py
│   │   ├── social.py
│   │   └── y_combinator.py
│   └── storage/                  # 存储抽象
│       └── writer.py
├── configs/
│   └── demo.yml                  # 样例配置（可自定义追踪公司、创始人）
├── examples/
│   └── build_dataset.py          # 快速将样例 JSON 合并成特征表
└── tests/
    └── test_config.py
```

## 功能细节

### Prediction Block（14 个类别型特征）

- **行业增长**：来自 Product Hunt 分类趋势、YC 最新批次标签。
- **市场规模**：集成 GLEIF 行业编码与市场报告数据。
- **发展速度**：对比竞争对手的更新频率、招聘节奏。
- **市场适应性**：使用网站改动频率、产品公告进行衡量。
- **执行能力**：结合 GitHub commit 节奏、职位发布量。
- **融资金额/估值变化/投资者背书**：联合 Crunchbase、OpenCorporates filings。
- **PMF/创新性提及/尖端技术使用**：对产品描述、评论进行 NLP 分类。
- **时间窗口/情绪分析/推荐评论**：通过 SERP 和社媒数据计算。

所有特征统一封装在 `StartupFundamentalsPipeline` 中，最终生成 `features_ssff.parquet`。

### Founder Segmentation Block

- 使用 `FounderProfile` 数据类管理创始人教育、经历、创业史。
- `FounderSegmentationPipeline` 调用 LinkedIn 解析器、新闻数据库，计算 L1-L5 分层。
- Founder-Idea Fit 值基于创始人经历简介与 Startup 描述之间的嵌入相似度，输出归一化得分。

### External Knowledge Block

- `ExternalKnowledgePipeline` 通过 `SerpClient` 搜索市场报告。
- 对网页正文进行关键信息抽取（市场规模、CAGR、竞争者数量等）。
- 将抽取结果保存为结构化 JSON，可与主特征表合并。

## 扩展与自定义

- 添加新数据源：继承 `BaseDataSource`，实现 `fetch` 与 `normalize`。
- 引入自建缓存：实现 `StorageWriter` 接口，将结果写入数据库或对象存储。
- 支持批量任务：在配置中添加多家 startup/创始人，CLI 会自动循环执行。

## 开源数据源建议

- **公司信息**：Product Hunt、Crunchbase 免费层、YC 名录、OpenCorporates。
- **创始人数据**：LinkedIn 导出、Crunchbase Founder profiles、新闻稿。
- **市场情报**：SERP API、公开行业报告、Google Patents、公司年报。
- **社区口碑**：Reddit、Twitter、App Store、G2、Product Hunt 评论。

## 贡献指南

1. Fork 本仓库并创建分支。
2. 运行 `make lint && make test`（可在 `common-make.mk` 基础上扩展）。
3. 提交 Pull Request，并附带数据源使用说明。

欢迎贡献更多数据连接器、特征工程方法和评估 Notebook！
