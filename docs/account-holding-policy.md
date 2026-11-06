# 账户持仓政策（研究规格）

日期：2026-11-05；研究线：`etf-implementable-frontier`。

本文把已有成员选择写成账户研究政策，适用初始资本人民币 **50,000–100,000 元**。既有定量比较主要来自 **50,000 元、15.1 bp gate、annual lots、六个历史入场日起至 2026-11-04** 的观察；证据适用范围小于政策资本范围。本政策尚未完整实现于当前回放引擎，也未完成前向纸面验证。

## 1. 成员、权重与现金

| 风险袖 | 归一化名义目标 | 本政策成员 | 研究规格 |
|---|---:|---|---|
| 权益 `equity` | 45% | 510300、510500、512100 | 保留成员集，按当时可用成员及整手约束构成 |
| 债券 `bond` | 35% | 511220、511380 | 保留成员集，上市可用性、整手与 NAV 路径可能改变实际成员数 |
| 商品 `commodity` | 10% | **518880** | 单一允许成员，排除该袖的 159934 |
| 海外 `overseas` | 10% | **513100** | 单一允许成员，排除该袖的 513500、159920 |

“单一成员”仅限商品与海外两袖，不推广到权益、债券。保留成员集也不等于保证每次全部成交。代码以首条 bar 日期判定成员是否可用，注释列 512100 为 2016-11-04、511380 为 2020-04-07。[可用成员逻辑](D:/newquant/newquant/replay.py:318)、[规格成员](D:/newquant/probe/spec_check.py:25)。

**45/35/10/10 是四个风险袖占总账户 NAV 的归一化名义目标，合计 100%；没有另外预设 10% 现金。** 即 `(45,35,10,10)/100 = (0.45,0.35,0.10,0.10)`。这不是成交后实际权重保证。[当前常量](D:/newquant/newquant/replay.py:56)。

当前 `lots` 按各袖 `weight × NAV` 预算，从可用成员前缀中减少成员数，直至每成员预算满足 `sleeve_floor`；再按 100 份一手向下取整得到表达金额。权益与债券保留这一既有构成语义；本文额外收紧海外与商品允许成员集。[构成逻辑](D:/newquant/newquant/replay.py:393)。

表达后四袖权重可以合计小于 100%，**不再次归一化到风险资产**。`lots` 将缺口留在现金；执行价格、整手、成交费用及被 gate 抑制的订单还会改变实际现金。现金是剩余账面余额，不是 511880/511990 持仓，也不是固定收益产品。`lots_deploy` 的残余再分配属于另一研究臂，本文未选择它。[保留现金的分支](D:/newquant/newquant/replay.py:414)、[现金定义](D:/newquant/docs/direction-architecture.md:165)。

应分别理解名义四袖权重、整手构成后的表达权重、成交后实际风险资产权重与现金余额；实际风险资产权重不强制缩放成合计 100%。

## 2. 成员选择依据及历史证据边界

`quant_ledger` adopted 决策 `name-one-fund-per-sleeve`（seq 230）具体选择海外 513100，applicability 限于六历史起点的 50,000 元海外袖比较。商品 518880、权益与债券保留成员，明确记录于交接与规格探针。seq 230 泛称 one fund per sleeve，不应据此压缩权益、债券；商品的明确出处是后两者。`quant_ledger` seq 231 的 progress 记录该规格；[探针规格](D:/newquant/probe/spec_check.py:25)。

seq 230 转述：**旧多成员 prefix 规则下的 513100-first 路径**相对事后最佳排序的年化差距均值约 **0.023 个百分点/年**、最大约 **0.136 个百分点/年**；513500-first 对应约 0.440/0.868，159920-first 约 1.766/2.280。这些是六起点的**历史事后相对最佳排序差距**，不是新单成员政策的实测差距、未来交易成本或未来成本上限。本次未独立复算其汇总公式，仅把它们作为 seq 230 的旧路径参考统计。历史出处：`quant_ledger` seq 230 及 seq 231 的 progress。

513100 是**看过样本后的选择**。它明确了集中暴露，但没有证明收益优势持续，也没有在独立未读样本证明该命名优于替代基金或事前规则。原排序表六排列的平均 gap 为 −0.776 至 +0.968 个百分点/年，跨度 1.743；该 gap 是 hold200 与 lots 的相对比较，不等同于相对事后最佳排序差距。[排序表](D:/newquant/evidence/probe-member-order/report.md:7)。

同一历史设置下，各袖排序终值色散均值为权益 0.000%、债券 0.124%、商品 0.567%、海外 12.643%。色散口径为每起点 `(最高终值−最低终值)/平均终值` 后取起点均值，不是年化成本。商品选择 518880 是明确的政策命名，0.567% 不证明该成员最优；已载终值表中 159934-first 在前五起点高于 518880-first，最后一个起点相反。[口径与色散表](D:/newquant/evidence/probe-sleeve-dispersion/report.md:3)、[商品终值](D:/newquant/evidence/probe-sleeve-dispersion/summary.json:75)。

海外约束对照的终值色散：base 12.643%、gate_off 0.000%、仅移除成员计数整手项的 lot_off 12.646%、free 0.000%。这支持“gate 是该海外袖在这一历史设置中暴露排序差异的关键约束”；没有证明所有袖、所有资本均只受 gate 约束。[约束对照](D:/newquant/evidence/probe-constraint-control/report.md:3)。

资料使用 Nasdaq-100、S&P 500、Hang Seng、Au99.99 等指数标签，但交接承认未以工作区基准映射表核验身份。本文不将这些映射视作本次确证；成员代码与排序差异已足以明确政策。seq 230 的 `19.77%−1.12%=16.5pp` 是算术误写，正确差为 **18.65 个百分点**；这是原文算术校正，不是新增指数身份验证。历史出处：`quant_ledger` seq 231 的 unverified。

## 3. 15.1 bp gate 的实际含义

保留既有 **15.1 bp 单边总成本 gate**，按每笔取整后可执行金额检查。它不是账户年化成本预算、跟踪误差限额或收益门槛。构成阶段 `sleeve_floor` 取代码 gate 最低金额与一手金额的较大者，再取成员中的最大要求；路由阶段再次对取整后金额执行 `gate_ok`。[构成门槛](D:/newquant/newquant/replay.py:343)、[路由检查](D:/newquant/newquant/order.py:74)。

回放费率为佣金 0.00025、每非零订单最低 5 元、印花税 0、过户费 0.00001，加代码级滑点代理。[费率](D:/newquant/newquant/replay.py:102)。`measured` 滑点为半个 tick 除以固定历史 `REPLAY_START..REPLAY_END` 区间中位收盘价，是冻结的历史代理；不是入场前可得估计，也不是逐笔实测买卖价差。该历史配置没有因此成为无前视的前向成本模型。[滑点代码](D:/newquant/newquant/replay.py:76)。

构成计数通过不保证成交。订单可能因 `zero_lot`、`below_cost_gate`、`insufficient_settled_cash` 等抑制；买单还需满足成交金额加现金费用不超过可用已结算现金。未成交金额继续留在现金。[抑制与资金检查](D:/newquant/newquant/order.py:79)。

## 4. annual lots：只陈述已读源码支持的时序

排序证据适用 **annual lots**，不是月度再平衡政策。项目条件里其他频率描述不因此改写；月度诊断也不等于月度成交。本次未重新执行回放。

1. **入场**：首个 session 以 `is_annual=True, prev=None` 构成，买意图进入 `pending[0]`。同一 session 开盘价经过滑点和 tick 处理后路由；构成估值日期也是该 session。本次未验证这种入场信息与定价是否满足前向执行标准。[入场](D:/newquant/newquant/replay.py:627)、[执行取价](D:/newquant/newquant/replay.py:699)。
2. **维护决策**：每个月末调用 `compose` 并记录诊断，annual 标志只在 **1 月月末**为真。`lots` 仅在 annual 或 `prev is None` 返回目标，其余月返回 `None`。这是年度重提交，不保证年度成交。[年度月份](D:/newquant/newquant/replay.py:598)、[月末调用](D:/newquant/newquant/replay.py:734)、[返回条件](D:/newquant/newquant/replay.py:515)。
3. **维护意图**：按决策日收盘 NAV，对本次成员映射中各代码的目标与当前市值求 delta。此循环没有自动清退所有已不在本次成员映射中的旧持仓；成员映射不等于全账户实际持仓清单。[delta 循环](D:/newquant/newquant/replay.py:800)。
4. **成交排程**：索引 `i` 决策，卖单排 `i+1`；买单通常排 `i+2`，即使没有卖单也如此。`i+2` 越窗时买单回退 `i+1`，连 `i+1` 都不存在则不排单。时槽用赋值写入，因此窗口末尾同槽行为不应概括为普遍成立的“两阶段结算保证”。[排单](D:/newquant/newquant/replay.py:800)。
5. **执行当日**：先 `book.settle(i)`，再公司行动，再待执行订单；买读取 `available_cash(i)`、卖读取 `sellable_lots(code,i)`，失败记录 suppression。本次未逐层核验 Book 内部结算日计算，不把时槽安排等同于交易所结算规则完整确证。[日内顺序](D:/newquant/newquant/replay.py:656)、[订单参数](D:/newquant/newquant/replay.py:708)。

早期方向提出年度静态政策和现金细调，架构提出“卖出结算后买入”不变式；这些设计文字不自动成为已通过验证的运行事实。[早期推荐](D:/newquant/docs/new-project-direction-and-plan.md:202)、[设计不变式](D:/newquant/docs/direction-architecture.md:200)。

## 5. 研究政策尚未实现；入场相同不证明全路径等价

当前引擎海外仍为 `(513100,513500,159920)`，商品仍为 `(518880,159934)`；`lot_composition` 按当时 NAV 与可用前缀选择 k。**海外与商品的永久单成员限制尚未实现。** 首位代码相同不阻止后续增员。[当前成员](D:/newquant/newquant/replay.py:57)、[计数逻辑](D:/newquant/newquant/replay.py:399)。

规格探针更新 `SLEEVE_MEMBERS`，而 `TRADED` 已在模块导入时由旧表生成。`replay` 遍历旧 `TRADED` 再用 `next(sl for sl, members in SLEEVE_MEMBERS.items() if code in members)` 查类别；删除代码无匹配，造成 **StopIteration** 阻塞。交接记录了既有失败，本次静态阅读确认该机制，没有重新触发或修复。[更新位置](D:/newquant/probe/spec_check.py:30)、[TRADED](D:/newquant/newquant/replay.py:63)、[失败位置](D:/newquant/newquant/replay.py:573)、既有失败记录见 `quant_ledger` seq 231 的 facts。

探针文首“单成员必须复现 513100-first 终值”是 P0 预期，不是结果。交接仅报告六起点入场构成相同；这不证明以后路径、成交、现金与终值相同。原表中两个同为 513100-first 的排序，2016 起点终值约 **81,605 与 81,225 元**，2017 起点约 **84,518 与 83,490 元**；仅第二成员换序已改变路径。[探针预期](D:/newquant/probe/spec_check.py:3)、[反例](D:/newquant/evidence/probe-member-order/report.md:24)。

因此，不将旧 prefix 净值成绩重新标为新单成员政策成绩。既有 100,000 元及后期增员记录，也使 seq 230 的“出现两成员再重开”条件并非尚未发生的触发条件。

## 6. 对交接 next 的判断与未核验项

“把已有选择写成文档”有证据支持，无需新测量；“研究问题已完全回答、排序已不再阻塞账户”过强。政策可写定，单成员执行与全路径仍待验证。next 的 one named fund per sleeve 应收窄为本文两个单成员袖，“承诺成本 ≤0.136pp/yr”应改称旧 prefix 的六起点历史事后相对最佳排序差距。历史出处：`quant_ledger` seq 231 的 next。

另两处不沿用：袖色散报告“海外 always k=1”与原排序反例及路径增员事实冲突；约束报告 fill-row count check 为 **2/30**，并非路径定律验证成功。本文只采用该报告四格色散结果。[过强概括](D:/newquant/evidence/probe-sleeve-dispersion/report.md:12)、[失败检查](D:/newquant/evidence/probe-constraint-control/report.md:15)。

本次实际未核验：

- 新单成员政策的完整回放、终值、成交路径及与旧 prefix 的差异；规格探针没有成功 P0 结果。
- 100,000 元下本政策的表现、六起点代表性、独立未读窗口及前向纸面结果；历史窗口重叠。
- 指数身份的官方映射、基金合同与标的核对；指数标签保留为待核验解释。
- 放宽 gate 后的月度再平衡结果；本次排序定量证据限 annual lots。
- Book 内部结算实现、市场冲击、真实价差与真实账户成交。

这些边界不构成新实验、新策略或实现设计。

## 7. 逐源阅读范围

`read:full` 为已读该源全文或该条完整记录，`read:partial` 为只读所列部分。报告和摘要没有因此成为逐笔账本复算。

| 来源 | 标记 | 覆盖 |
|---|---|---|
| quant ledger seq 230 `name-one-fund-per-sleeve` | read:full | 完整决策及其条件、验证计划；未写 ledger |
| 交接历史版本（`quant_ledger` seq 231） | read:full | 当时投影 1–62 行；最新交接会继续刷新 |
| [方向与计划](D:/newquant/docs/new-project-direction-and-plan.md:185) | read:partial | 185–299 行 |
| [架构方向](D:/newquant/docs/direction-architecture.md:145) | read:partial | 145–254、380–429 行 |
| [袖色散报告](D:/newquant/evidence/probe-sleeve-dispersion/report.md:1) | read:full | 1–29 行 |
| [袖色散摘要](D:/newquant/evidence/probe-sleeve-dispersion/summary.json:1) | read:partial | 1–130 行 |
| [成员排序报告](D:/newquant/evidence/probe-member-order/report.md:1) | read:full | 1–59 行 |
| [约束对照报告](D:/newquant/evidence/probe-constraint-control/report.md:1) | read:full | 1–15 行 |
| [约束对照摘要](D:/newquant/evidence/probe-constraint-control/summary.json:313) | read:partial | 仅关键词定位 path_check/paths；不据此新增结论 |
| [规格探针](D:/newquant/probe/spec_check.py:1) | read:full | 1–64 行，未执行 |
| [回放引擎](D:/newquant/newquant/replay.py:54) | read:partial | 54–115、287–546、553–837 行 |
| [订单规划器](D:/newquant/newquant/order.py:1) | read:full | 1–116 行 |

文档起草阶段只新增本文，没有运行回测或修改代码、既有业务文档。主会话另将续接边界和反例写入 `quant_ledger`（seq 233、234），并更新研究交接。核验强度为已有报告与源码的有界独立核对，不是新政策的运行验证。
