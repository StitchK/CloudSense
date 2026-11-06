import boto3, yaml, json, hashlib
from pathlib import Path
from urllib.parse import urlparse
stack = "cloudsense-http-ingest-test"
cf = boto3.client("cloudformation")
original = cf.get_template(StackName=stack, TemplateStage="Original")["TemplateBody"]
t = yaml.safe_load(original) if isinstance(original, str) else original
assert "QueryFunction" not in t["Resources"], "QueryFunction already exists; inspect before replacing"
payload = Path("cloudsense-query.zip").read_bytes()
digest = hashlib.sha256(payload).hexdigest()
assert digest == "17c6dc6cf27153a450cec595a997ca93466d0cc1de3d04f54f893e96ca904c39"
source = urlparse(t["Resources"]["ProcessFunction"]["Properties"]["CodeUri"])
key = "cloudsense/query/" + digest + ".zip"
boto3.client("s3").put_object(Bucket=source.netloc, Key=key, Body=payload)
t.setdefault("Parameters", {})["DashboardAllowedOrigins"] = {"Type":"CommaDelimitedList","Default":"http://localhost:5173"}
t["Resources"]["ReadingsHttpApi"]["Properties"] = {"CorsConfiguration":{"AllowOrigins":{"Ref":"DashboardAllowedOrigins"},"AllowMethods":["GET","POST","OPTIONS"],"AllowHeaders":["Content-Type","Authorization"],"ExposeHeaders":["x-request-id"],"MaxAge":300}}
events = {{"latest":"GetLatestReading","history":"GetReadingHistory","alerts":"GetAlertHistory"}[view]:{"Type":"HttpApi","Properties":{"ApiId":{"Ref":"ReadingsHttpApi"},"Path":"/devices/{device_id}/" + view,"Method":"GET","PayloadFormatVersion":"2.0"}} for view in ("latest","history","alerts")}
t["Resources"]["QueryFunction"] = {"Type":"AWS::Serverless::Function","Properties":{"FunctionName":"cloudsense-query-readings","CodeUri":"s3://" + source.netloc + "/" + key,"Handler":"query.app.lambda_handler","Runtime":"python3.13","MemorySize":128,"Timeout":10,"Role":t["Resources"]["ProcessFunction"]["Properties"]["Role"],"Environment":{"Variables":{"ALERT_STATE_TABLE":{"Ref":"AlertStateTable"},"DATA_STALE_SECONDS":300}},"Events":events}}
t["Outputs"]["QueryApiBaseUrl"] = {"Description":"Dashboard query API base URL","Value":{"Fn::Sub":"https://${ReadingsHttpApi}.execute-api.${AWS::Region}.amazonaws.com"}}
t["Outputs"]["QueryFunctionName"] = {"Value":{"Ref":"QueryFunction"}}
previous = cf.describe_stacks(StackName=stack)["Stacks"][0]
parameters = [{"ParameterKey":p["ParameterKey"],"UsePreviousValue":True} for p in previous.get("Parameters",[])]
parameters.append({"ParameterKey":"DashboardAllowedOrigins","ParameterValue":"http://localhost:5173"})
result=cf.create_change_set(StackName=stack,ChangeSetName="add-dashboard-query-20261106",ChangeSetType="UPDATE",TemplateBody=json.dumps(t),Parameters=parameters,Capabilities=["CAPABILITY_AUTO_EXPAND"])
print(json.dumps({"change_set_id":result["Id"],"zip_sha256":digest}))
