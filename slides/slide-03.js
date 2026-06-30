// slide-03.js - 基本信息与分工
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 3, title: '基本信息与分工' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  // Header bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.08,
    fill: { color: theme.primary }
  });

  // Section title
  slide.addText("基本信息与分工", {
    x: 0.8, y: 0.4, w: 8, h: 0.7,
    fontSize: 28, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true
  });

  // Left card: Project Info
  const cardY = 1.5;
  // Card background
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: cardY, w: 4.2, h: 3.2,
    fill: { color: "F7F9FC" },
    rectRadius: 0.1
  });

  slide.addText("项目信息", {
    x: 0.8, y: cardY + 0.15, w: 3.5, h: 0.4,
    fontSize: 18, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true
  });

  const infoLines = [
    { label: "项目名称", value: "野生蓝莓产量预测分析" },
    { label: "实训课程", value: "软件工程实训" },
    { label: "实训周期", value: "2026.6.29 — 2026.7.13" },
    { label: "技术栈", value: "Python 3.12 + NumPy + Pandas" },
    { label: "", value: "Scikit-learn + Matplotlib + Seaborn" },
    { label: "", value: "statsmodels + uv + Git" },
  ];

  infoLines.forEach((line, i) => {
    const y = cardY + 0.7 + i * 0.38;
    if (line.label) {
      slide.addText(line.label, {
        x: 0.8, y: y, w: 1.3, h: 0.35,
        fontSize: 12, fontFace: "Microsoft YaHei",
        color: theme.secondary, bold: true
      });
    }
    slide.addText(line.value, {
      x: 2.2, y: y, w: 2.3, h: 0.35,
      fontSize: 12, fontFace: "Microsoft YaHei",
      color: "333333"
    });
  });

  // Right card: Personal Role
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.3, y: cardY, w: 4.2, h: 3.2,
    fill: { color: "F7F9FC" },
    rectRadius: 0.1
  });

  slide.addText("个人分工", {
    x: 5.6, y: cardY + 0.15, w: 3.5, h: 0.4,
    fontSize: 18, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true
  });

  slide.addText("全流程数据分析与建模", {
    x: 5.6, y: cardY + 0.65, w: 3.5, h: 0.35,
    fontSize: 13, fontFace: "Microsoft YaHei",
    color: theme.accent, bold: true
  });

  const tasks = [
    "数据预处理：加载、清洗、标准化",
    "特征工程：相关性分析、PCA降维、VIF诊断",
    "聚类分析：K-Means + PCA可视化",
    "回归建模：Ridge/Lasso + 随机森林",
    "模型对比评估与测试集预测",
    "可视化图表生成（12张）"
  ];

  tasks.forEach((t, i) => {
    slide.addShape(pres.shapes.OVAL, {
      x: 5.6, y: cardY + 1.15 + i * 0.36, w: 0.16, h: 0.16,
      fill: { color: theme.secondary }
    });
    slide.addText(t, {
      x: 5.9, y: cardY + 1.1 + i * 0.36, w: 3.3, h: 0.3,
      fontSize: 11, fontFace: "Microsoft YaHei",
      color: "444444"
    });
  });

  // Page badge
  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.secondary } });
  slide.addText("3", { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 12, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle" });

  return slide;
}

module.exports = { createSlide, slideConfig };
