from PIL import Image

im = Image.open(r"d:\Veneno\CallMyCar\Car_Visits_Tracker\backend\uploads\ZoneA_Entry_20260924_173101_775402.jpg")
w, h = im.size
print("Image dimensions:", w, h)

# In the 1280x720 image, the Suzuki is on the right side:
# x from ~950 to 1250, y from ~350 to 600
im.crop((950, 350, 1250, 600)).save(r"d:\Veneno\CallMyCar\Car_Visits_Tracker\backend\uploads\crop_suzuki2.jpg")

# The white Toyota is in the middle:
# x from ~500 to 700, y from ~350 to 580
im.crop((500, 350, 700, 580)).save(r"d:\Veneno\CallMyCar\Car_Visits_Tracker\backend\uploads\crop_toyota2.jpg")
print("Saved crops.")
