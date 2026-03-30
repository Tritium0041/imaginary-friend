
import json
import os
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor, white, black, grey

# 注册中文字体和Emoji字体
FONT_PATH = "./wqy-microhei.ttc"
pdfmetrics.registerFont(TTFont('MainFont', FONT_PATH))
EMOJI_FONT_PATH = "./Symbola.ttf"
pdfmetrics.registerFont(TTFont('EmojiFont', EMOJI_FONT_PATH))

class CardRenderer:
    def __init__(self, canvas_obj):
        self.c = canvas_obj
        self.width = 63 * mm
        self.height = 88 * mm
        self.corner_radius = 3 * mm
        
        # 颜色配置
        self.colors = {
            "古代时代": HexColor("#ba5653"), # 古铜色
            "近代时代": HexColor("#618f98"), # 工业蓝
            "未来时代": HexColor("#011a4b"), # 科技蓝
            "function": HexColor("#508D4E"), # 功能绿
            "event": HexColor("#D89216"),    # 事件橙
            "header_bg": HexColor("#F5F5F5"),
            "text_main": HexColor("#333333")
        }
    


    def is_emoji(self, char):
        """检查字符是否为Emoji"""
        # Emoji的Unicode范围
        emoji_ranges = [
            (0x1F000, 0x1F9FF),  # 杂项符号和图形
            (0x1F600, 0x1F64F),  # 表情符号
            (0x1F300, 0x1F5FF),  # 符号和象形文字
            (0x2600,  0x26FF),   # 杂项符号
            (0x2700,  0x27BF),   # 装饰符号
            (0xFE00,  0xFE0F),   # 变体选择符
            (0x1F900, 0x1F9FF),  # 补充符号和图形
            (0x1F1E0, 0x1F1FF),  # 国旗
        ]
        
        code = ord(char)
        for start, end in emoji_ranges:
            if start <= code <= end:
                return True
        return False
    
    def draw_text_with_emoji_switch(self, text, x, y, font_size):
        """绘制文本，遇到Emoji时切换字体"""
        current_x = x
        self.c.setFont('MainFont', font_size)
        
        for char in text:
            if self.is_emoji(char):
                # 切换到Emoji字体
                self.c.setFont('EmojiFont', font_size)
            else:
                # 切换到中文字体
                self.c.setFont('MainFont', font_size)
            
            # 绘制单个字符
            self.c.drawString(current_x, y, char)
            
            # 计算当前字符宽度，更新x坐标
            # 使用reportlab的字符宽度计算
            current_x += self.c.stringWidth(char, 
                                          'EmojiFont' if self.is_emoji(char) else 'MainFont', 
                                          font_size)
    
    def draw_base_card(self, x, y, theme_color):
        # 绘制外框（带圆角引导线）
        self.c.setStrokeColor(grey)
        self.c.setLineWidth(0.05 * mm)
        self.c.roundRect(x, y, self.width, self.height, self.corner_radius)
        
        # 绘制主题色顶部条
        self.c.setFillColor(theme_color)
        self.c.rect(x + 1*mm, y + self.height - 10*mm, self.width - 2*mm, 8*mm, fill=1, stroke=0)
        
        # 绘制内边框
        self.c.setStrokeColor(theme_color)
        self.c.setLineWidth(0.3 * mm)
        self.c.roundRect(x + 1*mm, y + 1*mm, self.width - 2*mm, self.height - 2*mm, 2*mm)

    def draw_artifact(self, x, y, data):
        theme_color = self.colors.get(data["era"], black)
        self.draw_base_card(x, y, theme_color)
        
        # 标题
        self.c.setFillColor(white)
        self.c.setFont('MainFont', 11)
        self.c.drawCentredString(x + self.width/2, y + self.height - 7.5*mm, data["name"])
        
        # 稀有度
        self.c.setFillColor(theme_color)
        self.c.setFont('MainFont', 8)
        self.c.drawString(x + 4*mm, y + self.height - 14*mm, data["rarity"])
        
        # 核心数值区
        self.c.setFillColor(HexColor("#F9F9F9"))
        self.c.rect(x + 4*mm, y + 35*mm, self.width - 8*mm, 30*mm, fill=1, stroke=0)
        
        self.c.setFillColor(self.colors["text_main"])
        self.c.setFont('MainFont', 9)
        y_offset = y + 58*mm
        
        # 使用字体切换法绘制包含emoji的文本
        self.draw_text_with_emoji_switch(f"时空消耗: {data['cost']}", x + 6*mm, y_offset, 9)
        self.draw_text_with_emoji_switch(f"基础价值: {data['value']}", x + 6*mm, y_offset - 6*mm, 9)
        self.draw_text_with_emoji_switch(f"拍卖类型: {data['type']}", x + 6*mm, y_offset - 12*mm, 9)
        
        # 关键字
        self.c.setFont('MainFont', 8)
        self.c.setFillColor(grey)
        self.c.drawCentredString(x + self.width/2, y + 38*mm, f"[{data['keywords']}]")
        
        # 时代标签
        self.c.setFillColor(theme_color)
        self.c.setFont('MainFont', 7)
        self.c.drawRightString(x + self.width - 5*mm, y + 4*mm, data["era"])

    def draw_special_card(self, x, y, data, card_type):
        theme_color = self.colors.get(card_type, black)
        self.draw_base_card(x, y, theme_color)
        
        # 标题
        self.c.setFillColor(white)
        self.c.setFont('MainFont', 11)
        self.c.drawCentredString(x + self.width/2, y + self.height - 7.5*mm, data["name"])
        
        # 效果描述区
        self.c.setFillColor(self.colors["text_main"])
        self.c.setFont('MainFont', 9)
        text_center = x + self.width/2
        text_y = y + self.height - 25*mm
        
        # 自动换行处理（简单模拟）
        effect_text = data.get("effect", "")
        lines = [effect_text[i:i+12] for i in range(0, len(effect_text), 12)]
        for i, line in enumerate(lines):
            self.c.drawCentredString(text_center, text_y - i*5*mm, line)
            
        # 类型标签
        label = "功能卡" if card_type == "function" else "事件卡"
        self.c.setFillColor(theme_color)
        self.c.setFont('MainFont', 7)
        self.c.drawRightString(x + self.width - 5*mm, y + 4*mm, label)

class PDFGenerator:
    def __init__(self, data_path, output_path):
        with open(data_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        self.output_path = output_path
        self.c = canvas.Canvas(output_path, pagesize=A4)
        self.page_w, self.page_h = A4
        self.card_w = 63 * mm
        self.card_h = 88 * mm
        self.margin_x = (self.page_w - 3 * self.card_w) / 2
        self.margin_y = (self.page_h - 3 * self.card_h) / 2
        self.renderer = CardRenderer(self.c)

    def draw_cut_lines(self):
        self.c.setDash([1, 2])
        self.c.setStrokeColor(grey)
        self.c.setLineWidth(0.05 * mm)
        # 横线
        for r in range(4):
            y = self.margin_y + r * self.card_h
            self.c.line(0, y, self.page_w, y)
        # 纵线
        for col in range(4):
            x = self.margin_x + col * self.card_w
            self.c.line(x, 0, x, self.page_h)
        self.c.setDash([])

    def generate(self):
        # 1. 文物卡
        self._batch_draw(self.data["artifacts"], "artifact")
        # 2. 功能卡
        self._batch_draw(self.data["functions"], "function")
        # 3. 事件卡
        self._batch_draw(self.data["events"], "event")
        
        self.c.save()

    def _batch_draw(self, items, card_type):
        for i in range(0, len(items), 9):
            page_items = items[i:i+9]
            self.draw_cut_lines()
            for idx, item in enumerate(page_items):
                col = idx % 3
                row = 2 - (idx // 3)
                x = self.margin_x + col * self.card_w
                y = self.margin_y + row * self.card_h
                
                if card_type == "artifact":
                    self.renderer.draw_artifact(x, y, item)
                else:
                    self.renderer.draw_special_card(x, y, item, card_type)
            self.c.showPage()

if __name__ == "__main__":
    gen = PDFGenerator("cards_data.json", "时空拍卖行_工程化美化版.pdf")
    gen.generate()
    print("PDF 生成成功！")
