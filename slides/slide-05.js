// slide-05.js - 技术方案
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 5, title: '技术方案' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.08, fill: { color: theme.primary } });
  slide.addText("技术方案", { x: 0.8, y: 0.4, w: 8, h: 0.7, fontSize: 28, fontFace: "Microsoft YaHei", color: theme.primary, bold: true });

  // Pipeline flow
  const steps = [
    { label: "数据加载", sub: "CSV读取", color: theme.primary },
    { label: "预处理", sub: "划分+标准化", color: theme.secondary },
    { label: "特征工程", sub: "PCA+VIF+相关", color: theme.accent.replace("#", "") },
    { label: "建模训练", sub: "3种模型", color: "E76F51" },
    { label: "评估预测", sub: "R²/RMSE/MAE", color: theme.light.replace("#", "") },
  ];

  const arrowY = 1.55;
  steps.forEach((s, i) => {
    const x = 0.4 + i * 1.9;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: 1.3, w: 1.7, h: 0.85,
      fill: { color: s.color }, rectRadius: 0.08
    });
    slide.addText(s.label, { x: x, y: 1.35, w: 1.7, h: 0.45, fontSize: 13, fontFace: "Microsoft YaHei", color: "FFFFFF", bold: true, align: "center" });
    slide.addText(s.sub, { x: x, y: 1.7, w: 1.7, h: 0.35, fontSize: 10, fontFace: "Microsoft YaHei", color: "FFFFFF", align: "center" });

    // Arrow between steps
    if (i < steps.length - 1) {
      slide.addText("▶", {
        x: x + 1.7, y: arrowY, w: 0.2, h: 0.3,
        fontSize: 14, color: "CCCCCC", align: "center", valign: "middle"
      });
    }
  });

  // Model cards
  const models = [
    { name: "K-Means 聚类", desc: "无监督学习\n肘部法则+轮廓系数确定最佳K\nPCA降至2维可视化\n揭示种植环境自然分组" },
    { name: "线性回归 (Ridge+Lasso)", desc: "L2/L1正则化防止过拟合\nPCA降维后训练\n交叉验证选最优alpha\nLasso可自动特征选择" },
    { name: "随机森林", desc: "200棵决策树集成\nBagging降低方差\n可处理非线性关系\n输出特征重要性排序" },
  ];

  models.forEach((m, i) => {
    const x = 0.5 + i * 3.15;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: 2.6, w: 2.85, h: 2.5,
      fill: { color: "F7F9FC" }, rectRadius: 0.08
    });

    // Number badge
    slide.addShape(pres.shapes.OVAL, {
      x: x + 0.15, y: 2.75, w: 0.4, h: 0.4,
      fill: { color: [theme.primary, theme.secondary, theme.accent.replace("#", "")][i] }
    });
    slide.addText(String(i + 1), {
      x: x + 0.15, y: 2.75, w: 0.4, h: 0.4,
      fontSize: 14, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle"
    });

    slide.addText(m.name, {
      x: x + 0.65, y: 2.75, w: 2, h: 0.4,
      fontSize: 14, fontFace: "Microsoft YaHei", color: theme.primary, bold: true
    });

    slide.addText(m.desc, {
      x: x + 0.2, y: 3.3, w: 2.45, h: 1.6,
      fontSize: 11, fontFace: "Microsoft YaHei", color: "555555", lineSpacingMultiple: 1.6
    });
  });

  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.secondary } });
  slide.addText("5", { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 12, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle" });

  return slide;
}

module.exports = { createSlide, slideConfig };
