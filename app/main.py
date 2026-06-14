"""桌面应用入口模块。

这个文件刻意保持很小，只负责创建 `QApplication` 对象、完成应用启动装配，
以及显示主窗口。较重的初始化逻辑集中放在 `app.bootstrap` 中，方便初学者
顺着单一入口阅读启动流程。
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.bootstrap import bootstrap_application


def main() -> int:
    """启动桌面应用，并返回事件循环的退出码。"""

    # `QApplication` 是桌面界面程序的根对象。
    # 几乎所有界面控件都依赖它，所以必须最先创建。
    app = QApplication(sys.argv)
    app.setApplicationName("Zero Caption")
    app.setOrganizationName("zero-caption")

    # bootstrap_application 会在一个地方完成配置、日志、工作区目录
    # 和依赖容器的组装，避免这些启动细节散落在入口文件里。
    context = bootstrap_application()
    window = context.container.create_main_window()
    window.show()

    # `app.exec()` 会进入事件循环。
    # 从这里开始，按钮点击等用户操作都会通过界面框架的事件和信号机制分发。
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
