from PIL import Image

def make_transparent(img_path):
    try:
        img = Image.open(img_path)
        img = img.convert("RGBA")
        datas = img.getdata()
        
        newData = []
        # Target white/near-white pixels
        for item in datas:
            # item is (R, G, B, A)
            if item[0] > 240 and item[1] > 240 and item[2] > 240:
                newData.append((255, 255, 255, 0)) # transparent
            else:
                newData.append(item)
                
        img.putdata(newData)
        img.save(img_path, "PNG")
        print("Successfully made logo transparent.")
    except Exception as e:
        print(f"Error processing image: {e}")

if __name__ == "__main__":
    make_transparent(r"d:\xampp\htdocs\face_grouping\frontend\src\assets\logo.png")
