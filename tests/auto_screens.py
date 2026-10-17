"""Independent fictional client screens; recognition imports none of this."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def font(size, serif=False):
    paths = ('C:/Windows/Fonts/timesbd.ttf' if serif else 'C:/Windows/Fonts/arial.ttf',
             '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    return ImageFont.truetype(next(p for p in paths if Path(p).exists()), size)


def screen(style='green'):
    purple = style == 'purple'
    image = Image.new('RGB', (1400, 850) if purple else (1000, 650), '#302045' if purple else '#105e4d')
    draw = ImageDraw.Draw(image)
    board = ('Ac', '7d', 'Ts', '2h', '9c')
    hand = ('Kc', 'Kh')
    suit_path = next(p for p in ('C:/Windows/Fonts/seguisym.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf') if Path(p).exists())
    symbols = dict(zip('cdhs', '♣♦♥♠'))
    def card(value, x, y):
        rank, suit = value
        color = {'c':'#00802b','d':'#2559c4','h':'#bb1234','s':'#121212'}[suit] if purple else '#bb1234' if suit in 'hd' else '#121212'
        draw.rounded_rectangle((x,y,x+80,y+112),radius=6,fill='#fffdf5',outline='#d8d8d8',width=1)
        draw.text((x+6,y+3),'10' if rank=='T' else rank,font=font(38,serif=purple),fill=color)
        symbol=Image.new('RGB',(100,110),'#fffdf5');d=ImageDraw.Draw(symbol)
        sf=ImageFont.truetype(suit_path,65);d.text((0,0),symbols[suit],font=sf,fill=color)
        box=Image.new('L',symbol.size);ImageDraw.Draw(box).text((0,0),symbols[suit],font=sf,fill=255)
        crop=symbol.crop(box.getbbox());crop.thumbnail((52,49))
        image.paste(crop,(x+40-crop.width//2,y+84-crop.height//2))
    bx,by=(130,350) if purple else (260,220)
    for i,value in enumerate(board):card(value,bx+i*93,by)
    hx,hy=(1050,160) if purple else (450,460)
    for i,value in enumerate(hand):card(value,hx+i*88,hy)
    draw.text((hx,hy+116),'Hero',font=font(22),fill='white')
    draw.text((hx,hy+147),'$200',font=font(22),fill='white')
    draw.text((40,20),'Hero',font=font(24),fill='white')
    draw.text((bx+110,by+122),'Pot: $125.50',font=font(25),fill='white')
    draw.text((bx,by-100),'Alpha',font=font(24),fill='white')
    draw.text((bx,by-68),'$240',font=font(24),fill='white')
    draw.text((bx+340,by-100),'Beta',font=font(24),fill='white')
    draw.text((bx+340,by-68),'$120',font=font(24),fill='white')
    return image,board,hand
