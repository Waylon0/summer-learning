// slide-08.js - 聚类分析结果
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 8, title: '聚类分析结果' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.08, fill: { color: theme.primary } });
  slide.addText("聚类分析结果", { x: 0.8, y: 0.4, w: 8, h: 0.7, fontSize: 28, fontFace: "Microsoft YaHei", color: theme.primary, bold: true });

  // Method description
  slide.addText("K-Means 聚类 + PCA 降维可视化", {
    x: 0.8, y: 1.2, w: 5, h: 0.35,
    fontSize: 15, fontFace: "Microsoft YaHei", color: theme.secondary, bold: true
  });

  const methods = [
    "肘部法则 + 轮廓系数 → 确定最优K值",
    "PCA 降至 2 维 → 散点图可视化聚类结果",
    "各簇特征偏离分析 → 识别高产/低产模式",
  ];
  methods.forEach((m, i) => {
    slide.addShape(pres.shapes.OVAL, {
      x: 0.8, y: 1.75 + i * 0.4, w: 0.18, h: 0.18,
      fill: { color: theme.secondary }
    });
    slide.addText(m, {
      x: 1.15, y: 1.7 + i * 0.4, w: 4, h: 0.35,
      fontSize: 12, fontFace: "Microsoft YaHei", color: "444444"
    });
  });

  // Findings cards
  const findings = [
    { title: "高产环境特征", items: "高熊蜂(bumbles)密度\n高地蜂(andrena)种群\n适宜的温度范围\n充沛的降雨天数", color: theme.primary },
    { title: "低产环境特征", items: "极端温度条件\n低蜜蜂种群密度\n降雨不足或过量\n需人工干预补充", color: "E76F51" },
    { title: "管理建议", items: "低产区域→增加蜂箱投放\n调整种植密度和布局\n根据温度预测提前调控\n数据驱动精准种植", color: theme.secondary },
  ];

  findings.forEach((f, i) => {
    const x = 0.5 + i * 3.15;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: 3.1, w: 2.85, h: 2.1,
      fill: { color: "F7F9FC" }, rectRadius: 0.08
    });
    slide.addShape(pres.shapes.RECTANGLE, {
      x: x, y: 3.1, w: 2.85, h: 0.05,
      fill: { color: f.color }
    });
    slide.addText(f.title, {
      x: x + 0.2, y: 3.25, w: 2.4, h: 0.4,
      fontSize: 14, fontFace: "Microsoft YaHei", color: f.color, bold: true
    });
    slide.addText(f.items, {
      x: x + 0.2, y: 3.7, w: 2.4, h: 1.3,
      fontSize: 11, fontFace: "Microsoft YaHei", color: "555555", lineSpacingMultiple: 1.7
    });
  });

  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.secondary } });
  slide.addText("8", { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 12, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle" });

  return slide;
}

module.exports = { createSlide, slideConfig };
