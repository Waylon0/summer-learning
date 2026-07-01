// compile.js - Combine all slides into final PPTX
const pptxgen = require('pptxgenjs');
const path = require('path');

const pres = new pptxgen();
pres.layout = 'LAYOUT_16x9';

const theme = {
  primary: "264653",
  secondary: "2a9d8f",
  accent: "e9c46a",
  light: "f4a261",
  bg: "F5F5F5"
};

for (let i = 1; i <= 10; i++) {
  const num = String(i).padStart(2, '0');
  const slideModule = require(`./slide-${num}.js`);
  slideModule.createSlide(pres, theme);
  console.log(`Slide ${num} added`);
}

const outputPath = path.join(__dirname, 'output', '蓝莓产量预测答辩PPT.pptx');
pres.writeFile({ fileName: outputPath }).then(() => {
  console.log(`PPT saved: ${outputPath}`);
});
