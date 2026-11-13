
import json
from datetime import datetime
from pathlib import Path
from json_repair import repair_json


def build_reflection_prompt(raw_text, bad_json, error):
    prompt = f"""
    The previous invoice extraction failed validation.

    Original document:
    {raw_text[:3000]}

    Previous extracted JSON:
    {bad_json[:3000]}

    Validation errors:
    {error[:2000]}

    Correct the errors using the original document.
    Do not invent missing information.
    Return the corrected invoice data.
    """

    return prompt


def repair_json_payload(raw_json):
    try:
        repaired = repair_json(raw_json, return_objects=True)
        return repaired
    except (ValueError, TypeError):
        return None


def save_to_dlq(raw_text, bad_json, error_log):
    folder = Path("dlq")
    folder.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = folder / f"failed_{timestamp}.json"

    failure_data = {
        "status": "DLQ_FAILED",
        "original_text": raw_text,
        "last_response": bad_json,
        "errors": error_log
    }

    with open(filename, "w", encoding="utf-8") as file:
        json.dump(failure_data, file, indent=2)

    return str(filename)
