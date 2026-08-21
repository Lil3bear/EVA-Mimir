# 立足点 → RCE 转化检查清单

> 当你已经拿到认证 / 文件读写 / 配置修改能力，但无法执行命令时，按此清单逐条排查。

## 规则 1：Observer 纠偏 = 最高优先级
Observer 明确给出攻击路径（如"立即打 CVE-XXXX SQLi"）时，立即停止当前方向执行，不自行修改。

## 规则 2：同一方向 3 次失败 = 强制换方向
同一类请求（file write、config modify、同 endpoint 同参数）已尝试 3 次且失败，禁止第 4 次。

## 规则 3：已认证 → 优先找已知 CVE
拿到有效 session/token 后，第一件事是查该产品的已知 CVE（`skill_load` 对应 product-playbook 或 `security_search("产品名 CVE RCE")`），不要手动枚举 API 端点。

## 规则 4：配置修改后 → 按顺序尝试所有触发方式
1. 重启端点（注意路径前缀差异，如 `/manager/reboot` vs `/api/manager/reboot`）
2. 配置热加载端点（`/reload`、`/refresh`、`/actuator/refresh`）
3. 发畸形请求触发崩溃自动重启
4. 等 60s 观察配置是否自动生效

## 规则 5：黑名单绕过 → 系统化分类，不逐个试关键字
1. 字符串拼接：`"Ru"+"ntime"`
2. 反射调用：`Class.forName()` + `getMethod().invoke()`
3. 编码绕过：Unicode / Base64
4. 替代 API：`ProcessBuilder` 替代 `Runtime`
5. 每类只试 1 个 payload，不用同类多变体

## 规则 6：Skill 中的攻击链 = 已验证路径
skill 里已有完整攻击链（含 curl 命令）时，直接复制执行，不要从零探测。
