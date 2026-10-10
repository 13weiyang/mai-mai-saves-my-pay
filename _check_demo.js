// 验 JS 侧 plan()：亲子模式 vs 成人+亲子 是否真有区别
// 用法：node _jstest.js
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync(__dirname + '/演示.html', 'utf-8');

function grabFn(src, name){
  const s = src.indexOf('function ' + name + '(');
  if (s < 0) throw new Error('找不到函数 ' + name);
  let d = 0, i = src.indexOf('{', s), e = -1;
  for (; i < src.length; i++){
    if (src[i] === '{') d++;
    else if (src[i] === '}'){ d--; if (d === 0){ e = i + 1; break; } }
  }
  return src.slice(s, e);
}

const dataM = html.match(/const DATA_ALL = (\{[\s\S]*?\});\r?\n/);
if (!dataM) throw new Error('找不到 DATA_ALL');
const DATA_ALL = JSON.parse(dataM[1]);

// ⚠️ 作用域陷阱：plan() 引用自由变量 DINERS / KIDSN / CUR。
//    不能把 `let DINERS` 一起 eval —— 会新建块级变量，外部改 global 不生效。
//    这里把三个变量声明成 context 的属性，plan 里读到的是 context 上的值。
const ctx = {
  DATA_ALL,
  CUR: null,
  DINERS: 'adult',
  KIDSN: 0,
  Math, JSON, console,
};
vm.createContext(ctx);

vm.runInContext(grabFn(html, 'maxPerSku'), ctx);
vm.runInContext(grabFn(html, 'countOf'), ctx);
vm.runInContext(grabFn(html, 'mergeSameCode'), ctx);
vm.runInContext(grabFn(html, 'diversifyPlan'), ctx);
// 套餐自选：settle 现在会调 unitPriceOf（含"自选加价"），得把它和依赖一起喂进来
vm.runInContext('var COMBO = {};', ctx);
vm.runInContext(grabFn(html, 'cfgCount'), ctx);
vm.runInContext(grabFn(html, 'cfgDiff'), ctx);
vm.runInContext(grabFn(html, 'unitPriceOf'), ctx);
vm.runInContext(grabFn(html, 'unitPayOf'), ctx);
vm.runInContext(grabFn(html, 'fillToTarget'), ctx);
vm.runInContext(grabFn(html, 'unitPriceByCode'), ctx);
vm.runInContext(grabFn(html, 'topUpTo'), ctx);
vm.runInContext(grabFn(html, 'plan'), ctx);

// ⚠️ 单款份数上限的常量是 `const` 声明，grabFn 抓的是 function，
//    抓不到它们 → 手动从 HTML 里抠出来塞进 context。
for (const cname of ['CHEAP_ITEM_PRICE', 'CHEAP_ITEM_CAP', 'MAX_PER_SKU_CAP']){
  const m = html.match(new RegExp('const ' + cname + '\\s*=\\s*([\\d.]+)'));
  if (!m) throw new Error('找不到常量 ' + cname);
  ctx[cname] = parseFloat(m[1]);
}

const codes = Object.keys(DATA_ALL);

// ⚠️ 配餐器 plan() 现在是**企业团餐专用**能力 —— 普通到店/外送没有满减
//    （2026-10-10 实测：三家店大额单折扣恒为 0），所以 DATA_ALL 里的 promos 是空的。
//    这里喂一组**企业团餐门槛**当夹具（测试用，不是她门店的真实规则）。
const GROUP_PROMOS = [
  {threshold: 300,  pct: 22},
  {threshold: 500,  pct: 26},
  {threshold: 1000, pct: 30},
  {threshold: 2000, pct: 34},
];

function runPlan(code, budget, diners, kids, picks, must, exclude){
  ctx.CUR = {
    code,
    meals: DATA_ALL[code].meals.map(m => ({
      code: m.code, name: m.name, price: m.price, kind: m.kind,
      category: m.category, img: m.img,
    })),
    promos: GROUP_PROMOS,
  };
  ctx.DINERS = diners;
  ctx.KIDSN = kids;
  ctx.KIDPICKS = picks || [];
  // 用户的"手"：点名要几份、明确不要啥（见演示页 plan 的 must/exclude）
  ctx.__MUST = must || [];
  ctx.__EXCL = exclude || [];
  return vm.runInContext('plan(' + budget + ', __MUST, __EXCL)', ctx);
}

let total = 0, fails = 0, warns = 0;
const budgets = [300, 350, 500, 700, 1000, 1500, 2000];
const hasFamily = code => DATA_ALL[code].meals.some(m => m.kind === 'family');

for (const code of codes){
  const kindOf = {};
  for (const m of DATA_ALL[code].meals) kindOf[m.code] = m.kind;

  // ⭐ 掉线保护：预算 300 起、任何模式都该出得来方案。
  //    旧版 `if (!r) continue;` 会把 null **静默跳过**，
  //    于是「¥300 亲子餐出不来」这种 bug 藏了很久没人发现。
  //    这里把"该有方案却返回 null"直接判失败。
  for (const budget of budgets){
    for (const [diners, kids] of [['adult',0],['kids',1],['kids',2],['mixed',2]]){
      const r0 = runPlan(code, budget, diners, kids);
      if (!r0){
        console.log(`FAIL 无方案 ${code} ${diners} kids=${kids} ¥${budget}`); fails++;
      }
    }
  }

  for (const budget of budgets){
    for (const [diners, kids] of [['adult',0],['kids',0],['kids',2],['mixed',2]]){
      const r = runPlan(code, budget, diners, kids);
      if (!r) continue;
      total++;

      let nKid = 0, nFam = 0;
      for (const it of r.items){
        if (kindOf[it.code] === 'kids') nKid += it.count;
        if (kindOf[it.code] === 'family') nFam += it.count;
      }
      const nToy = nKid + nFam;

      if (diners === 'adult' && nToy){
        console.log(`FAIL adult 含带玩具餐 ${code} ¥${budget} kid=${nKid} fam=${nFam}`); fails++;
      }
      if (diners === 'kids'){
        const need = kids > 0 ? kids : 1;
        if (nToy !== need){
          console.log(`FAIL kids 份数 ${code} ¥${budget} kids=${kids} toy=${nToy} need=${need}`); fails++;
        }
        // ⭐ 带娃场景优先官方套餐：店里若有 family，方案里就该出现
        if (hasFamily(code) && nFam === 0){
          console.log(`WARN kids 模式未用官方套餐 ${code} ¥${budget} kids=${kids}`); warns++;
        }
      }
      if (diners === 'mixed'){
        // ⭐ 成人+亲子也优先官方套餐（商家设计要落地）
        if (hasFamily(code) && nFam === 0){
          console.log(`WARN mixed 模式未用官方套餐 ${code} ¥${budget} kids=${kids}`); warns++;
        }
        if (nToy !== kids){
          console.log(`FAIL mixed 份数 ${code} ¥${budget} kids=${kids} toy=${nToy}`); fails++;
        }
      }

      // ⭐ 单款份数上限（bug 9 · 2026-10-09）
      //   起因：用户报「某一款被默认点了5份」。
      //   ⚠️ 与 Python 侧断言 6 同口径——两边引擎是两份代码，
      //      规则必须两边都钉，否则改了一边另一边悄悄漏。
      const priceOf = {};
      for (const mm of DATA_ALL[code].meals) priceOf[mm.code] = mm.price;
      for (const it of r.items){
        const pr = priceOf[it.code];
        const cap = (pr != null && pr <= ctx.CHEAP_ITEM_PRICE)
                      ? ctx.CHEAP_ITEM_CAP : ctx.MAX_PER_SKU_CAP;
        if (it.count > cap){
          console.log(`FAIL 单款超上限 ${code} ¥${budget} ${it.code} ×${it.count} > ${cap}`); fails++;
        }
      }
    }
  }
}

// ============================================================
// 逐娃口味（kid_picks）：指定款必须点到位，不能只挑最便宜的
// ============================================================
let pickTotal = 0, pickFails = 0;
for (const code of codes){
  const km = DATA_ALL[code].meals.filter(m => m.kind === 'kids');
  if (km.length < 2) continue;
  const kindOf = {};
  for (const m of DATA_ALL[code].meals) kindOf[m.code] = m.kind;
  const byName = (kw) => km.find(m => m.name.indexOf(kw) >= 0);

  for (const budget of [500, 700]){
    // 单娃点名要"最贵"那款 → 必须出现
    const dearest = km.slice().sort((a,b)=>b.price-a.price)[0];
    let r = runPlan(code, budget, 'mixed', 1, [dearest.code]);
    if (r){
      pickTotal++;
      const got = r.items.find(p => p.code === dearest.code);
      if (!got) { console.log(`FAIL 点名款未出现 ${code} ¥${budget} ${dearest.name}`); pickFails++; }
    }
    // 两娃点两款不同的 → 两款都该出现
    const mlj = byName('麦乐鸡'), hd = byName('汉堡');
    if (mlj && hd){
      r = runPlan(code, budget, 'mixed', 2, [hd.code, mlj.code]);
      if (r){
        pickTotal++;
        const hasHd = r.items.some(p => p.code === hd.code);
        const hasMlj = r.items.some(p => p.code === mlj.code);
        if (!hasHd || !hasMlj){
          console.log(`FAIL 两娃两款未各就位 ${code} ¥${budget} hd=${hasHd} mlj=${hasMlj}`); pickFails++;
        }
      }
    }
    // 都"any" → 不该凭空冒出指定款（走官方套餐或最便宜）
    r = runPlan(code, budget, 'mixed', 2, ['any','any']);
    if (r) pickTotal++;
  }
}

console.log(`\nJS 侧：总案 ${total} · 失败 ${fails} · 提醒 ${warns}`);
console.log(`逐娃口味：${pickTotal} 组 · 失败 ${pickFails}`);

// ============================================================
// ⭐ 用户点名 / 排除（选择自由）· 与 Python 侧断言 7 同口径
//
// 起因：2026-10-09「如果某一个套餐我比较喜欢，我想要点N份，
//      这个没有选择自由」。
// ⚠️ 跟"单款份数上限"是一对，钉同一个变量的两个方向：
//      上限    → 引擎自己凑单不许超（防算法瞎堆）
//      点名/排除 → 用户说了必须算（防算法绑住用户的手）
//    两边引擎是两份代码，规则必须两边都钉，否则改了一边另一边悄悄漏。
// ============================================================
let mTotal = 0, mFails = 0;
for (const code of codes){
  const meals = DATA_ALL[code].meals;
  // 挑一款"便宜货"——正是会被单款上限压到 2 份的那一类
  const cheap = meals
    .filter(m => (m.kind === 'main' || m.kind === 'side')
                 && m.price > 0 && m.price <= ctx.CHEAP_ITEM_PRICE)
    .sort((a,b)=>a.price-b.price);
  if (!cheap.length) continue;
  const target = cheap[0];

  // 点名要 5 份：必须原样给 5 份（哪怕远超单款上限）
  for (const [diners, kids] of [['adult',0],['kids',1]]){
    for (const budget of [500, 1200]){
      mTotal++;
      const r = runPlan(code, budget, diners, kids, [], [{code:target.code, count:5}], []);
      if (!r){ console.log(`FAIL 点名无方案 ${code} ${diners} ¥${budget}`); mFails++; continue; }
      const got = (r.items.find(i=>i.code===target.code) || {}).count || 0;
      if (got !== 5){
        console.log(`FAIL 点名「${target.name}」要5份只给${got}份 ${code} ${diners} ¥${budget}`);
        mFails++;
      }
    }
  }

  // 排除：用户说不要的款，结果里不许出现
  const dearest = meals.filter(m=>m.kind==='main').sort((a,b)=>b.price-a.price)[0];
  if (dearest){
    for (const budget of [500, 1200]){
      mTotal++;
      const r = runPlan(code, budget, 'adult', 0, [], [], [dearest.code]);
      if (r && r.items.some(i=>i.code===dearest.code)){
        console.log(`FAIL 排除「${dearest.name}」却还是出现了 ${code} ¥${budget}`);
        mFails++;
      }
    }
  }
}
console.log(`用户点名/排除：${mTotal} 组 · 失败 ${mFails}`);

// ============================================================
// ⭐ 方案里不得有重复 code（bug 10）· 与 Python 侧断言 8 同口径
//
// 起因：2026-10-09「300元档，默认的是三款，最后一款默认的是N=2，
//      点'全部恢复'也是这样」——其实那是**同一款出现了两条**，
//      渲染成两张一样的卡，看着像三款、实际只有两款。
//
// ⚠️ 这是"数据不变式"，不是某个场景的期望值：
//    凑单流程里有好几处「换一件」，漏一处就重复。
//    必须**全方案扫**，漏一个角落等于没做。
// ============================================================
let dTotal = 0, dFails = 0;
for (const code of codes){
  const nameOf = {};
  for (const m of DATA_ALL[code].meals) nameOf[m.code] = m.name;
  for (const [diners, kids] of [['adult',0],['kids',1],['kids',2],['mixed',2]]){
    for (const budget of [300, 500, 800, 1000, 1200, 2000]){
      dTotal++;
      const r = runPlan(code, budget, diners, kids);
      if (!r) continue;
      const seen = new Set(), dups = [];
      for (const it of r.items){
        if (seen.has(it.code)) dups.push(nameOf[it.code] || it.code);
        seen.add(it.code);
      }
      if (dups.length){
        console.log(`FAIL 同一款出现多次 ${code} ${diners} ${kids}娃 ¥${budget}：${dups.join('、')}`);
        dFails++;
      }
    }
  }
}
console.log(`方案不重复：${dTotal} 组 · 失败 ${dFails}`);

// ============================================================
// ⭐ 点单表结算逻辑（v1.15 换的新交互）
//
// 新交互：菜单全摊开、**每款默认 0**、用户点多少算多少。
// 那"算账"就成了整个页面的心脏 —— 必须准：
//   · 空表 = 0；份数 0 的款不算钱
//   · 原价 = 各款单价 × 份数 之和
//   · 实付 = 原价 − 省额；省额不许超过原价
//   · 套上的优惠档必须真够得着（门槛 ≤ 原价）
// ⚠️ 注意"超预算"比较的是**实付**（用户真掏的钱），不是原价 ——
//    这条在 renderOverBudget 里，此处把 settle 的口径钉住。
// ============================================================
vm.runInContext(grabFn(html, 'couponSaveOf'), ctx);   // settle() 现在会调它
vm.runInContext(grabFn(html, 'settle'), ctx);

let sTotal = 0, sFails = 0;
for (const code of codes){
  const meals = DATA_ALL[code].meals;
  ctx.CUR = {
    code,
    meals: meals.map(m=>({code:m.code,name:m.name,price:m.price,kind:m.kind,category:m.category,img:m.img})),
    promos: DATA_ALL[code].promos,
  };

  // ① 空表 → 一分不花
  ctx.PICK = {};
  let s = vm.runInContext('settle()', ctx);
  sTotal++;
  if(s.original !== 0 || s.final !== 0){
    console.log(`FAIL 空表应算 0 ${code}（得原价${s.original}）`); sFails++;
  }

  // ② 点两款 → 原价 = 单价和；实付 = 原价 − 省；档位必须够得着
  const m1 = meals.find(m=>m.kind==='main');
  const m2 = meals.find(m=>m.kind==='side');
  if(m1 && m2){
    ctx.PICK = {}; ctx.PICK[m1.code] = 2; ctx.PICK[m2.code] = 1;
    s = vm.runInContext('settle()', ctx);
    sTotal++;
    const want = Math.round((m1.price*2 + m2.price)*100)/100;
    if(Math.abs(s.original - want) > 1e-9){
      console.log(`FAIL 原价算错 ${code}：得 ${s.original}，应 ${want}`); sFails++;
    }
    if(Math.abs(s.final - (s.original - s.saved)) > 1e-9){
      console.log(`FAIL 实付≠原价−省 ${code}`); sFails++;
    }
    if(s.saved > s.original + 1e-9){
      console.log(`FAIL 省的比原价还多 ${code}`); sFails++;
    }
    if(s.promo && s.promo.threshold > s.original + 1e-9){
      console.log(`FAIL 套了够不着的档 ${code}`); sFails++;
    }
  }

  // ③ 份数 0 的款不该算钱
  const anyCode = (m1 || meals[0]).code;
  ctx.PICK = {}; ctx.PICK[anyCode] = 0;
  s = vm.runInContext('settle()', ctx);
  sTotal++;
  if(s.original !== 0){
    console.log(`FAIL 0 份不该算钱 ${code}`); sFails++;
  }
}
console.log(`点单结算：${sTotal} 组 · 失败 ${sFails}`);

// ============================================================
// 🧧 券省（v1.28 新）
//   · 没点 / 没券 → 不省
//   · 踩到券 → 券省 = 不用券的实付价 − 券价
//   · **券只作用于 1 份**（实测：挂券时接口把该商品份数吃成 1）
//   · 拿不到券价（pay 非数字）→ 跳过、不编
// ============================================================
let cTotal = 0, cFails = 0;
for (const code of codes){
  const meals = DATA_ALL[code].meals;
  const mi = meals.find(m=>m.kind==='main');
  const mkCur = (coupons)=>ctx.CUR = {
    code,
    meals: meals.map(m=>({code:m.code,name:m.name,price:m.price,kind:m.kind,category:m.category,img:m.img})),
    promos: DATA_ALL[code].promos,
    coupons,
  };

  if(mi){
    // ① 没点 → 0
    mkCur({ store: [{ title:'测试券', pay: 9.9, products:[{code: mi.code}] }] });
    ctx.PICK = {};
    let s = vm.runInContext('settle()', ctx);
    cTotal++;
    if(s.couponSave !== 0){ console.log(`FAIL 没点不该有券省 ${code}`); cFails++; }

    // ② 点 1 份 → 券省 = 单价 − 券价
    ctx.PICK = {}; ctx.PICK[mi.code] = 1;
    s = vm.runInContext('settle()', ctx);
    cTotal++;
    const want = Math.round((mi.price - 9.9)*100)/100;
    if(Math.abs(s.couponSave - want) > 1e-9){
      console.log(`FAIL 券省算错 ${code}：得 ${s.couponSave}，应 ${want}`); cFails++;
    }
    if(Math.abs(s.final - (s.original - s.saved)) > 1e-9){
      console.log(`FAIL 有券时 实付≠原价−省 ${code}`); cFails++;
    }

    // ③ 点 3 份 → 券省**不变**（券只算 1 份）
    ctx.PICK = {}; ctx.PICK[mi.code] = 3;
    s = vm.runInContext('settle()', ctx);
    cTotal++;
    if(Math.abs(s.couponSave - want) > 1e-9){
      console.log(`FAIL 券该只算 1 份 ${code}：得 ${s.couponSave}，应 ${want}`); cFails++;
    }
  }

  // ④ 券价拿不到（pay 非数字）→ 跳过、不编
  const any = mi || meals[0];
  mkCur({ store: [{ title:'没价券', pay: null, products:[{code: any.code}] }] });
  ctx.PICK = {}; ctx.PICK[any.code] = 1;
  let s2 = vm.runInContext('settle()', ctx);
  cTotal++;
  if(s2.couponSave !== 0){ console.log(`FAIL 拿不到券价不该省 ${code}`); cFails++; }
}
console.log(`券省：${cTotal} 组 · 失败 ${cFails}`);
