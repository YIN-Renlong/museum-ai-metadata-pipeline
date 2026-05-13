# 🏛️ Museum Archival AI Pipeline

**Author:** YIN Renlong (KU Leuven, Digital Humanities)
**Course:** Digital Cultural Heritage [F0YS9a]

## Overview
This repository contains the Proof of Concept (PoC) for the automated metadata generation pipeline discussed in my 10-page thesis. It addresses the "Semantic Gap" created when digitizing massive collections of color negatives (e.g., 100,000 uncatalogued images).

## Architecture
To solve the 8,000-hour human labor bottleneck, this pipeline utilizes an **Asynchronous Microservices Architecture**:
1. **Input:** Ingests Access Copies (DIPs) from the `input_images/` directory.
2. **Orchestration:** Uses Python `asyncio` and `httpx` to send concurrent, high-throughput requests to Microsoft Azure OpenAI.
3. **Validation:** System prompts force the Multimodal LLM to output strict JSON mapped to the **Dublin Core (DC)** schema.
4. **Provenance:** Injects an `ai_provenance` object into the JSON, tagging the data as `pending_human_review` to support a Human-in-the-Loop (HITL) archival workflow.
5. **Output:** Saves the structured metadata to `output_metadata/` for eventual ingestion into a museum CMS (e.g., Omeka S).

## How to Run Locally
1. Clone the repository.
2. Install dependencies: `pip install -r requirements.txt`
3. Add your Azure credentials to a `.env` file.
4. Place sample JPEGs in `/input_images`
5. Run the batch processor: `python batch_processor.py`
