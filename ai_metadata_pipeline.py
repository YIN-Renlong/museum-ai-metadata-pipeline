import os
import json
import base64
import asyncio
import httpx
import time
import csv
from datetime import datetime, timezone
from typing import Any, Dict, List

import pydantic
from PIL import Image
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError


# ============================================================
# Pydantic Middleware Schema
# ============================================================
# This schema is the Python middleware validation layer.
# It prevents structurally invalid LLM output from being saved
# as successful museum metadata.
# ============================================================

class MuseumMetadataSchema(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid"
    )

    dc_identifier: StrictStr = Field(alias="dc:identifier")
    dc_title: StrictStr = Field(alias="dc:title")
    dc_description: StrictStr = Field(alias="dc:description")

    dc_subject_lcsh: List[StrictStr] = Field(alias="dc:subject_LCSH")
    dc_subject_aat: List[StrictStr] = Field(alias="dc:subject_AAT")
    dc_subject_tgm: List[StrictStr] = Field(alias="dc:subject_TGM")
    dc_subject_rkd: List[StrictStr] = Field(alias="dc:subject_RKD")

    condition_note: StrictStr = Field(alias="condition_note")
    ai_provenance: Dict[str, Any] = Field(alias="ai_provenance")


# ============================================================
# Environment and Configuration
# ============================================================

load_dotenv()

API_KEY = os.getenv("AZURE_API_KEY")
ENDPOINT = os.getenv("AZURE_ENDPOINT")
MODEL = os.getenv("DEPLOYMENT_NAME")

INPUT_DIR = "input_images"
OUTPUT_DIR = "output_metadata"
TRIAGE_DIR = "human_triage"

CSV_FILE = "evaluation_metrics.csv"
SUMMARY_FILE = "evaluation_summary.md"
VALIDATION_LOG_FILE = "validation_audit.jsonl"

SCHEMA_NAME = "MuseumMetadataSchema"
SCHEMA_VERSION = "1.0.0"

# If True, successful output JSON receives a schema_validation
# record inside ai_provenance.
EMBED_VALIDATION_PROVENANCE = True

# Pricing config, per 1,000,000 tokens
PRICE_INPUT_MILLION = 5.00
PRICE_CACHED_MILLION = 0.50
PRICE_OUTPUT_MILLION = 30.00


# ============================================================
# Utility Functions
# ============================================================

def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def append_jsonl(path, record):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def get_image_resolution(image_path):
    with Image.open(image_path) as img:
        return img.size  # returns width, height


def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


# ============================================================
# Validation Audit and Human Triage
# ============================================================

def log_validation_event(
    filename,
    effort,
    status,
    timestamp,
    errors=None,
    triage_path=None
):
    """
    Writes a structured validation event to validation_audit.jsonl.

    This creates an external audit trail showing whether each LLM output
    passed or failed Pydantic validation.
    """

    event = {
        "timestamp_utc": timestamp,
        "filename": filename,
        "reasoning_effort": effort,
        "status": status,
        "validator": {
            "name": "pydantic",
            "version": pydantic.__version__
        },
        "schema": {
            "name": SCHEMA_NAME,
            "version": SCHEMA_VERSION
        }
    }

    if errors is not None:
        event["errors"] = errors

    if triage_path is not None:
        event["triage_file"] = triage_path

    append_jsonl(VALIDATION_LOG_FILE, event)


def save_schema_triage_record(filename, effort, raw_metadata, errors, timestamp):
    """
    Saves structurally invalid, but parseable, JSON to the human_triage folder.

    This preserves the rejected LLM output together with the exact Pydantic
    validation errors for human archivist review.
    """

    os.makedirs(TRIAGE_DIR, exist_ok=True)

    safe_base = filename.rsplit(".", 1)[0]
    triage_filename = f"{safe_base}_{effort}_schema_validation_failed.json"
    triage_path = os.path.join(TRIAGE_DIR, triage_filename)

    triage_record = {
        "timestamp_utc": timestamp,
        "filename": filename,
        "reasoning_effort": effort,
        "status": "schema_validation_failed",
        "validator": {
            "name": "pydantic",
            "version": pydantic.__version__
        },
        "schema": {
            "name": SCHEMA_NAME,
            "version": SCHEMA_VERSION
        },
        "errors": errors,
        "raw_llm_json": raw_metadata
    }

    with open(triage_path, "w", encoding="utf-8") as f:
        json.dump(triage_record, f, indent=4, ensure_ascii=False, default=str)

    return triage_path


def save_json_parse_triage_record(filename, effort, raw_content, error_message, timestamp):
    """
    Saves non-parseable JSON responses to human triage.

    This is not a Pydantic failure because Pydantic validation cannot run
    until JSON syntax has first been successfully parsed.
    """

    os.makedirs(TRIAGE_DIR, exist_ok=True)

    safe_base = filename.rsplit(".", 1)[0]
    triage_filename = f"{safe_base}_{effort}_json_parse_failed.json"
    triage_path = os.path.join(TRIAGE_DIR, triage_filename)

    triage_record = {
        "timestamp_utc": timestamp,
        "filename": filename,
        "reasoning_effort": effort,
        "status": "json_parse_failed",
        "error": error_message,
        "raw_llm_content": raw_content
    }

    with open(triage_path, "w", encoding="utf-8") as f:
        json.dump(triage_record, f, indent=4, ensure_ascii=False, default=str)

    return triage_path


def parse_llm_json_or_triage(raw_content, filename, effort):
    """
    Parses the raw LLM response string into JSON.

    If JSON parsing fails, the response is routed to human triage and
    None is returned.
    """

    timestamp = utc_now_iso()

    try:
        return json.loads(raw_content)

    except json.JSONDecodeError as e:
        triage_path = save_json_parse_triage_record(
            filename=filename,
            effort=effort,
            raw_content=raw_content,
            error_message=str(e),
            timestamp=timestamp
        )

        log_validation_event(
            filename=filename,
            effort=effort,
            status="json_parse_failed",
            timestamp=timestamp,
            errors=[{"message": str(e)}],
            triage_path=triage_path
        )

        print("\n🚨 JSON PARSE FAILED: Routing to Human Triage")
        print(f"   File: {filename} | Reasoning: {effort.upper()}")
        print(f"   Triage file: {triage_path}")
        print("   Pydantic validation was not attempted because the response was not valid JSON.")

        return None


def validate_museum_metadata(raw_metadata, filename, effort):
    """
    Validates raw LLM JSON against MuseumMetadataSchema.

    If validation succeeds:
        - returns safe validated data using original JSON aliases;
        - writes a passed event to validation_audit.jsonl;
        - optionally embeds validation provenance in ai_provenance.

    If validation fails:
        - writes a failed event to validation_audit.jsonl;
        - saves the rejected output to human_triage/;
        - returns None so the output is not saved as successful metadata.
    """

    timestamp = utc_now_iso()

    try:
        validated_model = MuseumMetadataSchema.model_validate(raw_metadata)

        safe_data = validated_model.model_dump(
            by_alias=True,
            mode="json"
        )

        if EMBED_VALIDATION_PROVENANCE:
            ai_provenance = dict(safe_data.get("ai_provenance", {}))

            ai_provenance["schema_validation"] = {
                "status": "passed",
                "validator": "pydantic",
                "pydantic_version": pydantic.__version__,
                "schema": SCHEMA_NAME,
                "schema_version": SCHEMA_VERSION,
                "validated_at_utc": timestamp
            }

            safe_data["ai_provenance"] = ai_provenance

        log_validation_event(
            filename=filename,
            effort=effort,
            status="passed",
            timestamp=timestamp
        )

        print(
            f"🛡️ Pydantic validation passed: "
            f"{filename} | {SCHEMA_NAME} v{SCHEMA_VERSION}"
        )

        return safe_data

    except ValidationError as e:
        errors = e.errors(include_input=False)

        triage_path = save_schema_triage_record(
            filename=filename,
            effort=effort,
            raw_metadata=raw_metadata,
            errors=errors,
            timestamp=timestamp
        )

        log_validation_event(
            filename=filename,
            effort=effort,
            status="failed",
            timestamp=timestamp,
            errors=errors,
            triage_path=triage_path
        )

        print("\n🚨 SCHEMA VALIDATION FAILED: Routing to Human Triage")
        print(f"   File: {filename} | Reasoning: {effort.upper()}")
        print(f"   Triage file: {triage_path}")
        print("   The output was not saved and will not be logged as a successful generation.")

        return None


# ============================================================
# CSV Metrics Logging
# ============================================================

def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Filename",
                "Resolution",
                "Reasoning_Effort",
                "Time_Seconds",
                "Prompt_Tokens",
                "Completion_Tokens",
                "Total_Cost_USD"
            ])


def log_to_csv(stat):
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            stat["filename"],
            stat["resolution"],
            stat["effort"],
            stat["time"],
            stat["prompt_tokens"],
            stat["completion_tokens"],
            stat["cost"]
        ])


# ============================================================
# Main Image Processing Function
# ============================================================

async def process_image_effort(client, filename, effort):
    image_path = os.path.join(INPUT_DIR, filename)
    base64_image = encode_image(image_path)
    resolution = get_image_resolution(image_path)

    print(f"🔄 Processing: {filename} | Reasoning: {effort.upper()}...")

    headers = {
        "api-key": API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "model": MODEL,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 15000,
        "messages": [
            {
                "role": "system",
                "content": f"""You are an expert museum archivist processing digitized access copies (DIPs) of 35mm color negatives.

                Because the original physical negatives suffer from chemical fading over time, colors in these inverted images are unverified and may exhibit color shifts. Do not infer artistic intent from color casts.

                Return ONLY a JSON object matching this exact structure:

                {{
                    "dc:identifier": "{filename}",
                    "dc:title": "Provisional title",
                    "dc:description": "Detailed, objective visual description.",
                    "dc:subject_LCSH": ["Broad Topic 1", "Broad Topic 2"],
                    "dc:subject_AAT": ["Specific Object 1", "Specific Object 2"],
                    "dc:subject_TGM": ["Visual Motif 1", "Photographic Genre 1"],
                    "dc:subject_RKD": ["Art Historical Term 1", "Topographical Term 1"],
                    "condition_note": "Colors unverified; image programmatically inverted from faded source negative.",
                    "ai_provenance": {{"reasoning_effort": "{effort.upper()}"}}
                }}

                CRITICAL INSTRUCTION FOR VOCABULARIES:

                'dc:subject_LCSH': Use ONLY Library of Congress Subject Headings (broad concepts, historical themes, human activities).

                'dc:subject_AAT': Use ONLY Getty Art & Architecture Thesaurus terms (specific physical objects, architectural elements, materials).

                'dc:subject_TGM': Use ONLY Thesaurus for Graphic Materials terms (visual elements, photographic genres, compositional features).

                'dc:subject_RKD': Use ONLY terms aligned with the RKD (Netherlands Institute for Art History) classification (European topographical descriptors, art historical iconography, structural classifications)."""
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"Generate Museum-Grade Dublin Core JSON for file: {filename}"
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ]
    }

    if effort != "none":
        payload["reasoning_effort"] = effort

    start_time = time.time()

    try:
        timeout = httpx.Timeout(
            connect=15.0,
            read=600.0,
            write=15.0,
            pool=15.0
        )

        response = await client.post(
            ENDPOINT,
            headers=headers,
            json=payload,
            timeout=timeout
        )

        response.raise_for_status()

        end_time = time.time()
        process_time = round(end_time - start_time, 2)

        r_data = response.json()

        raw_llm_content = r_data["choices"][0]["message"]["content"]

        # ------------------------------------------------------------
        # Stage 1: JSON parsing
        # ------------------------------------------------------------
        raw_result_json = parse_llm_json_or_triage(
            raw_content=raw_llm_content,
            filename=filename,
            effort=effort
        )

        if raw_result_json is None:
            return None

        # ------------------------------------------------------------
        # Stage 2: Pydantic schema validation
        # ------------------------------------------------------------
        result_json = validate_museum_metadata(
            raw_metadata=raw_result_json,
            filename=filename,
            effort=effort
        )

        if result_json is None:
            return None

        # ------------------------------------------------------------
        # Existing usage, token, and cost calculations
        # ------------------------------------------------------------
        usage = r_data.get("usage", {})

        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        cached_tokens = usage.get("prompt_tokens_details", {}).get("cached_tokens", 0)

        standard_input_tokens = prompt_tokens - cached_tokens

        cost_input = (standard_input_tokens / 1_000_000) * PRICE_INPUT_MILLION
        cost_cached = (cached_tokens / 1_000_000) * PRICE_CACHED_MILLION
        cost_output = (completion_tokens / 1_000_000) * PRICE_OUTPUT_MILLION

        total_cost = cost_input + cost_cached + cost_output

        output_filename = f"{filename.rsplit('.', 1)[0]}_{effort}.json"
        output_path = os.path.join(OUTPUT_DIR, output_filename)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result_json, f, indent=4, ensure_ascii=False)

        print(
            f"✅ Success: {output_filename} | "
            f"Time: {process_time}s | "
            f"Prompt T: {prompt_tokens} | "
            f"Comp T: {completion_tokens} | "
            f"Cost: ${total_cost:.5f}"
        )

        stat = {
            "effort": effort,
            "filename": filename,
            "resolution": f"{resolution[0]}x{resolution[1]}",
            "time": process_time,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost": total_cost
        }

        log_to_csv(stat)

        return stat

    except Exception as e:
        print(f"❌ Error processing {filename} at {effort}: {e}")
        return None


# ============================================================
# Summary Markdown Generation
# ============================================================

def generate_summary_markdown(stats):
    print(f"\n📝 Generating {SUMMARY_FILE}...")

    summary = {}

    for effort in ["high"]:
        effort_stats = [
            s for s in stats
            if s and s["effort"] == effort
        ]

        if effort_stats:
            avg_time = sum(s["time"] for s in effort_stats) / len(effort_stats)
            avg_prompt = sum(s["prompt_tokens"] for s in effort_stats) / len(effort_stats)
            avg_comp = sum(s["completion_tokens"] for s in effort_stats) / len(effort_stats)
            avg_cost = sum(s["cost"] for s in effort_stats) / len(effort_stats)

            cost_100k = avg_cost * 100_000
            time_100k_hours = (avg_time * 100_000) / 3600

            summary[effort] = {
                "avg_time": round(avg_time, 2),
                "avg_prompt": int(avg_prompt),
                "avg_comp": int(avg_comp),
                "avg_cost": round(avg_cost, 5),
                "cost_100k": round(cost_100k, 2),
                "time_100k_hours": round(time_100k_hours, 2)
            }

    md_content = "# 📊 AI Reasoning Resource Implications\n\n"

    md_content += (
        "This table dynamically calculates the Token Usage, Financial Cost, "
        "and Processing Time based on the image resolution and OpenAI's "
        "Reasoning parameters.\n\n"
    )

    md_content += (
        "| Reasoning Effort | Avg Time/Image | Avg Prompt Tokens | "
        "Avg Completion Tokens | Avg Cost/Image | Extrapolated 100k Cost | "
        "Extrapolated 100k Time |\n"
    )

    md_content += (
        "|------------------|----------------|-------------------|"
        "-----------------------|----------------|------------------------|"
        "------------------------|\n"
    )

    for effort in ["high"]:
        if effort in summary:
            s = summary[effort]
            md_content += (
                f"| **{effort.upper()}** | "
                f"{s['avg_time']}s | "
                f"{s['avg_prompt']} | "
                f"{s['avg_comp']} | "
                f"${s['avg_cost']:.5f} | "
                f"**${s['cost_100k']:,.2f}** | "
                f"{s['time_100k_hours']:,.0f} hours |\n"
            )

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(md_content)


# ============================================================
# Main Batch Runner
# ============================================================

async def main():
    print("🚀 Starting Archival Batch Processor (LCSH, AAT, TGM, & RKD Enabled - HIGH REASONING ONLY)...")

    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(TRIAGE_DIR, exist_ok=True)

    init_csv()

    files = [
        f for f in os.listdir(INPUT_DIR)
        if f.lower().endswith((".png", ".jpg", ".jpeg"))
    ]

    if not files:
        print(f"⚠️ No images found in '{INPUT_DIR}/'.")
        return

    stats = []

    try:
        async with httpx.AsyncClient() as client:
            for filename in files:
                for effort in ["high"]:
                    stat = await process_image_effort(client, filename, effort)

                    if stat:
                        stats.append(stat)

    except KeyboardInterrupt:
        print("\n⚠️ Process interrupted by user! Generating summary for completed items...")

    finally:
        if stats:
            generate_summary_markdown(stats)
            print("🎉 Evaluation complete! Check 'evaluation_metrics.csv' and 'evaluation_summary.md'.")

        print(f"🧾 Validation audit log: {VALIDATION_LOG_FILE}")
        print(f"🧑‍💼 Human triage folder: {TRIAGE_DIR}/")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass