from PIL import Image

# ★ 修改成本地图片路径（推荐正斜杠）
png_path = "C:/Users/admin/vscode/CCCC/cccc_image.webp"

img = Image.open(png_path)
img = img.convert("RGBA")

ico_path = "icon.ico"

img.save(
    ico_path,
    format="ICO",
    sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)]
)

print("已生成 icon.ico ！请在当前目录查看。")
