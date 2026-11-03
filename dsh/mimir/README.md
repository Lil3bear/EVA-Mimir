# @local/dsh-mimir

把 mimir-pi 接进 DeepSeek Harness 的 **host 组合包**。装好后在 DSH 里输入 `/mimir`，它会启动（或复用）本机 mimir-pi 服务并返回地址；在 DSH 右侧栏浏览器打开这个地址，就能一边对话一边看论文修订。

这不是把 Pi 的 extension 硬塞进 DSH。Pi 包（`pi.extensions`）和 DSH 的 profile bundle 是两套扩展模型；这里只保留 mimir-pi 的**独立 Web 服务**，用 DSH 原生的命令 + 侧栏浏览器接入。

## 安装

在 DSH 里用 **设置 → 插件 → 安装本地组合包**，选择这个目录：

```text
/Users/mz/Documents/New project 2/mimir-pi/dsh/mimir
```

或者让 agent 调 `plugin_manager`：

```json
{"action": "install_bundle", "target": "/Users/mz/Documents/New project 2/mimir-pi/dsh/mimir"}
```

安装后如果命令列表没刷新，重启一次 DSH。组合包里没有 npm 依赖、没有构建脚本。

## 自带 skills

组合包的 patch 同时插入一个 `dsh-skill-filesystem` 提供方，扫描两处：

- `dsh/mimir/skills/`：`drawio-figure`、`mimir-guide`；
- `skills/sections/`：8 个章节 skill（`section-abstract` … `section-other`），DSH 的 subagent 可直接加载；
- `skills/`：原有的写作/审稿/图示 skills（`snap-write`、`writing-ai-paper`、`zhihu-*` 等）。

这些技能随组合包一起安装，不需要再往 `~/.dsh/skills` 放文件。

## 使用

```text
/mimir
/mimir https://git.overleaf.com/PROJECT_ID
/mimir https://git@git.overleaf.com/PROJECT_ID
/mimir https://www.overleaf.com/project/PROJECT_ID
```

地址会统一转成 `https://git.overleaf.com/<id>`。**不要把 Git token 放进命令**；token 只在打开后的网页表单里填写。

命令返回类似：

```text
Mimir 已就绪：http://127.0.0.1:59199
在 DSH 右侧栏打开：按 ⌘T 后粘贴地址，或把链接偏好设为「应用内侧边栏」再点链接。
```

- 第一次调用会启动服务，之后复用同一个实例（`~/.local/share/mimir-pi/writer.json`）。
- 服务由插件创建时，插件卸载或 DSH 退出会发 `SIGTERM` 停掉它；如果复用的是别人已启动的实例，不会误杀。
- 数据目录与 LaTeX 环境沿用 mimir-pi 自己的配置，DSH 不复制这些数据。
- 模型调用由**本机 DSH headless 后端**执行，不需要在 mimir 里另配 DeepSeek key；DSH 必须已在 Models 页配置可用模型。每次后端调用都会带一个禁用工具的最小 patch，只返回 JSON。

### 在 DSH 里看页面

DSH Desktop 自带 Sidebar Browser（`⌘T`）。把地址粘进去即可；也可以在聊天里把链接偏好设为「应用内侧边栏」后点链接。

### 画图（draw.io 网页版）

用 `/drawio-figure`（或直接说“画一张架构图”）：技能会写一个 `.drawio` 文件，并在 DSH 侧栏打开 `https://app.diagrams.net/`；在网页里 **File → Open From → Device** 选择该文件，编辑后 **File → Export as → PNG/PDF**。不安装桌面版。

mimir 默认发送 `X-Frame-Options: DENY`：Desktop 的 `<webview>` 通常能加载，Web 版的 iframe 会被拦。Web 版要用侧栏，需要给 mimir 加一个只允许 DSH origin 的 `frame-ancestors` 白名单——默认没有放开，避免削弱本地应用的点击劫持防护。

## 配置

`cordis.patch.yml` 已经把 `packageDir` 指向本机 checkout：

```yaml
- id: dsh-mimir
  name: '@local/dsh-mimir'
  config:
    packageDir: /Users/mz/Documents/New project 2/mimir-pi
```

移动仓库后改这一行即可。不写 `packageDir` 时，插件会从 `dsh/mimir` 的上两级推断。

## 卸载

在 DSH 插件页停用/移除组合包即可。已启动的 mimir 服务会随插件释放停止；如果要手动清理：

```bash
rm -f ~/.local/share/mimir-pi/writer.json
```

## 开发校验

```bash
node --check dsh/mimir/index.js
```

组合包清单与 patch 的最小结构：

```text
package.json      dsh.bundle.patch + 导出的 locale/icon
cordis.patch.yml  insert 一条 host 插件行
index.js          apply(ctx)：注册 /mimir 命令，管理服务生命周期
locale/*.json     meta.title / meta.description
icon.svg          插件页图标
```

在一个临时 profile 里用 `dsh --profile <name> --dump-config` 可以看到 `- id: dsh-mimir` 出现在组合结果末尾；真正加载需要安装到当前 profile。
