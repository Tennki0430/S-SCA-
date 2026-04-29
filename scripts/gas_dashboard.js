// ================================================================
// S-SCA Google Apps Script  Dashboard Edition
// GASエディタに全文貼り付けて syncAll を実行してください
// ================================================================

var PROPS = PropertiesService.getScriptProperties();
var SUPABASE_URL = PROPS.getProperty('SUPABASE_URL');
var SUPABASE_KEY = PROPS.getProperty('SUPABASE_KEY');

var SYMBOLS = ['Wheat', 'Corn', 'Naphtha', 'Copper', 'Lithium'];

var REGRESSOR_CONFIG = [
  { symbol: 'BDI',      color: '#1a73e8', label: 'BDI (海運指数)' },
  { symbol: 'VIX',      color: '#e53935', label: 'VIX (恐怖指数)' },
  { symbol: 'Gold',     color: '#7B1FA2', label: '金先物 (Gold)' },
  { symbol: 'Oil',      color: '#00838F', label: '原油WTI (Oil)' },
  { symbol: 'DXY',      color: '#388e3c', label: 'ドル指数 (DXY)' },
  { symbol: 'NatGas',   color: '#E65100', label: '天然ガス (NatGas)' },
  { symbol: 'ChinaETF', color: '#AD1457', label: '中国ETF (FXI)' },
  { symbol: 'Brent',    color: '#4527A0', label: 'ブレント原油 (Brent)' }
];

var SYMBOL_JP = {
  'Wheat':   '小麦',
  'Corn':    'トウモロコシ',
  'Naphtha': 'ナフサ',
  'Copper':  '銅',
  'Lithium': 'リチウムETF'
};

// Supabase 接続（1リクエスト分）
function fetchSupabase(table, params) {
  if (!SUPABASE_URL || !SUPABASE_KEY) {
    throw new Error('スクリプトプロパティに SUPABASE_URL と SUPABASE_KEY を設定してください。');
  }
  var url = SUPABASE_URL + '/rest/v1/' + table + '?' + params;
  var resp = UrlFetchApp.fetch(url, {
    method: 'get',
    headers: { 'apikey': SUPABASE_KEY, 'Authorization': 'Bearer ' + SUPABASE_KEY },
    muteHttpExceptions: true
  });
  if (resp.getResponseCode() !== 200) {
    Logger.log('fetch error [' + table + ']: ' + resp.getContentText());
    return [];
  }
  return JSON.parse(resp.getContentText());
}

// Supabase 全件取得（1000件上限をページネーションで突破）
function fetchSupabaseAll(table, baseParams) {
  var all = [];
  var size = 1000;
  var offset = 0;
  while (true) {
    var batch = fetchSupabase(table, baseParams + '&limit=' + size + '&offset=' + offset);
    if (!batch || batch.length === 0) break;
    all = all.concat(batch);
    if (batch.length < size) break;
    offset += size;
    Utilities.sleep(300);
  }
  Logger.log(table + ' 全件取得: ' + all.length + '件');
  return all;
}

// シート書き込み
function writeSheet(sheetName, data, columns, headers) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getSheetByName(sheetName) || ss.insertSheet(sheetName);
  sheet.clearContents();
  if (!data || data.length === 0) {
    sheet.getRange(1, 1).setValue('データなし');
    return;
  }
  sheet.getRange(1, 1, 1, headers.length)
    .setValues([headers])
    .setFontWeight('bold')
    .setBackground('#e8f0fe');
  var rows = data.map(function(r) {
    return columns.map(function(c) {
      var v = r[c];
      if (v === null || v === undefined) return '';
      if (typeof v === 'object') return JSON.stringify(v);
      return v;
    });
  });
  sheet.getRange(2, 1, rows.length, columns.length).setValues(rows);
  sheet.autoResizeColumns(1, columns.length);
  Logger.log(sheetName + ': ' + data.length + '件');
}

// メイン同期関数
function syncAll() {
  var mktData = fetchSupabaseAll('market_data',
    'select=id,timestamp,symbol,price,source&order=timestamp.asc');
  var predData = fetchSupabaseAll('prediction_log',
    'select=id,timestamp,symbol,target_date,current_price,predicted_price,reasoning_text&order=timestamp.asc');
  var fbData = fetchSupabaseAll('feedback_log',
    'select=id,timestamp,symbol,error_rate,self_reflection_notes,parameter_updates&order=timestamp.asc');
  var newsData = fetchSupabase('news_log',
    'select=id,timestamp,symbol,headline,source&order=timestamp.desc&limit=200');

  writeSheet('market_data', mktData,
    ['timestamp', 'symbol', 'price', 'source'],
    ['日時', '銘柄', '価格', 'データ元']);

  writeSheet('prediction_log', predData,
    ['timestamp', 'symbol', 'target_date', 'current_price', 'predicted_price', 'reasoning_text'],
    ['予測実行日', '銘柄', '予測対象日(14日後)', '現在価格(実績)', '予測価格', 'Claudeの分析']);

  writeSheet('feedback_log', fbData,
    ['timestamp', 'symbol', 'error_rate', 'self_reflection_notes', 'parameter_updates'],
    ['日時', '銘柄', '誤差率(MAPE%)', '外れた理由 (AI分析)', '改善した内容 (パラメータ更新)']);

  writeSheet('news_log', newsData,
    ['timestamp', 'symbol', 'headline', 'source'],
    ['日時', '銘柄', 'ニュース', 'ソース']);

  updateDashboard(mktData, predData, fbData);
  SpreadsheetApp.getActiveSpreadsheet()
    .toast('同期完了！ダッシュボードを更新しました。', 'S-SCA', 5);
}

// ================================================================
// ダッシュボード生成
// ================================================================
function updateDashboard(mktData, predData, fbData) {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var ds = ss.getSheetByName('Dashboard') || ss.insertSheet('Dashboard');
  ds.clearContents();
  ds.getCharts().forEach(function(c) { ds.removeChart(c); });

  var row = 1;

  ds.getRange(row, 1)
    .setValue('S-SCA ダッシュボード - Sentient Supply-Chain Agent')
    .setFontSize(16)
    .setFontWeight('bold');
  ds.getRange(row, 8)
    .setValue('更新: ' + Utilities.formatDate(new Date(), 'Asia/Tokyo', "yyyy/MM/dd HH:mm '(JST)'"));
  row += 2;

  row = buildLegendSection(ds, row);
  row += 2;

  var regTitleRow = row;
  row = buildRegressorTable(ds, mktData, row);
  buildRegressorChart(ds, regTitleRow + 1, row - 1);
  row += 2;

  row = buildPredActualSection(ds, predData, mktData, row);
  row += 2;

  row = buildFeedbackSection(ds, fbData, row);
  row += 2;

  var mapeTitleRow = row;
  row = buildMapeTable(ds, fbData, row);
  buildMapeChart(ds, mapeTitleRow + 1, row - 1);

  ds.autoResizeColumns(1, 10);
}

// 凡例テーブル
function buildLegendSection(ds, row) {
  ds.getRange(row, 1)
    .setValue('先行指標 凡例 - グラフの色対応表')
    .setFontSize(13)
    .setFontWeight('bold');
  row++;

  ds.getRange(row, 1, 1, 3)
    .setValues([['グラフの色と指標名', '意味', '価格への影響']])
    .setFontWeight('bold')
    .setBackground('#e8f0fe');
  row++;

  var entries = [
    ['BDI (海運指数)',        '#1a73e8', '世界の船舶輸送量の先行指標。上昇=物流が活発',         '上昇 -> コモディティ需要増 -> 価格上昇傾向'],
    ['VIX (恐怖指数)',        '#e53935', '株式市場の不安定さ・不確実性の指標',                 '上昇 -> リスクオフ -> コモディティ下落傾向'],
    ['金先物 (Gold)',         '#7B1FA2', '安全資産への逃避需要。有事に上昇しやすい',           '上昇 -> 地政学リスク高 -> 他銘柄は不安定'],
    ['原油WTI (Oil)',         '#00838F', 'エネルギーコスト。製造・輸送コストに直結',           '上昇 -> 生産コスト増 -> 価格転嫁で上昇'],
    ['ドル指数 (DXY)',        '#388e3c', '米ドルの強さ (コモディティはドル建て取引)',          '上昇(ドル高) -> 相対的に割高 -> 価格下落圧力'],
    ['天然ガス (NatGas)',     '#E65100', 'ナフサの競合原料。銅製錬のエネルギーコストにも連動', '上昇 -> ナフサ価格の下押し圧力 / 銅の製造コスト増'],
    ['中国ETF (FXI)',         '#AD1457', '銅消費の約50%を占める中国経済の代理指標',           '上昇(中国好調) -> 銅・コモディティ需要増 -> 価格上昇'],
    ['ブレント原油 (Brent)',  '#4527A0', 'アジア・欧州向けナフサ価格はWTIよりブレントに連動', '上昇 -> ナフサ価格の直接押し上げ要因']
  ];

  entries.forEach(function(e, i) {
    ds.getRange(row + i, 1).setValue(e[0]).setBackground(e[1]).setFontColor('#ffffff').setFontWeight('bold');
    ds.getRange(row + i, 2).setValue(e[2]);
    ds.getRange(row + i, 3).setValue(e[3]);
  });

  return row + entries.length;
}

// 先行指標 正規化テーブル
function buildRegressorTable(ds, mktData, startRow) {
  ds.getRange(startRow, 1)
    .setValue('先行指標 推移 (100=90日前の水準 / 100超=上昇 / 100未満=下落)')
    .setFontSize(13)
    .setFontWeight('bold');
  startRow++;

  var syms = REGRESSOR_CONFIG.map(function(r) { return r.symbol; });
  var byDate = {};

  mktData.forEach(function(row) {
    if (syms.indexOf(row.symbol) < 0) return;
    var d = (row.timestamp || '').substring(0, 10);
    if (!byDate[d]) byDate[d] = {};
    if (!byDate[d][row.symbol]) byDate[d][row.symbol] = [];
    byDate[d][row.symbol].push(parseFloat(row.price) || 0);
  });

  var dates = Object.keys(byDate).sort().slice(-90);
  var base = {};
  syms.forEach(function(sym) {
    for (var i = 0; i < dates.length; i++) {
      if (byDate[dates[i]][sym]) {
        var avg = arrAvg(byDate[dates[i]][sym]);
        if (avg > 0) { base[sym] = avg; break; }
      }
    }
  });

  var headers = ['日付'].concat(REGRESSOR_CONFIG.map(function(r) { return r.label; }));
  ds.getRange(startRow, 1, 1, headers.length)
    .setValues([headers])
    .setFontWeight('bold')
    .setBackground('#e8f0fe');
  REGRESSOR_CONFIG.forEach(function(r, i) {
    ds.getRange(startRow, i + 2).setFontColor(r.color).setFontWeight('bold');
  });
  startRow++;

  var rows = dates.map(function(d) {
    return [d].concat(syms.map(function(sym) {
      if (byDate[d][sym] && base[sym]) {
        return Math.round(arrAvg(byDate[d][sym]) / base[sym] * 1000) / 10;
      }
      return '';
    }));
  });

  if (rows.length > 0) {
    ds.getRange(startRow, 1, rows.length, headers.length).setValues(rows);
  }
  return startRow + rows.length;
}

// 先行指標グラフ
function buildRegressorChart(ds, headerRow, lastDataRow) {
  if (lastDataRow <= headerRow) return;
  var numCols = 1 + REGRESSOR_CONFIG.length;
  var range = ds.getRange(headerRow, 1, lastDataRow - headerRow + 1, numCols);
  var series = {};
  REGRESSOR_CONFIG.forEach(function(r, i) {
    series[i] = { color: r.color, lineWidth: 2, labelInLegend: r.label };
  });
  var chart = ds.newChart()
    .setChartType(Charts.ChartType.LINE)
    .addRange(range)
    .setPosition(3, 9, 0, 0)
    .setOption('title', '先行指標 正規化推移 (100=90日前の水準)')
    .setOption('titleTextStyle', { fontSize: 14, bold: true })
    .setOption('width', 720)
    .setOption('height', 380)
    .setOption('hAxis', { title: '日付', slantedText: true, slantedTextAngle: 45 })
    .setOption('vAxis', { title: '正規化指数 (100=90日前の水準)' })
    .setOption('legend', { position: 'right', textStyle: { fontSize: 11 } })
    .setOption('series', series)
    .setOption('curveType', 'function')
    .build();
  ds.insertChart(chart);
}

// 予測 vs 実績テーブル
function buildPredActualSection(ds, predData, mktData, startRow) {
  ds.getRange(startRow, 1)
    .setValue('予測 vs 実績  (評価: 優秀=MAPE5%以内  良好=10%以内  要改善=20%以内  大きな誤差=20%超)')
    .setFontSize(13)
    .setFontWeight('bold');
  startRow++;

  var actualMap = {};
  var regressorSyms = REGRESSOR_CONFIG.map(function(r) { return r.symbol; });
  mktData.forEach(function(row) {
    if (regressorSyms.indexOf(row.symbol) >= 0) return;
    var key = row.symbol + '_' + (row.timestamp || '').substring(0, 10);
    if (!actualMap[key]) actualMap[key] = [];
    actualMap[key].push(parseFloat(row.price) || 0);
  });

  var headers = ['銘柄', '予測実行日', '予測対象日(14日後)', '予測価格', '実績価格', '誤差率(MAPE)', '精度評価'];
  ds.getRange(startRow, 1, 1, headers.length)
    .setValues([headers])
    .setFontWeight('bold')
    .setBackground('#e8f0fe');
  startRow++;

  var rows = [];
  var bgs = [];

  predData.slice().reverse().slice(0, 100).forEach(function(p) {
    var targetDate = (p.target_date || '').substring(0, 10);
    var actualArr = actualMap[p.symbol + '_' + targetDate];
    var actual = (actualArr && actualArr.length) ? Math.round(arrAvg(actualArr) * 100) / 100 : null;
    var predicted = Math.round(parseFloat(p.predicted_price) * 100) / 100;
    var mape = actual ? Math.round(Math.abs((predicted - actual) / actual) * 1000) / 10 : null;

    var label, bg;
    if (mape === null)   { label = '(実績待ち)';   bg = '#ffffff'; }
    else if (mape <= 5)  { label = '優秀';          bg = '#c8e6c9'; }
    else if (mape <= 10) { label = '良好';          bg = '#dcedc8'; }
    else if (mape <= 20) { label = '要改善';        bg = '#fff9c4'; }
    else                 { label = '大きな誤差';    bg = '#ffcdd2'; }

    rows.push([
      (SYMBOL_JP[p.symbol] || p.symbol) + ' (' + p.symbol + ')',
      (p.timestamp || '').substring(0, 10),
      targetDate,
      predicted,
      actual !== null ? actual : '(未来)',
      mape !== null ? mape + '%' : '-',
      label
    ]);
    bgs.push(bg);
  });

  if (rows.length > 0) {
    ds.getRange(startRow, 1, rows.length, headers.length).setValues(rows);
    rows.forEach(function(_, i) {
      ds.getRange(startRow + i, 7).setBackground(bgs[i]);
    });
  }
  return startRow + rows.length;
}

// 外れ予測の分析と改善履歴
function buildFeedbackSection(ds, fbData, startRow) {
  ds.getRange(startRow, 1)
    .setValue('外れ予測の分析と改善履歴 - なぜ外れたか・何を修正したか (MAPE 10%超のケース)')
    .setFontSize(13)
    .setFontWeight('bold');
  startRow++;

  var headers = ['日時', '銘柄', '誤差率(MAPE%)', '外れた理由 (AI分析)', '改善した内容 (パラメータ更新)'];
  ds.getRange(startRow, 1, 1, headers.length)
    .setValues([headers])
    .setFontWeight('bold')
    .setBackground('#fce4ec');
  startRow++;

  var misses = fbData
    .filter(function(r) { return parseFloat(r.error_rate) > 10; })
    .slice().reverse()
    .slice(0, 50);

  if (misses.length === 0) {
    ds.getRange(startRow, 1)
      .setValue('誤差10%超のケースなし（全予測が良好な精度）')
      .setFontColor('#388e3c');
    return startRow + 1;
  }

  var rows = misses.map(function(r) {
    var paramText = '(更新なし)';
    if (r.parameter_updates) {
      try {
        var p = typeof r.parameter_updates === 'string'
          ? JSON.parse(r.parameter_updates)
          : r.parameter_updates;
        paramText = Object.keys(p).map(function(k) {
          return k + ' -> ' + p[k];
        }).join(' / ');
      } catch (e) {
        paramText = String(r.parameter_updates);
      }
    }
    return [
      (r.timestamp || '').substring(0, 10),
      (SYMBOL_JP[r.symbol] || r.symbol) + ' (' + r.symbol + ')',
      parseFloat(r.error_rate).toFixed(1) + '%',
      r.self_reflection_notes || '(分析なし)',
      paramText
    ];
  });

  if (rows.length > 0) {
    ds.getRange(startRow, 1, rows.length, headers.length).setValues(rows);
    // MAPE列の色分け
    misses.forEach(function(r, i) {
      var mape = parseFloat(r.error_rate);
      var bg = mape > 20 ? '#ffcdd2' : '#fff9c4';
      ds.getRange(startRow + i, 3).setBackground(bg);
    });
    // 理由・改善列を折り返し表示
    ds.getRange(startRow, 4, rows.length, 2).setWrap(true);
  }
  return startRow + rows.length;
}

// MAPEテーブル
function buildMapeTable(ds, fbData, startRow) {
  ds.getRange(startRow, 1)
    .setValue('予測誤差率 (MAPE) 推移 - 低いほど高精度')
    .setFontSize(13)
    .setFontWeight('bold');
  startRow++;

  var dateMap = {};
  fbData.forEach(function(row) {
    var d = (row.timestamp || '').substring(0, 10);
    if (!dateMap[d]) dateMap[d] = {};
    dateMap[d][row.symbol] = parseFloat(row.error_rate) || 0;
  });

  var dates = Object.keys(dateMap).sort();
  var headers = ['日付'].concat(SYMBOLS.map(function(s) {
    return (SYMBOL_JP[s] || s) + ' (' + s + ')';
  }));
  ds.getRange(startRow, 1, 1, headers.length)
    .setValues([headers])
    .setFontWeight('bold')
    .setBackground('#e8f0fe');
  startRow++;

  var rows = dates.map(function(d) {
    return [d].concat(SYMBOLS.map(function(s) {
      return dateMap[d][s] !== undefined ? dateMap[d][s] : '';
    }));
  });
  if (rows.length > 0) {
    ds.getRange(startRow, 1, rows.length, headers.length).setValues(rows);
  }
  return startRow + rows.length;
}

// MAPEグラフ
function buildMapeChart(ds, headerRow, lastDataRow) {
  if (lastDataRow <= headerRow) return;
  var numCols = 1 + SYMBOLS.length;
  var range = ds.getRange(headerRow, 1, lastDataRow - headerRow + 1, numCols);
  var colors = ['#4285F4', '#EA4335', '#FBBC04', '#34A853', '#9C27B0'];
  var series = {};
  SYMBOLS.forEach(function(_, i) {
    series[i] = {
      color: colors[i],
      lineWidth: 2,
      labelInLegend: (SYMBOL_JP[SYMBOLS[i]] || SYMBOLS[i]) + ' (' + SYMBOLS[i] + ')'
    };
  });
  var chart = ds.newChart()
    .setChartType(Charts.ChartType.LINE)
    .addRange(range)
    .setPosition(55, 9, 0, 0)
    .setOption('title', '銘柄別 予測誤差率 (MAPE) 推移 - 低いほど高精度')
    .setOption('titleTextStyle', { fontSize: 14, bold: true })
    .setOption('width', 720)
    .setOption('height', 380)
    .setOption('hAxis', { title: '日付', slantedText: true, slantedTextAngle: 45 })
    .setOption('vAxis', { title: '誤差率 MAPE (%)' })
    .setOption('legend', { position: 'right', textStyle: { fontSize: 11 } })
    .setOption('series', series)
    .setOption('curveType', 'function')
    .build();
  ds.insertChart(chart);
}

// ユーティリティ
function arrAvg(arr) {
  return arr.reduce(function(a, b) { return a + b; }, 0) / arr.length;
}
