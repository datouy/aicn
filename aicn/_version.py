# -*- coding: utf-8 -*-
"""aicn 的唯一版本号来源。

放在独立模块里，`pyproject.toml` 通过
`[tool.setuptools.dynamic] version = {attr = "aicn._version.__version__"}`
静态读取它 —— 版本号全仓库只写一遍，不会再出现 pyproject / CLI / README
三处各写一份、改了一处忘了另一处的情况。
"""
__version__ = "0.2.0"
