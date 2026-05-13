# 🏛️ Museum Archival AI Pipeline: Automated Metadata Generation

**Author:** YIN Renlong (KU Leuven)  
**Course:** Digital Cultural Heritage [F0YS9a]  

## 📖 Executive Summary
This repository contains the Proof of Concept (PoC) for the automated metadata generation pipeline discussed in my course paper. When digitizing massive archival collections (e.g., 100,000 cut 35mm color negatives), capturing "Scene-Referred" optical data successfully preserves the physical media but inadvertently creates a "Dark Archive." Without descriptive metadata, the collection is invisible to public search.

This Python-based middleware solves the 8,000-hour human cataloging bottleneck by orchestrating Multimodal Large Language Models (LLMs) to automatically generate structured, schema-compliant **Dublin Core** visual annotations.

## 🏗️ Architectural Shift: Why Multimodal LLMs?
Traditional museum workflows relied on specialized, narrow Vision APIs. However, as of early 2026, [Microsoft officially deprecated Azure Image Analysis](https://learn.microsoft.com/en-us/azure/ai-services/computer-vision/how-to/migrate-image-analysis), recommending enterprise clients migrate to Generative AI. 

Following this industry standard, this pipeline utilizes the **Azure OpenAI API (GPT-4 class)**. Unlike narrow AI, Multimodal LLMs possess zero-shot reasoning, allowing them to understand historical context, extract native OCR, and map outputs directly to institutional JSON schemas via strict Prompt Engineering.

## 📊 Evaluation & Resource Implications
To evaluate the financial and computational feasibility of processing 100,000 images, this pipeline was engineered to test three different LLM "Reasoning Efforts" (**None, Medium, High**). 

The script dynamically calculates token usage and extrapolated costs based on [Azure OpenAI Pricing algorithms](https://azure.microsoft.com/en-us/pricing/details/cognitive-services/openai-service/).

### 📂 Explore the Results:
*   👉 **[View the Extrapolated Cost Analysis (Summary)](evaluation_summary.md)**
*   👉 **[View the Raw CSV Benchmarking Data](evaluation_metrics.csv)**
*   👉 **[View the generated Dublin Core JSON Files](output_metadata/)**

## 💡 Key Academic Insights
1. **The "Medium" Reasoning Sweet Spot:** Empirical testing revealed that "Medium" reasoning was actually *cheaper* at scale than "None." Zero-shot models (None) compensated for their lack of reasoning by generating overly verbose descriptions (inflating Completion Tokens). 
2. **Mitigating Prompt-Induced Hallucinations:** When processing inverted Access Copies (DIPs), the "None" model blindly adhered to the system prompt, hallucinating the words "color negative" into positive images. Activating "Medium" reasoning allowed the model's internal Chain-of-Thought to override the prompt bias and correctly identify the asset type, proving that reasoning models are essential for curatorial accuracy.
3. **Provenance & Human-in-the-Loop:** All generated metadata is automatically tagged as `pending_human_review`. LLMs act as a high-speed triage layer, but institutional integrity requires a final human audit before CMS ingestion.

## 🚀 How to Run Locally
1. Clone the repository and install dependencies: `pip install -r requirements.txt`
2. Add your Azure credentials to a `.env` file (DO NOT commit this file).
3. Place sample JPEGs in `/input_images`
4. Run the asynchronous batch processor: `python batch_processor.py`
