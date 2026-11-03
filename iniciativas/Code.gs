// === Iniciativas HotelDO · HTML — Apps Script ===
// Sirve el HTML que genera el refresh diario (rama tablero-live, carpeta iniciativas/).
// Si el link trae ?i=<nombre|fecha>, el tablero abre directo el impacto de esa iniciativa.

var DASHBOARD_URL = "https://raw.githubusercontent.com/dananabel-netizen/tribu-b2b-dana-/tablero-live/iniciativas/iniciativas_dashboard.html";

function doGet(e) {
  var html = UrlFetchApp.fetch(DASHBOARD_URL, {headers: {'Cache-Control': 'no-cache'}}).getContentText();
  var open = (e && e.parameter && e.parameter.i) ? e.parameter.i : '';
  if (open) {
    var inj = '<script>window.OPEN_IMPACT=' + JSON.stringify(open).replace(/</g, '\\u003c') + ';</script>';
    html = html.replace('<head>', '<head>' + inj);
  }
  return HtmlService
    .createHtmlOutput(html)
    .setTitle('Iniciativas HotelDO')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}
