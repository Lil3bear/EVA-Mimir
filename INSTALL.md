# 安装 mimir-pi

## 直接安装（推荐）

下载轻量包：

<https://github.com/Lil3bear/EVA-Mimir/releases/tag/mimir-lite-v0.1.0>

1. 安装并至少打开一次 DeepSeek Harness（模型认证由 DSH 管理）。
2. 解压 `mimir-pi-0.1.0-macos.tar.gz`。
3. 双击 `install.command`。首次被 macOS 拦截时，右键 → 打开。
4. 脚本会把应用复制到 `~/.local/share/mimir-pi/app`，写入 DSH 的 desktop profile，并创建插件软链。
5. 完全退出并重新打开 DeepSeek Harness。
6. 在 DSH 输入 `/mimir`。

安装包已经包含 Web 构建、运行时依赖、写作/审稿/章节/图示 skills 和 DSH 插件；不需要 Node、npm 或 `npm run build`。

## 依赖

- macOS + DeepSeek Harness。
- LaTeX 可选：没有 `pdflatex` 仍可编辑、批注、审稿和翻译；编译 PDF 需要 MacTeX / TeX Live。
- Overleaf 同步需要有效 Git token；token 不要发到聊天里。

## 可选：Gemini 联合修订

安装包本身不包含 Gemini key。要让 DSH 和 Gemini 一起修改：

1. 在 <https://aistudio.google.com/apikey> 建 key。
2. 保存到 `~/.config/autopaperreview/gemini.json`（权限 0600）：

```json
{"apiKey":"...","model":"gemini-3.5-flash"}
```

3. 重启 mimir / DSH。修订会变成三个阶段：DSH 起草 → Gemini 复核 → DSH 终检；仍走提案、定位校验和编译，不会自动应用。
4. 不需要 Gemini 时，移走这个文件并重启，或设置 `MIMIR_GEMINI_COWRITER=0`。

不要把 key 发到聊天、源码或 README。

## 数据位置

```text
~/.local/share/mimir-pi/        论文项目与历史
~/.local/share/mimir-pi/app    轻量版应用
~/.dsh/profiles/desktop        DSH 插件注册
```

卸载：双击 `uninstall.command`，只移除 DSH 插件注册和软链，不删除论文数据。

## 从源码运行

```sh
git clone --branch autoresearch-v0 --single-branch https://github.com/Lil3bear/EVA-Mimir.git
cd EVA-Mimir
npm ci
npm run build
node pi/launch.mjs
```

源码模式默认使用本机 DSH headless 后端，不读取 mimir 自己的 DeepSeek key。模型凭据在 DSH 的 Models 页面配置。

## 故障排查

- `/mimir` 没出现：确认装完后**完全退出** DSH，而不是只关窗口；再检查 `~/.dsh/profiles/desktop/package.json` 是否含 `@local/dsh-mimir`。
- `/mimir` 启动失败：确认应用目录存在，且 `~/.local/share/mimir-pi/app/server/index.mjs` 可读。
- 编译失败：确认 `pdflatex` 在 PATH 中。
- 本地翻译一直准备语言包：打开 `chrome://on-device-translation-internals` 检查英语→简体中文语言包，或改用“快速云翻译”。
