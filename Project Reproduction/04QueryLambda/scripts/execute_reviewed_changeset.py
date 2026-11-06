import boto3,json
c=boto3.client("cloudformation")
s="cloudsense-http-ingest-test"
n="add-dashboard-query-20261106"
r=c.describe_change_set(StackName=s,ChangeSetName=n)
changes=[x["ResourceChange"] for x in r["Changes"]]
assert r["Status"]=="CREATE_COMPLETE", r["Status"]
assert all((x["Action"]=="Add" and x["LogicalResourceId"].startswith("QueryFunction")) or (x["Action"]=="Modify" and x["LogicalResourceId"]=="ReadingsHttpApi" and x.get("Replacement")=="False") for x in changes), changes
print("VERIFIED_CHANGES", json.dumps([{k:x.get(k) for k in ("Action","LogicalResourceId")} for x in changes]))
c.execute_change_set(StackName=s,ChangeSetName=n)
print("DEPLOYMENT_STARTED")
