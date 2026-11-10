"""Build the Chinese evaluation report from saved evidence and real screenshots."""

import json
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
IMAGES = ROOT / "improve_img"


def main():
    costs = json.loads((HERE / "costs/costs.json").read_text())
    faults = json.loads((HERE / "cloud_evidence/faults.json").read_text())
    runs = [json.loads((HERE / "results" / run_id / "summary.json").read_text()) for run_id in costs["run_ids"]]
    output = HERE / "report"
    output.mkdir(exist_ok=True)
    Image.open(IMAGES / "02_low_load/03_run_code_complete.jpg").crop((0, 0, 1470, 865)).save(IMAGES / "02_low_load/05_summary_crop.jpg", quality=95)
    Image.open(IMAGES / "03_recovery/03_clean_recovery_summary.jpg").crop((0, 0, 1470, 355)).save(IMAGES / "03_recovery/04_summary_crop.jpg", quality=95)
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.27), Inches(11.69)
    section.top_margin = section.bottom_margin = Inches(0.65)
    section.left_margin = section.right_margin = Inches(0.7)
    section.header_distance = section.footer_distance = Inches(0.25)
    for name in ["Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Caption"]:
        style = doc.styles[name]
        style.font.name = "Arial Unicode MS"
        style.font.color.rgb = RGBColor(0, 0, 0)
        fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        for attribute in ["ascii", "hAnsi", "eastAsia", "cs"]:
            fonts.set(qn("w:" + attribute), "Arial Unicode MS")
        for attribute in ["asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"]:
            fonts.attrib.pop(qn("w:" + attribute), None)
        style.font.size = Pt(10.5 if name == "Normal" else 9 if name == "Caption" else 24 if name == "Title" else 16 if name == "Heading 1" else 12)
        style.paragraph_format.space_after = Pt(7)
        style.paragraph_format.line_spacing = 1.15
    doc.styles["Normal"].paragraph_format.widow_control = True
    doc.styles["Heading 1"].paragraph_format.space_before = Pt(8)
    doc.styles["Heading 1"].paragraph_format.space_after = Pt(6)
    header = section.header.paragraphs[0]
    header.text = "CloudSense  |  CDS538 Cloud Computing  |  实验评估"
    header.runs[0].font.size = Pt(8)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run("2026年11月9日  ·  ").font.size = Pt(8)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)

    def paragraph(text, style=None):
        return doc.add_paragraph(text, style)

    def heading(text):
        doc.add_heading(text, level=1)

    def page(text):
        doc.add_page_break()
        heading(text)

    def table(headers, rows):
        result = doc.add_table(rows=1, cols=len(headers))
        result.style = "Table Grid"
        result.autofit = True
        for cell, text in zip(result.rows[0].cells, headers):
            cell.text = str(text)
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), "E8EEF3")
            cell._tc.get_or_add_tcPr().append(shade)
            for run in cell.paragraphs[0].runs:
                run.bold = True
        repeat = OxmlElement("w:tblHeader")
        result.rows[0]._tr.get_or_add_trPr().append(repeat)
        for values in rows:
            for cell, text in zip(result.add_row().cells, values):
                cell.text = str(text)
        for row in result.rows:
            prevent = OxmlElement("w:cantSplit")
            row._tr.get_or_add_trPr().append(prevent)
            for cell in row.cells:
                for para in cell.paragraphs:
                    para.paragraph_format.space_after = Pt(4)
                    para.paragraph_format.space_before = Pt(3)
                    for run in para.runs:
                        run.font.size = Pt(9)
        paragraph("").paragraph_format.space_after = Pt(0)

    def picture(relative, caption, width=6.85):
        doc.add_picture(str(IMAGES / relative), width=Inches(width))
        paragraph(caption, "Caption")

    paragraph("CloudSense 实验评估报告", "Title")
    paragraph("日志与结果记录  低负载性能  受控失败与恢复  用量成本", "Subtitle")
    paragraph("本报告记录 CloudSense 在 AWS Academy Learner Lab 的真实实验，用于补充 L2 小组项目要求中的评估和演示证据。三轮低负载实验共发送 360 条正常模拟数据，360 条均被接收并最终处理完成；专用故障环境通过暂停恢复、重复数据、重试进入 DLQ 和修复重放检查。成本按保存的用量与 AWS 公开价格计算。")
    paragraph("本次完成约定的第 1、2、3、5 步。第 4 步安全评估按要求延期；这份报告是项目评估的补充材料，不能代表 L2 全部提交要求已经满足。")
    table(["L2 相关要求", "本次结果", "证据边界"], [
        ("性能与监控", "三轮通过，360/360 完成", "1/s 与 2/s，仅验证低负载"),
        ("弹性与恢复", "6 项故障检查通过，恢复 8.77 秒", "专用实验配置，不是主系统 SLA"),
        ("日志与演示", "数据 ID 可串联，VS Code Run Code 已实跑", "截图与原始 JSON/CSV 均保存"),
        ("成本", f'模型小计 USD {costs["estimated_modeled_subtotal_usd"]:.6f}', "共享窗口及部分请求估算，不是完整账单"),
        ("安全与扩展能力", "安全延期；高负载容量未测", "仍需后续补充"),
    ])
    heading("环境与范围")
    paragraph("区域 us-east-1；运行环境 Python 3.13。三个现有 Lambda 分别为接收 128 MB / 10 秒、处理 256 MB / 60 秒、查询 128 MB / 10 秒。主 SQS 触发器 Enabled，批大小 10，并启用 ReportBatchItemFailures。数据均为合成模拟读数。")
    paragraph("实验日期为 2026年11月9日。正文时间采用 UTC；香港时间为 UTC 加 8 小时。日志导出窗口为 12:03–12:18；分钟指标按工具对齐为 12:03–12:19。指标延迟后重新采集，API 请求数与脚本记录已经对齐。")
    paragraph("依据 L2 第 5 页的五项评估维度、第 10 页的监控与证据要求、第 11 页的成功流程和受控失败演示要求。架构替代方案、组员分工、展示及互评仍属于完整课程交付范围。")

    page("1 日志与结果记录")
    paragraph("后端新增统一 JSON 事件日志。接收、入队、处理开始、处理完成、处理失败和查询都能追踪。每次测试有独立 run_id，reading_id 与 device_id 带运行前缀，便于与日常数据区分；关键事件还带毫秒时间、耗时、请求 ID 或 SQS 消息 ID。接收日志不再打印完整模拟健康读数。")
    table(["要回答的问题", "记录或文件"], [
        ("API 接收是否等于成功", "分别保存 sent、accepted、completed、late、pending"),
        ("这一条为什么失败", "reading_id 对应 processing_failed 与 error_type"),
        ("每轮条件和结果", "results/<run_id>/summary.json 与 requests.csv"),
        ("AWS 原始证据", "cloud_evidence/logs.json、metrics.json、faults.json"),
    ])
    picture("01_logging/02_unobstructed_trace.jpg", "图 1 真实 CloudShell 导出的 CloudWatch 链路日志与失败重试记录")
    paragraph("示例 reading_id 为 eval-20261109T121201-9c9e57-00000。导出日志依次包含 reading_received、reading_enqueued、processing_started、processing_completed，最终为 COMPLETE。故障读数的日志另有三次 KeyError 和两次 DUPLICATE_SKIPPED，可分别支持重试与去重结论。")
    paragraph("主要代码位于 src/common/observability.py 及接收、处理、查询函数。完成时写入 completed_at_ms；查询接口返回该字段，测试脚本才有条件计算后端完成延迟。没有该时间戳的记录保持未知，不补造数字。")
    paragraph("注意：Lambda 的 Errors 指标为零，并不等于每条 SQS 消息都没有处理失败。部分批处理失败通过响应内容交回重试，必须结合 processing_failed 日志与 DLQ 结果判断。")

    page("2 低负载性能结果")
    paragraph("Python 脚本通过真实 HTTP API 发送正常读数，再通过设备历史接口查询终态。每轮 10 台虚拟设备、120 条数据，使用独立 ID。默认通过条件为计划数、发送数、202 接收数与最终完成数一致，且没有 LATE。")
    table(["实验 UTC 开始", "输入条件", "接收与完成", "API P95 ms", "后端 P95 ms"], [
        (run["started_at"][11:19], f'{run["target_rate"]:g}/s × {run["target_duration_seconds"]}s', f'{run["accepted"]}/{run["completed"]}', f'{run["api_p95_ms"]:.1f}', f'{run["backend_p95_ms"]:.1f}') for run in runs
    ])
    picture("02_low_load/05_summary_crop.jpg", "图 2 由 VS Code Run Code 启动的第二轮完成画面  原始截图上部裁切")
    paragraph("三轮均为 PASS，未完成、拒绝或未知、LATE 均为 0。第二轮实际发送率 1.001/s，API P95 约 1208 ms、后端 P95 约 664 ms。第三轮 2/s 仍全部完成，但样本量和负载均较小，不能据此宣称生产扩展能力。")
    paragraph("API 延迟包含本机网络；后端延迟等于 AWS 保存完成时间减接收时间。图中约 23 秒的首次观测延迟还包含逐设备轮询、网络和索引可见性，不能当作实际后端处理耗时。首轮尾延迟较高，但本实验没有隔离并验证具体原因。")

    page("3 如何再次运行")
    paragraph("在 VS Code 打开 evaluation/run_low_load.py，点击右上角 Run Code。脚本使用现有 simulator/simulator.local.json 中的 API 地址，无须 AWS 密钥和第三方 Python 库；需要 Python 3.9 或以上。默认每秒 1 条、持续 120 秒，浏览器自动显示实时曲线。")
    picture("02_low_load/04_vscode_run_code.jpg", "图 3 实际 VS Code Run Code 与终端 PASS 结果")
    paragraph("运行前启动 AWS Lab，并确认主 SQS 触发器 Enabled。完成后在终端按 Ctrl+C 关闭查看器，再启动下一次测试，避免叠加流量。点击 Run Code 只执行正常低负载流程；故障实验是 CloudShell 中独立的命令。")
    table(["操作", "入口或结果"], [
        ("默认低负载", "evaluation/run_low_load.py 右上角 Run Code"),
        ("调整低负载", "python3 evaluation/run_low_load.py --rate 2 --duration 60"),
        ("查看归档", "results/<run_id>/dashboard.html 双击打开"),
        ("重新算已保存用量", "evaluation/calculate_costs.py 不连接 AWS"),
    ])
    paragraph("脚本最多允许 5 条/秒、300 秒、1500 条；这些限制用于控制实验规模。端点读取失败、查询不完整或超时不会被当成成功。第二轮 run_id 为 eval-20261109T121201-9c9e57，运行证据与本页终端一致。")

    page("4 受控失败与恢复")
    paragraph(f'实验 {faults["run_id"]} 创建了专用 SQS、DLQ、处理 Lambda 和无订阅 SNS topic；使用现有处理代码与 LabRole，在现有表中仅写带 fault 前缀的模拟记录。主队列未清空。')
    table(["场景", "实际结果"], [
        ("缺字段请求", "API 返回 400，表中未写入该记录"),
        ("暂停消费者", "发送 5 条，队列保留 5 条，表中均未完成"),
        ("恢复消费者", "5 条全部 COMPLETE，从恢复操作到观测完成为 8.77 秒"),
        ("重复发送", "同一 ID 重放两次，原记录不变，日志两次 DUPLICATE_SKIPPED"),
        ("毒消息重试", "绕过 API 直接向专用 SQS 注入缺 timestamp 消息，三次 KeyError 后进 DLQ"),
        ("修复与重放", "同一 reading_id 补全字段后重放，最终 COMPLETE"),
    ])
    picture("03_recovery/04_summary_crop.jpg", "图 4 真实 CloudShell 故障结果与恢复时间线  原始截图上部裁切")
    paragraph("故障数据从 12:05:14 注入到 12:08:14 被 DLQ 观察到，约 180 秒。修复后于 12:08:16 观察到 COMPLETE。修复是在测试脚本中补全后重新入队，不代表系统能自动修复任意坏数据。")
    paragraph("专用队列可见性 60 秒、最大接收 3 次，专用 Lambda 超时 10 秒；主队列为 360 秒和 5 次，主处理函数超时 60 秒。因此 8.77 秒恢复和约 180 秒 DLQ 时间仅属于本实验。结束后专用触发器 Disabled，测试资源保留便于复核；主流程保持可用。")

    page("5 用量与成本计算")
    paragraph(f'采用 AWS 官方 us-east-1 价格表，读取时间为 {costs["price_retrieved_at"]}。所有金额为美元，未扣免费额度、Lab 学分或折扣。成本模型小计为 USD {costs["estimated_modeled_subtotal_usd"]:.8f}；它不是 AWS 单独开具的实验账单。')
    table(["项目", "用量", "公开单价", "估算 USD"], [
        ("Lambda 请求", "900 次 REPORT", "0.20 / 百万次", "0.00018000"),
        ("Lambda 计算", "74.749 GB 秒", "0.0000166667 / GB 秒", "0.00124582"),
        ("HTTP API", "532 次", "1.00 / 百万次", "0.00053200"),
        ("DynamoDB 写", "16,470 单位", "0.625 / 百万单位", "0.01029375"),
        ("DynamoDB 读", "3,545.5 单位", "0.125 / 百万单位", "0.00044319"),
        ("CloudWatch 日志", "680,856 Bytes", "0.50 / GB", "0.00031705"),
        ("主 SQS 模型", "1,651 次模型请求", "0.40 / 百万次", "0.00066040"),
    ])
    paragraph("Lambda 使用每条 REPORT 的 Billed Duration × 内存 GB，包含专用故障函数。API 532 次等于 360 条正常发送 + 171 次历史查询 + 1 次无效输入，已与 CloudWatch 对齐。DynamoDB 为按需计费，合计基础表与 GSI 的消费量，覆盖同一共享时间窗口。")
    paragraph("主 SQS 模型为 360 发送 + 360 接收 + 360 删除 + 571 空接收。SQS 按 API 请求和载荷分块计费，批处理会使消息计数与计费请求不同；该项明确为估算，不冒充精确计费量。")
    picture("05_cost/04_unobstructed_usage.jpg", "图 5 AWS CloudShell 的日志用量 按需表模式 价格来源和账号总账")

    page("6 成本边界与月度示例")
    picture("05_cost/01_usage_cost_model.jpg", "图 6 浏览器展示由已保存 AWS 证据计算的成本明细", width=6.1)
    paragraph(f'若假设 100 台设备、每分钟一条、连续 30 天，则为 4,320,000 条。按本次混合实验小计除以 360 后线性外推约 USD {costs["scenario"]["modeled_subtotal_usd"]:.2f}。此示例保留实验中的轮询密度、故障和空轮询开销，不代表生产报价，也不证明该流量容量。')
    paragraph("模型未包括专用故障队列全部 API 调用、SNS、网络传输、S3 前端、EC2/VPC/CloudShell 环境及取指标产生的费用。数据存储需要保留字节时长；当前表快照不能代表实验新增量，因此未加进小计。公开参考价为 DynamoDB 0.25/GB 月、日志 0.03/GB 月。")
    paragraph(f'账号月初至今的延迟账单为 USD {costs["account_month_to_date_usd"]:.10f}，包含其他资源，与上述实验模型范围不同。本轮采用正常读数，没有验证 SNS 邮件投递或估计实际告警邮件用量。')

    page("7 证据索引与后续工作")
    closing_start = len(doc.paragraphs)
    table(["位置", "内容与用途"], [
        ("evaluation/results/", "三轮 summary.json、requests.csv、离线 dashboard.html"),
        ("evaluation/cloud_evidence/", "部署快照、故障结果、日志、指标、用量、价格和总账"),
        ("evaluation/costs/", "可复算成本 JSON、CSV、HTML，含价格 SKU 与来源 URL"),
        ("improve_img/01_logging/", "CloudWatch 链路与重试截图"),
        ("improve_img/02_low_load/", "运行中、完成、Run Code 与图表裁切截图"),
        ("improve_img/03_recovery/", "故障过程、PASS 和恢复时间线截图"),
        ("improve_img/05_cost/", "计算明细与 AWS 价格用量截图"),
    ])
    heading("尚未证明的内容")
    paragraph("安全检查延期，尚未完成 IAM 最小权限、认证授权、资源策略、传输与存储保护以及敏感日志的系统评估。缺字段 400 只证明这一输入验证行为，不能替代安全评估。")
    paragraph("1/s 和 2/s 的低负载对比不能证明自动扩展、容量上限或突发承载能力。后续应在 Lab 额度与并发限制内逐档增加负载，观察完成率、尾延迟、队列积压和节流，并在相同条件下重复实验。跨可用区、跨区域恢复和长时间运行也未验证。")
    paragraph("故障实验使用专用资源及缩短配置；没有证明主系统灾难恢复目标。SNS publish 成功也不等于邮件真正投递。本次成本是有排除项的模型小计，仍需要生产查询率、告警率、保留周期和网络用量才能形成完整预算。")
    heading("复现与验证")
    paragraph("正常测试在 VS Code Run Code 执行。CloudShell 的打包、部署、故障、采集及下载步骤见 evaluation/README.md。重新计算成本运行 calculate_costs.py。报告由 build_report.py 根据原始证据与截图构建，不通过截图识别编造数值。")
    paragraph("本地验证结果为 91 passed 与 4 subtests passed，覆盖业务逻辑、分页、接收与完成区分、结构化日志、完成时间和计量对账。图片来自实际浏览器或 VS Code；图 2 与图 4 裁取所需内容，完整原图保留。")
    heading("参考依据")
    paragraph("L2 Cloud Architectures and Core Services，第 5、10、11 页。AWS 官方区域 Price List JSON，精确 URL、SKU、阶梯起点、发布日期保存在 cloud_evidence/pricing.json 与 costs/costs.json。报告仅对约定实验给出结论，不替代完整课程报告及最终评分。")
    for para in doc.paragraphs[closing_start:]:
        if para.style.name == "Normal":
            para.paragraph_format.line_spacing = 1.05
            para.paragraph_format.space_after = Pt(5)
            for run in para.runs:
                run.font.size = Pt(9.5)
    path = output / "CloudSense_Evaluation_Report.docx"
    for border in list(doc.styles.element.xpath(".//w:pBdr")) + list(doc.element.xpath(".//w:pBdr")):
        border.getparent().remove(border)
    doc.save(path)
    print(path)


if __name__ == "__main__":
    main()
