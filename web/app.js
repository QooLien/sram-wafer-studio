
const $ = id => document.getElementById(id);
const labels = {import:'Import ASC',maps:'Wafer Maps',data:'Data Inspection',correlation:'W/R Correlation',batch:'Batch export',settings:'TNO Configuration'};
const layers = {fail:'Fail BLK Count',wr:'W/R quadrants',loss:'Fail BLK / Loss',cat:'Cat Wafer Map',repair:'BL=0 Failure Analysis',vmin:'Chip Vmin Map'};
const tables = {audit:'Missing BLK Address',address:'Fail Address',fbc:'BLK_FBC_Comparison',vmin:'Chip Vmin'};
const s = {page:'import', files:[], batch:[], config:{}, mode:'FBC0', wt:1, pattern:'', layer:'fail', selected:null, vminJudge:null, block:null, blocks:[], mapStage:'wafer', detailPattern:null, detailChart:'fbc', viewPage:0, dataReturn:{page:'import',top:0}, targetAddress:null, demo:null, report:null, busy:false, last:null, versions:0, gridVersion:0, detailVersion:0, distributionVersion:0, distribution:null, correlationVersion:0, correlationSelection:null, correlationData:null, correlationDetailVersion:0, correlationContext:null};
const nfmt = new Intl.NumberFormat('en-US');
const vfmt = v => v == null ? '—' : Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:6}) + ' V';
const vminfmt = (result,value=result?.voltage) => (result?.relation==='>='&&value!=null?'≥ ':'')+vfmt(value);
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
      $('data-back').title='Back to '+labels[s.page];
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
  $('breadcrumb').textContent = 'Workspace / ' + labels[page];
  if (page === 'maps' && s.report) return Promise.all([refreshMap(),refreshDistribution()]);
  if (page === 'data' && s.report) return refreshTable();
  if (page === 'correlation') return refreshCorrelation();
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
  $(batch ? 'batch-count' : 'file-count').textContent = list.length ? list.length + ' ASC files' : 'No files selected';
  if (!list.length) return put(id, el('span', 'Select one or more .asc files'));
  put(id, ...list.map((path, i) => {
    const row = el('div', null, 'file-row');
    const name = path.split(/[\\/]/).pop();
    const description = el('div');
    description.append(el('span', name), el('br'), el('small', path));
    const remove = el('button','Remove','quiet'); remove.disabled = s.busy;
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
  document.querySelectorAll('[data-pattern-export],#correlation-export').forEach(button=>{button.disabled=value;});
  renderFiles(); renderFiles(true);
}
async function selectAsc(batch) {
  const data = await api('pick',{kind:'asc'});
  if (!data.paths.length) return;
  if (batch) s.batch = [...new Set([...s.batch,...data.paths])];
  else {
    if (data.paths.length > 3) throw new Error('Full analysis supports up to 3 ASC files.');
    s.files = data.paths; s.demo = null; $('full-profile').textContent = 'Using the full-analysis TNO configuration';
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
  const scopes = {chip:'Chip Vmin',...Object.fromEntries(report.patterns.map(p=>['pattern:'+p,p+' Vmin']))};
  if(['scan','march'].every(p=>report.patterns.some(name=>name.toLowerCase()===p)))scopes.merge='Merge 90%';
  options($('dist-scope'),scopes,'chip');
  $('dist-match-label').hidden=report.source_mode!=='full';
  options($('correlation-wt'),Object.fromEntries(report.wt_numbers.map(wt=>[wt,'WT'+wt])),s.wt);
  options($('correlation-scope'),report.monitor_scopes,report.monitor_scopes.merge?'merge':Object.keys(report.monitor_scopes)[0]);
  s.correlationSelection=null;s.correlationData=null;s.correlationContext=null;++s.correlationDetailVersion;
  put('correlation-content');
  s.distribution=null;
  options($('pattern'),pats,s.pattern);
  options($('data-pattern'),{'':'All Patterns',...pats},'');
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
    block.append(el('h2','Created '+output.length+' files'));
    const list = el('ul');
    for(const path of output) list.append(el('li',path));
    block.append(list);
  }
  if(warnings.length) {
    const details = el('details'); details.open = true;
    details.append(el('summary',warnings.length+' import diagnostics'));
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
    if (['export','pattern-export'].includes(kind) && result.output.length) notice('Exported '+result.output.join('\n'));
    if (['analyze','reopen'].includes(kind) && !result.error && result.data) {
      setReport(result.data);
      if (result.warnings.length) notice('Analysis complete. '+result.warnings.length+' diagnostics are available in Import Info.');
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
  $('full-profile').textContent = 'Using the 128-Chip demo TNO configuration'; renderFiles();
});
$('vmin-mode').onchange = () => {s.mode = $('vmin-mode').value;};
$('run-full').onclick = safe(()=>{
  if(!s.files.length) throw new Error('Select ASC files or load the 128-Chip demo first.');
  return run('analyze',{paths:s.files, rows:(s.demo || s.config.full).rows, mode:s.mode, source_mode:$('source-mode').value});
});
$('run-batch').onclick = safe(()=>{
  if(!s.batch.length) throw new Error('Select ASC files first.');
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
  if(s.layer === 'vmin') return [[val === null ? (row.status==='Not Applicable'?'N/A':row.status) : vminfmt(row,val).replace(/ V$/, ''),val === null ? (row.status==='Pass'?'#dbeafe':'#e2e8f0') : (s.vminScale?.color(val) ?? '#f3d86b')]];
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
  const items = [[s.report.label,'Lot / Wafer'],[nfmt.format(rows.length),'Chip'],[nfmt.format(current.fbc),'FBC records'],
                 [nfmt.format(current.address),'WT'+s.wt+' Address']];
  put('kpis',...items.map(([value,key])=>{
    const box=el('div',null,'card kpi');box.append(el('span',key),el('b',value));return box;
  }));
}
function showChip(row) {
  if(!row) return put('chip-summary',el('h2','Chip Details'),el('p','Select a Chip on the Wafer Map.'));
  const fields=[['WT','WT'+s.wt],['Status',row.status]];
  if(s.layer === 'vmin'){
    fields.push(['Judgment scope',s.vminJudge?.source??'Chip Vmin'],['Vmin',vminfmt(row,row.value)],['Judge BLK',row.blk ?? '—'],['TNO',row.tno ?? '—'],['Func.',row.func ?? '—'],
      ['Hard Fail',row.hard.length],['Tail BLK',row.tail.length],['Tail upper fence',row.cutoff==null?'—':vfmt(row.cutoff)],['Highest Vmin before Tail exclusion',vminfmt(row.before_tail)],
      ['Remaining / Incomplete',row.remaining+'／'+row.incomplete]);
  } else if(row.wr){
    fields.push(['Fail BLK',row.value ?? '—'],['Loss BLK',row.loss],
                ['Read / Write',row.wr[0]+' / '+row.wr[1]],['RW / No Monitor',row.wr[2]+' / '+row.wr[3]]);
  }
  if(row.reason)fields.push(['Judgment reason',row.reason]);
  if(row.voltage_rule==='terminal-recovery')fields.push(['Judgment reason',crossingReason(row)]);
  const details=el('dl');
  for(const [k,v] of fields){const line=el('div');line.append(el('dt',k),el('dd',v));details.append(line);}
  const link=el('button','View Chip data','secondary');
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
  $('wafer-grid').closest('.map-layout').classList.toggle('vmin-layout',s.layer==='vmin');
  const readableCell=data=>Math.max(34,...data.filter(row=>row.value!=null).map(row=>(vfmt(row.value).replace(/ V$/, '').length*7+8)));
  let cellMin=s.layer==='vmin'?readableCell(rows):20;
  showKpis(rows);
  put('wt-list',...s.report.wt_numbers.map(wt=>{
    const button=el('button','WT'+wt,s.wt===wt?'active':'');
    button.setAttribute('aria-pressed',s.wt===wt);
    button.onclick=safe(async()=>{
      s.wt=wt;$('data-wt').value=wt;
      await Promise.all([refreshMap(),refreshDistribution()]);
      if(s.block!==null)await refreshDetail();
    });
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
  if(Math.max(nx,ny)>100) throw new Error('Wafer Map coordinate range exceeds 100.');
  const board=$('wafer-grid');board.replaceChildren();
  const dualPatterns=s.layer==='vmin'
    ? s.report.patterns.filter(name=>['scan','march'].includes(name.toLowerCase())) : [];
  const dual=dualPatterns.length===2;
  board.classList.toggle('wafer-dual-host',dual);
  const renderBoard=(target,data,scale,source='Chip Vmin')=>{
    target.style.setProperty('--wafer-columns',nx);
    target.style.setProperty('--wafer-rows',ny);
    target.style.setProperty('--wafer-min',Math.max(nx,ny)*cellMin+'px');
    target.style.setProperty('--wafer-max',Math.max(Math.max(nx,ny)*cellMin,Math.min(s.layer==='vmin'?900:660,Math.min(nx,ny)*66))+'px');
    const axis=(text,col,row)=>{const a=el('span',text,'axis');a.style.gridColumn=col;a.style.gridRow=row;target.append(a);};
    axis('Y/X',1,1);
    for(let x=x0;x<=x1;x++)axis(x,x-x0+2,1);
    for(let y=y0;y<=y1;y++)axis(y,1,y-y0+2);
    for(const row of data){
      const values=s.layer==='vmin'
        ? [[row.value===null?(row.status==='Not Applicable'?'N/A':row.status):vminfmt(row,row.value).replace(/ V$/, ''),
            row.value===null?(row.status==='Pass'?'#dbeafe':'#e2e8f0'):(scale?.color(row.value)??'#f3d86b')]]
        : tint(row);
      const chip=el('button',null,'chip'+(values.length===4?' quad':values.length===2?' half':''));
      chip.dataset.chip=chipKey(row);
      chip.style.gridColumn=row.x-x0+2;chip.style.gridRow=row.y-y0+2;
      chip.title='X'+row.x+' Y'+row.y+' · '+row.status+(row.value!=null?' · '+vminfmt(row,row.value):'');
      chip.setAttribute('aria-label',chip.title);
      chip.dataset.active=String(s.selected===chipKey(row));
      for(const [value,bg,fg] of values){
        const span=el('span',value);
        if(s.layer==='vmin'&&row.value!=null){
          span.className='chip-vmin-label';span.replaceChildren();
          if(row.relation==='>=')span.append(el('span','≥ ','chip-relation'));
          span.append(el('span',vfmt(row.value).replace(/ V$/, ''),'chip-number'));
        }
        span.style.backgroundColor=bg;if(fg)span.style.color=fg;chip.append(span);
      }
      chip.onclick=safe(async()=>{
        const selected=chipKey(row);
        s.selected=selected;s.block=null;s.blocks=[];s.detailPattern=row.pattern||s.pattern;
        put('block-detail');setMapStage('wafer');
        board.querySelectorAll('.chip').forEach(btn=>{btn.dataset.active=String(btn.dataset.chip===s.selected);});
        selectMapJudge(row,source);showChip(row);
        $('dist-scope').value=source==='Chip Vmin'?'chip':source==='Merge 90%'?'merge':'pattern:'+source;
        s.distribution=null;
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
    cellMin=readableCell(allValues);
    pair.style.setProperty('--vmin-panel-min',Math.max(280,Math.max(nx,ny)*cellMin+56)+'px');
    const commonScale=vminScale(allValues);
    s.vminScale=commonScale;
    renderLegend('map-legend',commonScale?[
      [commonScale.color(commonScale.min),'Low '+vfmt(commonScale.min)],
      [commonScale.color(commonScale.median),'Median '+vfmt(commonScale.median)],
      [commonScale.color(commonScale.max),'High '+vfmt(commonScale.max)],
      ['#dbeafe','Pass'],['#e2e8f0','No Data / status · N/A: Scan Fail']
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
function renderTailList(tails) {
  const details=$('dist-tails');
  details.hidden=!tails.length;
  $('dist-tails-label').textContent='Tail BLKs ('+tails.length+')';
  const sorted=[...tails].sort((a,b)=>b.fbc90_voltage-a.fbc90_voltage||a.blk-b.blk);
  const buttons=sorted.map(entry=>{
    const button=el('button',null,'tail-list-item');
    button.append(el('strong','BLK '+entry.blk),
      el('span','FBC90% '+vfmt(entry.fbc90_voltage)),
      el('span',entry.steps_above_median+' voltage steps above median'));
    button.onclick=()=>$('blk-grid').children[entry.blk]?.click();
    return button;
  });
  put('dist-tail-list',...buttons);
}

async function refreshDistribution() {
  if(!s.selected||!s.blocks.length)return;
  const id=++s.distributionVersion;
  const wt=s.wt, chip=s.selected, scope=$('dist-scope').value;
  const matches=s.report.source_mode==='full'&&$('dist-match').checked;
  const data=await api(params({view:'vmin_distribution',scope,matches:matches?'1':'0',...selection()}));
  if(id!==s.distributionVersion||wt!==s.wt||chip!==s.selected||scope!==$('dist-scope').value||s.page!=='maps')return;
  const {summary,mode,entries,box}=data;
  s.distribution=entries;
  const source=$('dist-scope').selectedOptions[0].textContent;
  const judge=summary.blk==null ? 'Judge: '+summary.status :
    'Judge BLK '+summary.blk+' · '+vminfmt(summary)+' · TNO '+summary.tno;
  const before=summary.before_tail;
  const highest=before.blk==null?'Highest before Tail: —':
    'Highest before Tail: '+vminfmt(before)+' (BLK '+before.blk+')';
  $('dist-judge').textContent=['WT'+wt,source,mode,highest,judge,'Tail BLKs: '+summary.tail.length].join(' · ');
  const note=$('dist-note');
  note.textContent=summary.reason??'';
  note.hidden=!summary.reason;
  const board=$('blk-grid');
  board.classList.toggle('show-match',matches);
  setDistributionView($('dist-view-outliers').getAttribute('aria-pressed')==='true');
  const cells=board.children;
  for(const entry of entries){
    const tile=cells[entry.blk];
    const label=tile.querySelector('.block-vmin');
    const voltage=entry.voltage!=null?vminfmt(entry):'';
    const hard=entry.status==='Hard Fail';
    const pass=entry.status==='Pass';
    tile.classList.toggle('hard',hard);
    tile.classList.toggle('clean',pass);
    tile.classList.toggle('tail-cell',entry.tail);
    tile.classList.toggle('judge-cell',entry.judge);
    tile.classList.toggle('has-vmin',Boolean(voltage));
    tile.style.background=entry.pattern&&voltage&&!entry.tail?patternColor(entry.pattern):'';
    const badge=tile.querySelector('.block-badge');
    badge.hidden=!entry.tail&&!entry.judge;
    badge.textContent=entry.judge?'J':entry.tail?'T':'';
    label.classList.toggle('worst',entry.judge);
    label.textContent=voltage.replace(/ V$/, '');
    const quadrants=tile.querySelector('.block-match');
    quadrants.hidden=!matches;
    if(matches){
      [...quadrants.children].forEach((cell,index)=>{
        const count=entry.matches[index];
        cell.textContent=count?nfmt.format(count):'';
        cell.title=matchLabels[index]+': '+nfmt.format(count);
        cell.classList.toggle('filled',count>0);
      });
    }
    const title=['BLK '+entry.blk,'WT'+wt,entry.pattern,voltage?'Vmin '+voltage:entry.status,
      entry.judge?'Judge BLK':entry.tail?'Tail BLK · excluded from Chip Vmin':'',
      entry.tno==null?'':'TNO '+entry.tno+' · '+entry.func,
      entry.peak_fbc?'Peak FBC '+nfmt.format(entry.peak_fbc):'',
      entry.fbc90_voltage==null?'':'FBC90% '+vminfmt({relation:entry.fbc90_relation},entry.fbc90_voltage),
      entry.steps_above_median==null?'':entry.steps_above_median+' voltage steps above median',
      ...(matches?entry.matches.map((count,index)=>matchLabels[index]+': '+nfmt.format(count)):[]),
      ...s.blocks[entry.blk].states.map(phase=>'WT'+phase.wt+' '+phase.status)].filter(Boolean).join(' · ');
    tile.title=title;
    tile.setAttribute('aria-label',title);
  }
  renderVminOutliers(box,entries);
  renderTailList(entries.filter(entry=>entry.tail));
  fitMapStage();
}
$('dist-scope').onchange=safe(()=>{
  s.distribution=null;
  return refreshDistribution();
});
$('dist-match').onchange=safe(refreshDistribution);

function setDistributionView(showOutliers) {
  $('dist-outliers').hidden=!showOutliers;
  $('dist-matrix').hidden=showOutliers;
  $('dist-legend').hidden=showOutliers;
  $('dist-wts').hidden=showOutliers;
  $('dist-match-label').hidden=showOutliers||s.report?.source_mode!=='full';
  $('dist-match-legend').hidden=showOutliers||s.report?.source_mode!=='full'||!$('dist-match').checked;
  for(const [id,active] of [['dist-view-matrix',!showOutliers],['dist-view-outliers',showOutliers]]){
    $(id).setAttribute('aria-pressed',active);
    $(id).classList.toggle('active',active);
  }
  fitMapStage();
}
$('dist-view-matrix').onclick=()=>setDistributionView(false);
$('dist-view-outliers').onclick=()=>setDistributionView(true);

function vminBoxPlot(box,exact) {
  if(!exact.length)return el('p','No exact FBC90% Vmin readings for this Chip, WT and scope.','correlation-note');
  const bottom=Math.min(...exact.map(entry=>entry.fbc90_voltage));
  const top=Math.max(box.upper_fence??bottom,...exact.map(entry=>entry.fbc90_voltage));
  const padding=Math.max(.004,(top-bottom)*.10);
  const base=bottom-padding, span=top+padding-base;
  const ticks=Array.from({length:5},(_,i)=>span*i/4);
  const chart=chartFrame('FBC90% Vmin box plot','Vmin (V)',span,ticks,530,
    offset=>Number((base+offset).toFixed(4)).toString(),335,'Exact FBC90% readings');
  const y=v=>chart.y(v-base);
  const boxX=chart.left+(chart.right-chart.left)*.30;
  const pointsX=chart.left+(chart.right-chart.left)*.73;
  if(box.upper_fence!=null){
    chart.add('line',{x1:chart.left,x2:chart.right,y1:y(box.upper_fence),y2:y(box.upper_fence),
      stroke:'#a74c0b','stroke-width':1.5,'stroke-dasharray':'5 4'});
  }
  chart.add('line',{x1:boxX,x2:boxX,y1:y(box.high),y2:y(box.low),stroke:'#35638c','stroke-width':2});
  for(const v of [box.low,box.high]){
    chart.add('line',{x1:boxX-17,x2:boxX+17,y1:y(v),y2:y(v),stroke:'#35638c','stroke-width':2});
  }
  chart.add('rect',{x:boxX-34,y:y(box.q3),width:68,height:Math.max(1,y(box.q1)-y(box.q3)),
    fill:'#dfeafb',stroke:'#35638c','stroke-width':1.3});
  chart.add('line',{x1:boxX-34,x2:boxX+34,y1:y(box.median),y2:y(box.median),stroke:'#15685d','stroke-width':3});
  for(const entry of [...exact].sort((a,b)=>Number(a.tail)-Number(b.tail))){
    const attrs={cx:pointsX+(entry.blk%13-6)*6,cy:y(entry.fbc90_voltage),
      r:entry.tail?5:entry.steps_above_median!=null?4:2.8,fill:entry.tail?'#ad4d0d':entry.steps_above_median!=null?'#d89726':entry.below_fence?'#007b77':'#587c9f',
      'fill-opacity':entry.steps_above_median!=null||entry.below_fence?1:.48};
    const title='BLK '+entry.blk+' · '+vfmt(entry.fbc90_voltage);
    const mark=chart.add('circle',attrs);
    chart.add('title',{},title,mark);
  }
  return chart.wrap;
}

function renderVminOutliers(box,entries) {
  const exact=entries.filter(e=>e.fbc90_voltage!=null&&!e.fbc90_relation);
  const count=box.count;
  const values=count?[['Q1',box.q1],['Median',box.median],['Q3',box.q3],['Upper fence',box.upper_fence]]:[];
  const stats=el('p','Exact FBC90% readings: '+count+' / 256'+
    (values.length?' · '+values.map(([label,v])=>label+' '+vfmt(v)).join(' · '):''),'vmin-stats');
  const left=section('FBC90% Vmin Box Plot',vminBoxPlot(box,exact));
  const right=el('section',null,'detail-section vmin-location');
  right.append(el('h3','BLK Outlier Locations'));
  const key=chartLegend(['Tail','Above upper fence only','Below lower fence','Exact Vmin','Other status'],['#cd641e','#ffd993','#b3dfde','#dce9f6','#edf0f3']);
  right.append(key);
  const board=el('div',null,'outlier-grid');
  for(const entry of entries){
    const cls=entry.tail?'tail':entry.steps_above_median!=null?'high':entry.below_fence?'low':entry.fbc90_voltage!=null&&!entry.fbc90_relation?'exact':'other';
    const cell=el('button',String(entry.blk),'outlier-block '+cls);
    cell.type='button';
    cell.style.gridRow=entry.blk%16+1;
    cell.style.gridColumn=Math.floor(entry.blk/16)+1;
    cell.classList.toggle('judge',entry.judge);
    const detail=entry.fbc90_voltage==null?entry.status:vminfmt({relation:entry.fbc90_relation},entry.fbc90_voltage);
    cell.title='BLK '+entry.blk+' · '+detail+(entry.tail?' · Tail':entry.steps_above_median!=null?' · Above upper fence':entry.below_fence?' · Below lower fence':'')+(entry.judge?' · Judge BLK':'');
    cell.setAttribute('aria-label',cell.title);
    cell.onclick=()=>$('blk-grid').children[entry.blk]?.click();
    board.append(cell);
  }
  const scroller=el('div',null,'outlier-grid-scroll');
  scroller.append(board);
  right.append(scroller);
  const grid=el('div',null,'vmin-stat-plots pattern-charts');
  grid.append(left,right);
  const notes=count<box.minimum_samples
    ? 'At least '+box.minimum_samples+' exact Vmin readings are required to classify Tail BLKs.'
    : 'Tail requires Vmin above the upper fence and at least '+box.minimum_steps+' tested voltage steps above the median.';
  put('dist-outliers',stats,grid,el('p',notes+' Pass, missing and lower-bound values are excluded from quartiles. Purple outline marks the Judge BLK.','correlation-note'));
}


async function refreshGrid() {
  const id=++s.gridVersion;
  ++s.detailVersion;
  const entries=await api(params({view:'grid',...selection()}));
  if(id!==s.gridVersion || s.page!=='maps')return;
  s.blocks=entries;
  const {x,y}=selection();$('dist-title').textContent='256 BLK Vmin Distribution · X'+x+' Y'+y;
  $('dist-wts').textContent='Status bands, left to right: '+s.report.wt_numbers.map(wt=>'WT'+wt).join(' / ');
  const board=$('blk-grid');board.replaceChildren();
  renderLegend('dist-legend',[['#7c3aed','J · Judge BLK'],['#ffcf83','T · Tail BLK (excluded)'],['#258044','Pass'],
    ['#f35b53','Fail band'],['#ffb9b4','Hard Fail'],['#d5dee7','No Data / Other Status'],...s.report.patterns.map(p=>[patternColor(p),p])]);
  renderLegend('dist-match-legend',matchLabels.map((label,i)=>[matchFills[i],['Top left','Top right','Bottom left','Bottom right'][i]+': '+label]));
  for(const entry of entries){
    const btn=el('button',null,'block');
    const phaseSummary=entry.states.map(phase=>'WT'+phase.wt+' '+phase.status);
    btn.style.gridRow=entry.blk%16+1;btn.style.gridColumn=Math.floor(entry.blk/16)+1;
    const number=el('span',null,'block-number');
    const badge=el('span',null,'block-badge');
    badge.hidden=true;
    badge.setAttribute('aria-hidden','true');
    number.append(badge,el('span','BLK ','block-prefix'),String(entry.blk));
    btn.setAttribute('aria-label','BLK '+entry.blk);
    btn.append(number,el('small',null,'block-vmin'));
    const quadrants=el('span',null,'block-match');
    quadrants.hidden=true;
    quadrants.setAttribute('aria-hidden','true');
    for(const [index,color] of matchFills.entries()){
      const cell=el('span',null,'match-quadrant match-'+index);
      cell.style.setProperty('--match-fill',color);
      quadrants.append(cell);
    }
    btn.append(quadrants);
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
      const scope=$('dist-scope').value;
      s.detailPattern=s.distribution?.[entry.blk].pattern??(scope.startsWith('pattern:')?scope.slice(8):s.pattern);
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
  await refreshDistribution();
}
function table(headers, rows) {
  const table=el('table'), head=el('thead'), body=el('tbody'), bar=el('tr');
  for(const header of headers)bar.append(el('th',header));
  head.append(bar);table.append(head,body);
  if(!rows.length){const row=el('tr'),msg=el('td','No matching data','tab-note');msg.colSpan=headers.length;row.append(msg);body.append(row);}
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
  const left = 80, right = width - rightMargin, bottom = height - (footer?.margin??(xLabel.includes('Scan / March') ? 128 : xLabel === 'Voltage (V)' ? 112 : 74)), top = footer?.top??43, tickY = footer?bottom+26:height-48;
  const y = value => bottom - value / maximum * (bottom-top);
  add('text', {x:left,y:footer?.unitY??24,class:'chart-label chart-axis-title'}, unit);
  for (const value of ticks) {
    add('line', {x1:left,x2:right,y1:y(value),y2:y(value),class:'chart-grid'});
    add('text', {x:left-12,y:y(value)+5,'text-anchor':'end',class:'chart-label'}, tickLabel(value));
  }
  add('line',{x1:left,x2:left,y1:top,y2:bottom,class:'chart-axis'});
  add('line',{x1:left,x2:right,y1:bottom,y2:bottom,class:'chart-axis'});
  add('text',{x:(left+right)/2,y:height-15,'text-anchor':'middle',class:'chart-label chart-axis-title'},xLabel);
  return {wrap,add,left,right,bottom,tickY,y,maximum};
}
function chartMark(chart, tag, attrs, description) {
  const mark = chart.add(tag,{...attrs,tabindex:0,'aria-label':description});
  chart.add('title',{},description,mark);
  return mark;
}
function crossingReason(result) {
  if(result.voltage_rule==='terminal-recovery')return 'Terminal recovery voltage; using Go/No-Go TNO '+result.voltage_tno+' ('+vfmt(result.voltage)+'); original crossing voltage: '+vfmt(result.test_voltage)+'.';
  const reasons={
    'Hard Fail':'This BLK is excluded by Hard Fail.',
    'Prior WT':'This BLK failed at a previous WT and is excluded.',
    'Prior Pattern':'This BLK failed an earlier Pattern in this WT and is excluded.',
    'No Data':'Required FBC or prerequisite test data is missing or invalid.',
    'Pass':'Complete FBC data is all zero; no Vmin crossing.',
    'Below':'The selected FBC threshold has not been reached.'
  };
  if(result.relation==='>=')return 'The highest test voltage failed. Vmin is a lower bound at the configured Hard Fail voltage, not an exact measurement.';
  if(result.status==='No Vmin')return s.report.mode==='FBC0'
    ? 'FBC0 has no voltage group before the first failure: the first group failed or the preceding voltage is not configured.'
    : 'The crossing TNO has no configured test voltage.';
  return reasons[result.status]??('Using '+s.report.mode+' threshold.');
}
function stationLabel(station) {
  const fbc = station.fbc === null ? 'No FBC data' : 'FBC '+nfmt.format(station.fbc);
  return station.func+' · TNO '+station.tno+' · '+vfmt(station.v)+' · '+fbc;
}
// Equal-width consecutive voltage intervals; keep every TNO in Config order inside its interval.
function voltageLayout(stations, grouped=false, rightMargin=100) {
  const runs=[];
  for(const [i,station] of stations.entries()){
    const last=runs.at(-1);
    if(last?.voltage===station.v&&last?.pattern===station.pattern)last.end=i;
    else runs.push({voltage:station.v,pattern:station.pattern,start:i,end:i});
  }
  const width=Math.max(360,rightMargin+180,Math.min(1100,window.innerWidth-(window.innerWidth>700?240:56)));
  const labels=runs.map(run=>run.voltage==null?'Not set':vfmt(run.voltage));
  const slot=(width-80-rightMargin)/Math.max(1,runs.length);
  const rotated=labels.some(label=>label.length*8+12>slot);
  const lanes=rotated?Math.max(1,Math.ceil(22/slot)):1;
  const labelRow=rotated?Math.max(80,...labels.map(label=>label.length*8+12)):24;
  const labelArea=labelRow*lanes;
  return {runs,labels,width,rotated,lanes,labelRow,labelArea,
    margin:labelArea+(grouped?78:48),positions:[],strides:[]};
}
function drawVoltageIntervals(chart, layout, grouped=false) {
  const {runs,labels,rotated,lanes,labelRow,labelArea}=layout;
  const slot=(chart.right-chart.left)/Math.max(1,runs.length);
  chart.wrap.classList.add('voltage-fit');
  chart.wrap.querySelector('svg').style.minWidth='0';
  const labelY=chart.bottom+(rotated?12:24);
  for(const [i,run] of runs.entries()){
    const left=chart.left+i*slot, mid=left+slot/2;
    for(let station=run.start;station<=run.end;station++){
      const stride=slot/(run.end-run.start+1);
      layout.positions[station]=left+(station-run.start+.5)*stride;
      layout.strides[station]=stride;
    }
    chart.add('line',{x1:left,x2:left,y1:chart.y(chart.maximum),y2:chart.bottom,class:'chart-voltage-grid'});
    const y=labelY+(rotated?(i%lanes)*labelRow:0);
    chart.add('text',{x:mid,y,'text-anchor':rotated?'end':'middle',
      ...(rotated?{transform:'rotate(-90 '+mid+' '+y+')'}:{}),class:'chart-label chart-voltage-label'},labels[i]);
  }
  chart.add('line',{x1:chart.right,x2:chart.right,y1:chart.y(chart.maximum),y2:chart.bottom,class:'chart-voltage-grid'});
  layout.patternY=chart.bottom+labelArea+38;
  return index=>layout.positions[index];
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
    'First crossing ≥90% · Vmin '+vminfmt(result)+' · '+result.func+' · TNO '+result.tno+(result.test_voltage!=null?' · Test '+vfmt(result.test_voltage):'')+(result.voltage_rule==='terminal-recovery'?' · Go/No-Go TNO '+result.voltage_tno:'');
  article.append(el('p',info,'chart-summary'));
  const grouped=segments.length>0;
  const rightMargin=Math.max(100,nfmt.format(result.peak).length*10+24);
  const layout=voltageLayout(stations,grouped,rightMargin);
  // Reserve right-axis space without allowing station count to expand the canvas.
  const width=layout.width;
  const chart=chartFrame(pattern+' FBC90% Accumulation','Cumulative FBC (%)',100,[0,25,50,75,90,100],
    width,n=>n+'%',244+layout.margin,'Test Voltage (V) · Config Order',{margin:layout.margin,...(width<600?{top:64,unitY:20}:{})},rightMargin);
  const x=drawVoltageIntervals(chart,layout,grouped);
  let offset=0;
  for(const segment of segments){
    const start=offset;offset+=segment.stations.length;
    const first=layout.positions[start]-layout.strides[start]/2;
    const last=layout.positions[offset-1]+layout.strides[offset-1]/2;
    chart.add('text',{x:(first+last)/2,y:layout.patternY,
      'text-anchor':'middle',class:'chart-label chart-pattern-label'},segment.name);
    if(start>0)chart.add('line',{x1:first,x2:first,y1:chart.y(100),y2:chart.bottom,
      class:'chart-pattern-divider'});
  }
  if (result.peak > 0) chart.add('line',{x1:chart.left,x2:chart.right,y1:chart.y(90),y2:chart.y(90),class:'chart-threshold'});
  // The right axis uses the same Peak as the percentage curve, while the raw series may fall.
  chart.add('line',{x1:chart.right,x2:chart.right,y1:chart.y(100),y2:chart.bottom,class:'chart-axis chart-fbc-axis'});
  chart.add('text',{x:width-12,y:width<600?44:24,'text-anchor':'end',class:'chart-label chart-axis-title chart-fbc-axis'},'Fail bit count (FBC)');
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
const matchLabels=['Read only','Write only','Write & Read','No monitor hit'];
const matchFills=['#ffffff','#ffd966','#ff6600','#ffffff'];

function monitorScatter(rows, side, label) {
  const points=rows.filter(row=>row.complete&&row[side]!=null);
  if(!points.length)return el('p','No chips with both Function FBC and '+label+' data.','correlation-note');
  const maxX=Math.max(1,...points.map(row=>row[side]));
  const maxY=Math.max(1,...points.map(row=>row.function));
  const ticks=max=>[...new Set(Array.from({length:6},(_,i)=>Math.round(max*i/5)))];
  const chart=chartFrame(label+' vs Function Fail Addresses','Function Fail Addresses',maxY,ticks(maxY),560,
    value=>nfmt.format(value),320,label+' Fail Addresses');
  const x=value=>chart.left+(chart.right-chart.left)*value/maxX;
  for(const value of ticks(maxX)){
    chart.add('line',{x1:x(value),x2:x(value),y1:chart.bottom,y2:chart.bottom+5,class:'chart-axis'});
    chart.add('text',{x:x(value),y:chart.bottom+20,'text-anchor':'middle',class:'chart-label'},nfmt.format(value));
  }
  for(const row of points){
    const title='X'+row.x+' Y'+row.y+' · '+label+' '+row[side]+' · Function '+row.function;
    const point=chartMark(chart,'circle',{cx:x(row[side]),cy:chart.y(row.function),r:5,
      role:'button',class:'correlation-point','data-chip':chipKey(row),fill:side==='write'?'#ad600b':'#2465a5','fill-opacity':0.8},title+' · Select to view Chip details');
    point.onclick=safe(()=>openCorrelationChip(row));
    point.onkeydown=safe(event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();return openCorrelationChip(row);}});
  }
  return chart.wrap;
}

async function openCorrelationChip(row) {
  const token=++s.correlationDetailVersion;
  const wt=$('correlation-wt').value,scope=$('correlation-scope').value;
  $('modal-title').textContent='WT'+wt+' · X'+row.x+' Y'+row.y+' · W/R correlation';
  const summary=table(['Item','Count / Status'],[
    ['Monitor category',monitorCategories[monitorCategory(row)].label],
    ['Function FBC coverage',row.complete?'Complete':'Incomplete'],['Function captured addresses',row.function],
    ['W-Low captured addresses',row.write??'No Data'],['R-Low captured addresses',row.read??'No Data'],
    ['Eligible Fail BLKs',row.fail_blks??'No Data'],['BLKs with Function addresses',row.address_blks],
    ...s.correlationData.labels.map((label,i)=>[label,row.counts[i]])]);
  put('modal-content',summary,el('p','Loading BLK match details…','correlation-note'));
  if(!$('modal').open)$('modal').showModal();
  const detail=await api(params({view:'vmin_distribution',wt,scope,x:row.x,y:row.y,matches:'1'}));
  if(token!==s.correlationDetailVersion||!$('modal').open)return;
  const entries=detail.entries.filter(entry=>entry.matches?.some(Boolean));
  const actions=el('div',null,'actions');
  const matrix=el('button','Open 256-BLK matrix','secondary');
  const jump=async blk=>{
    $('modal').close();s.wt=Number(wt);s.selected=chipKey(row);s.pattern=scope.startsWith('pattern:')?scope.slice(8):s.report.patterns[0];
    s.layer='fail';s.block=null;s.blocks=[];s.mapStage='matrix';s.detailPattern=s.pattern;
    $('pattern').value=s.pattern;$('layer').value=s.layer;$('data-wt').value=wt;
    await navigate('maps');await refreshGrid();setMapStage('matrix',true);
    if(blk!=null){s.block=blk;await refreshDetail();setMapStage('detail',true);}
  };
  matrix.onclick=safe(()=>jump(null));actions.append(matrix);
  const blocks=table(['BLK','Function matched addresses',...s.correlationData.labels,'Details'],entries.map(entry=>{
    const cell=el('td'),button=el('button','View BLK','quiet');button.onclick=safe(()=>jump(entry.blk));cell.append(button);
    return [entry.blk,entry.matches.reduce((a,b)=>a+b,0),...entry.matches,cell];
  }));
  put('modal-content',summary,el('p','X uses monitor addresses captured across the Chip; Y uses Function addresses in eligible BLKs of the selected scope. Neither is complete FBC.','correlation-note'),actions,section('BLK matching breakdown',blocks));
}
const monitorCategories = {
  write: {label:'W worse',symbol:'W',color:'#f6c58b'},
  read: {label:'R worse',symbol:'R',color:'#bad6f6'},
  equal: {label:'W = R',symbol:'=',color:'#dfc8ef'},
  zero: {label:'No captured W/R fails',symbol:'0',color:'#cbe9d4'},
  missing: {label:'No data',symbol:'?',color:'#d8dee7'}
};
function monitorCategory(row) {
  if(!row.complete||row.write==null||row.read==null)return 'missing';
  if(row.write===0&&row.read===0)return 'zero';
  return row.write>row.read?'write':row.read>row.write?'read':'equal';
}
function correlationMap() {
  const rows=s.correlationData.rows, selected=s.correlationSelection;
  const box=el('section',null,'card correlation-selection');
  box.append(el('h2','Wafer Map · Chip Selection'),el('p','Click to select one Chip; Shift-click to add or remove Chips. Show all and an empty selection are distinct.','correlation-note'));
  const controls=el('div',null,'toolbar');
  for(const [label,value] of [['Show all',null],['Clear selection',[]]]){
    const button=el('button',label,'secondary');button.onclick=safe(()=>{s.correlationSelection=value;return updateCorrelationSelection();});controls.append(button);
  }
  controls.append(el('span',selected===null?'All '+rows.length+' Chips':'Selected '+selected.length+' / '+rows.length+' Chips','correlation-selection-count'));
  box.append(controls);
  if(!rows.length)return box;
  const xs=rows.map(r=>r.x),ys=rows.map(r=>r.y),x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);
  if(x1-x0>99||y1-y0>99){box.append(el('p','Coordinate range exceeds 100; this Wafer Map cannot be drawn.','correlation-note'));return box;}
  const scroll=el('div',null,'correlation-wafer-scroll'),board=el('div',null,'correlation-wafer');
  board.style.gridTemplateColumns='36px repeat('+(x1-x0+1)+',minmax(34px,1fr))';
  const axis=(text,col,line)=>{const a=el('span',text,'axis');a.style.gridColumn=col;a.style.gridRow=line;board.append(a);};
  axis('Y/X',1,1);for(let x=x0;x<=x1;x++)axis(x,x-x0+2,1);for(let y=y0;y<=y1;y++)axis(y,1,y-y0+2);
  for(const row of rows){
    const key=chipKey(row),active=selected===null||selected.includes(key);
    const category=monitorCategory(row), info=monitorCategories[category];
    const button=el('button',info.symbol,'correlation-chip');
    button.dataset.category=category;button.style.setProperty('--correlation-chip-color',info.color);
    button.dataset.chip=key;button.dataset.selected=String(active);button.setAttribute('aria-pressed',active);
    button.style.gridColumn=row.x-x0+2;button.style.gridRow=row.y-y0+2;
    button.classList.toggle('incomplete',!row.complete);
    button.title='X'+row.x+' Y'+row.y+' · '+info.label+' · Function '+row.function+' · W '+(row.write??'No Data')+' · R '+(row.read??'No Data');
    button.setAttribute('aria-label',button.title);
    button.onclick=safe(event=>{
      const keys=new Set(event.shiftKey?(s.correlationSelection??[]):[]);
      if(event.shiftKey&&keys.has(key))keys.delete(key);else keys.add(key);
      s.correlationSelection=[...keys];return updateCorrelationSelection();
    });board.append(button);
  }
  const legend=chartLegend(Object.values(monitorCategories).map(info=>info.label),Object.values(monitorCategories).map(info=>info.color));
  scroll.append(board);box.append(scroll,legend,el('p','W/R worse compares captured monitor Fail Address counts, not physical failure severity or complete FBC. No data means incomplete Function coverage or missing W/R monitor data. Borders indicate selected Chips.','correlation-note'));
  return box;
}
async function refreshCorrelation() {
  const version=++s.correlationVersion;++s.correlationDetailVersion;
  const available=s.report?.source_mode==='full'&&Object.keys(s.report.monitor_scopes).length>0;
  $('correlation-empty').hidden=available;$('correlation-report').hidden=!available;
  if(!available)return;
  const context=$('correlation-wt').value+'|'+$('correlation-scope').value;
  const preserve=context===s.correlationContext;
  const data=await api(params({view:'monitor_correlation',wt:$('correlation-wt').value,scope:$('correlation-scope').value}));
  if(version!==s.correlationVersion||s.page!=='correlation')return;
  s.correlationData=data;s.correlationContext=context;
  if(preserve&&s.correlationSelection!==null)return updateCorrelationSelection();
  s.correlationSelection=null;renderCorrelation(data);
}
async function updateCorrelationSelection() {
  const version=++s.correlationVersion;++s.correlationDetailVersion;
  const chips=s.correlationSelection?.map(key=>key.split(',').map(Number));
  const data=await api(params({view:'monitor_correlation',wt:$('correlation-wt').value,scope:$('correlation-scope').value,
    ...(chips===undefined?{}:{chips:JSON.stringify(chips)})}));
  if(version!==s.correlationVersion||s.page!=='correlation')return;
  renderCorrelation(data);
}
function renderCorrelation(data) {
  const total=data.counts.reduce((sum,count)=>sum+count,0);
  const matched=total-data.counts[3];
  const pct=total?((matched/total)*100).toFixed(1)+'%':'—';
  const overview=el('div',null,'correlation-kpis');
  for(const [label,value] of [['Function Fail Addresses',nfmt.format(total)],['Any W/R Match',pct],
    ...data.labels.map((label,index)=>[label,nfmt.format(data.counts[index])])]){
    const card=el('div',null,'card kpi');
    card.append(el('span',label),el('b',value));
    overview.append(card);
  }
  const charts=el('div',null,'correlation-charts pattern-charts');
  for(const [side,label] of [['write','W-Low'],['read','R-Low']]){
    const info=data.relationships[side];
    const panel=section(label+' vs Function',monitorScatter(data.rows,side,label));
    panel.append(el('p','Pearson r: '+(info.r==null?'—':info.r.toFixed(3))+' · Chips: '+nfmt.format(info.chips),'correlation-note'));
    charts.append(panel);
  }
  const note=el('p','X: captured W/R addresses across each Chip. Y: captured Function addresses in eligible BLKs for the selected scope. Addresses are deduplicated by WT / Chip / BLK / WL / BL / IO. Pearson r uses selected Chips with complete Function FBC and observed monitor data.','correlation-note');
  const details=section('Chip Breakdown',table(['X','Y','Function FBC coverage','Fail BLKs','BLKs with Address','Function Addresses',...data.labels,'W-Low Addresses','R-Low Addresses','Details'],
    data.rows.map(row=>{const cell=el('td'),button=el('button','View Chip','quiet');button.onclick=safe(()=>openCorrelationChip(row));cell.append(button);
      return [row.x,row.y,row.complete?'Complete':'Incomplete',row.fail_blks??'—',row.address_blks,row.function,...row.counts,row.write??'—',row.read??'—',cell];})));
  put('correlation-content',correlationMap(),overview,charts,note,details);
}
$('correlation-wt').onchange=safe(refreshCorrelation);
$('correlation-scope').onchange=safe(refreshCorrelation);
$('correlation-export').onclick=safe(async()=>{
  const data=await api('pick',{kind:'folder'});
  if(data.paths.length)await run('export',{kind:'monitor',folder:data.paths[0],chips:s.correlationSelection?.map(key=>key.split(',').map(Number))});
});

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
  article.append(el('p','Merge 90% combines Scan/March in Config order with a shared Peak FBC as 100%. The curve uses the running maximum FBC.','chart-note'));
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
  const layout=voltageLayout(groups.map(group=>({v:group.voltage,pattern:group.stations[0]?.pattern})),combined);
  const peak=Math.max(...groups.flatMap(group=>group.stations.map(row=>row.fbc)));
  const ceiling=Math.max(1,peak), step=Math.ceil(ceiling/Math.min(4,ceiling));
  const top=step*Math.ceil(ceiling/step);
  const compact=new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1});
  const chart=chartFrame(title,'FBC',top,Array.from({length:top/step+1},(_,i)=>i*step),layout.width,
    n=>compact.format(n),244+layout.margin,'Test Voltage (V) · Config Order',{margin:layout.margin},100);
  const x=drawVoltageIntervals(chart,layout,combined);
  if(combined){
    for(const pattern of comparison.patterns){
      const indices=groups.map((group,i)=>group.stations[0]?.pattern===pattern?i:-1).filter(i=>i>=0);
      if(indices.length){
        const first=indices[0],last=indices.at(-1);
        chart.add('text',{x:(x(first)-layout.strides[first]/2+x(last)+layout.strides[last]/2)/2,
          y:layout.patternY,'text-anchor':'middle',class:'chart-label chart-pattern-label'},pattern);
      }
    }
  }
  for (const [index,group] of groups.entries()) {
    const mid=x(index);
    const barWidth=Math.max(.5,Math.min(25,layout.strides[index]*.75));
    for (const [i,station] of group.stations.entries()) {
      const height=chart.bottom-chart.y(station.fbc);
      const item=series[station.series];
      const description=(combined?item.pattern+' · ':'')+stationLabel(station);
      const part=barWidth/group.stations.length;
      chartMark(chart,'rect',{x:mid-barWidth/2+i*part+part*.05,y:chart.bottom-Math.max(2,height),
        width:Math.max(.4,part*.9),height:Math.max(2,height),class:'chart-bar',fill:item.color},description);
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
  for (const [kind,text] of [['charts','Export PDF/PNG'],['excel','Export Excel']]) {
    const button = el('button',text,'secondary');
    button.dataset.patternExport = kind;
    button.disabled = s.busy;
    button.onclick = safe(async()=>{
      const scope = {wt:s.wt,chip:s.selected.split(','),blk:s.block,pattern:activePattern,kind};
      const {paths} = await api('pick',{kind:'folder'});
      if (!paths.length) return;
      exportStatus.hidden = false;
      exportStatus.textContent = 'Exporting '+scope.pattern+'…';
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
  const sweep=section('Function sweep (Config order)',sweepData,true);
  const address=section('Fail Address / Monitor matching',addressData,true);
  sweep.open=Boolean(march);
  const showTables=(pattern,stations)=>{
    sweepData.replaceChildren(table(['Pattern','TNO','Func.','Test Voltage','FBC','Status'],
      details.sweep.map(r=>[r.pattern,r.tno,r.func,vfmt(r.v),r.fbc,r.state])));
    const addresses=details.addresses.map(r=>{
      const cell=el('td'), btn=el('button','View address','quiet');
      btn.onclick=safe(()=>{
        $('data-view').value='address';$('filter-chip').checked=true;
        s.targetAddress=r.address.join(',');s.viewPage=0;return navigate('data');
      });
      cell.append(btn);
      const voltage=el('td',r.function_voltages.map(vfmt).join(', '));
      voltage.title='Function TNO '+r.function.join(', ');
      return [r.pattern,...r.address,voltage,r.write,r.read,r.category,cell];
    });
    addressData.replaceChildren(table(['Pattern','BLK','WL','BL','IO','Function Voltage','Write TNO','Read TNO','Classification','Source'],addresses));
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
  if(block)body.append(section('WT status and W/R matching',table(['WT','Status','Write','Read'],
    block.states.map(phase=>['WT'+phase.wt,phase.status,phase.w,phase.r])),true));
  body.append(section('Vmin judgment',table(['Pattern','Status','TNO','Func.','Vmin','Peak FBC','Judgment reason'],
    details.crossings.map(c=>[c.pattern,c.status,c.tno,c.func,c.voltage==null?c.status:vminfmt(c),c.peak,crossingReason(c)])),true));
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
  $('page-no').textContent='Page '+(s.viewPage+1)+'';
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
  if(!data.data&&!data.output.length&&!data.warnings.length)block.append(el('p','No import records available.'));
  if(data.data)block.append(section(data.data.label,table(['WT','STEP','Version','Chip','FBC','Address','Ignored addresses','Duplicate FBC','Source'],
    data.data.manifest.map(r=>['WT'+r.wt,r.step,r.version,r.chips,r.fbc,r.address,r.invalid,r.duplicates,r.path]))));
  if(data.output.length||data.warnings.length)block.append(showPaths(data.output,data.warnings));
  modal('Import Info',block);
});
$('open-export').onclick=safe(()=>{
  if(!s.report)throw new Error('Import ASC files first.');
  const block=el('div',null,'modal-files');
  block.append(el('p','The default output folder is the first ASC source folder.'));
  if (s.selected) block.append(el('p','The full Excel BLK matrix uses X'+selection().x+' Y'+selection().y+'.'));
  let folder='';
  const path=el('p','Use the ASC source folder','modal-path');
  const picker=el('button','Select output folder','secondary');
  picker.onclick=safe(async()=>{const data=await api('pick',{kind:'folder'});if(data.paths.length){folder=data.paths[0];path.textContent=folder;}});
  block.append(picker,path);
  const modes={full:'Full Excel report (original layout)',address:'Fail Address Excel',fbc:'FBC Excel',cat:'Cat Map Excel',ppt:'Wafer Maps PowerPoint · 37 cm'};
  for(const [kind,label] of Object.entries(modes)){
    if(s.report.source_mode!=='full' && ![s.report.source_mode,'cat'].includes(kind))continue;
    const button=el('button',label,'secondary');
    button.onclick=safe(()=>{$('modal').close();return run('export',{kind,folder,chip:s.selected?.split(',')});});
    block.append(button);
  }
  modal('Export Report',block);
});
function profile() {return $('profile').value;}
function renderSettings() {
  const current=s.config[profile()];if(!current)return;
  const full=profile()==='full', header=el('tr');
  const fields=[['tno','TNO'],['name','Func.'],['voltage','Voltage (V)'],['cat','Fail Cat.']];
  if(full)fields.push(['stop','Stop Sign']);
  for(const title of ['Group',...fields.map(f=>f[1]),'Row actions'])header.append(el('th',title));
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
    for(const [icon,offset,name] of [['↑',-1,'Move up'],['↓',1,'Move down'],['✕',0,'Remove']]){
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
  if(result.config){s.config[profile()]=result.config;renderSettings();notice('Loaded '+result.paths[0].split(/[\\/]/).pop()+'. Edit and save as needed.');}
});
$('save-config').onclick=safe(async()=>{
  const key=profile(), data=s.config[key];
  s.config[key]=await api('save-settings',{profile:key,rows:data.rows,mode:key==='full'?s.mode:data.mode});
  renderSettings();notice('Saved '+(key==='full'?'Full analysis':'Batch export')+' configuration.');
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
