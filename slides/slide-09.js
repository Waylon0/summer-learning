// slide-09.js - 测试集预测
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 9, title: '测试集预测' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.08, fill: { color: theme.primary } });
  slide.addText("测试集预测", { x: 0.8, y: 0.4, w: 8, h: 0.7, fontSize: 28, fontFace: "Microsoft YaHei", color: theme.primary, bold: true });

  // Final model box
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 1.4, w: 9, h: 1.4,
    fill: { color: "F0FAF8" }, rectRadius: 0.1
  });

  slide.addText("最终预测方案", {
    x: 0.8, y: 1.5, w: 3, h: 0.4,
    fontSize: 16, fontFace: "Microsoft YaHei", color: theme.secondary, bold: true
  });

  const steps = [
    { label: "模型", value: "随机森林 (n_estimators=200)" },
    { label: "特征", value: "排除果实特征的 15 个环境变量" },
    { label: "训练数据", value: "全部训练集（含 yield 标签）" },
    { label: "预测输出", value: "outputs/models/test_predictions.csv" },
  ];

  steps.forEach((s, i) => {
    const y = 2.0 + i * 0.28;
    slide.addText(s.label, { x: 1.0, y: y, w: 1.2, h: 0.28, fontSize: 12, fontFace: "Microsoft YaHei", color: theme.secondary, bold: true });
    slide.addText(s.value, { x: 2.3, y: y, w: 6, h: 0.28, fontSize: 12, fontFace: "Arial", color: "444444" });
  });

  // Results
  slide.addText("预测结果分析", {
    x: 0.8, y: 3.2, w: 5, h: 0.4,
    fontSize: 16, fontFace: "Microsoft YaHei", color: theme.primary, bold: true
  });

  // Stats cards
  const stats = [
    { label: "预测均值", value: "合理范围", desc: "与训练集产量均值\n在同一数量级" },
    { label: "预测范围", value: "[min, max]", desc: "分布无异常极值\n模型输出稳定" },
    { label: "实际价值", value: "参考意义", desc: "辅助种植管理\n产量预估与资源配置" },
  ];

  stats.forEach((s, i) => {
    const x = 0.5 + i * 3.15;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: 3.8, w: 2.85, h: 1.4,
      fill: { color: "FFFFFF" }, rectRadius: 0.06,
      shadow: { type: "outer", blur: 4, offset: 2, color: "E0E0E0", opacity: 0.3 }
    });
    slide.addText(s.label, {
      x: x + 0.2, y: 3.9, w: 2.4, h: 0.3,
      fontSize: 12, fontFace: "Microsoft YaHei", color: "999999"
    });
    slide.addText(s.value, {
      x: x + 0.2, y: 4.15, w: 2.4, h: 0.4,
      fontSize: 20, fontFace: "Arial", color: theme.primary, bold: true
    });
    slide.addText(s.desc, {
      x: x + 0.2, y: 4.55, w: 2.4, h: 0.5,
      fontSize: 10, fontFace: "Microsoft YaHei", color: "888888"
    });
  });

  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.secondary } });
  slide.addText("9", { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 12, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle" });

  return slide;
}

module.exports = { createSlide, slideConfig };
