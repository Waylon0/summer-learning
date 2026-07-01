// slide-06.js - 核心创新点：果实特征对照实验
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 6, title: '核心创新点' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.08, fill: { color: theme.accent } });
  slide.addText("核心创新点：果实特征对照实验", {
    x: 0.8, y: 0.4, w: 8.5, h: 0.7,
    fontSize: 26, fontFace: "Microsoft YaHei", color: theme.primary, bold: true
  });
  slide.addText("KEY INNOVATION: FRUIT FEATURE ABLATION STUDY", {
    x: 0.8, y: 1.0, w: 8, h: 0.3,
    fontSize: 10, fontFace: "Arial", color: theme.accent, charSpacing: 2
  });

  // Two big comparison boxes
  // Left: With fruit features
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 1.6, w: 4.2, h: 2.8,
    fill: { color: "FFF5F5" }, rectRadius: 0.1
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.5, y: 1.6, w: 4.2, h: 0.06,
    fill: { color: "E76F51" }
  });

  slide.addText("方案 A：包含果实特征", {
    x: 0.8, y: 1.8, w: 3.5, h: 0.4,
    fontSize: 18, fontFace: "Microsoft YaHei", color: "E76F51", bold: true
  });
  slide.addText("18个特征 → PCA降维 → Ridge回归", {
    x: 0.8, y: 2.2, w: 3.5, h: 0.3,
    fontSize: 11, fontFace: "Microsoft YaHei", color: "888888"
  });

  // Big R² number
  slide.addText("0.78", {
    x: 0.8, y: 2.7, w: 3.5, h: 0.9,
    fontSize: 56, fontFace: "Arial", color: "E76F51", bold: true, align: "center"
  });
  slide.addText("R² 决定系数", {
    x: 0.8, y: 3.5, w: 3.5, h: 0.3,
    fontSize: 13, fontFace: "Microsoft YaHei", color: "999999", align: "center"
  });

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 3.95, w: 3.4, h: 0.02,
    fill: { color: "E0E0E0" }
  });
  slide.addText("⚠ 数据泄露：果实特征在种植前无法获知", {
    x: 0.8, y: 4.05, w: 3.5, h: 0.3,
    fontSize: 10, fontFace: "Microsoft YaHei", color: "CC0000"
  });

  // VS divider
  slide.addShape(pres.shapes.OVAL, {
    x: 4.65, y: 2.65, w: 0.7, h: 0.7,
    fill: { color: theme.primary }
  });
  slide.addText("VS", {
    x: 4.65, y: 2.65, w: 0.7, h: 0.7,
    fontSize: 16, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle"
  });

  // Right: Without fruit features
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.3, y: 1.6, w: 4.2, h: 2.8,
    fill: { color: "F0FAF8" }, rectRadius: 0.1
  });
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.3, y: 1.6, w: 4.2, h: 0.06,
    fill: { color: theme.secondary }
  });

  slide.addText("方案 B：排除果实特征", {
    x: 5.6, y: 1.8, w: 3.5, h: 0.4,
    fontSize: 18, fontFace: "Microsoft YaHei", color: theme.secondary, bold: true
  });
  slide.addText("15个特征 → PCA降维 → Ridge回归", {
    x: 5.6, y: 2.2, w: 3.5, h: 0.3,
    fontSize: 11, fontFace: "Microsoft YaHei", color: "888888"
  });

  slide.addText("0.33", {
    x: 5.6, y: 2.7, w: 3.5, h: 0.9,
    fontSize: 56, fontFace: "Arial", color: theme.secondary, bold: true, align: "center"
  });
  slide.addText("R² 决定系数", {
    x: 5.6, y: 3.5, w: 3.5, h: 0.3,
    fontSize: 13, fontFace: "Microsoft YaHei", color: "999999", align: "center"
  });

  slide.addShape(pres.shapes.RECTANGLE, {
    x: 5.6, y: 3.95, w: 3.4, h: 0.02,
    fill: { color: "E0E0E0" }
  });
  slide.addText("✓ 只用可干预环境变量，模型合理可信", {
    x: 5.6, y: 4.05, w: 3.5, h: 0.3,
    fontSize: 10, fontFace: "Microsoft YaHei", color: theme.secondary
  });

  // Bottom conclusion
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 4.65, w: 9, h: 0.55,
    fill: { color: theme.primary }, rectRadius: 0.06
  });
  slide.addText("\"高 R² 不等于好模型\" —— 特征选择需兼顾统计指标与业务逻辑，避免数据泄露", {
    x: 0.8, y: 4.68, w: 8.4, h: 0.5,
    fontSize: 14, fontFace: "Microsoft YaHei", color: "FFFFFF", bold: true, align: "center", valign: "middle"
  });

  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.secondary } });
  slide.addText("6", { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 12, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle" });

  return slide;
}

module.exports = { createSlide, slideConfig };
