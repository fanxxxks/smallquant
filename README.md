# smallquant

面向人民币 5万—10万元账户的中国 ETF 量化研究项目。目标是在整手、成交成本、现金和结算约束下研究净收益与回撤，保存可追溯的实验输入、结果和决策。本仓库当前用于历史研究与纸面验证。

## 当前研究状态

四类名义目标权重为权益 45%、债券 35%、商品 10%、海外 10%。研究政策固定商品为 518880、海外为 513100，权益和债券保留成员集；实际现金由整手取整、订单抑制和费用形成。

具体规格与证据边界见 [账户持仓政策](docs/account-holding-policy.md)。固定单成员政策尚未完整实现和通过全路径回放；旧 prefix 排序路径的成绩不代表新政策成绩。

## 目录

| 目录 | 内容 |
|---|---|
| `newquant/` | 交易场所约束、订单、账户账本、回放、数据冻结和评估模块 |
| `tests/` | 当前单元与回归测试 |
| `data/` | 冻结行情、manifest、公司行动及数据准备脚本 |
| `evidence/` | 已有实验报告、汇总与交易账本 |
| `probe/` | 一次性研究测量脚本；其中假设和失败尝试不等于验证结论 |
| `docs/` | 项目方向、架构与研究政策 |
| `.quant/` | 哈希链研究账本、项目条件、状态与交接 |

历史输入、证据和研究账本随 Git 保存；Python 缓存、DuckDB 溢写、虚拟环境和环境变量文件由 `.gitignore` 排除。保留的数据快照可能与重新采集的行情不同。`.quant/ledger.jsonl` 为既有哈希链记录，请通过相应研究工具追加，避免手工改写历史。

## 环境与测试

当前验证环境为 Python 3.13.12。核心依赖版本记录于 [requirements.txt](requirements.txt)。

```bash
python -m venv .venv
# Git Bash / Windows
source .venv/Scripts/activate
# Linux / macOS 则使用 source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest
```

数据采集脚本另需 `akshare`，部分探索脚本另需 `torch`；它们不属于上述核心依赖。按需要另行安装，重采集前先检查对应脚本的输出位置，以保留历史证据。

部分面板实验还依赖仓库外的 DuckDB 数据库，通过环境变量指定：

```bash
export NEWQUANT_PANEL='/absolute/path/to/ashare_v2.duckdb'
export NEWQUANT_SPILL='.duckdb_tmp'
```

外部数据库未包含在仓库中。运行 E1 等面板实验前，需要准备符合 `newquant/panel/source.py` 表结构要求的数据；测试通过不代表所有依赖外部数据的实验均可在新机器复现。

## 研究入口

从项目根目录运行。执行前阅读模块说明和已有证据；以下命令会计算或更新研究产物：

```bash
python -m newquant.data.freeze
python -m newquant.eval.feasibility
python -m newquant.eval.e1
python -m newquant.eval.e2
python -m newquant.eval.e3
```

最新交接见 [.quant/handoff/etf-implementable-frontier.md](.quant/handoff/etf-implementable-frontier.md)，当前状态以账本及对应证据为准。既有文档中的 `D:/newquant/...` 链接保留了原工作站路径，其他机器可按仓库内相对路径定位。

## 版本同步

远端：<https://github.com/fanxxxks/smallquant.git>；主分支：`main`。

```bash
git status
git diff
git add <本次修改的路径>
git commit -m "说明本次修改"
git push
```

首次获取项目：

```bash
git clone https://github.com/fanxxxks/smallquant.git
cd smallquant
```
