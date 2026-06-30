// slide-02.js - Table of Contents
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'toc', index: 2, title: '目录' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  // Left accent bar
  slide.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 0.12, h: 5.625,
    fill: { color: theme.primary }
  });

  // Title
  slide.addText("目  录", {
    x: 1.5, y: 0.4, w: 7, h: 0.8,
    fontSize: 32, fontFace: "Microsoft YaHei",
    color: theme.primary, bold: true
  });

  slide.addText("CONTENTS", {
    x: 1.5, y: 1.0, w: 7, h: 0.4,
    fontSize: 12, fontFace: "Arial",
    color: theme.accent, charSpacing: 3
  });

  const items = [
    { num: "01", cn: "基本信息与分工", en: "Basic Info & Role" },
    { num: "02", cn: "任务分析", en: "Task Analysis" },
    { num: "03", cn: "技术方案", en: "Technical Approach" },
    { num: "04", cn: "核心创新点", en: "Key Innovation" },
    { num: "05", cn: "模型对比结果", en: "Model Comparison" },
    { num: "06", cn: "聚类分析结果", en: "Clustering Analysis" },
    { num: "07", cn: "测试集预测", en: "Test Set Prediction" },
    { num: "08", cn: "个人总结", en: "Summary" },
  ];

  const startY = 1.8;
  const rowH = 0.45;

  items.forEach((item, i) => {
    const y = startY + i * rowH;
    const xBase = 1.8;

    // Number circle
    slide.addShape(pres.shapes.OVAL, {
      x: xBase, y: y + 0.05, w: 0.35, h: 0.35,
      fill: { color: i % 2 === 0 ? theme.primary : theme.secondary }
    });
    slide.addText(item.num, {
      x: xBase, y: y + 0.05, w: 0.35, h: 0.35,
      fontSize: 12, fontFace: "Arial",
      color: "FFFFFF", bold: true, align: "center", valign: "middle"
    });

    // Chinese title
    slide.addText(item.cn, {
      x: xBase + 0.6, y: y, w: 4, h: 0.26,
      fontSize: 15, fontFace: "Microsoft YaHei",
      color: theme.primary, bold: true
    });

    // English subtitle
    slide.addText(item.en, {
      x: xBase + 0.6, y: y + 0.24, w: 4, h: 0.2,
      fontSize: 10, fontFace: "Arial",
      color: theme.light.replace("#", "")
    });

    // Separator line (using accent color)
    if (i < items.length - 1) {
      slide.addShape(pres.shapes.RECTANGLE, {
        x: xBase + 0.6, y: y + 0.42, w: 6, h: 0.01,
        fill: { color: "E0E0E0" }
      });
    }
  });

  // Page badge
  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.secondary } });
  slide.addText("2", { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 12, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle" });

  return slide;
}

module.exports = { createSlide, slideConfig };
