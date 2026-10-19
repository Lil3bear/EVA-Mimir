"""Render the application's validated primitive scene, never executable model code."""
import json
import sys
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor

with open(sys.argv[1], encoding="utf-8") as stream:
    scene = json.load(stream)
scale = 0.6
w, h = scene["width"], scene["height"]
c = canvas.Canvas(sys.argv[2], pagesize=(w * scale, h * scale), invariant=1)
c.scale(scale, scale)
for shape in scene["shapes"]:
    kind = shape["type"]
    stroke = shape.get("stroke", "none")
    fill = shape.get("fill", "none")
    if stroke != "none":
        c.setStrokeColor(HexColor(stroke))
    if fill != "none":
        c.setFillColor(HexColor(fill))
    c.setLineWidth(2 if kind == "path" else 1)
    if kind == "rect":
        if shape["w"] <= 0 or shape["h"] <= 0:
            continue
        radius = min(4, shape["w"]/2, shape["h"]/2)
        c.roundRect(shape["x"], h-shape["y"]-shape["h"], shape["w"], shape["h"], radius,
                    fill=int(fill != "none"), stroke=int(stroke != "none"))
    elif kind == "text":
        c.setFont("Helvetica", shape["size"])
        draw = {"middle": c.drawCentredString, "end": c.drawRightString}.get(shape["anchor"], c.drawString)
        draw(shape["x"], h-shape["y"], shape["text"])
    elif kind == "line":
        c.line(shape["x1"], h-shape["y1"], shape["x2"], h-shape["y2"])
    elif kind == "path":
        points = shape["points"]
        p = c.beginPath()
        p.moveTo(points[0][0], h-points[0][1])
        for x, y in points[1:]:
            p.lineTo(x, h-y)
        c.drawPath(p)
        x, y = points[-1]
        a, b = points[-2]
        dx, dy = x-a, y-b
        length = (dx*dx+dy*dy)**0.5
        if length:
            ux, uy = dx/length, dy/length
            for side in [-1, 1]:
                c.line(x, h-y, x-9*ux+side*4*uy, h-(y-9*uy-side*4*ux))
c.showPage()
c.save()
