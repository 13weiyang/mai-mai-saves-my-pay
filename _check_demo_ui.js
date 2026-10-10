// UI 回归：jsdom 真跑演示页，验「Agent 成果台」三块改动 ——
//   ① 🧾 战报条（找店 / 拉菜单 / 领券）填对了没
//   ② 💬 拟话条（点 + / 撤单 / 踩券 / 换店）跟着变没变
//   ③ ⚠️ 退位区（原下单区、去结算按钮）确实收起来了
// 用法：NODE_PATH=<jsdom 所在目录> node _check_demo_ui.js
// 配套：_check_demo.js 管**引擎**（plan / settle / 券省），本脚本管**界面**。
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const html = fs.readFileSync(path.join(__dirname, '演示.html'), 'utf-8');
const errs = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errs.push('jsdomError: ' + e.message));
vc.on('error', (...a) => errs.push('console.error: ' + a.join(' ')));

const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true, virtualConsole: vc });
const d = dom.window.document;
const g = id => d.getElementById(id);

setTimeout(() => {
  const log = (...a) => console.log(...a);

  log('=== 运行期错误 ===');
  log(errs.length ? errs.join('\n') : '（无）');

  log('\n=== 战报条（Agent 干了什么）===');
  ['rpStoreV', 'rpMenuV', 'rpCouponV'].forEach(id => {
    const e = g(id);
    log('  ' + id.padEnd(12), e ? e.innerHTML : '❌ 元素不存在');
  });

  log('\n=== 券卡（扶正后）===');
  log('  couponCard display =', g('couponCard').style.display);
  log('  couponCard class   =', g('couponCard').className);
  log('  cpSum              =', g('cpSum').textContent.trim());
  log('  券行数             =', d.querySelectorAll('#cpList .cp').length);

  log('\n=== 退位区（应为 none / 不可见）===');
  log('  orderZone display  =', g('orderZone') ? g('orderZone').style.display : '❌ 不存在');
  log('  wGo 存在           =', !!g('wGo'), '| disabled =', g('wGo') ? g('wGo').disabled : '-');
  log('  #wallet 里有 .w-go 隐藏规则 =',
      /\.wallet\s+\.w-go\s*\{\s*display\s*:\s*none/.test(d.querySelector('style').textContent));

  log('\n=== 拟话条 · 空态 ===');
  log('  class =', g('syTxt').className, '| 文案 =', g('syTxt').textContent.trim());

  log('\n=== 点两个 + ===');
  const plus = d.querySelectorAll('.qbtn[data-q="1"]');
  log('  + 按钮总数 =', plus.length);
  if (plus[0]) plus[0].click();
  if (plus[5]) plus[5].click();
  log('  syTxt  =', g('syTxt').textContent.trim());
  log('  class  =', g('syTxt').className);
  log('  syFoot =', g('syFoot').textContent.trim());
  log('  钱包   =', g('wNum').textContent, '|', g('wCnt').textContent, '件 |', g('wSaveWrap').textContent.trim());

  log('\n=== 点 − 撤回，空态应回来 ===');
  const minus = d.querySelectorAll('.qbtn[data-q="-1"]');
  if (minus[0]) minus[0].click();
  if (minus[5]) minus[5].click();
  log('  syTxt =', g('syTxt').textContent.trim(), '| class =', g('syTxt').className);

  log('\n=== 踩券：点冰美式（507411）===');
  const bev = d.querySelector('.item[data-code="507411"] .qbtn[data-q="1"]');
  if (bev) {
    bev.click();
    log('  syTxt     =', g('syTxt').textContent.trim());
    log('  wSaveWrap =', g('wSaveWrap').textContent.trim());
    log('  sum 摘要  =', g('sum').textContent.replace(/\s+/g, ' ').trim().slice(0, 180));
  } else log('  ⚠️ 没找到 507411 的 + 按钮');

  log('\n=== 套餐自选面板：图（2026-10-10 补）===');
  const comboBtn = d.querySelector('.item.hascombo .combo-go');
  if (comboBtn) {
    comboBtn.click();
    const opts = d.querySelectorAll('#cpBody .cp-opt');
    const thumbs = d.querySelectorAll('#cpBody .cp-thumb');
    const phs = d.querySelectorAll('#cpBody .cp-thumb-ph');
    log('  面板选项 =', opts.length, '| 有图 =', thumbs.length, '| 占位 =', phs.length,
        '| 覆盖率 =', (100 * thumbs.length / Math.max(1, opts.length)).toFixed(0) + '%');
    const t0 = d.querySelector('#cpBody .cp-thumb');
    log('  首图 src =', t0 ? t0.getAttribute('src') : '（无）');
    log('  前 4 个选项 =',
        [...opts].slice(0, 4).map(o => o.querySelector('.cp-nm').textContent).join(' / '));
    log('  面板标题 =', g('cpTitle').textContent);
  } else {
    log('  （这家店没有可自选套餐，跳过）');
  }

  log('\n=== 换门店（第 2 家）===');
  const sp = d.querySelectorAll('.sp');
  log('  门店卡数 =', sp.length);
  if (sp[1]) {
    sp[1].click();
    log('  换店后 rpStoreV  =', g('rpStoreV').innerHTML);
    log('  换店后 rpMenuV   =', g('rpMenuV').innerHTML);
    log('  换店后 rpCouponV =', g('rpCouponV').innerHTML);
    log('  换店后 syTxt     =', g('syTxt').textContent.trim());
    log('  换店后 已点件数  =', g('wCnt').textContent);
  }

  process.exit(0);
}, 700);
