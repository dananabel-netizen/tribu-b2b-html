// === Iniciativas HotelDO · HTML — Apps Script ===
// Sirve el HTML que genera el refresh diario (rama tablero-live, carpeta iniciativas/).
// - Si el link trae ?i=<nombre|fecha>, el tablero abre directo el impacto de esa iniciativa.
// - Los links al impacto que se cargan desde el tablero (setLink) se guardan en las propiedades del script,
//   así los ven todos los que abren la web app.

var DASHBOARD_URL = "https://raw.githubusercontent.com/dananabel-netizen/tribu-b2b-dana-/tablero-live/iniciativas/iniciativas_dashboard.html";
var LINK_PREFIX = 'L_';

function _id(key) {
  return LINK_PREFIX + Utilities.computeDigest(Utilities.DigestAlgorithm.MD5, key)
    .map(function (b) { return ('0' + (b & 0xff).toString(16)).slice(-2); }).join('');
}

function _getLinks() {
  var props = PropertiesService.getScriptProperties().getProperties(), out = {};
  Object.keys(props).forEach(function (k) {
    if (k.indexOf(LINK_PREFIX) !== 0) return;
    try { var o = JSON.parse(props[k]); out[o.k] = o.u; } catch (e) {}
  });
  return out;
}

// Lo llama el tablero (google.script.run). url vacío = quitar el link.
function setLink(key, url) {
  key = String(key || '');
  url = String(url || '').trim();
  if (!key) throw new Error('Falta la iniciativa');
  if (url && !/^https?:\/\//i.test(url)) throw new Error('El link tiene que empezar con http o https');
  if (url.length > 2000) throw new Error('El link es demasiado largo');
  var props = PropertiesService.getScriptProperties();
  if (url) props.setProperty(_id(key), JSON.stringify({k: key, u: url}));
  else props.deleteProperty(_id(key));
  return true;
}

function doGet(e) {
  var html = UrlFetchApp.fetch(DASHBOARD_URL, {headers: {'Cache-Control': 'no-cache'}}).getContentText();
  var open = (e && e.parameter && e.parameter.i) ? e.parameter.i : '';
  var safe = function (v) { return JSON.stringify(v).replace(/</g, '\\u003c'); };
  var inj = '<script>window.IMPACT_LINKS=' + safe(_getLinks()) + ';' + (open ? 'window.OPEN_IMPACT=' + safe(open) + ';' : '') + '</script>';
  html = html.replace('<head>', '<head>' + inj);
  return HtmlService
    .createHtmlOutput(html)
    .setTitle('Iniciativas HotelDO')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}
