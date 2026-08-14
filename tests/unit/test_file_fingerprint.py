"""文件指纹计算器单元测试。

这些测试保护阶段 2 的缓存身份基础：相同文件内容应得到相同指纹，
内容变化后指纹必须变化，并且实现不能依赖一次性读取整个文件。
"""

from __future__ import annotations

from hashlib import sha256

from infrastructure.storage.fingerprint import Sha256FileFingerprintCalculator


def test_file_fingerprint_matches_sha256_when_read_in_small_chunks(tmp_path) -> None:
    """分块读取产生的指纹应与标准 `SHA256` 结果一致。"""

    # arrange：故意把分块设得很小，确保测试实际经过多次读取循环。
    payload = b"zero-caption-video-content"
    source_path = tmp_path / "demo.mp4"
    source_path.write_bytes(payload)
    calculator = Sha256FileFingerprintCalculator(chunk_size=4)

    # act
    result = calculator.calculate(source_path)

    # assert：缓存身份必须只由文件内容决定，不能因为分块大小改变。
    assert result == sha256(payload).hexdigest()


def test_file_fingerprint_changes_when_source_content_changes(tmp_path) -> None:
    """源文件内容变化后应生成不同指纹，避免错误复用旧缓存。"""

    # arrange
    source_path = tmp_path / "demo.mp4"
    calculator = Sha256FileFingerprintCalculator()
    source_path.write_bytes(b"first-version")
    first = calculator.calculate(source_path)

    # act
    source_path.write_bytes(b"second-version")
    second = calculator.calculate(source_path)

    # assert
    assert first != second
