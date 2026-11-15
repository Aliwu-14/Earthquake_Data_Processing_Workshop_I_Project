# Earthquake Data Processing Workshop I Project

使用课程中的 Python、NumPy 和 Pandas 语法，逐步练习地震数据检查和清理。项目仍在学习与完善中。

## 文件结构

- `earthquake_cleaning.py`：数据检查、筛选与日期格式整理脚本。
- `data/07earthquake.csv`：课程提供的原始数据，保持原样。
- `requirements.txt`：验证运行时使用的依赖版本。

## 运行方法

使用 Python 3.11 或更新版本，在本仓库根目录运行：

```bash
python -m pip install -r requirements.txt
python earthquake_cleaning.py
```

如果已在 `python-common` Conda 环境中安装依赖，可以激活环境后直接运行脚本。

## 当前处理流程

1. 读取原始数据，建立工作副本。
2. 查看数据维度、前几行、列类型和描述性统计。
3. 统计缺失值，定位负深度记录供后续核查。
4. 按事件类型统计记录数，并筛选 `Earthquake` 事件。
5. 用循环、字符串切片和 `.loc` 将三条完整时间戳形式的日期整理为 `MM/DD/YYYY`。

原始数据包含 23,412 条记录和 7 列，筛选后保留 23,232 条 `Earthquake` 记录。日期整理只修改内存中的工作表，脚本目前输出检查结果，没有导出清理后的 CSV。

## 后续练习

- 检查和规范 `Time` 列中的完整时间戳，保留小数秒等原始信息。
- 核查负深度记录，明确处理依据。
- 验证日期有效性及清理前后的记录数量。
- 按分析需求完成汇总，并导出清理结果。

## 数据来源

Data Processing Workshop I 课程提供的 `ProjectData/07earthquake.csv`。仓库记录本人的学习代码与处理过程；数据集的原始发布来源和说明待补充。
