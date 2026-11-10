try:
    from common.observability import emit
except ModuleNotFoundError:
    from src.common.observability import emit


def send_alert(topic_arn, reading, alert, sns_client=None):
    """Publish one formatted alert to the configured SNS topic."""
    if sns_client is None:
        import boto3

        sns_client = boto3.client("sns")
    message = "\n".join(
        (
            f"Device: {reading['device_id']}",
            f"Reading ID: {reading.get('reading_id', 'unknown')}",
            f"Measured at: {reading.get('timestamp', 'unknown')}",
            f"Severity: {alert['level']}",
            f"Alert: {alert['message']}",
        )
    )
    result = sns_client.publish(
        TopicArn=topic_arn,
        Subject=f"CloudSense {alert['level'].upper()} alert",
        Message=message,
        MessageAttributes={
            "device_id": {"DataType": "String", "StringValue": reading["device_id"]},
            "metric": {"DataType": "String", "StringValue": alert["metric"]},
            "level": {"DataType": "String", "StringValue": alert["level"]},
        },
    )
    emit("notification_published", reading_id=reading.get("reading_id"), device_id=reading["device_id"], metric=alert["metric"], level=alert["level"], message_id=result.get("MessageId"))
