# 群友成分检测器

## 消息导出
使用[ycccccccy/echotrace](https://github.com/ycccccccy/echotrace)导出群聊消息。

## 直接使用
下载dist目录中的exe直接运行即可。可以不选择任何模板，使用项目默认的模板进行分析。提示词模板和报告模板可以参考项目中的test模板进行编写，注意提示词和报告中的变量保持一致。

## 自行构建
1. 下载代码
2. 安装依赖
3. `pyinstaller --noconfirm --onefile --windowed --name "ChatMemberAnalyzer" --clean gui_app.py`
