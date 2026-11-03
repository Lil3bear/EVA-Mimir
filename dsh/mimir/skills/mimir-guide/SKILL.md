---
name: mimir-guide
description: 启动或打开本机 mimir-pi 论文写作工作区（独立 Web 应用），查看某一轮修订的对话与轨迹，或带 Overleaf Git 地址导入。
whenToUse: 用户要求打开 mimir-pi / 论文写作工作台 / Overleaf 修订工作区，或查看论文修订的对话与轨迹时。
user-invocable: false
---

# Mimir 论文工作区

mimir-pi 是独立的本地 Web 应用（Express + React），不是 DSH 的内嵌视图。启动后在本机浏览器打开，数据目录是 `~/.local/share/mimir-pi`。

项目路径固定为：

```text
/Users/mz/Documents/New project 2/mimir-pi
```

## 打开工作区

1. 先看 `~/.local/share/mimir-pi/writer.json`。如果存在，取其中的 `url` 请求 `GET <url>/api/health`；返回 200 且 `mimirInstance` 与记录一致时直接复用，跳到第 4 步。
2. 否则用托管后台任务启动（不要用 `npm run dev`，它不带 Pi 会话目录和 DeepSeek 配置）：

   ```bash
   cd "/Users/mz/Documents/New project 2/mimir-pi" && node pi/launch.mjs
   ```

3. 读取该任务输出中的第一行 `http://127.0.0.1:<port>`，轮询 `GET <url>/api/health` 直到 200。启动失败时原样报告错误：缺少 DeepSeek 凭据会明确提示，不要切换到其他 provider。
4. 在 macOS 上执行 `open "<url>"`，并把 URL 告诉用户。

同一个数据目录只允许一个写入者：如果已有实例在跑，直接复用它的 URL，不要重复启动。

## 可选：带 Overleaf Git 地址

用户给出 `https://git.overleaf.com/<project-id>` 时，在打开前拼成：

```text
<url>/?overleaf=<urlencoded 地址>
```

Overleaf token 只能由用户在网页表单里输入。不要把它写进命令、日志、文件或对话。

## 查看修订轨迹（不打开浏览器也可以）

服务运行时：

```bash
curl -s "<url>/api/projects"
curl -s "<url>/api/projects/<id>/traces/main"
```

- `turns[]`：每轮的指令、批注、状态、模型、token、补丁、版本。
- `events[]`：`turn/start`、`comment/attach`、`tool/result`、`assistant/message`、`patch/proposed`、`revision/created`、`overleaf/flush` 等。
- `remote[]`：Overleaf 远端版本，作者是「该版本最后编辑者」，标注 `version-author`，不是逐次编辑。

汇报时区分事实与推断：远端只能证明「哪个版本、哪些文件、最后谁改的」，不能证明逐次顺序或修改理由。

## 边界

- 不要修改 `~/.config/autopaperreview`、`~/.local/share/mimir-pi` 里的论文、凭据或 Pi 会话；只读查询 API 除外。
- 不要执行 `npm run build` 来“修复”运行中的服务；需要时先说明。
- 402 / 401 分别报告余额与凭据问题，不静默换模型。
- 不要把 mimir 说成 DSH 原生插件；它只是被 DSH 启动的本地服务。
