// === Usabilidad HotelDO · CTR de filtros — Apps Script ===
// Sirve el HTML generado por build_html.py (rama tablero-live, carpeta usabilidad/).

var DASHBOARD_URL = "https://raw.githubusercontent.com/dananabel-netizen/tribu-b2b-dana-/tablero-live/usabilidad/usabilidad_dashboard.html";

function doGet() {
  try {
    var html = UrlFetchApp.fetch(DASHBOARD_URL, {headers: {'Cache-Control': 'no-cache'}}).getContentText();
    return HtmlService
      .createHtmlOutput(html)
      .setTitle('Usabilidad HotelDO')
      .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  } catch (e) {
    return HtmlService.createHtmlOutput('<p style="font:14px sans-serif;color:#b00020;padding:24px">No pude cargar el tablero: ' + e.message + '</p>');
  }
}
