# CloudSense 实验与评估

GitHub 同步仅包含工具源码、测试和说明。AWS 原始日志、配置快照、账单、实验结果及截图保留在本地，不随代码上传；下文的历史实测文件路径指本地材料。缺少这些材料时，历史账单核对测试会跳过；重新运行实验可生成新的结果。

## 直接运行低负载测试

在 VS Code 打开 **evaluation/run_low_load.py**，点击右上角 **Run Code**。

需要 Python 3.9 或以上；低负载脚本只用标准库，无须安装 boto3，也不需要 AWS 密钥。脚本会读取现有 `simulator/simulator.local.json` 中的 API 地址，自动打开实时图表。

默认每秒 1 条、持续 120 秒、10 个虚拟设备，共 120 条正常模拟数据。每次运行使用新的设备和数据 ID。测试结束会继续显示结果；在运行它的终端按 **Ctrl+C** 关闭。再次测试前先停止上一次运行，避免叠加流量。AWS Lab 必须处于运行状态，主 SQS 触发器必须 Enabled。

结果保存在 `evaluation/results/<run_id>/`：

- `summary.json`：条件、计数、分位数、时间序列和逐条结果。
- `requests.csv`：逐条请求和完成记录，可在 Excel 打开。
- `dashboard.html`：自包含离线图表，双击即可再次查看。

命令行可选：

```sh
python3 evaluation/run_low_load.py --rate 2 --duration 60
```

脚本限制每秒最多 5 条、最长 300 秒、最多 1500 条。它只发送正常数据，不运行故障实验。HTTP 202 表示 API 接收；只有查询返回 COMPLETE/LATE 才算最终处理，且出现 LATE 时不通过默认实验。没有完成时间的数据不会伪造延迟。当前低负载脚本不是高并发压力测试工具。

API 延迟包含客户端网络；后端延迟由 AWS 的接收时间和保存完成时间计算；观测延迟包含轮询、查询与索引可见性，只能作为上界。历史查询也产生 API、Lambda 和数据库用量。

## CloudShell 工具

以下操作仅在已登录的 AWS CloudShell 中执行，使用现有临时角色。不要把 AWS 密钥写入代码。

```sh
python3 evaluation/build_lab_bundle.py
```

将生成的 `lab_bundle.zip` 通过 CloudShell Actions → Upload file 上传，解压后运行：

```sh
unzip lab_bundle.zip
python3 evaluation/cloud_lab.py snapshot
python3 evaluation/cloud_lab.py deploy
python3 evaluation/cloud_lab.py faults
python3 evaluation/cloud_lab.py collect --start 2026-11-09T12:03:00Z --end 2026-11-09T12:18:00Z
python3 evaluation/collect_usage_details.py
python3 evaluation/cloud_lab.py pricing
python3 evaluation/cloud_lab.py billing
python3 evaluation/cloud_lab.py bundle
```

重新上传同名文件会被 CloudShell 拒绝；先将旧上传包改名保留，再上传新包。`deploy` 更新三个现有 Lambda 的代码，并备份原始 ZIP 至 CloudShell `evaluation/backups/`；如果主队列触发器 Disabled，会恢复它。保留原有 IAM、函数配置及订阅。

`faults` 会创建专用 SQS、DLQ、处理 Lambda 和没有订阅的 SNS topic，使用原有 LabRole，并把带 `fault-` 前缀的模拟记录写入现有表。测试暂停消费、恢复、重复数据、失败重试、DLQ 和修复重放；不会清空主队列。测试结束后关闭专用触发器，保留资源与证据。实验队列设置为 60 秒可见性和 3 次接收，主队列仍为 360 秒和 5 次，因此报告不能把测试恢复时间当作主队列 SLA。

`collect` 导出按分钟汇总的共享资源指标与测试日志；缺失指标不是零，不能直接声称没有错误。`billing` 的账单是账号范围且可能延迟；`pricing` 保存 AWS 官方公开价格。估算不扣免费额度、Lab 学分或折扣，并与实验测量分开说明。

第四步现已补做当前权限内的安全评估。在 CloudShell 运行 `python3 evaluation/collect_security.py`，再下载 `cloud_evidence/security.json`；本地运行 `review_security.py` 汇总配置和源码检查。它仅检查配置，并发送少量无效请求及一条正常模拟读数，不改变 IAM、API 认证、资源策略或加密配置。

已确认 10 项输入检查返回预期的 400/413/415；HTTPS、查询 no-store、CORS 和主队列/DLQ 的 SQS 托管加密有证据。发现匿名 API 可写可读、三个函数共用 LabRole、SNS 未配置 KMS、日志永久保留。三份 Lab 托管策略因 AccessDenied 未核实，不绕过权限限制。检查完成不代表这些缺口已经修复，也不构成医疗数据合规认证。

## 查看本次实测与重新计算成本

三轮实验均已实际连接 AWS Lab：每轮 120 条，合计 360 条全部完成。第二轮由 VS Code 的 Run Code 启动。前两轮为 1 条/秒、120 秒，第三轮为 2 条/秒、60 秒；这仍是低负载对比，不能证明高负载扩展能力。原始结果在 `results/`，云端日志、指标、故障时间线、价格和总账在 `cloud_evidence/`。

直接运行 `calculate_costs.py` 可从已保存的证据重新生成 `costs/costs.json`、`costs.csv` 和 `costs.html`；双击 HTML 查看。脚本不连接 AWS、不产生流量。该模型小计约 **USD 0.013672**，包含所选窗口的共享资源用量和 SQS 请求模型，不是精确实验账单；详细排除项见 HTML。账号月初至今的延迟账单约 USD 0.884950，范围不同。

100 台设备、每分钟一条、30 天的示例为 4,320,000 条。按本次混合实验成本线性外推约 USD 164.07；它保留了实验的轮询、故障和闲置开销，不能直接作为生产报价。实际部署需独立估计查询频率、告警率、存储保留、流量和免费额度。

本次没有做完整安全审计、容量上限测试、跨区域故障或邮件实际投递验证。新增安全探测在原成本窗口之后，未纳入旧成本小计。
