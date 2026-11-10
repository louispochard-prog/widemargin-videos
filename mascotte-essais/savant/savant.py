"""Essai de mascotte « savant » pour Wide Margin (proposition, PAS en production).

Trois personnages originaux, dessinés par calcul (skia-python), même interface que VagueVisage :
    s = Savant("prof")            # "prof", "inventeur" ou "moderne"
    s.draw(canvas, t, mouth=0..1, wink=False, appear=1.0)
Position par défaut : coin haut droit, dans la boîte réservée x 760-1015, y 275-425 (CHARTE.md).
"""
import math
import numpy as np
import skia


def C(hexs, a=1.0):
    hexs = hexs.lstrip("#")
    r, g, b = (int(hexs[i:i + 2], 16) for i in (0, 2, 4))
    return skia.Color4f(r / 255, g / 255, b / 255, a).toColor()


def fill(col, a=1.0, blur=0):
    p = skia.Paint(AntiAlias=True, Color=C(col, a))
    if blur:
        p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur))
    return p


def pen(col, w, a=1.0):
    return skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=w,
                      StrokeCap=skia.Paint.kRound_Cap, StrokeJoin=skia.Paint.kRound_Join, Color=C(col, a))


def smooth(pts, closed=True):
    """Chemin lisse passant par les points (Catmull-Rom -> cubiques)."""
    P = [np.asarray(p, float) for p in pts]
    n = len(P)
    path = skia.Path()
    path.moveTo(*P[0])
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        p0 = P[(i - 1) % n] if (closed or i > 0) else P[0]
        p1, p2 = P[i], P[(i + 1) % n]
        p3 = P[(i + 2) % n] if (closed or i + 2 < n) else P[-1]
        c1 = p1 + (p2 - p0) / 6
        c2 = p2 - (p3 - p1) / 6
        path.cubicTo(c1[0], c1[1], c2[0], c2[1], p2[0], p2[1])
    if closed:
        path.close()
    return path


def oval(cx, cy, rx, ry):
    return skia.Rect.MakeLTRB(cx - rx, cy - ry, cx + rx, cy + ry)


SKIN, SKIN_SH, CHEEK = "#F0C6A0", "#D49A73", "#E58F78"
INK = "#1B1D29"
TEAL, AMBER = "#3EC1C9", "#F2B134"

STYLES = {
    # Le Professeur : longs cheveux blancs jusqu'aux épaules, lunettes rondes dorées, courte barbe blanche,
    # nœud papillon aux couleurs du compte (turquoise -> ambre).
    "prof": dict(hair="#F3F1EA", hair_sh="#C9C5BA", jacket="#2B3552", glasses="#C8922E", glasses_shape="round",
                 hair_style="long", beard=True, neck="bow"),
    # L'Inventeur : crâne dégarni, deux nuages de cheveux blancs ébouriffés sur les côtés, lunettes de soudeur
    # ambre relevées sur le front, joues rouges, blouse blanche.
    "inventeur": dict(hair="#F5F4EE", hair_sh="#C4C2BC", jacket="#ECEBE6", glasses=None, glasses_shape=None,
                      hair_style="tufts", beard=False, neck="coat"),
    # Le Moderne : cheveux blancs tirés en arrière en queue de cheval, lunettes carrées noires,
    # petit bouc blanc, col roulé noir.
    "moderne": dict(hair="#EEEDE8", hair_sh="#BDBBB4", jacket="#2A2C36", glasses="#15161C", glasses_shape="square",
                    hair_style="pony", beard="goatee", neck="turtle"),
}


class Savant:
    CORNER = dict(anchor=(888.0, 342.0), scale=0.66)   # boîte ~ x 815-962, y 276-425

    def __init__(self, style="prof", anchor=None, scale=None, seed=0):
        self.s = STYLES[style]
        self.style = style
        self.anchor = anchor or self.CORNER["anchor"]
        self.scale = scale or self.CORNER["scale"]
        self.seed = seed
        self._e = 0.0

    @staticmethod
    def _pop(a):
        a = min(1.0, max(0.0, a))
        c1, c3 = 1.70158, 2.70158
        return 1 + c3 * (a - 1) ** 3 + c1 * (a - 1) ** 2 if a < 1 else 1.0

    def draw(self, canvas, t, mouth=0.0, wink=False, look=None, appear=1.0, alpha=1.0, anchor=None, scale=None,
             **_ignored):
        if appear <= 0 or alpha <= 0:
            return
        self._e = 0.8 * self._e + 0.2 * mouth
        e = self._e
        ax, ay = anchor or self.anchor
        sc = (scale or self.scale) * self._pop(appear)
        canvas.save()
        canvas.translate(ax, ay)
        canvas.scale(sc, sc)
        if alpha < 1:
            canvas.saveLayerAlpha(None, int(alpha * 255))
        # ombre portée douce pour la lisibilité sur n'importe quel décor
        canvas.drawOval(oval(0, 8, 118, 128), fill("#000000", 0.35, blur=18))
        self._bust(canvas, t, e)
        # la tête bouge un peu : balancement lent + hochement quand la voix porte
        tilt = 3.0 * math.sin(t * 1.3 + self.seed) + 4.0 * e * math.sin(t * 7.0)
        bob = 2.0 * math.sin(t * 2.6) - 3.0 * e
        canvas.save()
        canvas.translate(0, 40 + bob)
        canvas.rotate(tilt)
        canvas.translate(0, -40)
        self._head(canvas, t, mouth, e, wink, look)
        canvas.restore()
        if alpha < 1:
            canvas.restore()
        canvas.restore()

    # ------------------------------------------------------------------ buste
    def _bust(self, c, t, e):
        s = self.s
        sh = smooth([(-112, 150), (-96, 104), (-50, 84), (0, 80), (50, 84), (96, 104), (112, 150)], closed=False)
        sh.lineTo(-112, 150)
        sh.close()
        c.save()
        c.clipRect(skia.Rect.MakeLTRB(-130, 60, 130, 132))
        c.drawPath(sh, fill(s["jacket"]))
        if s["neck"] == "coat":   # blouse blanche + revers + stylos
            c.drawPath(sh, pen("#B9B8B2", 3))
            for side in (-1, 1):
                lap = smooth([(side * 14, 82), (side * 34, 112), (side * 58, 132), (side * 46, 96)])
                c.drawPath(lap, fill("#D9D8D2"))
            c.drawRect(skia.Rect.MakeLTRB(-16, 80, 16, 132), fill("#5B6B8C"))
            c.drawRect(skia.Rect.MakeLTRB(52, 104, 56, 126), fill(TEAL))
            c.drawRect(skia.Rect.MakeLTRB(60, 106, 64, 126), fill(AMBER))
        elif s["neck"] == "turtle":
            pass
        else:  # chemise + nœud papillon dégradé turquoise -> ambre
            c.drawPath(smooth([(-26, 78), (26, 78), (12, 118), (0, 124), (-12, 118)]), fill("#F2EEE4"))
            grad = skia.GradientShader.MakeLinear([skia.Point(-26, 0), skia.Point(26, 0)], [C(TEAL), C(AMBER)])
            bow = skia.Path()
            bow.moveTo(0, 96); bow.lineTo(-24, 84); bow.lineTo(-24, 108); bow.close()
            bow.moveTo(0, 96); bow.lineTo(24, 84); bow.lineTo(24, 108); bow.close()
            p = skia.Paint(AntiAlias=True, Shader=grad)
            c.drawPath(bow, p)
            c.drawCircle(0, 96, 6, fill(AMBER))
        c.restore()

    # ------------------------------------------------------------------ tête
    def _head(self, c, t, mouth, e, wink, look):
        s = self.s
        sway = 3.0 * math.sin(t * 1.7 + 0.5)
        # cheveux de derrière
        if s["hair_style"] == "long":
            back = smooth([(0, -84), (52, -76), (84, -40), (94, 10), (98, 60), (92 + sway, 96), (60, 104),
                           (40, 70), (-40, 70), (-60, 104), (-92 + sway, 96), (-98, 60), (-94, 10), (-84, -40),
                           (-52, -76)])
            c.drawPath(back, fill(s["hair"]))
            for k, x in enumerate((70, 80, 88, -70, -80, -88)):
                sg = 1 if x > 0 else -1
                c.drawPath(smooth([(x - sg * 10, -10), (x + sway * 0.5, 40), (x + sg * 4 + sway, 92)], closed=False),
                           pen(s["hair_sh"], 3))
        elif s["hair_style"] == "pony":
            back = smooth([(0, -84), (50, -74), (68, -36), (68, 20), (56, 50), (-56, 50), (-68, 20), (-68, -36),
                           (-50, -74)])
            c.drawPath(back, fill(s["hair_sh"]))
        # oreilles
        for sg in (-1, 1):
            c.drawOval(oval(sg * 58, 8, 11, 16), fill(SKIN_SH))
            c.drawOval(oval(sg * 57, 8, 8, 12), fill(SKIN))
        # cou + visage
        if s["neck"] != "turtle":
            c.drawRect(skia.Rect.MakeLTRB(-18, 50, 18, 86), fill(SKIN_SH))
        if s["neck"] == "turtle":
            col = skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(-30, 46, 30, 96), 12, 12)
            c.drawRRect(col, fill("#2A2C36"))
            for k in range(5):
                c.drawLine(-26, 62 + 7 * k, 26, 62 + 7 * k, pen("#3A3D4A", 2))
        face = smooth([(0, -74), (40, -66), (58, -30), (56, 20), (40, 58), (0, 76), (-40, 58), (-56, 20),
                       (-58, -30), (-40, -66)])
        c.drawPath(face, fill(SKIN))
        c.save(); c.clipPath(face, doAntiAlias=True)
        c.drawOval(oval(-14, -30, 30, 26), fill("#FFE3C8", 0.45, blur=10))     # reflet du front
        c.drawOval(oval(30, 40, 40, 40), fill(SKIN_SH, 0.35, blur=14))        # ombre de joue
        c.restore()
        # joues
        a_cheek = 0.55 if self.style == "inventeur" else 0.32
        for sg in (-1, 1):
            c.drawOval(oval(sg * 32, 24, 11, 7), fill(CHEEK, a_cheek, blur=3))
        # cheveux de devant
        if s["hair_style"] == "long":
            for sg in (-1, 1):
                lock = smooth([(sg * 2, -80), (sg * 34, -76), (sg * 58, -52), (sg * 66, -10), (sg * 62, 30),
                               (sg * 54, -6), (sg * 44, -44), (sg * 14, -66)])
                c.drawPath(lock, fill(s["hair"]))
                c.drawPath(smooth([(sg * 10, -70), (sg * 40, -58), (sg * 56, -24)], closed=False),
                           pen(s["hair_sh"], 2.5))
        elif s["hair_style"] == "tufts":
            c.drawPath(smooth([(-40, -66), (0, -76), (40, -66), (20, -72), (-20, -72)]), fill(SKIN_SH, 0.25))
            for sg in (-1, 1):
                puffs = [(60, -40, 20), (74, -22, 22), (70, 2, 20), (82, -46, 16), (88, -10, 17), (60, 18, 15),
                         (50, -56, 15)]
                for dx, dy, r in puffs:
                    w = 1.5 * math.sin(t * 3 + dx + dy)
                    c.drawCircle(sg * (dx + w), dy, r + 3, fill(s["hair_sh"]))
                for dx, dy, r in puffs:
                    w = 1.5 * math.sin(t * 3 + dx + dy)
                    c.drawCircle(sg * (dx + w), dy, r, fill(s["hair"]))
                for dx, dy, r in puffs[:4]:
                    c.drawPath(smooth([(sg * (dx - 6), dy - 4), (sg * dx, dy - 9), (sg * (dx + 7), dy - 5)],
                                      closed=False), pen(s["hair_sh"], 2))
            # trois cheveux rebelles sur le crâne
            for k, x in enumerate((-8, 2, 12)):
                c.drawPath(smooth([(x, -72), (x - 6 + 2 * math.sin(t * 4 + k), -92), (x + 4, -100)], closed=False),
                           pen(s["hair_sh"], 2.5))
            # lunettes de soudeur relevées sur le front
            c.drawRect(skia.Rect.MakeLTRB(-56, -60, 56, -50), fill("#5A4632"))
            for sg in (-1, 1):
                c.drawCircle(sg * 22, -56, 17, fill("#6B5435"))
                c.drawCircle(sg * 22, -56, 12, fill(AMBER))
                c.drawCircle(sg * 22 - 4, -60, 4, fill("#FFF3C8", 0.8))
        elif s["hair_style"] == "pony":
            cap = smooth([(-58, -24), (-50, -60), (-20, -80), (20, -82), (50, -64), (60, -26), (48, -46),
                          (20, -62), (-20, -62), (-48, -46)])
            c.drawPath(cap, fill(s["hair"]))
            for k in range(5):
                x = -36 + 18 * k
                c.drawPath(smooth([(x * 0.6, -76), (x, -62), (x * 1.15, -46)], closed=False), pen(s["hair_sh"], 2))
        self._face(c, t, mouth, e, wink, look)

    def _face(self, c, t, mouth, e, wink, look):
        s = self.s
        # clignement toutes les ~3,9 s
        ph = (t + 0.41 * self.seed) % 3.9
        blink = 1.0 - (max(0.0, 1 - abs(ph - 0.08) / 0.08) if ph < 0.16 else 0.0)
        lx, ly = look if look is not None else (2.0 * math.sin(t * 0.7), 1.2 * math.sin(t * 0.9))
        brow_up = 5 * e + (2 if wink else 0)
        eyes = ((-22, -6), (22, -6))
        for i, (ex, ey) in enumerate(eyes):
            closed = wink and i == 1
            if closed:
                c.drawPath(smooth([(ex - 9, ey + 1), (ex, ey - 5), (ex + 9, ey + 1)], closed=False), pen(INK, 3.2))
            else:
                h = 7.5 * max(0.1, blink)
                c.drawOval(oval(ex, ey, 9.5, h), fill("#FFFFFF"))
                if blink > 0.35:
                    c.drawCircle(ex + lx, ey + ly + 0.5, 4.6, fill(INK))
                    c.drawCircle(ex + lx + 1.6, ey + ly - 1.4, 1.4, fill("#FFFFFF"))
            # sourcils blancs broussailleux (ou gris foncé pour le moderne)
            sg = -1 if i == 0 else 1
            lift = brow_up - (3 if closed else 0)
            bcol = s["hair"] if self.style != "moderne" else "#8F8E8A"
            brow = smooth([(ex - sg * 14, ey - 14 - lift), (ex, ey - 21 - lift), (ex + sg * 14, ey - 18 - lift * 0.6),
                           (ex + sg * 13, ey - 13 - lift * 0.6), (ex, ey - 15 - lift), (ex - sg * 13, ey - 10 - lift)])
            c.drawPath(brow, fill(bcol))
            c.drawPath(brow, pen(s["hair_sh"], 1.5))
        # lunettes
        if s["glasses_shape"] == "round":
            for ex, ey in eyes:
                c.drawCircle(ex, ey, 16, fill("#FFFFFF", 0.10))
                c.drawCircle(ex, ey, 16, pen(s["glasses"], 3.4))
                c.drawPath(smooth([(ex - 9, ey - 8), (ex - 3, ey - 12)], closed=False), pen("#FFFFFF", 2, 0.7))
            c.drawPath(smooth([(-6, -9), (0, -13), (6, -9)], closed=False), pen(s["glasses"], 3))
            c.drawLine(-38, -8, -56, -4, pen(s["glasses"], 3))
            c.drawLine(38, -8, 56, -4, pen(s["glasses"], 3))
        elif s["glasses_shape"] == "square":
            for ex, ey in eyes:
                r = skia.RRect.MakeRectXY(skia.Rect.MakeLTRB(ex - 18, ey - 13, ex + 18, ey + 12), 5, 5)
                c.drawRRect(r, fill("#FFFFFF", 0.10))
                c.drawRRect(r, pen(s["glasses"], 5))
            c.drawLine(-4, -9, 4, -9, pen(s["glasses"], 4))
            c.drawLine(-40, -9, -56, -6, pen(s["glasses"], 4))
            c.drawLine(40, -9, 56, -6, pen(s["glasses"], 4))
        # nez
        nose = 1.25 if self.style == "inventeur" else 1.0
        c.drawPath(smooth([(-2, 2), (5 * nose, 18 * nose), (-3, 22 * nose)], closed=False), pen(SKIN_SH, 3.4))
        if self.style == "inventeur":
            c.drawOval(oval(1, 18, 8, 6), fill(CHEEK, 0.45, blur=2))
        # bouche + barbe (la mâchoire descend avec la voix)
        m = min(1.0, max(0.0, mouth))
        mh = 3 + 26 * m
        my = 40
        if s["beard"] is True:
            jaw = 0.5 * mh
            beard = smooth([(-54, 14), (-46, 50), (-26, 78 + jaw), (0, 90 + jaw), (26, 78 + jaw), (46, 50), (54, 14),
                            (40, 36), (22, 34), (0, 30), (-22, 34), (-40, 36)])
            c.drawPath(beard, fill(s["hair"]))
            for x in (-30, -12, 8, 26):
                c.drawPath(smooth([(x, 52 + jaw * 0.6), (x + 2, 70 + jaw)], closed=False), pen(s["hair_sh"], 2))
            # moustache courte
            c.drawPath(smooth([(-20, 33), (-6, 28), (0, 31), (6, 28), (20, 33), (8, 36), (0, 34), (-8, 36)]),
                       fill(s["hair"]))
            c.drawPath(smooth([(-20, 33), (-6, 28), (0, 31), (6, 28), (20, 33), (8, 36), (0, 34), (-8, 36)]),
                       pen(s["hair_sh"], 1.5))
            my = 39
        elif s["beard"] == "goatee":
            jaw = 0.5 * mh
            gt = smooth([(-14, 50 + jaw), (0, 46 + jaw), (14, 50 + jaw), (10, 70 + jaw), (0, 76 + jaw),
                         (-10, 70 + jaw)])
            c.drawPath(gt, fill(s["hair"]))
            c.drawPath(gt, pen(s["hair_sh"], 1.5))
        self._mouth(c, my, m, mh, wink)

    def _mouth(self, c, my, m, mh, wink):
        if m < 0.08:
            if wink:   # sourire en coin du clin d'œil final
                c.drawPath(smooth([(-13, my), (0, my + 6), (15, my - 4)], closed=False), pen("#7A2E25", 3.4))
            else:
                c.drawPath(smooth([(-11, my), (0, my + 4), (11, my)], closed=False), pen("#7A2E25", 3.4))
            return
        w = 13 + 5 * m
        p = skia.Path()
        p.moveTo(-w, my); p.quadTo(0, my - 3, w, my)
        p.quadTo(w * 0.9, my + mh, 0, my + mh); p.quadTo(-w * 0.9, my + mh, -w, my)
        c.drawPath(p, fill("#5A1E1A"))
        c.save(); c.clipPath(p, doAntiAlias=True)
        c.drawRect(skia.Rect.MakeLTRB(-w, my - 4, w, my + 2.5), fill("#FFFFFF"))
        c.drawOval(oval(0, my + mh, 7, 5), fill("#D9706A"))
        c.restore()
