"""Planche contact : planche.py "<glob d'images>" sortie.png [colonnes] [largeur_vignette]"""
import glob
import sys

from PIL import Image, ImageDraw

fs = sorted(glob.glob(sys.argv[1]))
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 10
tw = int(sys.argv[4]) if len(sys.argv) > 4 else 270
ims = [Image.open(f).convert("RGB") for f in fs]
th = int(tw * ims[0].height / ims[0].width)
rows = (len(ims) + cols - 1) // cols
o = Image.new("RGB", (cols * tw, rows * (th + 22)), (20, 20, 20))
d = ImageDraw.Draw(o)
for i, (f, im) in enumerate(zip(fs, ims)):
    x, y = (i % cols) * tw, (i // cols) * (th + 22)
    o.paste(im.resize((tw, th)), (x, y + 22))
    d.text((x + 4, y + 4), f.split("/")[-1], fill=(255, 255, 0))
o.save(sys.argv[2])
