// 小知己 layouts; renderer dependency: gitbrent/PptxGenJS (MIT).
const fs = require('node:fs');
const pptxgen = require('pptxgenjs');
const deck = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = '小知己';
pptx.subject = 'Research report with traceable sources';
pptx.title = deck.title;
pptx.lang = 'zh-CN';
pptx.theme = { headFontFace: 'Microsoft YaHei', bodyFontFace: 'Microsoft YaHei', lang: 'zh-CN' };
const sourceMap = new Map(deck.sources.map(s => [s.id, s]));
let count = 0;
function base(title, sources) {
  const slide = pptx.addSlide();
  slide.background = {color:'F6F8FC'};
  slide.addShape(pptx.ShapeType.rect, {x:0,y:0,w:0.16,h:7.5,fill:{color:'245AA5'},line:{color:'245AA5'}});
  slide.addText(title, {x:0.6,y:0.35,w:12.1,h:0.8,fontSize:26,bold:true,color:'183453',breakLine:false,fit:'shrink'});
  const foot = sources.map(id => sourceMap.get(id)).filter(Boolean).map(s => s.url).join(' | ');
  slide.addText(foot || deck.title, {x:0.6,y:7.04,w:11.4,h:0.3,fontSize:8,color:'526579',fit:'shrink'});
  slide.addText(String(++count), {x:12.1,y:7.0,w:0.6,h:0.3,fontSize:10,color:'526579'});
  return slide;
}
for (const item of deck.slides) {
  // Split long bullets into bounded editable text blocks; table/chart get their own pages.
  const lines = item.bullets.flatMap(t => {
    const chars = Array.from(t); const result=[];
    for(let i=0;i<chars.length;i+=100) result.push(chars.slice(i,i+100).join(''));
    return result;
  });
  const pages = Math.max(1, Math.ceil(lines.length/6));
  for(let p=0;p<pages;p++) {
    const slide=base(item.title + (pages>1?` (${p+1}/${pages})`:''), item.source_ids);
    lines.slice(p*6,p*6+6).forEach((t,i)=>slide.addText('• '+t,{x:0.8,y:1.45+i*0.8,w:11.7,h:0.7,fontSize:20,color:'25384D',fit:'shrink',margin:0.03}));
    slide.addNotes(item.notes || '');
  }
  if(item.table.length) {
    for(let start=1;start<item.table.length || start===1;start+=10) {
      const slide=base(item.title+' · 表格',item.source_ids);
      const rows=[item.table[0],...item.table.slice(start,start+10)];
      slide.addTable(rows,{x:0.7,y:1.5,w:11.9,h:4.9,fontSize:14,border:{type:'solid',color:'D0DAE8',pt:1},color:'25384D',fill:'FFFFFF',autoPage:false,margin:0.08});
      slide.addNotes(item.notes || '');
    }
  }
  if(item.chart.length) {
    const slide=base(item.title+' · 图表',item.source_ids);
    slide.addChart(pptx.ChartType.bar,item.chart,{x:0.8,y:1.5,w:11.5,h:4.9,showLegend:true,showTitle:false,showValue:true,catAxisLabelFontFace:'Microsoft YaHei',valAxisLabelFontFace:'Microsoft YaHei'});
    slide.addNotes(item.notes || '');
  }
}
if(deck.sources.length) {
  for(let i=0;i<deck.sources.length;i+=7) {
    const slide=base('参考来源',[]);
    deck.sources.slice(i,i+7).forEach((s,j)=>slide.addText(`${i+j+1}. ${s.title}\n${s.url}`,{x:0.8,y:1.35+j*0.75,w:11.7,h:0.67,fontSize:12,color:'25384D',fit:'shrink',...(/^https?:\/\//.test(s.url)?{hyperlink:{url:s.url}}:{})}));
  }
}
pptx.writeFile({fileName:process.argv[3]}).then(()=>console.log(`Rendered ${count} slides`)).catch(e=>{console.error(e);process.exit(1)});
