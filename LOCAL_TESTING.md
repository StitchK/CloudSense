# 本机测试 Lambda3（无需打开 CloudShell）

## 1. 不连接 AWS：单元测试

在终端进入仓库 `cloudsense/`（已克隆的 GitHub 仓库可能名为 `CloudSense/`）。首次创建环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

只测试 Lambda3：

```bash
python -m pytest -q tests/test_query.py
```

测试整个项目：

```bash
python -m pytest -q tests
```

这些测试使用模拟的 DynamoDB 和事件，不需要 AWS 账号、凭证、CloudShell 或已部署的服务，也不会发送邮件。
它们验证代码行为，不能证明云端 IAM、API Gateway 与真实数据库连通。
以后打开新终端，只需重新执行 `source .venv/bin/activate` 再运行测试。

## 2. 连接已部署的 AWS：本机直接调用 HTTP API

不需要 AWS CLI、boto3、访问密钥或 CloudShell；需要联网且 Learner Lab 服务当前可用。
当前实验查询 API 未配置登录授权器，因此可直接发送 GET。
从 API Gateway 控制台或 CloudFormation 输出复制 `QueryApiBaseUrl`，不要追加 `/readings`。

在仓库目录执行，把占位符换为实际地址：

```bash
python3 scripts/test_query_api.py \
  --base-url 'https://<api-id>.execute-api.us-east-1.amazonaws.com' \
  --device-id email-critical-001 \
  --from 2026-10-01T00:00:00Z \
  --to 2026-11-07T00:00:00Z
```

脚本仅依赖 Python 标准库，调用 latest、history、alerts 并打印状态、异常参数和是否有下一页。
这是三个接口的首屏连通性测试；完整数据库比对与分页检查使用下一节脚本。
2026-11-06 已在本机实际执行：三个接口均为 HTTP 200，history 与 alerts 各返回 2 条已有记录。
已有样本比较旧，因此指定时间范围；不传 `from/to` 时列表默认最近 24 小时，可能为空。
`is_stale: true` 表示测量时间超过 300 秒，不代表接口失败。

也可以直接在浏览器打开：

```text
https://<api-id>.execute-api.us-east-1.amazonaws.com/devices/email-critical-001/latest
```

或在本机终端运行：

```bash
curl -i 'https://<api-id>.execute-api.us-east-1.amazonaws.com/devices/email-critical-001/latest'
```

## 3. 可选：本机比对真实 DynamoDB 与 API

此脚本会只读访问 CloudFormation、DynamoDB 和 HTTP API；需要 AWS 凭证及对应读取权限。
在虚拟环境中安装 SDK：

```bash
python -m pip install boto3
```

从 AWS Academy Learner Lab 的 **AWS Details** 获取当前临时凭证。
将其中的访问密钥、秘密密钥、会话令牌保存在本机专用 AWS profile 中，区域为 `us-east-1`。
推荐用本机编辑器编辑 `~/.aws/credentials`，新增类似条目；不要将它存入 Git 仓库：

```ini
[cloudsense-lab]
aws_access_key_id = <当前临时 Access Key>
aws_secret_access_key = <当前临时 Secret Key>
aws_session_token = <当前临时 Session Token>
```

在仓库目录执行：

```bash
AWS_PROFILE=cloudsense-lab AWS_DEFAULT_REGION=us-east-1 \
python 'Project Reproduction/04QueryLambda/scripts/verify_live_queries.py'
```

临时凭证到期后需从 Lab 更新；不需要打开 CloudShell，但需要 Lab 会话和有效凭证。
脚本按运行时表内未过期记录计算预期值，逐条验证三个接口、时间边界、分页和错误参数。
本次云端结果为 7 个设备、11 条读数通过；未来数据过期或新增后数量会变化。

## 当前新数据链路的已知状态

2026-11-06 测试时 Lambda2 的 SQS 触发器为 `Disabled`，一条新正常样本已被采集 API 接受，
但尚未写入 DynamoDB。因此用 `query-demo-20261106` 查询最新值会返回 404。
请先用已有设备 `email-critical-001` 验证 Lambda3；恢复 Lambda2 消费后才能验证新数据整条链路。

实现、部署与实际截图见 [复现资料](Project%20Reproduction/04QueryLambda/QueryLambda.md)。
