"""PDF输出模块。

将校对后的字符覆盖绘制到原始页面图像上，生成最终的可视化PDF文件。
依赖 reportlab 库进行PDF生成，依赖 os 模块进行文件路径操作。
"""

import os

from PyQt5.QtCore import QThread, pyqtSignal
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader
from reportlab.lib.colors import Color
from reportlab.pdfbase.pdfmetrics import stringWidth

"""在模块加载时注册微软雅黑字体供 reportlab 使用。

尝试从系统字体目录加载微软雅黑（msyh.ttc），若注册成功则将其设为默认字体，
否则回退至 reportlab 内置的 Helvetica 字体，以确保中文内容可正常渲染。
"""
font_path = os.path.join(
    os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts', 'msyh.ttc'
)
if os.path.exists(font_path):
    pdfmetrics.registerFont(TTFont('MicrosoftYaHei', font_path))
    default_font = 'MicrosoftYaHei'
else:
    default_font = 'Helvetica'


class PDFOutputGenerator:
    """PDF输出生成器。

    将校对后的字符文本以黑色绘制在对应的原始页面图像上方，
    逐页生成包含图像底图与校对文字叠加的PDF文件。

    依赖:
        reportlab: PDF生成库（canvas, pdfmetrics, TTFont, ImageReader）
    """

    def generate(self, corrected_chars, page_images, output_path,
                 pdf_path=None, text_color="red", progress_callback=None):
        """生成校对后的PDF文件。

        将每页原始图像作为底图绘制到PDF中，并在对应位置叠加校对后的字符文本，
        生成最终的可视化校对结果PDF。

        Args:
            corrected_chars (list): 校对后的字符对象列表，每个对象需包含
                page_num（页码）、bbox（边界框坐标）、text（文本内容）、
                ignored（是否忽略）属性。
            page_images (list): 按页码顺序排列的页面图像对象列表，
                每个对象需包含 width 和 height 属性。
            output_path (str): 输出PDF文件的保存路径。
            pdf_path (str, optional): 原始PDF文件路径（当前未使用），
                保留供后续扩展。默认为 None。
            text_color (str, optional): 覆盖文字的颜色，支持 "red"（红色）
                和 "transparent"（透明）。默认为 "red"。

        Returns:
            None

        Raises:
            RuntimeError: 当页面图像列表为空或PDF生成过程中发生异常时抛出。

        调用关系:
            被 MainWindow._on_refine_save 调用。

        依赖:
            reportlab.pdfgen.canvas: 用于创建PDF画布并绘制内容。
            reportlab.lib.utils.ImageReader: 用于将图像对象转换为 reportlab
                可读取的格式。
        """
        try:
            if not page_images:
                raise RuntimeError("没有页面图像，无法生成PDF")

            first_img = page_images[0]
            page_width = first_img.width
            page_height = first_img.height

            c = canvas.Canvas(output_path)

            chars_by_page = {}
            for char in corrected_chars:
                if not char.ignored:
                    if char.page_num not in chars_by_page:
                        chars_by_page[char.page_num] = []
                    chars_by_page[char.page_num].append(char)

            for page_idx in range(len(page_images)):
                img = page_images[page_idx]
                page_width = img.width
                page_height = img.height
                c.setPageSize((page_width, page_height))

                c.drawImage(
                    ImageReader(img), 0, 0,
                    width=page_width, height=page_height
                )

                for char in chars_by_page.get(page_idx, []):
                    x1, y1, x2, y2 = char.bbox
                    bbox_height = y2 - y1
                    bbox_width = x2 - x1
                    font_size = bbox_height
                    if font_size < 1:
                        font_size = 1
                    text_w = stringWidth(char.text, default_font, font_size)
                    if text_w > bbox_width and bbox_width > 0:
                        font_size = font_size * bbox_width / text_w
                        text_w = stringWidth(char.text, default_font, font_size)
                    c.setFont(default_font, font_size)
                    lly = (page_height - y2) + (bbox_height - font_size) / 2
                    llx = x1 + (bbox_width - text_w) / 2
                    if text_color == "transparent":
                        c.setFillColor(Color(0, 0, 0, alpha=0))
                    else:
                        c.setFillColorRGB(1, 0, 0)
                    c.drawString(llx, lly, char.text)

                c.showPage()
                if progress_callback:
                    progress_callback(page_idx + 1, len(page_images))

            c.save()
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"生成PDF失败: {e}")


class PDFOutputWorker(QThread):
    """PDF输出工作线程。

    在子线程中依次生成红色文字版和透明文字版两份PDF文件，
    通过信号实时报告生成进度，避免阻塞主线程UI。

    信号:
        progress_signal(int, str): 进度百分比(0-100)和描述文字。
        finished_signal(): 两份PDF全部生成成功完成。
        error_signal(str): 生成过程中出现错误，携带错误信息。

    依赖:
        PDFOutputGenerator: 实际执行PDF生成的生成器实例。
    """

    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal()
    error_signal = pyqtSignal(str)

    def __init__(self, generator, corrected_chars, page_images,
                 red_path, transparent_path, pdf_path=None):
        """初始化PDF输出工作线程。

        参数:
            generator: PDFOutputGenerator 实例，用于执行PDF生成。
            corrected_chars: 校对后的字符对象列表。
            page_images: 按页码顺序排列的页面图像对象列表。
            red_path: 红色文字版PDF的输出路径。
            transparent_path: 透明文字版PDF的输出路径。
            pdf_path: 原始PDF文件路径（当前未使用），默认为 None。
        """
        super().__init__()
        self._generator = generator
        self._corrected_chars = corrected_chars
        self._page_images = page_images
        self._red_path = red_path
        self._transparent_path = transparent_path
        self._pdf_path = pdf_path

    def run(self):
        """执行PDF生成任务。

        依次生成红色文字版和透明文字版PDF，每完成一页通过
        progress_signal 报告进度。全部完成后发射 finished_signal，
        出错时发射 error_signal。
        """
        try:
            total_pages = len(self._page_images)
            total_steps = total_pages * 2

            def on_red_progress(current_page, _total):
                step = current_page
                percent = int(step / total_steps * 100)
                desc = f"正在生成红色文字版... (第 {current_page}/{total_pages} 页)"
                self.progress_signal.emit(percent, desc)

            self._generator.generate(
                self._corrected_chars, self._page_images,
                self._red_path, self._pdf_path,
                text_color="red", progress_callback=on_red_progress,
            )

            def on_transparent_progress(current_page, _total):
                step = total_pages + current_page
                percent = int(step / total_steps * 100)
                desc = f"正在生成透明文字版... (第 {current_page}/{total_pages} 页)"
                self.progress_signal.emit(percent, desc)

            self._generator.generate(
                self._corrected_chars, self._page_images,
                self._transparent_path, self._pdf_path,
                text_color="transparent", progress_callback=on_transparent_progress,
            )

            self.finished_signal.emit()
        except Exception as e:
            self.error_signal.emit(str(e))