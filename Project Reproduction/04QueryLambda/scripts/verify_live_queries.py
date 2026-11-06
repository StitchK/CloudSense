import boto3,json,time
from datetime import datetime,timezone
from decimal import Decimal
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode,quote
cf=boto3.client("cloudformation")
stack=cf.describe_stacks(StackName="cloudsense-http-ingest-test")["Stacks"][0]
assert stack["StackStatus"]=="UPDATE_COMPLETE"
outputs={x["OutputKey"]:x["OutputValue"] for x in stack["Outputs"]}
base=outputs["QueryApiBaseUrl"]
table=boto3.resource("dynamodb").Table(outputs["AlertStateTableName"])
def number(x):
    return int(x) if x==x.to_integral_value() else float(x)
def plain(x):
    return json.loads(json.dumps(x,default=number))
def http(path,params=None,method="GET",body=None,headers=None):
    url=base+path+("?"+urlencode(params) if params else "")
    request=Request(url,data=json.dumps(body).encode() if body is not None else None,method=method,headers=headers or {})
    try:
        with urlopen(request,timeout=20) as r:
            raw=r.read()
            return r.status,json.loads(raw) if raw else {},dict(r.headers)
    except HTTPError as e:
        return e.code,json.loads(e.read()),dict(e.headers)
rows=[]
args={}
while True:
    page=table.scan(**args)
    rows += [plain(x) for x in page["Items"] if x.get("SK")=="DATA" and int(x.get("expires_at",time.time()+1))>time.time()]
    if not page.get("LastEvaluatedKey"): break
    args["ExclusiveStartKey"]=page["LastEvaluatedKey"]
groups={}
for row in rows:
    groups.setdefault(row["reading"]["device_id"],[]).append(row)
assert groups,"No stored readings to test"
checks=[]
for device,expected in sorted(groups.items()):
    expected.sort(key=lambda x:x["GSI1SK"],reverse=True)
    prefix="/devices/"+quote(device,safe="")
    status,latest,_=http(prefix+"/latest")
    assert status==200,(device,status,latest)
    assert latest["data"]["reading"]==expected[0]["reading"]
    assert latest["data"]["evaluations"]==expected[0]["evaluations"]
    assert latest["is_stale"]==(time.time()-expected[0]["measured_at_epoch"]>300)
    epochs=[x["measured_at_epoch"] for x in expected]
    iso=lambda epoch:datetime.fromtimestamp(epoch,timezone.utc).isoformat().replace("+00:00","Z")
    params={"from":iso(min(epochs)),"to":iso(max(epochs)),"limit":"2"}
    for view in ("history","alerts"):
        received=[]
        query=dict(params)
        page_count=0
        while True:
            status,result,_=http(prefix+"/"+view,query)
            assert status==200,(status,result)
            received += result["items"]
            page_count += 1
            assert page_count<100
            if not result["next_token"]: break
            query["next_token"]=result["next_token"]
        wanted=[x for x in expected if view=="history" or any(e["level"] in ("warning","critical") for e in x["evaluations"])]
        assert [x["reading"]["reading_id"] for x in received]==[x["reading"]["reading_id"] for x in wanted],(device,view)
        for actual,stored in zip(received,wanted):
            assert actual["reading"]==stored["reading"]
            assert actual["evaluations"]==stored["evaluations"]
            levels={"normal":0,"warning":1,"critical":2}
            assert actual["overall_status"]==max((e["level"] for e in stored["evaluations"]),key=levels.get)
            for alert in actual["alerts"]:
                assert alert["notification_status"]==stored["alert_history"][alert["metric"]]["status"]
        checks.append({"device":device,"route":view,"records_matched":len(received),"pages":page_count})
    checks.append({"device":device,"route":"latest","matched":True,"is_stale":latest["is_stale"]})
first=next(iter(groups))
prefix="/devices/"+quote(first,safe="")
assert http(prefix+"/history",{"limit":"101"})[0]==400
assert http(prefix+"/history",{"from":"not-a-time"})[0]==400
assert http(prefix+"/history",{"next_token":"bad-token"})[0]==400
assert http("/devices/query-nonexistent-20261106/latest")[0]==404
assert http("/devices/query-nonexistent-20261106/history")[1]["items"]==[]
s,_,headers=http(prefix+"/latest",method="OPTIONS",headers={"Origin":"http://localhost:5173","Access-Control-Request-Method":"GET"})
assert s==204,(s,headers)
assert {k.lower():v for k,v in headers.items()}["access-control-allow-origin"]=="http://localhost:5173"
report={"result":"PASS","stored_readings_compared":len(rows),"devices":len(groups),"checks":checks,"invalid_parameters":"PASS","missing_device":"PASS","cors_preflight":"PASS","base_url":"<QueryApiBaseUrl>"}
print("LIVE_QUERY_REPORT",json.dumps(report))
