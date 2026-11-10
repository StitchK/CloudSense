"""Build the group report with a bounded main text and real evidence appendices."""

import json
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT.parent / "report" / "group11_report.docx"
IMG = ROOT / "improve_img"


def main():
    cost = json.loads((HERE / "costs/costs.json").read_text())
    runs = [json.loads((HERE / "results" / name / "summary.json").read_text()) for name in cost["run_ids"]]
    security = json.loads((HERE / "cloud_evidence/security.json").read_text())
    review = json.loads((HERE / "cloud_evidence/security_review.json").read_text())
    assets = HERE / "report_assets"
    assets.mkdir(exist_ok=True)
    canvas = Image.new("RGB", (1600, 650), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 27)
    small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 22)

    def box(rect, text):
        draw.rounded_rectangle(rect, radius=10, fill="#edf2f5", outline="#6b7783", width=2)
        bounds = draw.multiline_textbbox((0, 0), text, font=font, align="center", spacing=7)
        draw.multiline_text(((rect[0] + rect[2] - bounds[2]) / 2, (rect[1] + rect[3] - bounds[3]) / 2), text, font=font, fill="#111111", align="center", spacing=7)

    def arrow(start, end):
        draw.line([start, end], fill="#34495e", width=4)
        if end[0] > start[0]:
            points = [end, (end[0] - 12, end[1] - 7), (end[0] - 12, end[1] + 7)]
        elif end[0] < start[0]:
            points = [end, (end[0] + 12, end[1] - 7), (end[0] + 12, end[1] + 7)]
        else:
            points = [end, (end[0] - 7, end[1] - 12), (end[0] + 7, end[1] - 12)]
        draw.polygon(points, fill="#34495e")

    for rect, text in [((20, 65, 235, 170), "Python\nsimulator"), ((295, 65, 520, 170), "API Gateway\nPOST /readings"), ((580, 65, 800, 170), "Lambda 1\nValidate input"), ((860, 65, 1060, 170), "SQS\nBuffer and retry"), ((1130, 65, 1570, 170), "Lambda 2\nClassify and process"), ((1130, 270, 1570, 375), "DynamoDB\nReadings and alert state"), ((640, 270, 980, 375), "SNS\nEmail subscription"), ((1130, 470, 1570, 575), "Lambda 3\nQuery stored results"), ((600, 470, 980, 575), "API Gateway\nGET latest history alerts"), ((20, 470, 440, 575), "React dashboard\nPoll and display")]:
        box(rect, text)
    for start, end in [((235,117),(295,117)),((520,117),(580,117)),((800,117),(860,117)),((1060,117),(1130,117)),((1350,170),(1350,270)),((1350,375),(1350,470)),((1130,522),(980,522)),((600,522),(440,522))]:
        arrow(start, end)
    draw.line([(1200,170),(1200,220),(810,220)], fill="#34495e", width=4)
    arrow((810,220),(810,270))
    draw.text((30, 245), "SQS retries failed processing.", font=small, fill="#333333")
    draw.text((30, 280), "CloudWatch logs all three Lambda stages.", font=small, fill="#333333")
    draw.text((30, 315), "The browser initiates GET requests.", font=small, fill="#333333")
    draw.text((640, 395), "Notify when alert rules permit", font=small, fill="#333333")
    diagram = assets / "architecture.png"
    canvas.save(diagram)
    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Inches(8.27), Inches(11.69)
    sec.top_margin = sec.bottom_margin = Inches(.68)
    sec.left_margin = sec.right_margin = Inches(.72)
    for name in ["Normal", "Title", "Subtitle", "Heading 1", "Heading 2", "Caption"]:
        style = doc.styles[name]
        style.font.name = "Arial"
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.font.size = Pt({"Normal":10.5,"Title":25,"Subtitle":12,"Heading 1":16,"Heading 2":11.5,"Caption":8.5}[name])
        style.paragraph_format.line_spacing = 1.12
        style.paragraph_format.space_after = Pt(7)
        style.paragraph_format.space_before = Pt(0)
    doc.styles["Heading 2"].paragraph_format.space_before = Pt(7)
    header = sec.header.paragraphs[0]
    header.text = "CDS538 Cloud Computing  |  Group 11  |  CloudSense"
    header.runs[0].font.size = Pt(8)
    footer = sec.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run("9 November 2026   |   ").font.size = Pt(8)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    paragraphs_by_page = []

    def p(text, style=None):
        return doc.add_paragraph(text, style)

    def h(text):
        return doc.add_heading(text, 2)

    def page(title, first=False):
        if not first:
            doc.add_page_break()
        doc.add_heading(title, 1)
        paragraphs_by_page.append(title)

    def table(headers, rows, widths=None):
        tab = doc.add_table(rows=1, cols=len(headers))
        tab.autofit = False
        if widths:
            for column, width in zip(tab.columns, widths):
                column.width = Inches(width)
        props = tab._tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for side in ["top", "left", "bottom", "right", "insideH", "insideV"]:
            edge = OxmlElement("w:" + side)
            for key, value in [("val", "single"), ("sz", "5"), ("color", "D9D9D9")]:
                edge.set(qn("w:" + key), value)
            borders.append(edge)
        props.append(borders)
        for cell, text in zip(tab.rows[0].cells, headers):
            cell.text = text
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), "E8EEF3")
            cell._tc.get_or_add_tcPr().append(shade)
            for run in cell.paragraphs[0].runs:
                run.bold = True
        repeat = OxmlElement("w:tblHeader")
        tab.rows[0]._tr.get_or_add_trPr().append(repeat)
        for row in rows:
            for cell, value in zip(tab.add_row().cells, row):
                cell.text = str(value)
        for row in tab.rows:
            prevent = OxmlElement("w:cantSplit")
            row._tr.get_or_add_trPr().append(prevent)
            for index, cell in enumerate(row.cells):
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                if widths:
                    cell.width = Inches(widths[index])
                margins = OxmlElement("w:tcMar")
                for side in ["top","left","bottom","right"]:
                    element = OxmlElement("w:" + side)
                    element.set(qn("w:w"), "85")
                    element.set(qn("w:type"), "dxa")
                    margins.append(element)
                cell._tc.get_or_add_tcPr().append(margins)
                for para in cell.paragraphs:
                    para.paragraph_format.space_after = Pt(3)
                    para.paragraph_format.line_spacing = 1.05
                    for run in para.runs:
                        run.font.size = Pt(9)
        p("").paragraph_format.space_after = Pt(1)

    def figure(path, caption, width=6.8, crop=None):
        if crop:
            target = assets / (Path(path).stem + "_crop.png")
            Image.open(path).crop(crop).save(target)
            path = target
        para = doc.add_paragraph()
        para.paragraph_format.keep_with_next = True
        para.add_run().add_picture(str(path), width=Inches(width))
        p(caption, "Caption")

    p("CloudSense Group Project Report", "Title")
    p("A serverless health monitoring prototype using simulated wearable data", "Subtitle")
    p("Group 11  |  CDS538 Cloud Computing")
    table(["Group member", "Student ID"], [("KUANG Zihao","5567479"),("SHEN Lang","5554032"),("LIANG Yueling","3163188"),("WU Xinying","5570452"),("HUANG Yazhen","5549881")], [4.5,2.3])
    h("Abstract")
    p("CloudSense receives synthetic wearable readings, classifies them with fixed rules, records the results and supports email alerts and a monitoring dashboard. We implemented the workflow with Amazon API Gateway, three AWS Lambda functions, Amazon SQS, Amazon DynamoDB and Amazon SNS. We evaluated the deployed system in AWS Academy Learner Lab using traceable logs, three bounded workload runs, controlled processing failures, security probes and a cost model based on recorded usage. All 360 normal readings in the workload runs were accepted and ultimately completed. Six recovery checks passed in an isolated experiment. Ten invalid-input checks returned the expected rejection responses. The measured cost model subtotal was USD 0.013672 for its stated window and included services. These results support the operation of the prototype under the tested conditions.")
    h("1 Introduction")
    p("A monitoring service must turn incoming measurements into results that users can retrieve and understand. A working webpage alone does not establish that measurements have been received, processed and retained. Our project therefore focuses on the complete cloud workflow and the evidence that links its stages. A Python simulator replaces physical sensors so that inputs can be repeated without collecting patient data.")
    p("This report explains the requirements, alternative designs, architecture, implementation and deployment, followed by the tests and their interpretation. The main report occupies pages 1 to 10; references follow on page 11. Screenshots and detailed supporting evidence are in Appendices A to D. The structure follows the written-report outline in Lecture 2 [1].")

    page("2 Background and requirements")
    p("The proposed users are caregivers and a care-monitoring coordinator who need to review recent readings, see abnormal classifications and receive an alert when a rule is met. CloudSense models that workflow as an educational prototype. It uses synthetic heart rate, body temperature, blood oxygen and blood pressure measurements, with an activity label. The classifications demonstrate application logic; they are not clinical diagnoses.")
    h("2 1 Functional requirements")
    table(["Requirement", "Implementation and acceptance evidence"], [
        ("Generate readings", "Python generates normal and abnormal JSON readings with device ID, reading ID and UTC measurement time."),
        ("Receive valid input", "Lambda 1 checks the request and enqueues valid events; HTTP 202 confirms acceptance."),
        ("Classify and retain data", "Lambda 2 evaluates four metrics and saves readings, classifications and processing status in DynamoDB."),
        ("Handle repeated or failed work", "Reading IDs, conditional state updates, SQS retries and a dead letter queue support recovery."),
        ("Notify and display", "SNS publishes permitted alerts; Lambda 3 exposes latest, history and alert queries for the React dashboard."),
        ("Explain observed behavior", "CloudWatch events and saved experiment files connect requests to completed results."),
    ], [1.65,5.15])
    h("2 2 Workload and operational requirements")
    p("The implemented evaluation uses ten virtual devices per run. Each run sends 120 normal readings, at either one reading per second for 120 seconds or two readings per second for 60 seconds. Successful acceptance and successful processing are counted separately. The intended checks are that every planned reading is sent, every accepted reading reaches its final state, and the measured delays can be explained from saved timestamps.")
    p("The system must tolerate temporary interruptions in processing, avoid rewriting completed duplicate readings and make repeatedly failing messages available for investigation. Security requirements include validated input, encrypted transport, appropriate service permissions and controlled access to device records. Cost must be explained using explicit workload assumptions and service quantities rather than a single account total.")
    h("2 3 Project scope and constraints")
    p("The deployment runs in us-east-1 using the Lab's temporary credentials and existing LabRole. We use synthetic data and a bounded test volume. The original proposal [2] preferred SMS with an email fallback; the implemented notification path uses an SNS email subscription. The final report describes that implementation. We distinguish AWS-hosted processing and storage from the locally served React interface, which calls the deployed API.")
    p("The core acceptance evidence combines API responses, completed database records, CloudWatch logs and repeatable test files. This makes it possible to assess the cloud solution independently of the appearance of the dashboard.")

    page("3 Comparison of architecture options")
    p("We considered a continuously running server, a container service and an event-driven serverless workflow. The choice depends on short processing tasks, varying input rates, recovery behavior and the effort needed to operate the system. The comparison below weighs these options qualitatively.")
    table(["Option", "Strengths", "Tradeoffs and decision"], [
        ("EC2 application server", "Direct control of the runtime and long-running connections; familiar request handling.", "Requires instance sizing, operating-system maintenance and a recovery design. An always-running instance is difficult to justify for this small, intermittent prototype."),
        ("Container service", "Packages dependencies consistently and supports services that run for a long time.", "Adds image, task and service configuration. It remains a reasonable future option for heavier processing, but is unnecessary for our short functions."),
        ("API and synchronous Lambda", "Simple request-to-result flow and fewer components.", "The client waits for processing and downstream calls. A transient processing failure is harder to decouple from ingestion."),
        ("API Lambda SQS DynamoDB", "Separates reception from processing; queue buffering, retries and managed storage suit short events.", "Requires eventual-consistency handling, idempotency and careful queue configuration. Selected for the implemented workflow."),
    ], [1.4,2.4,3.0])
    h("3 1 Reliability and service boundaries")
    p("SQS provides a boundary between accepting a measurement and processing it. Once an event is queued, processing can resume independently of the original HTTP connection. This benefit also creates an obligation: a 202 response cannot be reported as proof that the database write or alert has completed. Our evaluator explicitly checks the later state [3,4].")
    p("Lambda performs reception, processing and queries in separate functions. This separates application responsibilities and makes each stage observable. DynamoDB conditional state and reading IDs help the processor recognize repeated work. SQS offers retries, while the dead letter queue provides a place for messages that repeatedly fail.")
    h("3 2 Security and cost considerations")
    p("Managed services reduce server-maintenance work, but they still require correctly scoped identities, API authorization and data-retention choices. The Lab supplies a shared role, so the report records the actual role arrangement rather than assuming that independent functions automatically have independent permissions.")
    p("The selected services charge largely by requests, processing duration and database activity. That allows a cost model to be tied to experiment evidence. Queue polling, query frequency, repeated writes and log ingestion also contribute to cost. These effects are included where quantities were available in the chosen window, with the calculation described in Section 10.")

    page("4 Architecture and fault tolerant design")
    figure(diagram, "Figure 1  Implemented CloudSense architecture and result flow", 6.8)
    p("The simulator sends JSON over HTTPS to API Gateway. Lambda 1 validates the request, attaches reception metadata and sends it to SQS. Lambda 2 receives queued messages, evaluates the readings and stores the original measurement and classifications before notification processing. It then updates alert history and the final processing state. SNS handles publication to the configured email subscription when the alert rules permit it.")
    p("The React dashboard initiates GET requests through API Gateway. Lambda 3 queries DynamoDB and returns latest readings, history or abnormal-reading history. The browser renders those saved results and refreshes them through polling. Browser refresh and background processing are independent operations.")
    h("4 1 Recovery mechanisms")
    table(["Failure or edge case", "Implemented response"], [
        ("Invalid HTTP input", "Reject before queueing with a request-level error response."),
        ("Processing interruption", "Retain queued messages and continue processing when the trigger is restored."),
        ("Completed duplicate", "Use reading progress to return DUPLICATE_SKIPPED and preserve the saved result."),
        ("Failure within an SQS batch", "Return failed message identifiers through ReportBatchItemFailures for retry."),
        ("Repeated processing failure", "Allow SQS redrive policy to move the message to a dead letter queue."),
        ("Late or repeated alerts", "Store late data without immediate notification; use per-device metric state and cooldown for alerts."),
    ], [1.85,4.95])
    p("The main queue has a 360-second visibility timeout and a maximum receive count of five; processing timeout is 60 seconds. These values give the processor time to finish before an unsuccessful message becomes visible again. Our controlled recovery experiment uses separate resources with shorter settings, identified in Section 8. AWS manages service infrastructure redundancy; the measured recovery result concerns the application experiment described here [3,4].")

    page("5 Implementation and deployment")
    h("5 1 Application components")
    table(["Component", "Implemented behavior"], [
        ("Simulator", "Creates JSON with unique reading IDs and device IDs. Normal values support bounded performance runs; demo senders also generate warning and critical scenarios."),
        ("Lambda 1 ingestion", "Enforces a 16 KiB application body limit, JSON object format, required fields, numeric ranges and timestamps. Adds received_at and request metadata, then sends to SQS."),
        ("Lambda 2 processing", "Checks progress, classifies four measurements, writes the original reading, evaluates notification state and completes the record. Partial batch failures request retry."),
        ("DynamoDB", "Stores readings, per-metric alert history, progress and cooldown state. DeviceTimeIndex supports device/time queries. expires_at enables TTL retention."),
        ("Lambda 3 queries", "Provides latest, history and alerts routes, validates query parameters and supports pagination. Query responses include processing status and completion time."),
        ("React interface", "Uses the three query views to display metrics, trends and alert history. Polling refreshes data; errors and stale readings have explicit states."),
    ], [1.5,5.3])
    h("5 2 Classification and alert behavior")
    p("The processor stores Normal, Warning or Critical for each metric using fixed demonstration thresholds. For example, heart rate below 45 or above 120 bpm is Critical; body temperature below 35 or at least 38 degrees Celsius is Critical. A critical notification requires two consecutive critical readings for the same metric. A 300-second cooldown suppresses repeated notifications, and late or out-of-order measurements affect notification decisions. Thus, an abnormal classification does not necessarily produce an email for every reading.")
    h("5 3 Deployment and reproduction")
    p("The repository contains an AWS SAM template describing the HTTP API, functions, queues, table and SNS resources. It uses the existing LabRole. A fresh deployment uses sam build and sam deploy --guided in an environment with the required temporary credentials. The evaluated environment already existed; the evaluation utility backed up its function packages, deployed the reviewed Python source and checked the deployed code hashes. All three functions use Python 3.13. Ingestion and query use 128 MB with 10-second timeouts; processing uses 256 MB with a 60-second timeout.")
    p("For the interface, install frontend dependencies, configure the private API base URL and start Vite on localhost:5173, the allowed browser origin. For an evaluation run, start the Lab, open evaluation/run_low_load.py in VS Code and click Run Code. The script reads the local simulator configuration and opens its own live results page. It requires Python 3.9 or later and no local AWS key. Each run saves JSON, CSV and an offline HTML chart. Appendix A shows the actual Run Code execution.")

    page("6 Evaluation method and log inspection")
    h("6 1 Experimental method")
    p("We conducted the AWS experiments on 9 November 2026. Unless stated otherwise, the report uses UTC; Hong Kong time is UTC plus eight hours. The workload and recovery evidence was collected around 12:03 to 12:18 UTC, with aligned one-minute metrics ending at 12:19 UTC. The later security assessment ran at 13:28 UTC and is kept separate from that cost window. Every run uses synthetic readings and a distinct prefix to connect its requests and records.")
    p("The evaluator records planned, sent, accepted and completed counts. A 202 response increments acceptance; completion requires the query API to return the final processing status. Late readings, unfinished accepted records and query errors remain separate fields. The main measurements are completion ratio, API P95 latency and backend P95 completion delay. P95 is the delay at or below which 95 percent of the measured observations fall.")
    h("6 2 Inspecting the three Lambda logs")
    p("After sending the test readings, we inspected the logs produced by all three Lambda functions in CloudWatch Logs. In the AWS console, the path is Lambda, selected function, Monitor, then View CloudWatch logs. The corresponding log groups are /aws/lambda/cloudsense-http-ingest-test, /aws/lambda/cloudsense-process-alerts and /aws/lambda/cloudsense-query-readings. We also exported these CloudWatch events to JSON and displayed the saved events in CloudShell for the evidence screenshots.")
    table(["Stage", "Observed event", "Interpretation"], [
        ("Lambda 1", "reading_received and reading_enqueued", "The request was validated and handed to SQS."),
        ("Lambda 2", "processing_started and processing_completed", "The processor ran and produced the recorded terminal state."),
        ("Lambda 3", "dashboard_query_completed", "A request for saved device data completed and returned its record count."),
    ], [1.0,2.65,3.15])
    p("Appendix Figure A1 shows one exported event from each log group. The ingestion and processing entries share the same reading ID, eval-20261109T120342-223aac-00000. The query event refers to the same device, returns HTTP 200 and reports a count of one. Together, the events demonstrate acceptance into the queue, completed processing and availability through the query interface. Figure A2 shows the additional failure and duplicate events used in the recovery analysis.")
    h("6 3 Saved results and local verification")
    p("Each run folder contains summary.json with conditions and aggregates, requests.csv with individual requests, and dashboard.html for offline review. Cloud evidence includes environment, logs, metrics, faults, pricing and usage snapshots. The backend and evaluation test suite passed 91 tests and four subtests. These tests cover validation, processing, query pagination, acceptance versus completion, timestamp logging and independent reconciliation of saved billing quantities. They complement the real AWS results rather than replacing them.")
    p("The saved export contains 2,533 events, including 1,633 parsed JSON events. A bounded review found no top-level payload field in those JSON events. Reception logging records identifiers instead of the full health-reading payload. This finding applies to the filtered experiment export.")

    page("7 Low load performance evaluation")
    h("7 1 Procedure")
    p("We used the Python evaluator to send normal measurements to the real ingestion API and then query the history endpoint until final processing states were observed. Each run used ten virtual devices and 120 readings. We first ran one reading per second for 120 seconds, repeated that condition through the actual VS Code Run Code button, and then ran two readings per second for 60 seconds. The real Run Code execution is shown in Figure A3; Figure B1 shows its completed visualization.")
    table(["UTC start", "Input rate and duration", "Sent accepted completed", "API P95 ms", "Backend P95 ms"], [(run["started_at"][11:19],f'{run["target_rate"]:g}/s for {run["target_duration_seconds"]}s',f'{run["sent"]} / {run["accepted"]} / {run["completed"]}',f'{run["api_p95_ms"]:.1f}',f'{run["backend_p95_ms"]:.1f}') for run in runs], [1.0,1.65,1.65,1.2,1.3])
    h("7 2 Results and interpretation")
    p("All three runs passed their default completion checks. Across the runs, 360 readings were sent, accepted and ultimately completed, giving an observed completion ratio of 100 percent. Each run reported zero unfinished accepted readings, zero late readings and no query errors. The second run achieved an actual send rate of 1.001 readings per second. Its API P95 latency was 1,208.2 ms and its backend P95 completion delay was 664.5 ms. The two-per-second run also completed all 120 readings, with a backend P95 of 693.2 ms.")
    p("These results show that the deployed ingestion, queue, processing, storage and query path handled a sustained small workload under the tested conditions. The plot records cumulative sent, accepted and completed readings, so it can expose a growing difference between acceptance and completion. By checking the final state of each accepted record, the evaluation provides stronger evidence than counting successful POST responses alone.")
    h("7 3 Meaning of the latency measurements")
    p("API latency is the elapsed time measured by the client and includes its network path. Backend delay is the AWS completion timestamp minus the reception timestamp, so it includes queueing and processing before the final record is marked complete. Observation delay is different: it also includes sequential polling, query requests and index visibility. The approximately 23-second P95 observation delay in the second run must therefore not be described as the processor's execution time.")
    p("The first run had a higher backend P95 of 3,783.4 ms. The saved measurement establishes the difference, but does not identify a single cause. The later runs provide the measured comparison at their stated rates. The evaluation characterizes those rates; further capacity claims require a separate experiment.")
    h("7 4 Relation to the monitoring webpage")
    p("The evaluator confirms that completed records are retrievable through the same query service used by the business dashboard. Its live chart is a separate experiment view. The React dashboard polls latest, history and alerts for the selected device; it does not receive a push from Lambda. Pausing browser refresh stops subsequent queries, while queued processing continues. This explains why a frontend pause and a processing outage are different tests.")

    page("8 Controlled failure and recovery evaluation")
    h("8 1 Procedure and isolation")
    p("We created a dedicated main queue, dead letter queue, processing Lambda and SNS topic for fault experiment fault-20261109120440. The Lambda used the existing processor source and LabRole, and synthetic records used a fault prefix in the existing table. The dedicated topic had no subscribers. This allowed processing failures to be exercised without clearing the main queue or sending fault-test alerts to an email recipient.")
    p("We disabled the dedicated SQS event-source mapping, sent five normal messages and checked that the queue retained five while none had completed storage. We then enabled the mapping and waited for every record to reach COMPLETE. Subsequent steps repeated a completed reading, injected an invalid message directly into the dedicated queue, observed retry and dead letter behavior, and replayed the repaired message. Figure B2 shows the six checks and the observed timeline.")
    table(["Test", "Observed result", "Conclusion"], [
        ("Invalid API input", "400 response and no stored test item", "Malformed input is rejected before normal processing."),
        ("Consumer paused", "Five messages retained; five records absent", "Queue buffering preserves work during the pause."),
        ("Consumer resumed", "Five records COMPLETE; 8.77 seconds observed recovery", "Processing resumes and clears the tested backlog."),
        ("Duplicate replay", "Two replays; saved record unchanged", "Completed duplicates are skipped in this case."),
        ("Poison message", "Three KeyError failures followed by DLQ arrival", "Repeated failure is retried and isolated."),
        ("Repair and replay", "Same ID completed after the missing field was supplied", "Corrected data can be reprocessed successfully."),
    ], [1.3,2.8,2.7])
    h("8 2 Evidence and interpretation")
    p("The logs include two DUPLICATE_SKIPPED events and three processing failures for the poison reading. The message was injected at 12:05:14 UTC and observed in the dead letter queue at 12:08:14, approximately 180 seconds later. After the test script supplied the missing timestamp and resent the same reading ID, the completed state was observed at 12:08:16. The repair was performed by the experiment script.")
    p("The dedicated queue used a 60-second visibility timeout and maximum receive count of three, with a 10-second Lambda timeout. The main system retains its 360-second visibility timeout, five receives and 60-second processing timeout. Accordingly, the recorded 8.77 seconds describes recovery of this five-message experiment. Afterward, the dedicated trigger was disabled and its resources and evidence were retained. The main trigger remained enabled.")
    p("Lambda's aggregate Errors metric alone is insufficient for this workflow: partial batch failures can be returned for retry without appearing as a failed whole-function invocation. Matching per-message logs, state checks and DLQ observations make the recovery conclusion assessable [3,4].")

    page("9 Security assessment")
    h("9 1 Method and passed controls")
    p("Within the Lab's available permissions, we read the deployed API, functions, role attachments, queue attributes, table settings, SNS attributes and log-group configuration. We sent ten bounded invalid requests and one normal synthetic reading through HTTPS. The anonymous read probe queried only its own synthetic test device. No IAM, authentication, resource-policy or encryption configuration was changed. Figures C1 and C2 show the real CloudShell results; security.json preserves the response metadata and configuration snapshot.")
    table(["Control checked", "Evidence and result"], [
        ("Malformed ingestion input", "Malformed JSON, missing fields, a JSON array and NaN each returned 400. text/plain returned 415. A body above the application's 16 KiB limit returned 413."),
        ("Query validation", "Invalid device ID, limit, timestamp and cursor each returned 400."),
        ("Transport and query caching", "The HTTPS probes used default certificate and hostname verification. Query responses included Cache-Control: no-store."),
        ("Browser origin handling", "CORS allowed localhost:5173. The untrusted-origin preflight returned no Access-Control-Allow-Origin header."),
        ("Queue encryption", "The main queue and dead letter queue both returned SqsManagedSseEnabled=true."),
        ("Retention mechanism", "DynamoDB TTL was enabled on expires_at. Reading code writes expiry timestamps; TTL deletion is asynchronous."),
        ("Source and log hygiene", "A bounded scan of 35 selected source files found no matches for the checked AWS-key/private-key patterns. The local simulator config is Git-ignored; saved experiment JSON logs had no top-level payload field."),
    ], [1.7,5.1])
    h("9 2 Interpretation and access scope")
    p("All ten invalid-input requests returned their expected rejection status. The CORS result restricts browser response access from the tested origin, but it does not authenticate a direct HTTP client. The API snapshot showed four routes with AuthorizationType NONE; the synthetic unauthenticated write returned 202 and its read returned 200 with the record visible. Authentication and device-level authorization are therefore required before using this prototype with actual health data.")
    p("The three functions share LabRole, which includes policies for services beyond this application's responsibilities. Three Lab-managed policy documents could not be read because AWS returned AccessDenied; those checks were left out of the completed review. The readable resource policies constrained API-to-Lambda invocation by source ARN and the SNS default policy by account SourceOwner. No explicit SQS queue policy was returned. These observations support an account-scoped configuration review, not a complete effective-permission proof.")
    p("The snapshot also showed no SNS KMS key and no expiry setting for the three log groups. These are documented configuration improvements. DynamoDB did not return SSEDescription; absence of that field is not evidence of unencrypted storage, because DynamoDB encrypts table data at rest by default [5]. The assessment reports individual checked controls and does not certify clinical compliance.")

    page("10 Cost evaluation and conclusions")
    h("10 1 Method and recorded cost")
    p("We multiplied recorded service quantities by the official us-east-1 public rates retrieved on 9 November 2026 [6]. Lambda quantities came from distinct REPORT lines and billed duration times configured memory. API, database and log quantities came from saved CloudWatch evidence. Metrics were recollected after reporting delay, and 532 API calls reconciled with 360 normal writes, 171 history queries and one invalid request. The cost window predates the security probes in Section 9.")
    table(["Service", "Quantity", "Rate", "Estimated USD"], [
        ("Lambda requests","900","0.20 per million","0.00018000"),
        ("Lambda compute","74.749 GB-seconds","0.0000166667 per GB-second","0.00124582"),
        ("HTTP API","532 requests","1.00 per million","0.00053200"),
        ("DynamoDB writes","16,470 units","0.625 per million","0.01029375"),
        ("DynamoDB reads","3,545.5 units","0.125 per million","0.00044319"),
        ("Log ingestion","680,856 bytes","0.50 per GB","0.00031705"),
        ("Main SQS request model","1,651 modeled requests","0.40 per million","0.00066040"),
        ("Modeled subtotal","","",f'{cost["estimated_modeled_subtotal_usd"]:.8f}'),
    ], [1.45,1.55,2.35,1.45])
    p("The SQS quantity models one request per sent, received and deleted message plus empty receives; batching can change actual billed request counts. The database quantities include the base table and index in a shared window. The subtotal excludes free-tier credits and discounts, dedicated fault-queue calls, SNS, network, frontend hosting, other Lab infrastructure, metric-collection charges and storage byte-hours. Figure D1 shows the saved model; Figure D2 shows its AWS usage and price sources.")
    h("10 2 Budget interpretation")
    p(f'The separate delayed account month-to-date total was USD {cost["account_month_to_date_usd"]:.6f}. A Start Lab or End Lab budget page is useful for monitoring the overall Lab allowance, but its total can include earlier activity and other resources and may update later. It cannot alone allocate cost to this experiment. The usage calculation explains the measured service contributions; it is a scoped model rather than an invoice.')
    p("For illustration, 100 devices sending once per minute for 30 days generate 4.32 million readings. Applying the mixed experiment subtotal per 360 completed readings gives about USD 164.07. This retains the experiment's query, fault and idle-polling pattern. A deployment budget should instead specify its own query frequency, alert frequency, retention and traffic assumptions.")
    h("10 3 Limitations and conclusions")
    p("CloudSense implements the complete reception, queue, classification, storage and query workflow. The real workload runs completed 360 of 360 readings, and six controlled recovery checks passed. Logs connect the stages, while input and configuration checks provide concrete security evidence. The results apply to the stated rates, synthetic data and dedicated fault settings. Production use requires API access controls and suitable permissions, encryption and retention choices; Lab-restricted IAM inspection remains outside this review. The completed evidence supports a working and explainable cloud prototype.")

    page("References")
    refs = [
        "[1] Lin, Z. CDS538 Lecture 2 Cloud Architectures and Core Services. Course slides, pp. 5-6 and 9-11. Written report example outline and evaluation dimensions.",
        "[2] Group 11. CloudSense A Serverless Health Monitoring and Alert System for Simulated Wearable Devices. Group project proposal, 27 September 2026. Used for project background and initial design options; final implementation uses email notifications.",
        "[3] Amazon Web Services. Using Lambda with Amazon SQS. https://docs.aws.amazon.com/lambda/latest/dg/with-sqs.html",
        "[4] Amazon Web Services. Using dead-letter queues in Amazon SQS. https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html",
        "[5] Amazon Web Services. Amazon DynamoDB encryption at rest. https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/EncryptionAtRest.html",
        "[6] Amazon Web Services. Regional Price List files for us-east-1, retrieved 9 November 2026. Service codes AWSLambda, AmazonApiGateway, AWSQueueService, AmazonDynamoDB, AmazonCloudWatch and AmazonSNS. Pattern: https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/<service-code>/current/us-east-1/index.json. Exact URLs, SKUs, publication dates and selected rates are preserved in evaluation/cloud_evidence/pricing.json and evaluation/costs/costs.json.",
        "[7] Amazon Web Services. Working with HTTP APIs. https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api.html",
        "[8] Amazon Web Services. IAM security best practices. https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html",
    ]
    for ref in refs:
        p(ref)
    h("Evidence record")
    p("Experiment records are stored in cloudsense/evaluation. The three result folders are eval-20261109T120342-223aac, eval-20261109T121201-9c9e57 and eval-20261109T121606-18873c. Each contains summary.json, requests.csv and dashboard.html. cloud_evidence/faults.json records the six recovery checks; logs.json contains the filtered CloudWatch export. security.json and security_review.json record the later bounded security assessment. The costs directory preserves the calculation inputs and outputs.")
    p("Screenshots are classified in cloudsense/improve_img by logging, low load, recovery, security and cost. CloudShell images show genuine exported AWS data; they are not screenshots of the CloudWatch console log table. Crops remove navigation or unused space while retaining the relevant observed output. Screenshots support the structured evidence rather than replacing it. Planned responsibilities in the proposal are not presented as verified final contribution records.")

    page("Appendix A Log and execution evidence")
    p("Figures A1 and A2 support Section 6. They show genuine CloudWatch events exported to CloudShell, including event names, record identifiers and final processing state.")
    figure(IMG / "01_logging/03_three_lambda_logs.png", "Figure A1  Three Lambda log groups with ingestion processing and query events", crop=(0,285,1470,575))
    figure(IMG / "01_logging/02_unobstructed_trace.jpg", "Figure A2  Additional trace duplicate handling and per-message failures", width=6.6)
    figure(IMG / "02_low_load/04_vscode_run_code.jpg", "Figure A3  Actual VS Code Run Code execution and terminal PASS result", width=5.3)

    page("Appendix B Performance and recovery evidence")
    figure(IMG / "02_low_load/05_summary_crop.jpg", "Figure B1  Second workload run completed with 120 sent accepted and completed", width=6.4)
    p("The observed API P95 is 1,208.2 ms and the backend P95 is 664.5 ms. Sent, accepted and completed are separate measurements. This is the experiment viewer, which queries the deployed API.")
    figure(IMG / "03_recovery/04_summary_crop.jpg", "Figure B2  Six recovery checks passed and the dedicated trigger ended disabled", width=6.8)
    p("The five paused messages completed after resuming the consumer. The screenshot also shows poison-message DLQ arrival and repaired replay. Dedicated settings are stated in Section 8.")

    page("Appendix C Security assessment evidence")
    figure(IMG / "04_security/01_input_and_anonymous_access.png", "Figure C1  Expected input rejections and observed anonymous synthetic write and read", crop=(0,230,1470,575))
    p("The ten rejection statuses support the input-validation result. The anonymous 202 and 200 responses identify the access-control improvement discussed in Section 9; the word PASS in raw probe output denotes an expected observation, not a security approval.")
    figure(IMG / "04_security/02_resource_protection.png", "Figure C2  Queue encryption TTL SNS key log retention and unavailable IAM reads", crop=(0,160,1470,575))
    p("SqsManagedSseEnabled is true for both queues. DynamoDB TTL is enabled. Three managed-policy reads returned AccessDenied. The processor resource-policy ResourceNotFoundException means no such policy was returned; it is distinct from a permission denial.")

    page("Appendix D Cost evidence")
    figure(IMG / "05_cost/01_usage_cost_model.jpg", "Figure D1  Browser view of the saved usage cost model and its stated scope", width=5.5)
    figure(IMG / "05_cost/04_unobstructed_usage.jpg", "Figure D2  AWS CloudShell usage quantities official price sources and separate account total", width=6.6)
    p("Figures D1 and D2 support Section 10. The cost model covers the selected earlier experiment window. The later security activity is excluded, and the account total has a different scope.")
    for element in list(doc.styles.element.xpath(".//w:pBdr")) + list(doc.element.xpath(".//w:pBdr")):
        element.getparent().remove(element)
    OUT.parent.mkdir(exist_ok=True)
    doc.save(OUT)
    text = " ".join(para.text for para in doc.paragraphs)
    print(OUT)
    print("Paragraph words", len(text.split()), "planned pages", len(paragraphs_by_page) + 1)


if __name__ == "__main__":
    main()
