"""Classification rules shared by the processing Lambda and tests."""


def check_heart_rate(bpm):
    if bpm < 45 or bpm > 120:
        return "critical"
    if 45 <= bpm <= 59 or 101 <= bpm <= 120:
        return "warning"
    return "normal"


def check_temperature(temp):
    if temp < 35 or temp >= 38:
        return "critical"
    if 35 <= temp < 36.1 or 37.5 <= temp < 38:
        return "warning"
    return "normal"


def check_blood_oxygen(spo2_pct):
    if spo2_pct < 92:
        return "critical"
    if 92 <= spo2_pct < 95:
        return "warning"
    return "normal"


def check_blood_pressure(systolic, diastolic):
    if systolic < 80 or systolic > 180 or diastolic < 50 or diastolic > 120:
        return "critical"
    if (
        80 <= systolic <= 89
        or 50 <= diastolic <= 59
        or 131 <= systolic <= 180
        or 86 <= diastolic <= 120
    ):
        return "warning"
    return "normal"


def evaluate_reading_results(reading):
    """Return the classification and display message for every metric."""
    blood_pressure = reading["blood_pressure"]
    values = (
        (
            "heart_rate_bpm",
            check_heart_rate(reading["heart_rate_bpm"]),
            f"Heart rate: {reading['heart_rate_bpm']} bpm",
        ),
        (
            "body_temperature_c",
            check_temperature(reading["body_temperature_c"]),
            f"Body temperature: {reading['body_temperature_c']} C",
        ),
        (
            "spo2_pct",
            check_blood_oxygen(reading["spo2_pct"]),
            f"Blood oxygen: {reading['spo2_pct']}%",
        ),
        (
            "blood_pressure",
            check_blood_pressure(
                blood_pressure["systolic"],
                blood_pressure["diastolic"],
            ),
            (
                f"Blood pressure: {blood_pressure['systolic']}/"
                f"{blood_pressure['diastolic']} mmHg"
            ),
        ),
    )
    return [
        {
            "metric": metric,
            "level": level,
            "message": f"{message}, level: {level}",
        }
        for metric, level, message in values
    ]


def evaluate_reading(reading):
    """Return only warning and critical classifications for one reading."""
    return [
        result
        for result in evaluate_reading_results(reading)
        if result["level"] in ("warning", "critical")
    ]
