---
name: drawio-figure
description: 用 draw.io 网页版生成可编辑论文示意图（.drawio），不安装桌面应用；适合方法框架、流程图、对比图。
whenToUse: 用户要求画论文示意图、架构图、流程图，或要求把已有图改成 draw.io 可编辑文件时。
---

# Draw.io 网页版论文示意图

用 mxGraph XML 生成 `.drawio` 文件，在 DSH 的侧栏浏览器里打开 draw.io 网页版编辑和导出。**不要安装 draw.io 桌面版**，也不要调用图像生成模型。

## 1. 写 .drawio

在目标目录创建 `figure.drawio`，使用**未压缩**的 mxGraph XML：

```xml
<mxfile host="mimir-pi" agent="mimir-pi" version="24.7.17" type="device">
  <diagram id="figure" name="Figure">
    <mxGraphModel dx="1200" dy="600" grid="0" page="1" pageWidth="1200" pageHeight="600" math="0" shadow="0">
      <root>
        <mxCell id="0"/><mxCell id="1" parent="0"/>
        <mxCell id="n1" value="Input" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#eaf4ef;strokeColor=#237253;fontSize=20;" vertex="1" parent="1">
          <mxGeometry x="60" y="220" width="220" height="90" as="geometry"/>
        </mxCell>
        <mxCell id="n2" value="Method" style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f6e9e2;strokeColor=#b97487;fontSize=20;" vertex="1" parent="1">
          <mxGeometry x="420" y="220" width="220" height="90" as="geometry"/>
        </mxCell>
        <mxCell id="e1" value="process" style="endArrow=block;html=1;rounded=0;strokeColor=#64757e;strokeWidth=2;fontSize=16;" edge="1" parent="1">
          <mxGeometry relative="1" as="geometry">
            <mxPoint x="280" y="265" as="sourcePoint"/>
            <mxPoint x="420" y="265" as="targetPoint"/>
          </mxGeometry>
        </mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

规则：

- 节点用 `rounded=1`，颜色只用少量语义色：动机/问题 `#b97487`，方法/创新 `#237253`，证据/结果 `#d4a648`，背景 `#f7f8fa`。
- 连线用 `endArrow=block`，标签必须有意义（“feeds”“evaluates”“fails when”），不要写装饰词。
- 文字用英文短标签；图注另外写。
- 不要编造模块、箭头或数据；图必须能对应论文原文。
- 页面尺寸按图内容设置。

## 2. 在 DSH 里打开网页版

用 `open` 打开 draw.io 网页版，或让用户在 DSH 右侧栏按 `⌘T` 后输入：

```text
https://app.diagrams.net/
```

然后：

1. **File → Open From → Device…** 选择 `figure.drawio`（或拖进窗口）。
2. 修改布局、文字、颜色。
3. **File → Export as → PNG / PDF** 导出；PNG 建议 2x 缩放。

不需要登录，不上传论文正文；只把这张图的数据带进 draw.io。

## 3. 检查

- 导出的 PNG 用 `read_image` 打开，检查文字溢出、箭头穿节点、空白过大。
- 需要改时改 `.drawio` 再导出，不要直接改 PNG。
- 报告 `.drawio`、`.png`、`.pdf` 路径，以及图的证据来源（对应论文哪一节/哪张表）。

## 边界

- draw.io 只负责布局和导出；科学内容、数字和箭头关系必须来自论文或用户确认。
- 不把整篇论文或未公开数据粘贴到在线版；只带当前这一张图。
- 不要建议安装 draw.io 桌面版；网页版足够。
