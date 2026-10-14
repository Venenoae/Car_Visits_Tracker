import os
import sys
import time
import random
import requests

# FastAPI backend url
API_URL = "http://127.0.0.1:8000/api/capture"
IMAGE_DIR = os.path.join(os.path.dirname(__file__), "test_images")

def check_setup():
    """Ensure test images folder exists and has at least one image"""
    os.makedirs(IMAGE_DIR, exist_ok=True)
    images = [f for f in os.listdir(IMAGE_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    if not images:
        print("\n" + "="*60)
        print("  WARNING: No test images found in 'edge/test_images/' directory!")
        print("  Please place some JPEG/PNG photos of cars (with visible license plates)")
        print(f"  into the folder: {os.path.abspath(IMAGE_DIR)}")
        print("  Then run this script again to simulate a camera trigger.")
        print("="*60 + "\n")
        return None
    return images

def send_test_capture(image_name: str, zone: str, direction: str):
    """Sends a single image snapshot to the backend API"""
    image_path = os.path.join(IMAGE_DIR, image_name)
    print(f"\n[Simulator] Simulating trigger: {image_name} passing through {zone} Gate ({direction})...")
    
    if not os.path.exists(image_path):
        print(f"Error: File not found at {image_path}")
        return

    # Prepare payload
    payload = {
        "zone": zone,
        "direction": direction
    }
    
    try:
        with open(image_path, "rb") as img_file:
            files = {
                "file": (image_name, img_file, "image/jpeg")
            }
            
            start_time = time.time()
            response = requests.post(API_URL, data=payload, files=files)
            duration = time.time() - start_time
            
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    print(f"[Simulator] Response received in {duration:.2f}s:")
                    print(f"            - Status: SUCCESS")
                    print(f"            - Plate Recognized: '{result.get('plate')}'")
                    print(f"            - Color Classified: '{result.get('color')}'")
                    print(f"            - Brand Classified: '{result.get('brand')}'")
                    print(f"            - Database Visit ID: {result.get('visit_id')}")
                else:
                    print(f"[Simulator] API processed image, but recognition failed:")
                    print(f"            - Detail: {result.get('detail')}")
                    print("\n            [TIP] The YOLOv8 AI model is trained on real-world photos.")
                    print("                  Please copy a real photo of a car (containing a visible license plate)")
                    print(f"                  into the folder '{os.path.abspath(IMAGE_DIR)}' and run the script again!")
            else:
                print(f"[Simulator] Response Error (Status Code: {response.status_code}):")
                print(f"            {response.text}")
                
    except requests.exceptions.ConnectionError:
        print("[Simulator] Connection Error: Could not connect to backend server at http://127.0.0.1:8000.")
        print("            Please ensure your FastAPI backend is running: 'uvicorn main:app --reload'")
    except Exception as e:
        print(f"[Simulator] An unexpected error occurred: {e}")

if __name__ == "__main__":
    images = check_setup()
    if not images:
        sys.exit(0)
        
    print("Select simulation mode:")
    print("1. Send a single random image from test_images folder")
    print("2. Send all images sequentially")
    
    choice = input("Enter choice (1 or 2): ").strip()
    
    zones = ["Zone A", "Zone B"]
    directions = ["Entry", "Exit"]
    
    if choice == "2":
        for img in images:
            # Cycle/randomize directions and zones for variety
            z = random.choice(zones)
            d = random.choice(directions)
            send_test_capture(img, z, d)
            print("Waiting 3 seconds before next image...")
            time.sleep(3)
    else:
        img = random.choice(images)
        z = random.choice(zones)
        d = random.choice(directions)
        send_test_capture(img, z, d)
