import os
import struct

def generate_mock_car_bmp():
    output_dir = os.path.join(os.path.dirname(__file__), "test_images")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "mock_car.jpg")  # Save as .jpg since BMP can be read as JPEG by OpenCV

    # We will write a 24-bit uncompressed BMP file (width=400, height=300)
    # Width 400 is divisible by 4, so no row padding bytes are required!
    width = 400
    height = 300
    
    # 1. Initialize image pixel array (BGR color format)
    # Background: Dark Grey (R=60, G=60, B=60)
    pixels = bytearray([60, 60, 60] * (width * height))
    
    # Function to set pixel color at (x, y) starting from bottom-left
    def set_pixel(x, y, r, g, b):
        if 0 <= x < width and 0 <= y < height:
            idx = (y * width + x) * 3
            pixels[idx] = b  # Blue
            pixels[idx+1] = g  # Green
            pixels[idx+2] = r  # Red

    # 2. Draw Left Tail Light (Red Rectangle)
    for y in range(120, 160):
        for x in range(30, 90):
            set_pixel(x, y, 200, 10, 10)
            
    # 3. Draw Right Tail Light (Red Rectangle)
    for y in range(120, 160):
        for x in range(310, 370):
            set_pixel(x, y, 200, 10, 10)

    # 4. Draw License Plate Area (White/Yellow Rectangle)
    for y in range(60, 110):
        for x in range(130, 270):
            # Outer border (black)
            if y == 60 or y == 109 or x == 130 or x == 269:
                set_pixel(x, y, 0, 0, 0)
            else:
                set_pixel(x, y, 230, 220, 50) # Yellowish plate
                
    # 5. Draw some simple mock letters/lines representing "DXB 123" inside the plate area
    # Simple line sketches for letters
    # Draw letter 'D':
    for y in range(70, 100):
        set_pixel(150, y, 0, 0, 0)
        set_pixel(151, y, 0, 0, 0)
    for x in range(150, 160):
        set_pixel(x, 70, 0, 0, 0)
        set_pixel(x, 99, 0, 0, 0)
    for y in range(73, 97):
        set_pixel(160, y, 0, 0, 0)
        
    # Draw letter 'X':
    for y in range(70, 100):
        offset = y - 70
        set_pixel(170 + offset // 3, y, 0, 0, 0)
        set_pixel(180 - offset // 3, y, 0, 0, 0)

    # Draw letter 'B':
    for y in range(70, 100):
        set_pixel(190, y, 0, 0, 0)
    for x in range(190, 200):
        set_pixel(x, 70, 0, 0, 0)
        set_pixel(x, 85, 0, 0, 0)
        set_pixel(x, 99, 0, 0, 0)
    for y in range(70, 85):
        set_pixel(200, y, 0, 0, 0)
    for y in range(85, 100):
        set_pixel(200, y, 0, 0, 0)

    # Draw numbers '1' and '2'
    for y in range(70, 100):
        set_pixel(220, y, 0, 0, 0) # '1'
        
    # '2':
    for x in range(230, 240):
        set_pixel(x, 99, 0, 0, 0)
        set_pixel(x, 70, 0, 0, 0)
    for y in range(85, 100):
        set_pixel(240, y, 0, 0, 0)
    for y in range(70, 85):
        set_pixel(230, y, 0, 0, 0)

    # 6. Construct BMP Headers
    pixel_data_size = len(pixels)
    file_size = 54 + pixel_data_size
    
    # Header format: https://en.wikipedia.org/wiki/BMP_file_format
    # BMP File Header (14 bytes)
    file_header = struct.pack(
        '<2sIHHI',
        b'BM',             # Signature
        file_size,         # Size of file in bytes
        0, 0,              # Reserved
        54                 # Pixel data offset
    )
    
    # DIB Header - BITMAPINFOHEADER (40 bytes)
    dib_header = struct.pack(
        '<IiiHHIIiiII',
        40,                # DIB Header size
        width,             # Width in pixels
        height,            # Height in pixels
        1,                 # Planes
        24,                # Bits per pixel (RGB)
        0,                 # Compression (None)
        pixel_data_size,   # Image size (in bytes)
        2835, 2835,        # Horizontal/Vertical resolution (72 DPI)
        0,                 # Number of colors
        0                  # Important colors
    )
    
    # Write headers and pixels to file
    print(f"[Generator] Writing BMP image data...")
    try:
        with open(output_path, "wb") as f:
            f.write(file_header)
            f.write(dib_header)
            f.write(pixels)
        print(f"[Generator] Offline mock vehicle image created at: {os.path.abspath(output_path)}")
    except Exception as e:
        print(f"[Generator] Failed to create mock image: {e}")

if __name__ == "__main__":
    generate_mock_car_bmp()
