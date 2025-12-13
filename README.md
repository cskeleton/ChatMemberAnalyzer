# 群友成分检测器

## 消息导出
使用[ycccccccy/echotrace](https://github.com/ycccccccy/echotrace)导出群聊消息。

## 填入必要信息
在`analyze_chat.py`中填入必要的 API 信息。修改文件开头的相关参数，运行即可。具体看代码注释描述。
如果某一个群友的消息太多，就对消息进行了抽样。`count_messages.py`可以帮助你分析数据的大致情况。然后根据实际情况修改`analyze_chat.py`中的参数。

## 分析结果
为了节省token，切片和分析的数据会被暂存在 `temp`，输出的结果在 `results`。
