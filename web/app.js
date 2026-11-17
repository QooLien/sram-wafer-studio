
const $ = id => document.getElementById(id);
const labels = {import:'匯入 ASC',maps:'Wafer Maps',data:'資料核對',batch:'批次匯出',settings:'TNO 設定'};
const layers = {fail:'Fail BLK Count',wr:'W&R 四宮格',loss:'Fail BLK / Loss',cat:'Cat Wafer Map',repair:'BL=0 Failure Analysis',vmin:'Chip Vmin Map'};
const tables = {audit:'Missing BLK Address',address:'Fail Address',fbc:'BLK_FBC_Comparison',vmin:'Chip Vmin'};
const s = {page:'import', files:[], batch:[], config:{}, mode:'FBC0', wt:1, pattern:'', layer:'fail', selected:null, vminJudge:null, block:null, blocks:[], mapStage:'wafer', detailPattern:null, detailChart:'fbc', viewPage:0, dataReturn:{page:'import',top:0}, targetAddress:null, demo:null, report:null, busy:false, last:null, versions:0, gridVersion:0, detailVersion:0};
const nfmt = new Intl.NumberFormat('zh-TW');
const vfmt = v => v == null ? '—' : Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:6}) + ' V';
const chipKey = row => row.x + ',' + row.y;
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function put(id, ...nodes) { $(id).replaceChildren(...nodes); }
function options(select, values, selected) {
  select.replaceChildren(...Object.entries(values).map(([key, text]) => {
    const opt = el('option', text); opt.value = key; return opt;
  }));
  if (String(selected) in values) select.value = selected;
}
async function api(path, body) {
  const [action, query] = path.split('?', 2);
  const data = await window.pywebview.api.request(action, body ?? Object.fromEntries(new URLSearchParams(query)));
  if (data.bridge_error) throw new Error(data.bridge_error);
  return data;
}
function notice(text, type='') {
  const node = $('notice'); node.hidden = !text; node.textContent = text;
  node.className = type;
  fitMapStage();
  fitDataTable();
}
function safe(fn) {
  return async event => {
    try { await fn(event); }
    catch (error) { notice(error.message, 'failure'); }
  };
}
function navigate(page) {
  if (s.page !== page) {
    if (page === 'data') {
      s.dataReturn={page:s.page,top:window.scrollY};
      $('data-back').title='返回 '+labels[s.page];
    }
    window.scrollTo(0,0);
  }
  s.page = page;
  for (const key of Object.keys(labels)) $('page-' + key).hidden = key !== page;
  document.querySelectorAll('.nav').forEach(button => {
    const selected = button.dataset.page === page;
    button.classList.toggle('selected', selected);
    button.setAttribute('aria-current', selected ? 'page' : 'false');
  });
  $('breadcrumb').textContent = '工作區 / ' + labels[page];
  if (page === 'maps' && s.report) return refreshMap();
  if (page === 'data' && s.report) return refreshTable();
  if (page === 'settings') renderSettings();
}
document.addEventListener('click', safe(event => {
  const btn = event.target.closest('button[data-page]');
  if (btn) return navigate(btn.dataset.page);
}));
$('data-back').onclick=safe(async()=>{
  const {page,top}=s.dataReturn;
  await navigate(page);
  window.scrollTo(0,top);
});
function renderFiles(batch=false) {
  const list = batch ? s.batch : s.files;
  const id = batch ? 'batch-files' : 'full-files';
  const container = $(id);
  container.classList.toggle('empty', !list.length);
  $(batch ? 'batch-count' : 'file-count').textContent = list.length ? list.length + ' 份 ASC' : '尚未選取檔案';
  if (!list.length) return put(id, el('span', '選擇一份或多份 .asc 檔案'));
  put(id, ...list.map((path, i) => {
    const row = el('div', null, 'file-row');
    const name = path.split(/[\\/]/).pop();
    const description = el('div');
    description.append(el('span', name), el('br'), el('small', path));
    const remove = el('button','移除','quiet'); remove.disabled = s.busy;
    remove.onclick = () => { list.splice(i,1); renderFiles(batch); };
    row.append(el('b','ASC','file-icon'), description, remove); return row;
  }));
}
function modes() {
  const values = Object.fromEntries(Array.from({length:11}, (_,n)=>['FBC'+n,'FBC'+n]).concat([['FBC90%','FBC90%']]));
  options($('vmin-mode'), values, s.mode);
}
function setBusy(value) {
  s.busy = value;
  for(const id of ['pick-full','pick-batch','run-full','run-batch','open-export','open-xlsm','demo','save-config']) $(id).disabled = value;
  document.querySelectorAll('[data-pattern-export]').forEach(button=>{button.disabled=value;});
  renderFiles(); renderFiles(true);
}
async function selectAsc(batch) {
  const data = await api('pick',{kind:'asc'});
  if (!data.paths.length) return;
  if (batch) s.batch = [...new Set([...s.batch,...data.paths])];
  else {
    if (data.paths.length > 3) throw new Error('完整版最多可選 3 份 ASC。');
    s.files = data.paths; s.demo = null; $('full-profile').textContent = '使用完整版 TNO 設定';
  }
  renderFiles(batch);
}
const mapStages = {wafer:'map-layout',matrix:'distribution',detail:'block-detail'};
function fitMapStage() {
  if(s.page!=='maps'||s.mapStage==='detail')return;
  const board = $(s.mapStage==='wafer'?'wafer-grid':'blk-grid');
  if(!board.childElementCount||!board.getClientRects().length)return;
  const top = board.getBoundingClientRect().top + window.scrollY;
  board.style.setProperty('--visible-height',Math.max(0,window.innerHeight-top-14)+'px');
}
window.addEventListener('resize',fitMapStage);
function setMapStage(stage, moveFocus=false) {
  const ready = {wafer:true,matrix:s.blocks.length>0,detail:s.block!==null&&$('block-detail').hasChildNodes()};
  if (!ready[stage]) stage='wafer';
  s.mapStage=stage;
  for (const [key,id] of Object.entries(mapStages)) {
    const active = key===stage;
    $(id).hidden=!active;
    const button = $('stage-'+key);
    button.disabled=!ready[key];
    button.classList.toggle('active',active);
    button.setAttribute('aria-pressed',active);
  }
  $('layer-label').hidden=stage!=='wafer';
  $('pattern-label').hidden=stage!=='wafer'||!['fail','loss','wr'].includes(s.layer);
  if (moveFocus) {
    window.scrollTo(0,0);
    $('stage-'+stage).focus({preventScroll:true});
  }
  fitMapStage();
}
for (const button of document.querySelectorAll('[data-stage]')) {
  button.onclick=()=>setMapStage(button.dataset.stage,true);
}
function setReport(report) {
  s.report = report; s.wt = report.wt_numbers[0]; s.selected = null; s.vminJudge = null; s.block = null; s.blocks = []; s.viewPage = 0;
  s.pattern = report.patterns[0] || ''; s.detailPattern = null; s.detailChart = 'fbc';
  s.layer = report.source_mode === 'address' ? 'cat' : 'fail';
  const pats = Object.fromEntries(report.patterns.map(p=>[p,p]));
  options($('pattern'),pats,s.pattern);
  options($('data-pattern'),{'':'所有 Pattern',...pats},'');
  options($('data-wt'),Object.fromEntries(report.wt_numbers.map(wt=>[wt,'WT'+wt])),s.wt);
  const mapLayers = {...layers}, available = {...tables};
  if(report.source_mode === 'address'){
    delete mapLayers.fail; delete mapLayers.wr; delete mapLayers.loss; delete mapLayers.vmin; delete mapLayers.repair;
    delete available.fbc; delete available.audit; delete available.vmin;
  }
  if(report.source_mode === 'fbc'){
    delete mapLayers.wr; delete mapLayers.loss; delete available.address; delete available.audit;
  }
  options($('layer'),mapLayers,s.layer);
  options($('data-view'),available);
  $('map-empty').hidden = $('data-empty').hidden = true;
  $('map-results').hidden = $('data-results').hidden = false;
  put('blk-grid'); put('block-detail'); setMapStage('wafer');
  $('map-caption').textContent = report.label+' · '+report.manifest[0].lot;
}
function showPaths(output, warnings) {
  const block = el('section',null,'card paths');
  if (output.length) {
    block.append(el('h2','已輸出 '+output.length+' 份檔案'));
    const list = el('ul');
    for(const path of output) list.append(el('li',path));
    block.append(list);
  }
  if(warnings.length) {
    const details = el('details'); details.open = true;
    details.append(el('summary',warnings.length+' 則匯入診斷'));
    for(const warning of warnings) details.append(el('p',warning));
    block.append(details);
  }
  return block;
}
async function waitJob(kind) {
  setBusy(true);
  for (;;) {
    const result = await api('status'); s.last = result;
    notice(result.error || result.message, result.error ? 'failure' : result.working ? 'busy' : '');
    if (result.working) { await new Promise(resolve=>setTimeout(resolve,350)); continue; }
    setBusy(false);
    if (kind === 'batch') put('batch-results',showPaths(result.output,result.warnings));
    if (['export','pattern-export'].includes(kind) && result.output.length) notice('已匯出 '+result.output.join('\n'));
    if (['analyze','reopen'].includes(kind) && !result.error && result.data) {
      setReport(result.data);
      if (result.warnings.length) notice('分析完成。'+result.warnings.length+' 則診斷可在「匯入資訊」查看。');
      await navigate(kind === 'reopen' || result.data.source_mode === 'address' ? 'data' : 'maps');
    }
    break;
  }
}
async function run(kind, data) {
  await api(kind,data);
  try { await waitJob(kind); } finally { setBusy(false); }
}
$('pick-full').onclick = safe(()=>selectAsc(false));
$('pick-batch').onclick = safe(()=>selectAsc(true));
$('demo').onclick = safe(async ()=>{
  const demo = await api('demo',{mode:s.mode}); s.files = demo.paths; s.demo = demo.config;
  $('full-profile').textContent = '使用 128 芯片範例的 TNO 設定'; renderFiles();
});
$('vmin-mode').onchange = () => {s.mode = $('vmin-mode').value;};
$('run-full').onclick = safe(()=>{
  if(!s.files.length) throw new Error('請先選擇 ASC，或載入 128 芯片範例。');
  return run('analyze',{paths:s.files, rows:(s.demo || s.config.full).rows, mode:s.mode, source_mode:$('source-mode').value});
});
$('run-batch').onclick = safe(()=>{
  if(!s.batch.length) throw new Error('請先選擇 ASC。');
  return run('batch',{paths:s.batch, rows:s.config.batch.rows, mode:s.config.batch.mode});
});

$('open-xlsm').onclick = safe(async()=>{
  const data=await api('pick',{kind:'report'});
  if(data.paths.length) await run('reopen',{path:data.paths[0]});
});
function params(extra) {
  return 'view?'+new URLSearchParams({wt:s.wt,pattern:s.pattern,...extra}).toString();
}
// Relative Vmin heatmap, recalculated for each WT. Null-status chips stay categorical.
function vminScale(rows) {
  const values=rows.map(row=>row.value).filter(value=>typeof value==='number'&&Number.isFinite(value)).sort((a,b)=>a-b);
  if (!values.length) return null;
  const min=values[0], max=values[values.length-1];
  const median=values[Math.floor((values.length-1)/2)];
  const stops=[[57,166,99],[255,221,87],[214,69,65]];
  const color=value=>{
    if(max===min)return '#f3d86b';
    const t=Math.max(0,Math.min(1,(value-min)/(max-min)));
    const position=t<=.5?t*2:(t-.5)*2;
    const from=stops[t<=.5?0:1],to=stops[t<=.5?1:2];
    return '#'+from.map((channel,i)=>Math.round(channel+(to[i]-channel)*position).toString(16).padStart(2,'0')).join('');
  };
  return {min,median,max,color};
}
function tint(row) {
  const val = row.value;
  if (s.layer === 'cat' || s.layer === 'repair') {
    const colors={1:'#c6efce',2:'#c6efce',3:'#bdd7ee',4:'#bdd7ee',9:'#ff9999',10:'#bfbfbf',11:'#bfbfbf',
      12:'#dbaddb',13:'#dbaddb',14:'#ffd966',15:'#d9d2e9',16:'#d9d2e9',17:'#d9d2e9',18:'#ffe699',19:'#9bc2e6',20:'#bfbfbf'};
    return [[val ?? '—',colors[val] || (val>=5&&val<=8?'#f8cbad':'#eef3f7')]];
  }
  if(s.layer === 'vmin') return [[val === null ? row.status : vfmt(val).split(' ')[0],val === null ? (row.status==='Pass'?'#dbeafe':'#e2e8f0') : (s.vminScale?.color(val) ?? '#f3d86b')]];
  if(row.gray) return [['','#808080']];
  if(row.blue) return [['','#00b0f0']];
  if(s.layer === 'wr') return row.wr.map((v,i)=>[v||'',v?['#fff','#ffd966','#ff6600','#fff'][i]:'#fff',i === 3?'#8c8c8c':'']);
  if(s.layer === 'loss') return [[val||'','#fff'],[row.loss||'',row.loss?'#ff433c':'#fff',row.loss?'white':'']];
  return [[val||'',val>=50?'#bf8f00':val>=20?'#ffd966':val>=10?'#ffe699':val>0?'#fff2cc':'#fff']];
}
function renderLegend(id, pairs) {
  put(id,...pairs.map(([color, label])=>{
    const node=el('span');const colorBox=el('i');colorBox.style.backgroundColor=color;node.append(colorBox,label);return node;
  }));
}
function showKpis(rows) {
  const current = s.report.manifest.find(phase => phase.wt === s.wt);
  const items = [[s.report.label,'Lot / Wafer'],[nfmt.format(rows.length),'Chip'],[nfmt.format(current.fbc),'FBC 紀錄'],
                 [nfmt.format(current.address),'WT'+s.wt+' Address']];
  put('kpis',...items.map(([value,key])=>{
    const box=el('div',null,'card kpi');box.append(el('span',key),el('b',value));return box;
  }));
}
function showChip(row) {
  if(!row) return put('chip-summary',el('h2','Chip 明細'),el('p','從 Wafer Map 點選一顆 Chip。'));
  const fields=[['WT','WT'+s.wt],['狀態',row.status]];
  if(s.layer === 'vmin'){
    fields.push(['判定來源',s.vminJudge?.source??'Chip Vmin'],['Vmin',vfmt(row.value)],['Judge BLK',row.blk ?? '—'],['TNO',row.tno ?? '—'],['Func.',row.func ?? '—'],
      ['Hard Fail',row.hard.length],['Tail BLK',row.tail.length],['Tail 門檻',row.cutoff==null?'—':Number(row.cutoff).toFixed(2)],
      ['剩餘／資料不足',row.remaining+'／'+row.incomplete]);
  } else if(row.wr){
    fields.push(['Fail BLK',row.value ?? '—'],['Loss BLK',row.loss],
                ['Read / Write',row.wr[0]+' / '+row.wr[1]],['RW / No Monitor',row.wr[2]+' / '+row.wr[3]]);
  }
  const details=el('dl');
  for(const [k,v] of fields){const line=el('div');line.append(el('dt',k),el('dd',v));details.append(line);}
  const link=el('button','查看 Chip 資料','secondary');
  link.onclick=safe(()=>{$('filter-chip').checked=true;s.viewPage=0;return navigate('data');});
  const title=el('h2','X'+row.x+' · Y'+row.y);
  put('chip-summary',title,details,link);
}
function selectMapJudge(row, source) {
  s.vminJudge=s.layer==='vmin'&&row
    ? {source,row,wt:s.wt,chip:chipKey(row)} : null;
}
async function refreshMap() {
  if (!s.report) return;
  const id=++s.versions;
  const rows = await api(params({layer:s.layer}));
  if(id !== s.versions || s.page !== 'maps') return;
  s.vminScale=s.layer==='vmin'?vminScale(rows):null;
  showKpis(rows);
  put('wt-list',...s.report.wt_numbers.map(wt=>{
    const button=el('button','WT'+wt,s.wt===wt?'active':'');
    button.setAttribute('aria-pressed',s.wt===wt);
    button.onclick=safe(async()=>{s.wt=wt;$('data-wt').value=wt;await refreshMap();if(s.block!==null) await refreshDetail();});
    return button;
  }));
  setMapStage(s.mapStage);
  const legend={fail:[['#fff2cc','1–9'],['#ffe699','10–19'],['#ffd966','20–49'],['#bf8f00','50+'],['#808080','Excluded by Cat.']],
    wr:[['#fff','Top left: Read'],['#ffd966','Top right: Write'],['#ff6600','Bottom left: Write & Read'],['#fff','Bottom right: No Monitor'],['#00b0f0','All blocks pass']],
    loss:[['#fff','Left: Fail BLK'],['#ff433c','Right: Loss BLK'],['#00b0f0','All blocks pass']],
    cat:[['#c6efce','C1–2'],['#bdd7ee','C3–4'],['#f8cbad','C5–8'],['#ff9999','C9'],['#bfbfbf','C10–11 / C20']],
    repair:[['#c6efce','C1–2'],['#f8cbad','C5–8'],['#ff9999','C9']],
    vmin:[...(s.vminScale?[
      [s.vminScale.color(s.vminScale.min),'Low '+vfmt(s.vminScale.min)],
      [s.vminScale.color(s.vminScale.median),'Median '+vfmt(s.vminScale.median)],
      [s.vminScale.color(s.vminScale.max),'High '+vfmt(s.vminScale.max)]]:[['#f3d86b','No valid Vmin']]),
      ['#dbeafe','Pass'],['#e2e8f0','Data / threshold status']]};
  renderLegend('map-legend',legend[s.layer]);
  const x0=Math.min(...rows.map(r=>r.x)), x1=Math.max(...rows.map(r=>r.x));
  const y0=Math.min(...rows.map(r=>r.y)), y1=Math.max(...rows.map(r=>r.y));
  const nx=x1-x0+1,ny=y1-y0+1;
  if(Math.max(nx,ny)>100) throw new Error('Wafer Map 座標範圍超過 100。');
  const board=$('wafer-grid');board.replaceChildren();
  const dualPatterns=s.layer==='vmin'
    ? s.report.patterns.filter(name=>['scan','march'].includes(name.toLowerCase())) : [];
  const dual=dualPatterns.length===2;
  board.classList.toggle('wafer-dual-host',dual);
  const renderBoard=(target,data,scale,source='Chip Vmin')=>{
    target.style.setProperty('--wafer-columns',nx);
    target.style.setProperty('--wafer-rows',ny);
    target.style.setProperty('--wafer-min',Math.max(nx,ny)*20+'px');
    target.style.setProperty('--wafer-max',Math.min(660,Math.min(nx,ny)*66)+'px');
    const axis=(text,col,row)=>{const a=el('span',text,'axis');a.style.gridColumn=col;a.style.gridRow=row;target.append(a);};
    axis('Y/X',1,1);
    for(let x=x0;x<=x1;x++)axis(x,x-x0+2,1);
    for(let y=y0;y<=y1;y++)axis(y,1,y-y0+2);
    for(const row of data){
      const values=s.layer==='vmin'
        ? [[row.value===null?row.status:vfmt(row.value).split(' ')[0],
            row.value===null?(row.status==='Pass'?'#dbeafe':'#e2e8f0'):(scale?.color(row.value)??'#f3d86b')]]
        : tint(row);
      const chip=el('button',null,'chip'+(values.length===4?' quad':values.length===2?' half':''));
      chip.dataset.chip=chipKey(row);
      chip.style.gridColumn=row.x-x0+2;chip.style.gridRow=row.y-y0+2;
      chip.title='X'+row.x+' Y'+row.y+' · '+row.status+(row.value!=null?' · '+vfmt(row.value):'');
      chip.setAttribute('aria-label',chip.title);
      chip.dataset.active=String(s.selected===chipKey(row));
      for(const [value,bg,fg] of values){const span=el('span',value);span.style.backgroundColor=bg;if(fg)span.style.color=fg;chip.append(span);}
      chip.onclick=safe(async()=>{
        const selected=chipKey(row);
        s.selected=selected;s.block=null;s.blocks=[];s.detailPattern=row.pattern||s.pattern;
        put('block-detail');setMapStage('wafer');
        board.querySelectorAll('.chip').forEach(btn=>{btn.dataset.active=String(btn.dataset.chip===s.selected);});
        selectMapJudge(row,source);showChip(row);
        if(s.report.source_mode==='address')return;
        await refreshGrid();
        if(s.page==='maps'&&s.selected===selected&&s.blocks.length){
          setMapStage('matrix',true);
          $('blk-grid').querySelector('.judge-cell')?.scrollIntoView({block:'nearest',inline:'nearest'});
        }
      });
      target.append(chip);
    }
  };
  if(dual){
    const pair=el('div',null,'wafer-vmin-pair');
    const datasets=await Promise.all([...dualPatterns.map(pattern=>api(params({view:'map',layer:'vmin_pattern',pattern}))),api(params({view:'map',layer:'vmin_merge'}))]);
    if(id!==s.versions||s.page!=='maps')return;
    const allValues=datasets.flat();
    const commonScale=vminScale(allValues);
    s.vminScale=commonScale;
    renderLegend('map-legend',commonScale?[
      [commonScale.color(commonScale.min),'Low '+vfmt(commonScale.min)],
      [commonScale.color(commonScale.median),'Median '+vfmt(commonScale.median)],
      [commonScale.color(commonScale.max),'High '+vfmt(commonScale.max)],
      ['#dbeafe','Pass'],['#e2e8f0','No Data / status']
    ]:[['#f3d86b','No valid Vmin']]);
    for(const [i,pattern] of [...dualPatterns,'Merge 90%'].entries()){
      const panel=el('section',null,'wafer-vmin-panel');
      panel.append(el('h3',pattern+' Vmin'));
      const map=el('div',null,'wafer');
      renderBoard(map,datasets[i],commonScale,pattern);
      panel.append(map);pair.append(panel);
    }
    board.append(pair);
    const sources=[...dualPatterns,'Merge 90%'];
    const source=sources.includes(s.vminJudge?.source)?s.vminJudge.source:sources[0];
    const selectedRow=datasets[sources.indexOf(source)].find(row=>chipKey(row)===s.selected);
    selectMapJudge(selectedRow,source);showChip(selectedRow);
  }else{
    renderBoard(board,rows,s.vminScale);
    const selectedRow=rows.find(row=>chipKey(row)===s.selected);
    selectMapJudge(selectedRow,'Chip Vmin');showChip(selectedRow);
  }
  showGridVmin();
  fitMapStage();
}
$('layer').onchange=safe(()=>{s.layer=$('layer').value;return refreshMap();});
$('pattern').onchange=safe(()=>{s.pattern=$('pattern').value;return refreshMap();});
function selection() {
  if(!s.selected)return {};
  const [x,y]=s.selected.split(',');return {x,y};
}
const patternColor = name => {
  const key=name.toLowerCase();
  if(key==='scan')return '#ffe0aa';
  if(key==='march')return '#c8d9ef';
  const index=Math.max(0,s.report.patterns.indexOf(name));
  return ['#f0ccee','#dddbf5','#f7d5c8'][index%3];
};
function renderWorstBlockList() {
  const target=$('worst-block-list');
  if(!target)return;
  target.replaceChildren();
  const names=s.report.patterns.filter(name=>['scan','march'].includes(name.toLowerCase()));
  const items=names.flatMap(pattern=>s.blocks.flatMap(entry=>entry.worst_vmin
    .filter(hit=>hit.wt===s.wt&&hit.pattern===pattern)
    .map(hit=>({pattern,blk:entry.blk,voltage:hit.voltage}))));
  const heading=el('div',null,'worst-list-heading');
  heading.append(el('h3','WT'+s.wt+' · Worst Scan / March Vmin'),
    el('p','點選 BLK 可直接開啟明細；同一 Pattern 若有相同最差 Vmin，會列出所有並列 BLK。','tab-note'));
  target.append(heading);
  if(!items.length){target.append(el('p','此 WT 沒有可用的 Scan／March Vmin 資料。','tab-note'));return;}
  const buttons=el('div',null,'worst-block-items');
  for(const item of items){
    const button=el('button',null,'worst-block-item');
    button.append(el('strong',item.pattern),el('span','BLK '+item.blk),el('span',vfmt(item.voltage)));
    button.title='開啟 '+item.pattern+' · BLK '+item.blk+' · '+vfmt(item.voltage);
    button.onclick=()=>{s.detailPattern=item.pattern;$('blk-grid').children[item.blk]?.click();};
    buttons.append(button);
  }
  target.append(buttons);
}
function showGridVmin() {
  const cells=$('blk-grid').children;
  const worstPatterns=new Map();
  const context=s.vminJudge;
  const judge=s.layer==='vmin'&&context?.wt===s.wt&&context.chip===s.selected
    &&context.row.value!=null&&Number.isInteger(context.row.blk)?context.row:null;
  const judgeSummary=$('dist-judge');
  judgeSummary.hidden=!judge;
  judgeSummary.textContent=judge
    ? 'WT'+s.wt+' · '+context.source+' · Judge BLK '+judge.blk+' · '+vfmt(judge.value)+' · TNO '+judge.tno : '';
  for(const [index,entry] of s.blocks.entries()) {
    const tile=cells[index];
    const label=tile.querySelector('.block-vmin');
    const isJudge=judge?.blk===entry.blk;
    tile.classList.toggle('judge-cell',isJudge);
    tile.querySelector('.block-judge').hidden=!isJudge;
    const normal=entry.trigger ? s.report.mode==='FBC90%' ? entry.trigger.func : entry.trigger.voltage==null?entry.trigger.status:vfmt(entry.trigger.voltage) : '';
    const worst=entry.worst_vmin.filter(hit=>hit.wt===s.wt);
    for(const hit of worst)worstPatterns.set(hit.pattern,hit.voltage);
    tile.classList.toggle('worst-cell',worst.length>0);
    label.classList.toggle('worst',worst.length>0);
    const worstVoltages=[...new Set(worst.map(hit=>vfmt(hit.voltage).replace(/ V$/, 'v')))];
    label.textContent=worstVoltages.length>1?'S/M':(worstVoltages[0]??normal);
    const title=['BLK '+entry.blk,isJudge?context.source+' Judge BLK · '+vfmt(judge.value)+' · TNO '+judge.tno:'',normal,entry.trigger?.status==='No Vmin'?crossingReason(entry.trigger):'',...entry.states.map(phase=>'WT'+phase.wt+' '+phase.status),
      ...worst.map(hit=>'WT'+hit.wt+' worst '+hit.pattern+' Vmin '+vfmt(hit.voltage))].filter(Boolean).join(' · ');
    tile.title=title;
    tile.setAttribute('aria-label',title);
  }
  const summary=$('dist-worst');
  summary.hidden=!worstPatterns.size;
  const summaryText=s.report.patterns.filter(pattern=>worstPatterns.has(pattern))
    .map(pattern=>pattern+' '+vfmt(worstPatterns.get(pattern))).join(' · ');
  summary.textContent='WT'+s.wt+' · Worst Vmin · '+summaryText;
}
async function refreshGrid() {
  const id=++s.gridVersion;
  ++s.detailVersion;
  const entries=await api(params({view:'grid',...selection()}));
  if(id!==s.gridVersion || s.page!=='maps')return;
  s.blocks=entries;
  const {x,y}=selection();$('dist-title').textContent='256 BLK Distribution · X'+x+' Y'+y;
  $('dist-wts').textContent='Status bands, left to right: '+s.report.wt_numbers.map(wt=>'WT'+wt).join(' / ');
  const board=$('blk-grid');board.replaceChildren();
  renderLegend('dist-legend',[['#258044','Pass'],['#f35b53','Fail'],['#ffb9b4','Hard Fail'],['#d5dee7','No Data'],...s.report.patterns.map(p=>[patternColor(p),p])]);
  for(const entry of entries){
    const btn=el('button',null,'block'+(entry.hard?' hard':entry.states.every(v=>v.status==='Pass')?' clean':''));
    const phaseSummary=entry.states.map(phase=>'WT'+phase.wt+' '+phase.status);
    btn.style.gridRow=entry.blk%16+1;btn.style.gridColumn=Math.floor(entry.blk/16)+1;
    if(entry.trigger&&!entry.hard)btn.style.background=patternColor(entry.trigger.pattern);
    const number=el('span',null,'block-number');
    const judgeBadge=el('span','J','block-judge');
    judgeBadge.hidden=true;judgeBadge.setAttribute('aria-hidden','true');
    number.append(judgeBadge,el('span','BLK ','block-prefix'),String(entry.blk));
    btn.append(number,el('small',null,'block-vmin'));
    const bars=el('span',null,'bands');
    bars.setAttribute('aria-hidden','true');
    for(const [index,phase] of entry.states.entries()){
      const band=el('i',null,phase.status.toLowerCase().replaceAll(' ','-'));
      band.title=phaseSummary[index];bars.append(band);
    }
    btn.append(bars);
    btn.onclick=safe(async()=>{
      const selected=s.selected;
      s.block=entry.blk;
      board.querySelector('.block.selected')?.classList.remove('selected');
      btn.classList.add('selected');
      put('block-detail');setMapStage('matrix');
      const focusTable=await refreshDetail(true);
      if(s.page==='maps'&&s.mapStage==='matrix'&&s.selected===selected&&s.block===entry.blk&&$('block-detail').hasChildNodes()){
        setMapStage('detail',true);
        focusTable?.scrollIntoView({block:'start'});
      }
    });
    board.append(btn);
  }
  showGridVmin();
  renderWorstBlockList();
}
function table(headers, rows) {
  const table=el('table'), head=el('thead'), body=el('tbody'), bar=el('tr');
  for(const header of headers)bar.append(el('th',header));
  head.append(bar);table.append(head,body);
  if(!rows.length){const row=el('tr'),msg=el('td','沒有符合條件的資料','tab-note');msg.colSpan=headers.length;row.append(msg);body.append(row);}
  for(const values of rows){
    const row=el('tr');for(const value of values)row.append(value instanceof Node ? value : el('td',Array.isArray(value)?value.join(', '):value??'—'));body.append(row);
  }
  return table;
}
function section(title, node, collapsible=false) {
  const block=el(collapsible?'details':'section',null,'detail-section');
  const sc=el('div',null,'table-scroll');sc.append(node);
  const caption=el('h3',title);
  if(collapsible){
    const summary=el('summary');
    summary.append(caption);block.append(summary,sc);
  } else block.append(caption,sc);
  return block;
}
function chartFrame(label, unit, maximum, ticks, width, tickLabel, height=318, xLabel='Test Voltage (V) · Config Order', footer=null, rightMargin=35) {
  const wrap = el('div', null, 'plot');
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 '+width+' '+height);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', label);
  svg.style.minWidth = Math.max(500,width-30)+'px';
  wrap.append(svg);
  const add = (tag, attrs, value, parent=svg) => {
    const node = document.createElementNS(ns, tag);
    for (const [key, val] of Object.entries(attrs)) node.setAttribute(key,val);
    node.textContent = value ?? '';
    parent.append(node);
    return node;
  };
  const left = 80, right = width - rightMargin, bottom = height - (footer?.margin??(xLabel.includes('Scan / March') ? 128 : xLabel === 'Voltage (V)' ? 112 : 74)), top = 43, tickY = footer?bottom+26:height-48;
  const y = value => bottom - value / maximum * (bottom-top);
  add('text', {x:left,y:24,class:'chart-label chart-axis-title'}, unit);
  for (const value of ticks) {
    add('line', {x1:left,x2:right,y1:y(value),y2:y(value),class:'chart-grid'});
    add('text', {x:left-12,y:y(value)+5,'text-anchor':'end',class:'chart-label'}, tickLabel(value));
  }
  add('line',{x1:left,x2:left,y1:top,y2:bottom,class:'chart-axis'});
  add('line',{x1:left,x2:right,y1:bottom,y2:bottom,class:'chart-axis'});
  add('text',{x:(left+right)/2,y:height-15,'text-anchor':'middle',class:'chart-label chart-axis-title'},xLabel);
  return {wrap,add,left,right,bottom,tickY,y};
}
function chartMark(chart, tag, attrs, description) {
  const mark = chart.add(tag,{...attrs,tabindex:0,'aria-label':description});
  chart.add('title',{},description,mark);
  return mark;
}
function crossingReason(result) {
  const reasons={
    'Hard Fail':'此 BLK 已被 Hard Fail 排除。',
    'Prior WT':'此 BLK 已在前序 WT Fail，故排除。',
    'Prior Pattern':'此 BLK 已在同 WT 的前序 Pattern Fail，故排除。',
    'No Data':'必要的 FBC／前序測試資料缺失或格式錯誤。',
    'Pass':'完整 FBC 皆為 0，未觸發 Vmin。',
    'Below':'尚未達到所選 FBC 門檻。'
  };
  if(result.status==='No Vmin')return s.report.mode==='FBC0'
    ? 'FBC0 找不到首筆 Fail 之前的電壓組：首個電壓組已 Fail，或前站未設定電壓。'
    : '達門檻的 TNO 未設定測試電壓。';
  return reasons[result.status]??('依 '+s.report.mode+' 門檻判定。');
}
function stationLabel(station) {
  const fbc = station.fbc === null ? 'No FBC data' : 'FBC '+nfmt.format(station.fbc);
  return station.func+' · TNO '+station.tno+' · '+vfmt(station.v)+' · '+fbc;
}
function accumulationChart(pattern, stations, result, segments=[]) {
  const article = el('div',null,'chart-content');
  if (['Hard Fail','Prior WT','Prior Pattern','No Data'].includes(result.status)) {
    const reason = {'Hard Fail':'Excluded by Hard Fail','Prior WT':'Failed at a prior WT',
      'Prior Pattern':'Failed an earlier pattern','No Data':'Missing FBC or prerequisite data'};
    article.append(el('p',reason[result.status]+'. FBC90% is unavailable.','tab-note'));
    return article;
  }
  const info = result.tno === null ? 'All Pass · Peak FBC 0' :
    'First crossing ≥90% · '+vfmt(result.voltage)+' · '+result.func+' · TNO '+result.tno;
  article.append(el('p',info,'chart-summary'));
  const runs = [];
  for (const [i,station] of stations.entries()) {
    const last = runs.at(-1);
    if (last?.voltage === station.v && last?.pattern === station.pattern) last.end = i;
    else runs.push({voltage:station.v,pattern:station.pattern,start:i,end:i});
  }
  // Unequal runs can put Scan ticks close together even when the total chart is wide.
  // Size from adjacent run centres and label lengths, preserving uniform Config-station spacing.
  let stride=15;
  const labels=runs.map(run=>run.voltage===null?'Not set':vfmt(run.voltage));
  const labelWidths=labels.map(label=>Math.max(66,label.length*10+16));
  for(const [i,run] of runs.entries()){
    if(i===0)stride=Math.max(stride,labelWidths[i]/(run.end-run.start+1));
    if(i===runs.length-1)stride=Math.max(stride,labelWidths[i]/(run.end-run.start+1));
    if(i>0){
      const previous=runs[i-1];
      const gap=(run.start+run.end-previous.start-previous.end)/2;
      stride=Math.max(stride,((labelWidths[i-1]+labelWidths[i])/2+12)/gap);
    }
  }
  const rightMargin=Math.max(100,nfmt.format(result.peak).length*10+24);
  const width=Math.max(560,Math.ceil(stations.length*stride)+80+rightMargin);
  const grouped=segments.length>0;
  const chart=chartFrame(pattern+' FBC90% Accumulation','Cumulative FBC (%)',100,[0,25,50,75,90,100],
    width,n=>n+'%',grouped?354:318,'Test Voltage (V) · Config Order',grouped?{margin:110}:null,rightMargin);
  const x = index => chart.left + (index+.5)*(chart.right-chart.left)/stations.length;
  for (const [i,run] of runs.entries()) {
    chart.add('text',{x:x((run.start+run.end)/2),y:chart.tickY,'text-anchor':'middle',class:'chart-label chart-voltage-label'},labels[i]);
  }
  // Keep the established axes and curve style; label merged pattern boundaries separately.
  let offset=0;
  for (const segment of segments) {
    const start=offset;
    offset+=segment.stations.length;
    chart.add('text',{x:x((start+offset-1)/2),y:chart.tickY+28,
      'text-anchor':'middle',class:'chart-label chart-pattern-label'},segment.name);
    if(start>0)chart.add('line',{x1:x(start-.5),x2:x(start-.5),y1:chart.y(100),y2:chart.bottom,
      class:'chart-pattern-divider'});
  }
  if (result.peak > 0) chart.add('line',{x1:chart.left,x2:chart.right,y1:chart.y(90),y2:chart.y(90),class:'chart-threshold'});
  // The right axis uses the same Peak as the percentage curve, while the raw series may fall.
  chart.add('line',{x1:chart.right,x2:chart.right,y1:chart.y(100),y2:chart.bottom,class:'chart-axis chart-fbc-axis'});
  chart.add('text',{x:width-12,y:24,'text-anchor':'end',class:'chart-label chart-axis-title chart-fbc-axis'},'Fail bit count (FBC)');
  const fbcTicks=[...new Set([0,.25,.5,.75,1].map(fraction=>Math.round(result.peak*fraction)))];
  for(const count of fbcTicks){
    const y=chart.y(result.peak?count/result.peak*100:0);
    chart.add('line',{x1:chart.right,x2:chart.right+5,y1:y,y2:y,class:'chart-axis chart-fbc-axis'});
    chart.add('text',{x:chart.right+10,y:y+5,class:'chart-label chart-fbc-tick'},nfmt.format(count));
  }
  let raw=[];
  const flushRaw=()=>{
    if(raw.length)chart.add('polyline',{points:raw.join(' '),class:'chart-fbc-curve'});
    raw=[];
  };
  for(const [i,station] of stations.entries()){
    if(station.fbc==null){flushRaw();continue;}
    const y=chart.y(result.peak?station.fbc/result.peak*100:0);
    raw.push(x(i)+','+y);
    chartMark(chart,'rect',{x:x(i)-3.5,y:y-3.5,width:7,height:7,class:'chart-fbc-point'},
      (station.pattern?station.pattern+' · ':'')+stationLabel(station)+' · Raw FBC (right axis)');
  }
  flushRaw();
  const points = stations.map(station=>station.accumulated*100);
  chart.add('polyline',{points:points.map((pct,i)=>x(i)+','+chart.y(pct)).join(' '),class:'chart-curve'});
  for (const [i,station] of stations.entries()) {
    const hit = station.tno === result.tno;
    chartMark(chart,'circle',{cx:x(i),cy:chart.y(points[i]),r:hit?7:4.5,
      class:hit?'chart-crossing':'chart-point'},stationLabel(station)+' · '+points[i].toFixed(1)+'%');
  }
  article.append(chartLegend(['Running maximum (%) · left axis','Raw FBC · right axis'],['#204f78','#c2762b']),chart.wrap);
  return article;
}
function combinedAccumulation(details) {
  const names=Object.keys(details.fbc90).filter(name=>['scan','march'].includes(name.toLowerCase()));
  if(names.length!==2)return null;
  const segments=names.map(name=>({name,stations:details.sweep.filter(row=>row.pattern===name)}));
  const allStations=segments.flatMap(segment=>segment.stations);
  const peak=Math.max(0,...allStations.map(station=>station.fbc??0));
  let running=0;
  const stations=allStations.map(station=>{
    running=Math.max(running,station.fbc??0);
    return {...station,accumulated:peak?running/peak:0};
  });
  const result={...(details.merged_fbc90??{status:'No Data',tno:null}),peak};
  const article=accumulationChart('Merge 90%',stations,result,segments);
  article.append(el('p','Merge 90%：依 Config 順序合併 Scan／March，共用 Peak FBC 作為 100%，曲線使用截至當站的最大 FBC。','chart-note'));
  return article;
}

function countChart(label, unit, peak, width, height, xLabel) {
  const ceiling=Math.max(1,peak);
  const step=Math.ceil(ceiling/Math.min(4,ceiling));
  const top=step*Math.ceil(ceiling/step);
  const compact=new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1});
  return chartFrame(label,unit,top,Array.from({length:top/step+1},(_,i)=>i*step),width,n=>compact.format(n),height,xLabel);
}
function chartLegend(labels, colors) {
  const legend = el('div',null,'legend chart-legend');
  for (const [index,label] of labels.entries()) {
    const item=el('span'), swatch=el('i');
    swatch.style.backgroundColor=colors[index];
    item.append(swatch,label);legend.append(item);
  }
  return legend;
}
function voltageDistribution(comparison) {
  const {groups,series,combined,title,incomplete}=comparison;
  if (!series.length || !groups.length) return el('p','No stations with both voltage and FBC data.','tab-note');
  const article=el('div',null,'chart-content');
  article.append(chartLegend(series.map(item=>item.label),series.map(item=>item.color)));
  // One compact slot per Config station: never merge repeated voltages or separate patterns.
  const slotWidth=34;
  const width=Math.max(560,groups.length*slotWidth+116);
  const peak=Math.max(...groups.flatMap(group=>group.stations.map(row=>row.fbc)));
  const chart=countChart(title,'FBC',peak,width,370,'Voltage (V)');
  const stride=(chart.right-chart.left)/groups.length;
  for (const [index,group] of groups.entries()) {
    const mid=chart.left+(index+.5)*stride;
    const label=vfmt(group.voltage).replace(/ V$/, 'v');
    chart.add('text',{x:mid,y:chart.bottom+76,transform:'rotate(-90 '+mid+' '+(chart.bottom+76)+')',
      'text-anchor':'start',class:'chart-label'},label);
    const barWidth=Math.max(4,Math.min(25,stride-5));
    for (const [i,station] of group.stations.entries()) {
      const height=chart.bottom-chart.y(station.fbc);
      const item=series[station.series];
      const description=(combined?item.pattern+' · ':'')+stationLabel(station);
      const part=barWidth/group.stations.length;
      chartMark(chart,'rect',{x:mid-barWidth/2+i*part+1,y:chart.bottom-Math.max(2,height),
        width:Math.max(2,part-2),height:Math.max(2,height),class:'chart-bar',fill:item.color},description);
    }
  }
  article.append(chart.wrap);
  if (incomplete)article.append(el('p','Only stations with recorded voltage and FBC are plotted.','chart-note'));
  return article;
}

function wrMatchDistribution(pattern, groups, labels) {
  const article=el('div',null,'chart-content');
  const colors=['#35638a','#ce8653','#725b83','#d7dce3'];
  article.append(chartLegend(labels,colors));
  if (!groups.length) {
    article.append(el('p','No Function fail addresses were captured.','tab-note'));
    return article;
  }
  const totals=groups.map(row=>row.counts.reduce((a,b)=>a+b,0));
  const chart=countChart(pattern+' W/R Match by Test Voltage','Captured Address Count',
    Math.max(...totals),Math.max(560,groups.length*66+108),275);
  const stride=(chart.right-chart.left)/groups.length;
  const barWidth=Math.min(45,stride*.55);
  for (const [index,row] of groups.entries()) {
    const mid=chart.left+(index+.5)*stride;
    const voltage=row.voltage===null?'Unspecified':vfmt(row.voltage);
    chart.add('text',{x:mid,y:chart.tickY,'text-anchor':'middle',class:'chart-label'},
      row.voltage===null?voltage:voltage.slice(0,-2));
    let base=0;
    for (const [category,count] of row.counts.entries()) {
      if(!count)continue;
      const end=base+count;
      chartMark(chart,'rect',{x:mid-barWidth/2,y:chart.y(end),width:barWidth,height:chart.y(base)-chart.y(end),
        class:'chart-bar',fill:colors[category]},
        voltage+' · '+labels[category]+' · '+nfmt.format(count)+' of '+nfmt.format(totals[index])+' captured addresses');
      base=end;
    }
    if(base)chart.add('text',{x:mid,y:chart.y(base)-6,'text-anchor':'middle',class:'chart-label'},nfmt.format(base));
  }
  article.append(chart.wrap,el('p',totals.some(Boolean)
    ?'Unique Function fail addresses per voltage. Only captured addresses are included.'
    :'No Function fail addresses were captured.','chart-note'));
  return article;
}
function patternCharts(details, initialPattern, showTables) {
  const names = Object.keys(details.fbc90);
  const panel = el('section',null,'detail-section pattern-charts');
  const heading = el('div',null,'toolbar');
  const activePattern=names.includes(initialPattern)?initialPattern:names[0];
  heading.append(el('span','Pattern: '+activePattern,'pattern-static-label'));
  const chartModes=el('div',null,'chips');
  chartModes.setAttribute('role','group');
  chartModes.setAttribute('aria-label','Voltage chart type');
  const modes=[['fbc','FBC'],['match','W/R Match']];
  for(const [mode,text] of modes){
    const button=el('button',text);
    button.onclick=()=>{s.detailChart=mode;render(false);};
    chartModes.append(button);
  }
  heading.append(chartModes);
  const exportStatus = el('p',null,'pattern-export-status');
  exportStatus.setAttribute('role','status');
  exportStatus.hidden = true;
  const actions = el('div',null,'actions pattern-export-actions');
  for (const [kind,text] of [['charts','匯出 PDF／PNG'],['excel','匯出 Excel']]) {
    const button = el('button',text,'secondary');
    button.dataset.patternExport = kind;
    button.disabled = s.busy;
    button.onclick = safe(async()=>{
      const scope = {wt:s.wt,chip:s.selected.split(','),blk:s.block,pattern:activePattern,kind};
      const {paths} = await api('pick',{kind:'folder'});
      if (!paths.length) return;
      exportStatus.hidden = false;
      exportStatus.textContent = '正在匯出 '+scope.pattern+'…';
      try {
        await run('pattern-export',{...scope,folder:paths[0]});
        exportStatus.textContent = s.last.error || s.last.output.join('\n');
      } catch (error) {
        exportStatus.textContent = error.message;
      }
    });
    actions.append(button);
  }
  heading.append(actions);
  const charts = el('div',null,'chart-pair');
  const render = (updateTables=true) => {
    const name = activePattern;
    const stations = details.sweep.filter(row=>row.pattern===name);
    for(const [index,[mode]] of modes.entries()) {
      const button=chartModes.children[index];
      button.classList.toggle('active',s.detailChart===mode);
      button.setAttribute('aria-pressed',s.detailChart===mode);
    }
    const comparison=details.voltage_comparisons.find(report=>report.patterns.includes(name));
    const showComparison=s.detailChart==='fbc'&&comparison.combined;
    const voltageChart=s.detailChart==='match'
      ? section('W/R Match by Test Voltage',wrMatchDistribution(name,details.wr_matches.patterns[name],details.wr_matches.labels))
      : section(comparison.title,voltageDistribution(comparison));
    const accumulation=section('FBC90% Accumulation',accumulationChart(name,stations,details.fbc90[name]));
    const hasCombined=Object.keys(details.fbc90).filter(n=>['scan','march'].includes(n.toLowerCase())).length===2;
    charts.classList.toggle('combined-voltage',showComparison);
    charts.replaceChildren(...(hasCombined?[voltageChart]:(showComparison?[voltageChart,accumulation]:[accumulation,voltageChart])));
    if(updateTables)showTables(name,stations);
  };
  render();
  panel.append(heading,exportStatus,charts);
  return panel;
}
function preferredMarch(details) {
  const names=Object.keys(details.fbc90);
  const scan=names.find(name=>name.toLowerCase()==='scan');
  const march=names.find(name=>name.toLowerCase()==='march');
  if(!scan||!march||details.fbc90[scan].status!=='Pass')return null;
  const result=details.fbc90[march];
  const endpointFailed=details.coverage.some(row=>row.pattern===march);
  return endpointFailed||['Fail','No Vmin'].includes(result.status)?march:null;
}
async function refreshDetail(fromMatrix=false) {
  if(s.block===null)return;
  const id=++s.detailVersion;
  const currentPattern=s.detailPattern;
  const details=await api(params({view:'detail',...selection(),blk:s.block}));
  if(id!==s.detailVersion||s.page!=='maps')return;
  const march=fromMatrix?preferredMarch(details):null;
  const initialPattern=march||currentPattern||s.pattern;
  const title=el('div',null,'section-title');
  const {x,y}=selection();
  title.append(el('h2','WT'+s.wt+' · X'+x+' Y'+y+' · BLK '+s.block),el('span',s.report.mode));
  const body=el('div',null,'details-body');
  if(details.hard_fail_tests.length){
    const hardFail=section('Hard Fail test items',table(['WT','TNO','Function','Test Voltage','FBC','Fail Cat.'],
      details.hard_fail_tests.map(test=>['WT'+test.wt,test.tno,test.func,vfmt(test.voltage),test.fbc,test.cat?'C'+test.cat:'—'])),true);
    hardFail.open=true;
    body.append(hardFail);
  }
  const sweepData=el('div');
  const addressData=el('div');
  const sweep=section('Function sweep（Config 順序）',sweepData,true);
  const address=section('Fail Address / Monitor 匹配',addressData,true);
  sweep.open=Boolean(march);
  const showTables=(pattern,stations)=>{
    sweepData.replaceChildren(table(['Pattern','TNO','Func.','Test Voltage','FBC','狀態'],
      details.sweep.map(r=>[r.pattern,r.tno,r.func,vfmt(r.v),r.fbc,r.state])));
    const addresses=details.addresses.map(r=>{
      const cell=el('td'), btn=el('button','查看地址','quiet');
      btn.onclick=safe(()=>{
        $('data-view').value='address';$('filter-chip').checked=true;
        s.targetAddress=r.address.join(',');s.viewPage=0;return navigate('data');
      });
      cell.append(btn);
      const voltage=el('td',r.function_voltages.map(vfmt).join(', '));
      voltage.title='Function TNO '+r.function.join(', ');
      return [r.pattern,...r.address,voltage,r.write,r.read,r.category,cell];
    });
    addressData.replaceChildren(table(['Pattern','BLK','WL','BL','IO','Function Voltage','Write TNO','Read TNO','分類','來源'],addresses));
  };
  const combined=combinedAccumulation(details);
  if(combined){
    const figures=el('div',null,'pattern-charts');
    const charts=el('div',null,'chart-pair combined-voltage');
    for(const name of Object.keys(details.fbc90).filter(n=>['scan','march'].includes(n.toLowerCase()))){
      charts.append(section(name+' FBC90% Accumulation',accumulationChart(name,details.sweep.filter(r=>r.pattern===name),details.fbc90[name])));
    }
    charts.append(section('Merge 90% Accumulation',combined));
    figures.append(charts);body.append(figures);
  }
  if(Object.keys(details.fbc90).length){
    s.detailPattern=initialPattern;
    for(const name of Object.keys(details.fbc90))body.append(patternCharts(details,name,showTables));
  }
  const block=s.blocks[s.block];
  if(block)body.append(section('各 WT 狀態與 W/R 匹配',table(['WT','狀態','Write','Read'],
    block.states.map(phase=>['WT'+phase.wt,phase.status,phase.w,phase.r])),true));
  body.append(section('Vmin 判定',table(['Pattern','狀態','TNO','Func.','Vmin','峰值 FBC','判定說明'],
    details.crossings.map(c=>[c.pattern,c.status,c.tno,c.func,c.voltage==null?c.status:vfmt(c.voltage),c.peak,crossingReason(c)])),true));
  body.append(sweep,address);
  put('block-detail',title,body);setMapStage(s.mapStage);
  return march?sweep:null;
}

function renderAddressHeader(addressTable) {
  const columns=el('colgroup');
  let width=0;
  for(const [i,heading] of [...addressTable.tHead.rows[0].cells].entries()){
    heading.scope='col';
    heading.title=heading.textContent;
    const size=i<7?46:Math.max(116,Math.min(300,heading.textContent.length*7+22));
    const column=el('col');
    column.style.width=size+'px';
    columns.append(column);
    width+=size;
  }
  const header=el('table',null,'address-table address-head-table');
  header.style.width=addressTable.style.width=width+'px';
  header.append(columns.cloneNode(true),addressTable.tHead.cloneNode(true));
  addressTable.prepend(columns);
  addressTable.classList.add('address-table','address-body-table');
  put('address-head',header);
}
function syncAddressHeader() {
  if(!$('address-header').hidden)$('address-head').scrollLeft=$('data-table').scrollLeft;
}
$('data-table').addEventListener('scroll',syncAddressHeader,{passive:true});
$('address-header').addEventListener('wheel',event=>{
  if(event.ctrlKey)return;
  const viewport=$('data-table');
  const line=event.deltaMode===WheelEvent.DOM_DELTA_LINE?32:1;
  const pages=event.deltaMode===WheelEvent.DOM_DELTA_PAGE;
  const x=event.deltaX||(event.shiftKey?event.deltaY:0);
  const y=event.shiftKey&&!event.deltaX?0:event.deltaY;
  viewport.scrollBy(x*(pages?viewport.clientWidth:line),y*(pages?viewport.clientHeight:line));
  event.preventDefault();
},{passive:false});
function fitDataTable() {
  if (s.page !== 'data' || !s.report) return;
  const viewport=$('data-table');
  const top=viewport.getBoundingClientRect().top+window.scrollY;
  const footer=$('data-results').querySelector('.pagination').offsetHeight;
  viewport.style.maxHeight=Math.max(120,Math.floor(window.innerHeight-top-footer-16))+'px';
  const header=$('address-header');
  if(!header.hidden){
    header.style.setProperty('--address-top',document.querySelector('.top').offsetHeight+'px');
    $('address-head').style.width=viewport.clientWidth+'px';
    syncAddressHeader();
  }
}
window.addEventListener('resize',fitDataTable);
async function refreshTable() {
  const mode=$('data-view').value,id=++s.versions;
  $('data-scope').hidden=mode!=='audit';
  $('data-wt').parentElement.hidden=!['audit','vmin'].includes(mode);
  $('filter-chip').disabled=!s.selected;
  const result=await api(params({view:mode,wt:$('data-wt').value,pattern:$('data-pattern').value,
    page:s.viewPage,...(s.targetAddress?{target:s.targetAddress}:{}),...($('filter-chip').checked?selection():{})}));
  if(id!==s.versions||s.page!=='data')return;
  s.viewPage=result.page;s.targetAddress=null;
  const rendered=table(result.headers,result.rows);
  const address=mode==='address';
  const viewport=$('data-table');
  $('address-header').hidden=!address;
  viewport.classList.toggle('address-viewport',address);
  if(address)renderAddressHeader(rendered);
  else put('address-head');
  put('data-table',rendered);
  viewport.scrollTop=0;
  $('prev').disabled=s.viewPage===0;$('next').disabled=!result.more;
  $('page-no').textContent='第 '+(s.viewPage+1)+' 頁';
  fitDataTable();
  if(result.highlighted!==null){
    const row=rendered.tBodies[0].rows[result.highlighted];
    row.classList.add('address-match');
    const relativeTop=row.getBoundingClientRect().top-viewport.getBoundingClientRect().top;
    viewport.scrollTop=relativeTop-(address?0:rendered.tHead.offsetHeight);
  }
}
for(const id of ['data-view','data-wt','data-pattern','filter-chip']) $(id).onchange=safe(()=>{s.viewPage=0;return refreshTable();});
$('prev').onclick=safe(()=>{if(s.viewPage>0)s.viewPage--;return refreshTable();});
$('next').onclick=safe(()=>{s.viewPage++;return refreshTable();});
function modal(title, node) {
  $('modal-title').textContent=title;put('modal-content',node);$('modal').showModal();
}
$('close-modal').onclick=()=>$('modal').close();
$('open-import').onclick=safe(async()=>{
  const data=await api('status'), block=el('div');
  if(!data.data&&!data.output.length&&!data.warnings.length)block.append(el('p','目前沒有匯入記錄。'));
  if(data.data)block.append(section(data.data.label,table(['WT','STEP','版本','Chip','FBC','Address','忽略的 Address','重複 FBC','來源'],
    data.data.manifest.map(r=>['WT'+r.wt,r.step,r.version,r.chips,r.fbc,r.address,r.invalid,r.duplicates,r.path]))));
  if(data.output.length||data.warnings.length)block.append(showPaths(data.output,data.warnings));
  modal('匯入資訊',block);
});
$('open-export').onclick=safe(()=>{
  if(!s.report)throw new Error('請先匯入 ASC。');
  const block=el('div',null,'modal-files');
  block.append(el('p','預設存回第一份 ASC 的資料夾。'));
  if (s.selected) block.append(el('p','完整 Excel 的 BLK 矩陣使用 X'+selection().x+' Y'+selection().y+'。'));
  let folder='';
  const path=el('p','使用 ASC 來源資料夾','modal-path');
  const picker=el('button','選擇匯出資料夾','secondary');
  picker.onclick=safe(async()=>{const data=await api('pick',{kind:'folder'});if(data.paths.length){folder=data.paths[0];path.textContent=folder;}});
  block.append(picker,path);
  const modes={full:'完整 Excel 報表（原版版面）',address:'Fail Address Excel',fbc:'FBC Excel',cat:'Cat Map Excel',ppt:'Wafer Maps PowerPoint · 37 cm'};
  for(const [kind,label] of Object.entries(modes)){
    if(s.report.source_mode!=='full' && ![s.report.source_mode,'cat'].includes(kind))continue;
    const button=el('button',label,'secondary');
    button.onclick=safe(()=>{$('modal').close();return run('export',{kind,folder,chip:s.selected?.split(',')});});
    block.append(button);
  }
  modal('匯出報表',block);
});
function profile() {return $('profile').value;}
function renderSettings() {
  const current=s.config[profile()];if(!current)return;
  const full=profile()==='full', header=el('tr');
  const fields=[['tno','TNO'],['name','Func.'],['voltage','Voltage (V)'],['cat','Fail Cat.']];
  if(full)fields.push(['stop','Stop Sign']);
  for(const title of ['Group',...fields.map(f=>f[1]),'列操作'])header.append(el('th',title));
  put('config-head',header);
  put('config-rows',...current.rows.map((obj,i)=>{
    const row=el('tr'), group=el('td'), select=el('select');
    options(select,{Monitor:'Monitor',Function:'Function'},obj.group);
    select.setAttribute('aria-label','Group '+(i+1));select.onchange=()=>{obj.group=select.value;};group.append(select);row.append(group);
    for(const [key,title] of fields){
      const cell=el('td'), input=el('input');
      input.value=obj[key]??'';input.setAttribute('aria-label',title+' '+(i+1));
      if(key==='tno'||key==='cat')input.inputMode='numeric';if(key==='voltage')input.inputMode='decimal';
      input.oninput=()=>{obj[key]=input.value;};cell.append(input);row.append(cell);
    }
    const actions=el('td'), moves=el('div',null,'moves');
    for(const [icon,offset,name] of [['↑',-1,'上移'],['↓',1,'下移'],['✕',0,'移除']]){
      const button=el('button',icon,offset?'quiet':'quiet remove');button.setAttribute('aria-label',name+' '+(i+1));
      button.disabled=offset!==0&&(i+offset<0||i+offset>=current.rows.length);
      button.onclick=()=>{
        if(!offset)current.rows.splice(i,1);
        else [current.rows[i],current.rows[i+offset]]=[current.rows[i+offset],current.rows[i]];
        renderSettings();
      };moves.append(button);
    }
    actions.append(moves);row.append(actions);return row;
  }));
}
$('profile').onchange=renderSettings;
$('add-row').onclick=()=>{s.config[profile()].rows.push({group:'Function',tno:'',name:'',voltage:'',cat:'',stop:''});renderSettings();$('config-rows').lastChild?.scrollIntoView({block:'nearest'});};
$('pick-config').onclick=safe(async()=>{
  const result=await api('pick',{kind:'settings'});
  if(result.config){s.config[profile()]=result.config;renderSettings();notice('已載入 '+result.paths[0].split(/[\\/]/).pop()+'，可編輯後儲存。');}
});
$('save-config').onclick=safe(async()=>{
  const key=profile(), data=s.config[key];
  s.config[key]=await api('save-settings',{profile:key,rows:data.rows,mode:key==='full'?s.mode:data.mode});
  renderSettings();notice('已儲存 '+(key==='full'?'完整版':'批次匯出')+'設定。');
});
const initialize = safe(async () => {
  const settings=await api('settings');s.config=settings.settings;s.mode=s.config.full.mode;modes();
  renderFiles();renderFiles(true);
  const result=await api('status');s.last=result;
  if(result.data)setReport(result.data);
  if(result.working)await waitJob('analyze');
});
if (window.pywebview?.api?.request) initialize();
else window.addEventListener('pywebviewready', initialize, {once:true});
