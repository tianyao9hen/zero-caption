"""本地文件指纹计算器。

这个模块属于基础设施层，因为它需要直接读取磁盘文件。
实现使用固定大小的数据块流式计算 `SHA256`，不会把大视频一次性读入内存。
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


class Sha256FileFingerprintCalculator:
    """以流式方式计算本地文件的 `SHA256` 指纹。"""

    def __init__(self, chunk_size: int = 1024 * 1024) -> None:
        """设置每次从磁盘读取的数据块大小。

        参数：
            chunk_size：单次读取字节数。默认一兆字节，既能控制内存，
                也能避免对大文件发起过多细碎读取。
        """

        if chunk_size <= 0:
            raise ValueError("文件指纹分块大小必须大于 0。")
        self.chunk_size = chunk_size

    def calculate(self, source_path: Path) -> str:
        """读取本地文件并返回十六进制 `SHA256` 指纹。

        这个方法只读取文件，不会修改源文件或创建额外产物。
        文件不存在时让标准 `FileNotFoundError` 直接向上抛出，
        这样导入流程可以给用户展示明确的路径错误。
        """

        digest = sha256()
        with Path(source_path).open("rb") as source_file:
            while chunk := source_file.read(self.chunk_size):
                digest.update(chunk)
        return digest.hexdigest()
