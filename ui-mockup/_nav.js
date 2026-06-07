/* Shared sidebar + active-nav helper. Each page calls: setActiveNav('id')
   Matches app.py NAV_ITEMS exactly — same icons, labels, sections, order. */

(function () {
  const SIDEBAR_HTML = `
<a class="sidebar-logo" href="index.html">
  <div class="logo-icon"><i class="ti ti-shield-bolt"></i></div>
  <span class="logo-text">soc-lab</span>
</a>
<div class="nav-section">Monitor</div>
<a class="nav-item" data-nav="overview" href="overview.html"><i class="ti ti-layout-dashboard"></i> Overview</a>
<a class="nav-item" data-nav="alerts" href="alerts.html"><i class="ti ti-bell-ringing"></i> Alerts <span class="badge"></span></a>
<a class="nav-item" data-nav="network" href="network.html"><i class="ti ti-network"></i> Network graph</a>
<div class="nav-section">Ingest</div>
<a class="nav-item" data-nav="ingest" href="ingest.html"><i class="ti ti-file-import"></i> Log upload</a>
<a class="nav-item" data-nav="capture-pcap" href="capture.html"><i class="ti ti-radar"></i> Packet replay</a>
<a class="nav-item" data-nav="capture-live" href="capture-live.html"><i class="ti ti-radio"></i> Live capture</a>
<div class="nav-section">Detect</div>
<a class="nav-item" data-nav="rules" href="rules.html"><i class="ti ti-adjustments"></i> Rules</a>
<a class="nav-item" data-nav="enrichment" href="enrichment.html"><i class="ti ti-microscope"></i> Enrichment</a>
<div class="nav-section">System</div>
<a class="nav-item" data-nav="stack" href="stack.html"><i class="ti ti-server"></i> Stack</a>
<a class="nav-item" data-nav="aliases" href="aliases.html"><i class="ti ti-link"></i> Aliases</a>
<a class="nav-item" data-nav="settings" href="settings.html"><i class="ti ti-settings"></i> Settings</a>
<div class="sidebar-bottom">
  <div class="stack-status">
    <div class="stack-title">Stack health</div>
    <div class="stack-row"><span class="dot green"></span> Elasticsearch</div>
    <div class="stack-row"><span class="dot green"></span> Kibana</div>
    <div class="stack-row"><span class="dot green"></span> Suricata</div>
    <div class="stack-row"><span class="dot green"></span> Filebeat</div>
  </div>
</div>`;

  document.getElementById('sidebar').innerHTML = SIDEBAR_HTML;

  window.setActiveNav = function (id) {
    document.querySelectorAll('.nav-item[data-nav]').forEach(function (el) {
      el.classList.toggle('active', el.getAttribute('data-nav') === id);
    });
  };
})();
