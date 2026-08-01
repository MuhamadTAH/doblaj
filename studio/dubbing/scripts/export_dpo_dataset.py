import os
import json
from convex import ConvexClient

def export_dpo_dataset():
    convex_url = os.environ.get("CONVEX_URL")
    if not convex_url:
        print("Error: CONVEX_URL environment variable must be set.")
        print("Example: set CONVEX_URL=https://<your-convex-domain>.convex.cloud")
        return
        
    print(f"Connecting to Convex at {convex_url}...")
    client = ConvexClient(convex_url)
    
    # Note: The Convex Python client requires invoking predefined query functions.
    # Here we assume there are queries designed to fetch from these tables.
    # If you have different query names, please update them accordingly.
    print("Fetching translation attempts and user edits...")
    try:
        attempts = client.query("translation_attempts:list") 
        edits = client.query("user_edits:list") 
    except Exception as e:
        print(f"Failed to fetch data from Convex: {e}")
        print("Make sure you have queries like 'translation_attempts:list' defined in your convex/ backend.")
        return
    
    # Group by chunk_id
    data_by_chunk = {}
    
    for attempt in attempts:
        chunk_id = attempt.get("chunk_id")
        if not chunk_id:
            continue
            
        if chunk_id not in data_by_chunk:
            data_by_chunk[chunk_id] = {
                "prompt": attempt.get("prompt", ""),
                "rejected": [],
                "chosen": None,
                "passed_translation": None
            }
            
        # Ensure prompt is set
        if not data_by_chunk[chunk_id]["prompt"] and attempt.get("prompt"):
            data_by_chunk[chunk_id]["prompt"] = attempt.get("prompt")
            
        status = attempt.get("status")
        translation = attempt.get("translation")
        
        if status == "PASSED":
            data_by_chunk[chunk_id]["passed_translation"] = translation
        elif status and status.startswith("FAILED"):
            if translation:
                data_by_chunk[chunk_id]["rejected"].append(translation)
            
    # Apply user edits (human corrections)
    for edit in edits:
        chunk_id = edit.get("chunk_id")
        if chunk_id in data_by_chunk:
            # The human's final state overrides the AI's PASSED state
            # Adjust the key "final_text" to whatever column name is used in your DB
            final_text = edit.get("final_text") or edit.get("text") or edit.get("translation")
            if final_text:
                data_by_chunk[chunk_id]["chosen"] = final_text
            
    # For chunks without human edits, fallback chosen to the PASSED translation
    for chunk_id, data in data_by_chunk.items():
        if not data["chosen"]:
            data["chosen"] = data["passed_translation"]
            
    # Construct DPO triplets
    triplets = []
    for chunk_id, data in data_by_chunk.items():
        # We only create a triplet if we have both a chosen translation and at least one rejected translation
        if data["chosen"] and data["rejected"]:
            for rejected_text in data["rejected"]:
                triplets.append({
                    "prompt": data["prompt"],
                    "chosen": data["chosen"],
                    "rejected": rejected_text
                })
                
    output_file = os.path.join(os.path.dirname(__file__), "dpo_dataset.jsonl")
    
    print(f"Constructed {len(triplets)} (prompt, chosen, rejected) triplets.")
    print(f"Exporting dataset to {output_file}...")
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for triplet in triplets:
            f.write(json.dumps(triplet, ensure_ascii=False) + '\n')
            
    print("Export complete!")

if __name__ == "__main__":
    export_dpo_dataset()
