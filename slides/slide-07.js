// slide-07.js - 模型对比结果
const pptxgen = require("pptxgenjs");
const slideConfig = { type: 'content', index: 7, title: '模型对比结果' };

function createSlide(pres, theme) {
  const slide = pres.addSlide();
  slide.background = { color: "FFFFFF" };

  slide.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.08, fill: { color: theme.primary } });
  slide.addText("模型对比结果", { x: 0.8, y: 0.4, w: 8, h: 0.7, fontSize: 28, fontFace: "Microsoft YaHei", color: theme.primary, bold: true });

  // Table
  const tableRows = [
    [{ text: "模型", options: { bold: true, color: "FFFFFF", fill: { color: theme.primary }, fontSize: 11, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "特征组合", options: { bold: true, color: "FFFFFF", fill: { color: theme.primary }, fontSize: 11, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "技术方案", options: { bold: true, color: "FFFFFF", fill: { color: theme.primary }, fontSize: 11, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "R²", options: { bold: true, color: "FFFFFF", fill: { color: theme.primary }, fontSize: 11, fontFace: "Arial", align: "center" } },
     { text: "评价", options: { bold: true, color: "FFFFFF", fill: { color: theme.primary }, fontSize: 11, fontFace: "Microsoft YaHei", align: "center" } }],

    [{ text: "Ridge回归", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "全部特征(18个)", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "PCA→RidgeCV", options: { fontSize: 10, fontFace: "Arial", align: "center" } },
     { text: "0.78", options: { fontSize: 16, fontFace: "Arial", bold: true, color: "E76F51", align: "center" } },
     { text: "⚠ 含作弊特征", options: { fontSize: 10, fontFace: "Microsoft YaHei", color: "CC0000", align: "center" } }],

    [{ text: "Lasso回归", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "全部特征(18个)", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "PCA→LassoCV", options: { fontSize: 10, fontFace: "Arial", align: "center" } },
     { text: "0.78", options: { fontSize: 16, fontFace: "Arial", bold: true, color: "E76F51", align: "center" } },
     { text: "⚠ 含作弊特征", options: { fontSize: 10, fontFace: "Microsoft YaHei", color: "CC0000", align: "center" } }],

    [{ text: "Ridge回归", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "排除果实(15个)", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "PCA→RidgeCV", options: { fontSize: 10, fontFace: "Arial", align: "center" } },
     { text: "0.33", options: { fontSize: 14, fontFace: "Arial", align: "center" } },
     { text: "合理基线", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center" } }],

    [{ text: "Lasso回归", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "排除果实(15个)", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center" } },
     { text: "PCA→LassoCV", options: { fontSize: 10, fontFace: "Arial", align: "center" } },
     { text: "0.33", options: { fontSize: 14, fontFace: "Arial", align: "center" } },
     { text: "与Ridge持平", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center" } }],

    [{ text: "随机森林", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center", bold: true } },
     { text: "排除果实(15个)", options: { fontSize: 10, fontFace: "Microsoft YaHei", align: "center", bold: true } },
     { text: "200棵树", options: { fontSize: 10, fontFace: "Arial", align: "center", bold: true } },
     { text: "> 线性", options: { fontSize: 14, fontFace: "Arial", bold: true, color: theme.secondary, align: "center" } },
     { text: "★ 最终选用", options: { fontSize: 10, fontFace: "Microsoft YaHei", color: theme.secondary, bold: true, align: "center" } }],
  ];

  slide.addTable(tableRows, {
    x: 0.5, y: 1.4, w: 9,
    border: { type: "solid", pt: 0.5, color: "D0D0D0" },
    colW: [1.5, 2.0, 1.8, 1.4, 2.3],
    rowH: [0.4, 0.45, 0.45, 0.45, 0.45, 0.45],
  });

  // Key conclusion
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 4.3, w: 9, h: 0.9,
    fill: { color: "F7F9FC" }, rectRadius: 0.06
  });
  slide.addText("结论", {
    x: 0.8, y: 4.35, w: 1, h: 0.35,
    fontSize: 14, fontFace: "Microsoft YaHei", color: theme.primary, bold: true
  });
  slide.addText("果实特征贡献了约0.45的R²增量 → 它们是数据泄露特征，不可用于实际预测\n随机森林略优于线性模型，能捕捉非线性关系，且可输出特征重要性排序 → 最终选用方案", {
    x: 0.8, y: 4.65, w: 8.2, h: 0.5,
    fontSize: 11, fontFace: "Microsoft YaHei", color: "555555", lineSpacingMultiple: 1.5
  });

  slide.addShape(pres.shapes.OVAL, { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fill: { color: theme.secondary } });
  slide.addText("7", { x: 9.3, y: 5.1, w: 0.4, h: 0.4, fontSize: 12, fontFace: "Arial", color: "FFFFFF", bold: true, align: "center", valign: "middle" });

  return slide;
}

module.exports = { createSlide, slideConfig };
