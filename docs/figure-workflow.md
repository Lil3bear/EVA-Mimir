# 图示工作区

## 模型与费用

默认使用本机 Codex 的 `gpt-6.1-sol`，没有 Claude、Opus、Fable、图像服务或收费 API 的自动回退。本机仍需登录且保持在线，使用账户额度。`gpt-6-astra` 可在每轮绘图任务单独选择，必须额外确认；选择不会改变写作默认模型。接口兼容不代表当前账户已经拥有该模型权限，未以真实 Astra 请求探测权限或计费。

## Skills 与出处

网页现有 12 个写作、审稿 Skills 保留，新增 4 个按绘图任务自动组合的 Skills：

- `paper-figure-story`：全文证据、动机与创新，参考 [Leey21](https://github.com/Leey21/awesome-ai-research-writing)。
- `paper-figure-layout`：布局选择，参考 [PaperBanana 的六类 Figure 1 布局](https://paper-banana.org/zh/blog/figure-1-layout-patterns)。
- `scientific-illustration`：作者提供的插画 prompt、矢量组件和视觉检查，附原始作者模板。
- `experiment-figures`：实验图表与原始数值追溯，参考 Leey21，另加入独立的实验诚信检查。

各文件注明来源与整理日期。未复制示例图、整篇文章或完整 prompt 集；外部作品的权利仍属原作者。新增绘图 Skills 不默认塞进每次文字润色，避免浪费上下文。

## 工作流程

右侧图示图标打开工作区。它盘点当前编译入口实际引用的全部图及能够解析的数字表格；当前 CyberRSI 稿有 5 张正文图、3 个数字表格。

1. 检查 Method：读取完整正文、Bib、图注与未解决批注，保存独立审查记录。结果绑定本轮源码版本。明确的 Method 人工批注、重大问题及审查阻塞没有处理时，不允许正式替换。
2. 对某张图或某个表写图示批注，确认后提交。后台只生成草稿，不把批注标成完成。现有图按源码与图注重新设计；本版不会声称模型已经看过原图的二进制 PDF。
3. 草稿使用可编辑结构化场景，导出 SVG、PDF 和 JSON。可以选中同一图稿继续提交新批注，保留前一版与实际模型身份。
4. 作者检查真实预览、图注和印刷尺寸并明确确认后，系统再次校验 Method、原文版本与数据来源；先编译再保存源码 Git 版本。成功后图示批注在图稿记录中归档，失败则仍待处理。

这不是无限制的图像生成器：现阶段是网格矢量模块和正交连线、从原表取数的分组条形图。建议布局由模型选取和放置，不执行模型提供的脚本、SVG、HTML 或任意绘图代码。没有自动声称视觉终检通过。

## 实验图的边界

只解析普通 `tabular` / `tabular*` 的完整数值行。复杂合并表格、原始分布、误差棒、学习曲线或缺失实验，需要作者补充可核对数据，不能由模型猜测。保留行列索引、表格哈希、单位与分组。不把任务数当百分比，也不把不同 backbone 的已发表参考配置和自己的同配置结果放进同一受控比较。

当前可先准备 TSecBench 各维度对比、NYU 相同 backbone 对比、CVE 的 zero-day / one-day 对比草稿；没有重复试验数据，不应画置信区间。效率图还缺明确统计群体等信息，应先解决 Method/结果证据问题。

所有应用都写入本机论文 Git 历史；这与 Overleaf 推送不同，仍需项目已有的显式同步操作。本版不自动开启 Overleaf 推送。

## 部署依赖

Node 沿用应用依赖。PDF 图稿由本机 Python 的 ReportLab 渲染，可用 `FIGURE_PYTHON` 指定解释器；默认寻找 Codex bundled Python，找不到则使用 `python3`。缺依赖即报错，不自动调用收费绘图服务。

接口：`GET /api/projects/:id/figures` 获取盘点、审查门禁和记录；`POST` 同一路径提交 `audit` / `diagram` / `chart` 任务；`/:recordId/preview` 为无主动内容 SVG；`/:recordId/export` 导出 PDF 或 JSON；`POST /:recordId/apply` 为显式的编译与 Git 应用。沿用全站登录保护和项目锁。
