// === Iniciativas HotelDO · Commercial & Engagement — Apps Script ===
// Sirve el HTML generado por GitHub Actions (rama tablero-live, carpeta iniciativas/).

var DASHBOARD_URL = "https://raw.githubusercontent.com/dananabel-netizen/tribu-b2b-dana-/tablero-live/iniciativas/iniciativas_dashboard.html";

function doGet() {
  var html = UrlFetchApp.fetch(DASHBOARD_URL, {headers: {'Cache-Control': 'no-cache'}}).getContentText();
  return HtmlService
    .createHtmlOutput(html)
    .setTitle('Iniciativas HotelDO')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}
