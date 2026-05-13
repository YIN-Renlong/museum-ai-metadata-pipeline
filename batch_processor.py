import os
import json
import base64
import asyncio
import httpx
from dotenv import load_dotenv

# Load environment variables securely
load_dotenv()
API_KEY = os.getenv("AZURE_API_KEY")
ENDPOINT = os.getenv("AZURE_ENDPOINT")
MODEL = os.getenv("DEPLOYMENT_NAME")

INPUT_DIR = "input_images"
OUTPUT_DIR = "output_metadata"

# Function to encode image to base64
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

# The Async function to call Azure AI
async def process_image(client, filename):
    image_path = os.path.join(INPUT_DIR, filename)
    base64_image = encode_image(image_path)
    
    print(f"🔄 Processing: {filename} (AI is thinking...)")
    
    headers = {
        "api-key": API_KEY,
        "Content-Type": "application/json",
    }
    
    payload = {
        "model": MODEL,
        "response_format": { "type": "json_object" },
        "reasoning_effort": "medium",  # <-- INSTRUCTS THE AI TO "THINK" FIRST
        "max_completion_tokens": 15000, # <-- ALLOWS TOKEN BUFFER FOR INTERNAL REASONING
        "messages": [
            {
                "role": "system",
                "content": """You are an expert museum archivist processing digitized color negatives. 
                Analyze the image deeply before responding.
                Return ONLY a JSON object matching this exact structure:
                {
                    "dc:identifier": "filename",
                    "dc:title": "A provisional title",
                    "dc:description": "Detailed visual description of the scene.",
                    "dc:subject": ["tag1", "tag2", "tag3"],
                    "ai_provenance": {
                        "model_used": "azure-gpt-reasoning",
                        "review_status": "pending_human_review",
                        "warning": "Provisional AI data. Do not infer dates or names unless clearly visible."
                    }
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
    
    try:
        # Extended timeout because "reasoning" models take longer to think
        timeout = httpx.Timeout(connect=15.0, read=300.0, write=15.0, pool=15.0)
        
        response = await client.post(ENDPOINT, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        
        # Parse the JSON response
        result_json = json.loads(response.json()["choices"][0]["message"]["content"])
        
        # Save to output folder
        output_filename = filename.rsplit('.', 1)[0] + ".json"
        output_path = os.path.join(OUTPUT_DIR, output_filename)
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result_json, f, indent=4)
            
        print(f"✅ Success: Saved metadata to {output_filename}")
        
    except Exception as e:
        print(f"❌ Error processing {filename}: {e}")

# The Main Async Batch Runner
async def main():
    print("🚀 Starting Archival Batch Processor with Reasoning Capabilities...")
    
    files = [f for f in os.listdir(INPUT_DIR) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    
    if not files:
        print(f"⚠️ No images found in '{INPUT_DIR}/'.")
        return

    async with httpx.AsyncClient() as client:
        tasks = [process_image(client, f) for f in files]
        await asyncio.gather(*tasks)
        
    print("🎉 Batch processing complete! Check the 'output_metadata' folder.")

if __name__ == "__main__":
    asyncio.run(main())