// slide-10.js - 个人总结
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'summary', index: 10, title: '个人总结' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: theme.primary };

  slide.addText("个人总结", {
    x: 0.8, y: 0.3, w: 8, h: 0.7,
    fontSize: 28, fontFace: "Microsoft YaHei", color: "FFFFFF", bold: true
  });
  slide.addText("SUMMARY", {
    x: 0.8, y: 0.85, w: 8, h: 0.3,
    fontSize: 11, fontFace: "Arial", color: theme.accent, charSpacing: 4
  });

  // 4 quadrant cards
  const sections = [
    {
      title: "技术收获", color: theme.accent,
      items: [
        "掌握数据分析全流程方法论",
        "理解 Ridge/Lasso 正则化原理",
        "学会随机森林等集成方法",
        "\"高 R² ≠ 好模型\"实践验证",
        "果实特征对照实验的价值认知"
      ]
    },
    {
      title: "自身不足", color: "E76F51",
      items: [
        "特征工程深度不够",
        "模型调参较为基础",
        "统计学理论需加强",
        "未尝试 XGBoost/LightGBM",
        "交叉验证使用较简单"
      ]
    },
    {
      title: "工具心得", color: theme.secondary,
      items: [
        "Python 数据科学生态链",
        "uv 项目依赖管理",
        "Git 版本控制协作",
        "Matplotlib 中文配置",
        "非交互后端(Agg)适配"
      ]
    },
    {
      title: "未来规划", color: theme.light,
      items: [
        "学习梯度提升模型",
        "了解深度学习回归应用",
        "强化统计学基础",
        "系统化特征工程方法论",
        "GridSearchCV/贝叶斯优化"
      ]
    },
  ];

  sections.forEach((s, i) => {
    const col = i % 2;
    const row = Math.floor(i / 2);
    const x = 0.5 + col * 4.7;
    const y = 1.4 + row * 2.0;

    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: y, w: 4.3, h: 1.8,
      fill: { color: "2A3A47" }, rectRadius: 0.08
    });

    slide.addText(s.title, {
      x: x + 0.25, y: y + 0.15, w: 3.5, h: 0.35,
      fontSize: 14, fontFace: "Microsoft YaHei", color: s.color, bold: true
    });

    s.items.forEach((item, j) => {
      slide.addText(`• ${item}`, {
        x: x + 0.25 + (j >= 3 ? 1.9 : 0), y: y + 0.55 + (j % 3) * 0.38, w: 1.8, h: 0.35,
        fontSize: 10, fontFace: "Microsoft YaHei", color: "CCCCCC"
      });
    });
  });

  // Bottom bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 5.4, w: 10, h: 0.04,
    fill: { color: theme.accent }
  });
  slide.addText("谢谢！", {
    x: 0.5, y: 5.1, w: 9, h: 0.4,
    fontSize: 16, fontFace: "Microsoft YaHei", color: theme.light, align: "right"
  });

  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.0, w: 0.35, h: 0.35, fill: { color: theme.accent } });
  slide.addText("10", { x: 9.3, y: 5.0, w: 0.35, h: 0.35, fontSize: 10, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle" });

  return slide;
}

module.exports = { createSlide, slideConfig };
