import os
from ai_pipeline import run_ai_pipeline

test_img = r"d:\Veneno\CallMyCar\Car_Visits_Tracker\backend\uploads\ZoneA_Exit_20260924_170638_582826.jpg"
if os.path.exists(test_img):
    print("Testing image:", test_img)
    result = run_ai_pipeline(test_img)
    print("AI Result:", result)
else:
    print("Image not found!")
