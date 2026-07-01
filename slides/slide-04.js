// slide-04.js - 任务分析
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 4, title: '任务分析' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.08, fill: { color: theme.primary } });
  slide.addText("任务分析", { x: 0.8, y: 0.4, w: 8, h: 0.7, fontSize: 28, fontFace: "Microsoft YaHei", color: theme.primary, bold: true });

  // Three goal boxes across top
  const goals = [
    { icon: "01", title: "数据理解", desc: "17个特征变量\n1个目标变量(yield)\n含训练集与测试集" },
    { icon: "02", title: "相关性分析", desc: "Pearson相关系数\n识别关键影响因素\n绘制热力图" },
    { icon: "03", title: "预测建模", desc: "对比多种模型\n评估预测精度\n输出测试集结果" },
  ];

  goals.forEach((g, i) => {
    const x = 0.5 + i * 3.15;
    slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: 1.4, w: 2.85, h: 1.6,
      fill: { color: i === 0 ? theme.primary : i === 1 ? theme.secondary : theme.accent },
      rectRadius: 0.08
    });
    slide.addText(g.icon, { x: x + 0.15, y: 1.5, w: 0.5, h: 0.4, fontSize: 20, fontFace: "Arial", color: "FFFFFF", bold: true });
    slide.addText(g.title, { x: x + 0.15, y: 1.9, w: 2.5, h: 0.35, fontSize: 16, fontFace: "Microsoft YaHei", color: "FFFFFF", bold: true });
    slide.addText(g.desc, { x: x + 0.15, y: 2.3, w: 2.5, h: 0.6, fontSize: 11, fontFace: "Microsoft YaHei", color: "FFFFFF" });
  });

  // Feature category table
  slide.addText("特征变量分类", { x: 0.8, y: 3.3, w: 4, h: 0.4, fontSize: 16, fontFace: "Microsoft YaHei", color: theme.primary, bold: true });

  const rows = [
    [{ text: "类别", options: { bold: true, color: "FFFFFF", fill: { color: theme.primary }, fontSize: 10, fontFace: "Microsoft YaHei" } },
     { text: "特征", options: { bold: true, color: "FFFFFF", fill: { color: theme.primary }, fontSize: 10, fontFace: "Microsoft YaHei" } },
     { text: "数量", options: { bold: true, color: "FFFFFF", fill: { color: theme.primary }, fontSize: 10, fontFace: "Arial", align: "center" } }],
    [{ text: "蜜蜂种群", options: { fontSize: 10, fontFace: "Microsoft YaHei" } }, { text: "honeybee, bumbles, andrena, osmia", options: { fontSize: 9, fontFace: "Arial" } }, { text: "4", options: { fontSize: 10, align: "center" } }],
    [{ text: "温度指标", options: { fontSize: 10, fontFace: "Microsoft YaHei" } }, { text: "上下限温度 max/min/average×2", options: { fontSize: 9, fontFace: "Arial" } }, { text: "6", options: { fontSize: 10, align: "center" } }],
    [{ text: "降雨", options: { fontSize: 10, fontFace: "Microsoft YaHei" } }, { text: "rainingdays, averagerainingdays", options: { fontSize: 9, fontFace: "Arial" } }, { text: "2", options: { fontSize: 10, align: "center" } }],
    [{ text: "果实特征", options: { fontSize: 10, fontFace: "Microsoft YaHei", color: theme.accent } }, { text: "fruitset, fruitmass, seeds  ⚠ 数据泄露", options: { fontSize: 9, fontFace: "Arial", color: theme.accent } }, { text: "3", options: { fontSize: 10, fontFace: "Arial", align: "center", color: theme.accent } }],
    [{ text: "果树规模", options: { fontSize: 10, fontFace: "Microsoft YaHei" } }, { text: "clonesize", options: { fontSize: 10, fontFace: "Arial" } }, { text: "1", options: { fontSize: 10, align: "center" } }],
  ];

  slide.addTable(rows, {
    x: 0.5, y: 3.8, w: 5.5,
    border: { type: "solid", pt: 0.5, color: "D0D0D0" },
    colW: [1.3, 3.4, 0.8],
    rowH: [0.35, 0.32, 0.32, 0.32, 0.32, 0.32],
  });

  // Right side note
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 6.5, y: 3.3, w: 3, h: 1.8,
    fill: { color: "FFF8F0" },
    rectRadius: 0.08
  });
  slide.addText("关键洞察", {
    x: 6.7, y: 3.4, w: 2.5, h: 0.35,
    fontSize: 14, fontFace: "Microsoft YaHei", color: theme.accent, bold: true
  });
  slide.addText("果实特征(fruitset/fruitmass/\nseeds)与yield高度共线\n(R>0.8)，是典型的\n\"数据泄露\"特征\n→ 需做对照实验验证", {
    x: 6.7, y: 3.8, w: 2.6, h: 1.2,
    fontSize: 11, fontFace: "Microsoft YaHei", color: "666666"
  });

  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.secondary } });
  slide.addText("4", { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 12, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle" });

  return slide;
}

module.exports = { createSlide, slideConfig };
