import cv2

img = cv2.imread(r"d:\Veneno\CallMyCar\Car_Visits_Tracker\backend\uploads\ZoneA_Entry_20260924_173101_775402.jpg")
# Crop the white car parked outside (around x: 400-550, y: 360-570)
# In image: white car is center-left: x from 400 to 540, y from 370 to 570
# Let's crop the center area
h, w, _ = img.shape
crop_toyota = img[350:580, 400:540]
cv2.imwrite(r"d:\Veneno\CallMyCar\Car_Visits_Tracker\backend\uploads\crop_toyota.jpg", crop_toyota)

# Crop the gold Suzuki Dzire on the right (x: 770 to 970, y: 370 to 580)
crop_suzuki = img[370:580, 770:970]
cv2.imwrite(r"d:\Veneno\CallMyCar\Car_Visits_Tracker\backend\uploads\crop_suzuki.jpg", crop_suzuki)

print("Saved crop_toyota.jpg and crop_suzuki.jpg")
