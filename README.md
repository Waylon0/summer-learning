# 野生蓝莓产量预测分析

## 项目背景

蓝莓在全球范围内备受欢迎，野生蓝莓养殖正处于蓬勃发展阶段。本项目基于计算机模拟与机器学习算法，对野生蓝莓产量进行预测分析，探索气候、蜂群密度、蓝莓克隆大小等因素与产量之间的关系。

## 数据来源

Kaggle Playground Series (S3E14) / Mendeley Data
引用: Qu, Hongchun; Obsie, Efrem; Drummond, Frank (2020)

## 项目结构

```
Blueberry/
├── README.md
├── pyproject.toml
├── data/
│   ├── raw/                    # 原始数据
│   │   ├── train.csv           # 训练集 (15289条×18列)
│   │   └── test.csv            # 测试集 (10194条×17列)
│   └── processed/              # 处理后数据
├── src/
│   ├── config.py               # 全局配置
│   ├── data/
│   │   ├── loader.py           # 数据加载
│   │   └── preprocessor.py     # 数据预处理
│   ├── features/
│   │   └── engineering.py      # 特征工程
│   ├── models/
│   │   ├── clustering.py       # K-Means聚类
│   │   ├── linear_regression.py # 线性回归
│   │   ├── random_forest.py    # 随机森林
│   │   └── evaluation.py       # 模型评估
│   └── visualization/
│       └── plots.py            # 可视化
├── notebooks/                  # Jupyter Notebooks
├── outputs/
│   ├── figures/                # 输出图表
│   └── models/                 # 保存的模型
└── tests/                      # 单元测试
```

## 特征说明

| 类别 | 字段 | 说明 |
|------|------|------|
| 克隆特征 | Clonesize | 蓝莓克隆平均大小 (m²) |
| 蜂群密度 | Honeybee, Bumbles, Andrena, Osmia | 4种蜂类密度 |
| 高温数据 | MaxOfUpperTRange, MinOfUpperTRange, AverageOfUpperTRange | 花期内最高温带数据 (°C) |
| 低温数据 | MaxOfLowerTRange, MinOfLowerTRange, AverageOfLowerTRange | 花期内最低温带数据 (°C) |
| 降雨数据 | RainingDays, AverageRainingDays | 降雨天数 |
| 果实指标 | fruitset, fruitmass, seeds | 果实集、果实质量、种子数 |
| 目标变量 | yield | 蓝莓产量 (仅train.csv) |

## 分析流程

1. 业务理解与数据读取
2. 初步探索（维度、缺失值、重复值、清洗）
3. 相关性分析（可视化探索）
4. 聚类分析（确定K值 → 建模 → 群组解读）
5. 线性回归（共线性处理 → 降维 → 建模 → 残差检验 → 预测）
6. 随机森林（参数调优 → 特征重要性 → 预测）
7. 模型对比与结论总结

## 快速开始

```bash
uv sync
uv run jupyter notebook notebooks/
```
