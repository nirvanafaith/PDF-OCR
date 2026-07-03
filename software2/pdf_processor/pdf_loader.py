import fitz
from PIL import Image
import os
from functools import lru_cache


class PDFProcessor:
    """PDF文档处理器，提供PDF转图像、懒加载和页数查询等核心功能。

    该类封装了PDF文档的常用操作，包括将整个PDF转换为图像列表、
    创建懒加载器以按需读取页面、以及获取PDF页数信息。

    依赖:
        - fitz (PyMuPDF): PDF文档解析和渲染
        - PIL.Image: 图像处理
        - os: 文件路径检查
    """

    def convert_to_images(self, pdf_path: str, dpi: int = 200) -> list:
        """将PDF文件的所有页面转换为PIL图像列表。

        逐页渲染PDF并生成对应的RGB图像，支持自定义DPI以控制输出图像的分辨率。
        渲染完成后自动关闭PDF文档以释放资源。

        参数:
            pdf_path (str): PDF文件的绝对路径。
            dpi (int, 可选): 渲染分辨率（每英寸点数），默认为200。
                值越大输出图像越清晰，但内存占用和渲染时间也会相应增加。

        返回:
            list[PIL.Image.Image]: 包含所有页面对应RGB图像的列表，
            列表索引与PDF页码一一对应（从0开始）。

        异常:
            RuntimeError: 当PDF文件不存在、文件格式无效、文件已加密或打开失败时抛出。

        调用关系:
            被 OCREngine.run_ocr 调用
            被 DataLoadWorker.run 调用

        依赖:
            - fitz (PyMuPDF): PDF文档打开、页面渲染及像素图生成
            - PIL.Image: 将原始像素数据转换为PIL图像对象
            - os: 验证文件路径是否存在
        """
        if not os.path.isfile(pdf_path):
            raise RuntimeError(f"PDF文件不存在: {pdf_path}")
        try:
            doc = fitz.open(pdf_path)
        except fitz.FileDataError:
            raise RuntimeError(f"文件不是有效的PDF: {pdf_path}")
        except Exception as e:
            raise RuntimeError(f"打开PDF文件时出错: {pdf_path}, 错误: {e}")
        try:
            if doc.is_encrypted:
                raise RuntimeError(f"PDF文件已加密，无法处理: {pdf_path}")
            images = []
            zoom = dpi / 72
            mat = fitz.Matrix(zoom, zoom)
            for page in doc:
                pix = page.get_pixmap(matrix=mat)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                images.append(img)
            return images
        finally:
            doc.close()

    def get_lazy_loader(self, pdf_path: str, dpi: int = 200):
        """创建并返回一个懒加载页面加载器实例。

        懒加载器不会一次性加载所有页面，而是按需渲染单页图像，
        适用于大文档或仅需访问部分页面的场景，可有效降低内存占用。

        参数:
            pdf_path (str): PDF文件的绝对路径。
            dpi (int, 可选): 渲染分辨率（每英寸点数），默认为200。

        返回:
            LazyPageLoader: 已初始化的懒加载页面加载器实例。

        调用关系:
            目前未被调用（预留接口）

        依赖:
            - LazyPageLoader: 懒加载页面加载器类
        """
        return LazyPageLoader(pdf_path, dpi)

    def get_page_count(self, pdf_path: str) -> int:
        """获取PDF文件的总页数。

        打开PDF文档后读取页数，随后立即关闭文档以释放资源。

        参数:
            pdf_path (str): PDF文件的绝对路径。

        返回:
            int: PDF文档的总页数。

        调用关系:
            目前未被调用（预留接口）

        依赖:
            - fitz (PyMuPDF): PDF文档打开与页数读取
        """
        doc = fitz.open(pdf_path)
        count = len(doc)
        doc.close()
        return count


class LazyPageLoader:
    """PDF页面懒加载器，支持按需渲染单页图像并带有LRU缓存机制。

    该类在初始化时打开PDF文档但不会加载任何页面图像，仅在调用
    get_page方法时才渲染指定页面。内置LRU缓存策略，最多保留最近
    访问的5页图像，超出时自动淘汰最早缓存的页面，以平衡内存占用
    与访问性能。

    属性:
        pdf_path (str): PDF文件的绝对路径。
        dpi (int): 渲染分辨率（每英寸点数）。
        page_count (int): PDF文档的总页数。

    调用关系:
        目前未被直接使用（预留接口），可通过 PDFProcessor.get_lazy_loader 创建实例

    依赖:
        - fitz (PyMuPDF): PDF文档解析、页面渲染及像素图生成
        - PIL.Image: 将原始像素数据转换为PIL图像对象
    """

    def __init__(self, pdf_path: str, dpi: int = 200):
        """初始化懒加载器，打开PDF文档并预计算渲染参数。

        初始化时打开PDF文档、计算缩放矩阵，并初始化LRU缓存相关数据结构。
        不会预先加载任何页面图像。

        参数:
            pdf_path (str): PDF文件的绝对路径。
            dpi (int, 可选): 渲染分辨率（每英寸点数），默认为200。

        依赖:
            - fitz (PyMuPDF): PDF文档打开与页数读取
        """
        self.pdf_path = pdf_path
        self.dpi = dpi
        self._doc = fitz.open(pdf_path)
        self._zoom = dpi / 72
        self._mat = fitz.Matrix(self._zoom, self._zoom)
        self._cache = {}
        self._cache_order = []
        self._max_cache = 5
        self.page_count = len(self._doc)

    def get_page(self, page_num: int) -> Image.Image:
        """按需加载指定页面的图像，带LRU缓存。

        若目标页面已在缓存中，则直接返回缓存图像；否则渲染该页面
        并存入缓存。当缓存页数超过上限（5页）时，自动淘汰最早
        缓存的页面以释放内存。

        参数:
            page_num (int): 目标页码，从0开始索引。

        返回:
            PIL.Image.Image: 指定页面对应的RGB图像。

        调用关系:
            按需加载单页图像，带LRU缓存

        依赖:
            - fitz (PyMuPDF): 页面渲染及像素图生成
            - PIL.Image: 将原始像素数据转换为PIL图像对象
        """
        if page_num in self._cache:
            return self._cache[page_num]
        page = self._doc[page_num]
        pix = page.get_pixmap(matrix=self._mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        self._cache[page_num] = img
        self._cache_order.append(page_num)
        while len(self._cache_order) > self._max_cache:
            oldest = self._cache_order.pop(0)
            if oldest in self._cache:
                del self._cache[oldest]
        return img

    def get_page_size(self, page_num: int):
        """获取指定页面渲染后的像素尺寸。

        根据初始化时设定的DPI计算页面渲染后的实际像素宽度和高度，
        不触发页面图像的渲染和缓存。

        参数:
            page_num (int): 目标页码，从0开始索引。

        返回:
            tuple[int, int]: 页面渲染后的像素尺寸，格式为 (宽度, 高度)。

        调用关系:
            获取指定页面的像素尺寸

        依赖:
            - fitz (PyMuPDF): 页面尺寸信息读取
        """
        page = self._doc[page_num]
        rect = page.rect
        return int(rect.width * self._zoom), int(rect.height * self._zoom)

    def get_pdf_page_size(self, page_num: int):
        page = self._doc[page_num]
        rect = page.rect
        return rect.width, rect.height

    def close(self):
        """关闭PDF文档并清理所有缓存。

        释放PDF文档句柄及所有已缓存的页面图像，清空缓存队列。
        调用后该实例不应再被使用。

        调用关系:
            关闭PDF文档并清理缓存

        依赖:
            - fitz (PyMuPDF): PDF文档句柄关闭
        """
        if self._doc:
            self._doc.close()
            self._doc = None
        self._cache.clear()
        self._cache_order.clear()