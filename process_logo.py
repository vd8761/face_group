from PIL import Image
import shutil
import os

source = r"C:\Users\HP\.gemini\antigravity\brain\b13c77ae-db84-438c-bc7a-a18c09adfd0c\constellation_logo_1784011925274.png"
dest = r"d:\xampp\htdocs\face_grouping\frontend\src\assets\logo.png"

# Copy the new image over the old one
shutil.copyfile(source, dest)

# Make transparent
try:
    img = Image.open(dest)
    img = img.convert("RGBA")
    datas = img.getdata()
    
    newData = []
    # Target white/near-white pixels
    for item in datas:
        if item[0] > 240 and item[1] > 240 and item[2] > 240:
            newData.append((255, 255, 255, 0)) # transparent
        else:
            newData.append(item)
            
    img.putdata(newData)
    img.save(dest, "PNG")
    print("Successfully copied and made transparent.")
except Exception as e:
    print(f"Error processing image: {e}")
