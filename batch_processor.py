import os
import json
import base64
import asyncio
import httpx
import time
import csv
from PIL import Image
from dotenv import load_dotenv

# Load environment variables securely
load_dotenv()
API_KEY = os.getenv("AZURE_API_KEY")
ENDPOINT = os.getenv("AZURE_ENDPOINT")
MODEL = os.getenv("DEPLOYMENT_NAME")

INPUT_DIR = "input_images"
OUTPUT_DIR = "output_metadata"
CSV_FILE = "evaluation_metrics.csv"
SUMMARY_FILE = "evaluation_summary.md"

# Pricing config (per 1,000,000 tokens)
PRICE_INPUT_MILLION = 5.00
PRICE_CACHED_MILLION = 0.50
PRICE_OUTPUT_MILLION = 30.00

def get_image_resolution(image_path):
    with Image.open(image_path) as img:
        return img.size # returns (width, height)

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

# Initialize CSV File with Headers
def init_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Filename", "Resolution", "Reasoning_Effort", "Time_Seconds", 
                             "Prompt_Tokens", "Completion_Tokens", "Total_Cost_USD"])

# Save a single row to CSV immediately
def log_to_csv(stat):
    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([stat["filename"], stat["resolution"], stat["effort"], 
                         stat["time"], stat["prompt_tokens"], stat["completion_tokens"], stat["cost"]])

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
        "response_format": { "type": "json_object" },
        "max_completion_tokens": 15000,
        "messages": [
            {
                "role": "system",
                "content": """You are an expert museum archivist processing digitized color negatives. 
                Return ONLY a JSON object matching this exact structure:
                {
                    "dc:identifier": "filename",
                    "dc:title": "Provisional title",
                    "dc:description": "Detailed visual description.",
                    "dc:subject": ["tag1", "tag2"],
                    "ai_provenance": {"reasoning_effort": "effort_level"}
                }"""
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Generate Dublin Core JSON for file: {filename}"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ]
    }

    if effort != "none":
        payload["reasoning_effort"] = effort

    start_time = time.time()
    
    try:
        timeout = httpx.Timeout(connect=15.0, read=600.0, write=15.0, pool=15.0)
        response = await client.post(ENDPOINT, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        
        end_time = time.time()
        process_time = round(end_time - start_time, 2)
        
        r_data = response.json()
        result_json = json.loads(r_data["choices"][0]["message"]["content"])
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
            json.dump(result_json, f, indent=4)
            
        # THE NEW UPDATED PRINT STATEMENT:
        print(f"✅ Success: {output_filename} | Time: {process_time}s | Prompt T: {prompt_tokens} | Comp T: {completion_tokens} | Cost: ${total_cost:.5f}")
        
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

def generate_summary_markdown(stats):
    print(f"\n📝 Generating {SUMMARY_FILE}...")
    
    summary = {}
    for effort in ["none", "medium", "high"]:
        effort_stats = [s for s in stats if s and s["effort"] == effort]
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
    md_content += "This table dynamically calculates the Token Usage, Financial Cost, and Processing Time based on the image resolution and OpenAI's Reasoning parameters.\n\n"
    md_content += "| Reasoning Effort | Avg Time/Image | Avg Prompt Tokens | Avg Completion Tokens | Avg Cost/Image | Extrapolated 100k Cost | Extrapolated 100k Time |\n"
    md_content += "|------------------|----------------|-------------------|-----------------------|----------------|------------------------|------------------------|\n"
    
    for effort in ["none", "medium", "high"]:
        if effort in summary:
            s = summary[effort]
            md_content += f"| **{effort.upper()}** | {s['avg_time']}s | {s['avg_prompt']} | {s['avg_comp']} | ${s['avg_cost']:.5f} | **${s['cost_100k']:,.2f}** | {s['time_100k_hours']:,.0f} hours |\n"

    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(md_content)

async def main():
    print("🚀 Starting Archival Batch Processor...")
    init_csv()
    
    files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    if not files:
        print(f"⚠️ No images found in '{INPUT_DIR}/'.")
        return

    stats = []
    try:
        async with httpx.AsyncClient() as client:
            for filename in files:
                for effort in ["none", "medium", "high"]:
                    stat = await process_image_effort(client, filename, effort)
                    if stat:
                        stats.append(stat)
    except KeyboardInterrupt:
        print("\n⚠️ Process interrupted by user! Generating summary for completed items...")
    finally:
        if stats:
            generate_summary_markdown(stats)
            print("🎉 Evaluation complete! Check 'evaluation_metrics.csv' and 'evaluation_summary.md'.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass