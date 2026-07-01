// slide-01.js - Cover
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'cover', index: 1, title: '野生蓝莓产量预测分析' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: theme.primary };

  // Decorative top bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06,
    fill: { color: theme.accent }
  });

  // Decorative side accent line
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 3.5, y: 1.8, w: 3, h: 0.04,
    fill: { color: theme.accent }
  });

  // Main title
  slide.addText("野生蓝莓产量预测分析", {
    x: 1, y: 1.0, w: 8, h: 1.0,
    fontSize: 40, fontFace: "Microsoft YaHei",
    color: "FFFFFF", bold: true, align: "center"
  });

  // English subtitle
  slide.addText("WILD BLUEBERRY YIELD PREDICTION", {
    x: 1, y: 2.0, w: 8, h: 0.6,
    fontSize: 16, fontFace: "Arial",
    color: theme.light, align: "center",
    charSpacing: 4
  });

  // Divider
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 3.5, y: 2.8, w: 3, h: 0.04,
    fill: { color: theme.accent }
  });

  // Subtitle
  slide.addText("软件工程实训答辩", {
    x: 1, y: 3.1, w: 8, h: 0.8,
    fontSize: 22, fontFace: "Microsoft YaHei",
    color: theme.light, align: "center"
  });

  // Author & institution
  slide.addText("王梓宇 | 中国石油大学（华东）", {
    x: 1, y: 4.2, w: 8, h: 0.6,
    fontSize: 16, fontFace: "Microsoft YaHei",
    color: theme.accent, align: "center"
  });

  slide.addText("2026年7月", {
    x: 1, y: 4.7, w: 8, h: 0.5,
    fontSize: 13, fontFace: "Arial",
    color: theme.light, align: "center"
  });

  return slide;
}

module.exports = { createSlide, slideConfig };
