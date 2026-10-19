try:
    from barcode.writer import BaseWriter, SVGWriter
    from typing import BinaryIO
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    import logging
    
    log = logging.getLogger("pyBarcode")
    log.info("Pillow not found. Image output disabled")
    Image = ImageDraw = ImageFont = None  # lint:ok

import os
import frappe
from barcode import Code128
from io import BytesIO

def mm2px(mm, dpi=300):
    return (mm * dpi) / 25.4


def pt2mm(pt):
    return pt * 0.352777778


class CustomImgWriter(BaseWriter):  # type: ignore[no-redef]
    format: str
    mode: str
    dpi: int

    def __init__(self, format="PNG", mode="RGB") -> None:
        """Initialise a new write instance.

        :params format: The file format for the generated image. This parameter can
            take any value that Pillow accepts.
        :params mode: The colour-mode for the generated image. Set this to RGBA if
            you wish to use colours with transparency.
        """
        BaseWriter.__init__(
            self, self._init, self._paint_module, self._paint_text, self._finish
        )
        self.format = format
        self.mode = mode
        self.dpi = 300
        self._image = None
        self._draw = None

    def _init(self, code):
        width, height = self.calculate_size(len(code[0]), len(code)/4) # reduce height by 2
        size = (int(mm2px(width, self.dpi)), int(mm2px(height, self.dpi)))
        self._image = Image.new(self.mode, size, self.background)
        self._draw = ImageDraw.Draw(self._image)

    def _paint_module(self, xpos, ypos, width, color):
        size = [
            (mm2px(xpos, self.dpi), mm2px(ypos, self.dpi)),
            (
                mm2px(xpos + width, self.dpi) - 1,
                mm2px(ypos + self.module_height/2, self.dpi), # reduce module_height by 2
            ),
        ]
        self._draw.rectangle(size, outline=color, fill=color)

    def _paint_text(self, xpos, ypos):
        font_size = int(mm2px(pt2mm(self.font_size/1.5), self.dpi)) # adjust text position
        font = ImageFont.truetype(self.font_path, font_size)
        for subtext in self.text.split("\n"):
            pos = (
                mm2px(xpos, self.dpi),
                mm2px(ypos/1.8, self.dpi),
            )
            self._draw.text(
                pos, subtext, font=font, fill=self.foreground, anchor="md"
            )
            ypos += pt2mm(self.font_size)  + self.text_line_distance 

    def _finish(self):
        return self._image

    def save(self, filename, output):
        filename = f"{filename}.{self.format.lower()}"
        output.save(filename, self.format.upper())
        return filename

    def write(self, content, fp: BinaryIO):
        """Write `content` into a file-like object.

        Content should be a barcode rendered by this writer.
        """
        content.save(fp, format=self.format)
        
@frappe.whitelist()
def generate_and_save_barcode(data, format='svg'):
    encoded_data = data
        
    if '/' in data:
        encoded_data = data.replace('/', '@')
            
    # my_code = Code128(encoded_data, writer=CustomImgWriter())
    my_code = Code128(encoded_data, writer=SVGWriter())
    file_name = f"{encoded_data}.{format}"

    # Create BytesIO to store barcode SVG
    barcode_bytes = BytesIO()
    my_code.write(barcode_bytes)

    # Set the directory to save the file
    base_directory = frappe.get_site_path("public", "files")
    file_path = os.path.join(base_directory, file_name)

    # Check if the file already exists
    if os.path.exists(file_path):
        os.remove(file_path)

    # Save the SVG content to a file
    with open(file_path, 'wb') as f:
        f.write(barcode_bytes.getvalue())
        
    return file_name
